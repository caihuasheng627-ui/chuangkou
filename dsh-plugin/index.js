import { defineTool } from '@deepseek-ai/dsh-tools';
import { spawn } from 'node:child_process';
import { request as httpRequest } from 'node:http';
import { readFileSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import {
  DEFAULT_RULES_PATH,
  loadRules,
  rulesForUi,
  cleanText,
  sanitizeMeasurement,
  measurementKey,
  buildSystemPrompt,
  buildMessages,
  validateAnswer,
  fallbackAnswer,
  sanitizeDraftContext,
  splitDetailBlock,
} from './runtime/assistant.js';

export const name = 'dsh-wound-clinic';
export const inject = ['tools'];

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const SERVICE = path.join(ROOT, 'runtime', 'plugin_service.py');
const EVIDENCE_PATH = path.join(ROOT, 'runtime', 'evidence.json');
const PYTHON = process.env.WOUND_CLINIC_PYTHON || 'python';

/** 侧边对话与草稿工作流路由：只在回环地址的 Web GUI 上注册。 */
const ROUTE_CHAT = '/wound-clinic/assistant/chat';
const ROUTE_RULES = '/wound-clinic/assistant/rules';
/** [方法, 路径, 本地执行层 action, 请求体/查询参数映射] */
const ROUTE_JSON = [
  ['POST', '/wound-clinic/draft/create', 'draft.create', body => ({ title: body.title, measurement: body.measurement, details: body.details })],
  ['GET', '/wound-clinic/draft/list', 'draft.list', () => ({})],
  ['GET', '/wound-clinic/draft/get', 'draft.get', (body, url) => ({ draft_id: url.searchParams.get('draft_id') })],
  ['POST', '/wound-clinic/draft/update', 'draft.update', body => body],
  ['POST', '/wound-clinic/draft/archive', 'draft.archive', body => ({ draft_id: body.draft_id })],
  ['GET', '/wound-clinic/archive/list', 'archive.list', () => ({})],
  ['GET', '/wound-clinic/archive/history', 'archive.history', (body, url) => ({ patient_ref: url.searchParams.get('patient_ref') })],
  ['GET', '/wound-clinic/report/list', 'report.list', (body, url) => ({ patient_ref: url.searchParams.get('patient_ref') })],
];

const ASSISTANT_DEFAULTS = {
  maxTokens: 1600,
  temperature: 0.3,
  timeoutMs: 45000,
};

function errorText(code, message, hint) {
  return JSON.stringify({ ok: false, error: { code, message, hint } }, null, 2);
}

/**
 * Model-facing text receipt. DSH 0.2.x requires every tool to declare
 * `output: { schema, render }`; the renderer owns the ContentBlock list.
 */
const TEXT_OUTPUT = {
  schema: { type: 'string' },
  render: (_args, value) => [{ type: 'text', text: typeof value === 'string' ? value : JSON.stringify(value, null, 2) }],
};

/** Call the plugin's local Python worker. No patient image or identifier is sent to any model API. */
function callService(action, payload = {}, timeoutMs = 60000) {
  return new Promise((resolve) => {
    const child = spawn(PYTHON, [SERVICE, action], {
      cwd: ROOT,
      windowsHide: true,
      env: { ...process.env, PYTHONUTF8: '1' },
    });
    let stdout = '';
    let stderr = '';
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };
    const timer = setTimeout(() => {
      child.kill();
      finish({ ok: false, error: { code: 'timeout', message: `本地服务超时：${action}` } });
    }, timeoutMs);

    child.stdout.on('data', (chunk) => { stdout += chunk.toString('utf8'); });
    child.stderr.on('data', (chunk) => { stderr += chunk.toString('utf8'); });
    child.on('error', (error) => {
      clearTimeout(timer);
      finish({ ok: false, error: { code: 'python_start_failed', message: error.message, hint: '安装 Python 或设置 WOUND_CLINIC_PYTHON。' } });
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      let parsed;
      try { parsed = JSON.parse(stdout); } catch {
        finish({ ok: false, error: { code: 'invalid_worker_response', message: stderr.trim() || stdout.trim() || `worker exit ${code}` } });
        return;
      }
      if (code !== 0 && parsed && parsed.ok !== false) {
        parsed.ok = false;
        parsed.error = { code: 'worker_exit', message: stderr.trim() || `exit ${code}` };
      }
      finish(parsed);
    });
    child.stdin.write(JSON.stringify(payload || {}), 'utf8');
    child.stdin.end();
  });
}

function clinicalTool(spec) {
  return defineTool({
    isConcurrencySafe: () => false,
    timeoutMs: 120000,
    ...spec,
    output: spec.output || TEXT_OUTPUT,
    execute: async (args, exec) => {
      try {
        const result = await spec.run(args || {}, exec);
        return JSON.stringify(result, null, 2);
      } catch (error) {
        return errorText('plugin_exception', String(error && error.message || error), '检查输入契约；不要补造医学数据。');
      }
    },
  });
}

/* ------------------------------------------------------------------ *
 * 侧边对话：本地规则引擎 + 医师角色提示词 + 输出校验
 * ------------------------------------------------------------------ */

function numberInRange(value, fallback, min, max) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(max, Math.max(min, number));
}

/** 读取插件 config.assistant，缺省值用于教学演示。 */
function resolveAssistantConfig(config) {
  const raw = config && typeof config === 'object' && config.assistant && typeof config.assistant === 'object'
    ? config.assistant
    : {};
  return {
    provider: typeof raw.provider === 'string' && raw.provider.trim() ? raw.provider.trim() : null,
    model: typeof raw.model === 'string' && raw.model.trim() ? raw.model.trim() : null,
    reasoningEffort: typeof raw.reasoningEffort === 'string' && raw.reasoningEffort.trim() ? raw.reasoningEffort.trim() : null,
    maxTokens: Math.round(numberInRange(raw.maxTokens, ASSISTANT_DEFAULTS.maxTokens, 120, 2000)),
    temperature: numberInRange(raw.temperature, ASSISTANT_DEFAULTS.temperature, 0, 1),
    timeoutMs: Math.round(numberInRange(raw.timeoutMs, ASSISTANT_DEFAULTS.timeoutMs, 5000, 120000)),
  };
}

/** 规则文件按 mtime 缓存，改规则后无需重启插件即可生效。 */
function createFileCache(file, parse, fallback) {
  let cached = { stamp: '', value: fallback };
  return () => {
    try {
      const stamp = String(statSync(file).mtimeMs);
      if (stamp !== cached.stamp) cached = { stamp, value: parse(file) };
      return cached.value;
    } catch {
      return cached.value === undefined ? fallback : cached.value;
    }
  };
}

const readRules = createFileCache(DEFAULT_RULES_PATH, (file) => loadRules(file), loadRules());
const readEvidence = createFileCache(
  EVIDENCE_PATH,
  (file) => {
    const parsed = JSON.parse(readFileSync(file, 'utf8'));
    return Array.isArray(parsed) ? parsed : [];
  },
  [],
);

const analysisCache = new Map();

function cacheAnalysis(key, value) {
  if (!key) return;
  analysisCache.delete(key);
  analysisCache.set(key, { at: Date.now(), value });
  while (analysisCache.size > 24) {
    const first = analysisCache.keys().next();
    if (first.done) break;
    analysisCache.delete(first.value);
  }
}

/** 质量门禁与等级由本地 Python 规则引擎独占；同一测量 5 分钟内复用结果。 */
async function analyzeMeasurement(measurement) {
  const key = measurementKey(measurement);
  const hit = analysisCache.get(key);
  if (hit && Date.now() - hit.at < 5 * 60 * 1000) return hit.value;
  const raw = await callService('thermal.analyze', measurement, 30000);
  const value = { ok: Boolean(raw && raw.ok !== false), raw: raw || null };
  cacheAnalysis(key, value);
  return value;
}

function readJsonBody(req, limit) {
  return new Promise((resolve, reject) => {
    let size = 0;
    let settled = false;
    const chunks = [];
    const fail = (error) => {
      if (settled) return;
      settled = true;
      req.resume();
      reject(error);
    };
    req.on('data', (chunk) => {
      if (settled) return;
      size += chunk.length;
      if (size > limit) {
        fail(Object.assign(new Error('请求体过大'), { code: 'payload_too_large' }));
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => {
      if (settled) return;
      settled = true;
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')));
      } catch (error) {
        reject(Object.assign(new Error('请求体不是合法 JSON'), { code: 'invalid_json', cause: error }));
      }
    });
    req.on('error', (error) => fail(error));
  });
}

function sendEvent(res, payload) {
  if (res.writableEnded) return;
  res.write(`data: ${JSON.stringify(payload)}\n\n`);
}

function plainReply(res, status, text) {
  if (!res || res.writableEnded || res.destroyed) return;
  try {
    res.writeHead(status, { 'content-type': 'text/plain; charset=utf-8', 'cache-control': 'no-store' });
    res.end(text);
  } catch {
    // 连接已断开时忽略重复响应。
  }
}

function isLoopbackOrigin(origin) {
  try {
    const url = new URL(origin);
    return url.hostname === '127.0.0.1'
      || url.hostname === 'localhost'
      || url.hostname === '[::1]'
      || url.hostname === '::1';
  } catch {
    return false;
  }
}

/** 允许 127.0.0.1 与 localhost 互相访问同一端口，拒绝其他来源。 */
function sameLoopbackOrigin(origin, expected) {
  try {
    const actual = new URL(origin);
    const target = new URL(expected);
    if (actual.protocol !== target.protocol || actual.port !== target.port) return false;
    return actual.hostname === target.hostname
      || (isLoopbackOrigin(origin) && isLoopbackOrigin(expected));
  } catch {
    return false;
  }
}

/** 调用 DSH 已配置的模型路由；失败时返回原因，由调用方回退到规则模板。 */
async function streamModel(child, cfg, { rules, analysis, blocked, engineError, history, question, evidence, draft, signal }) {
  if (!child.llm || typeof child.llm.stream !== 'function') {
    return { ok: false, reason: 'llm_unavailable', text: '' };
  }
  let provider = cfg.provider;
  let model = cfg.model;
  let reasoningEffort = cfg.reasoningEffort;
  let selectionEffort = null;
  if (!provider || !model) {
    let selection = {};
    try { selection = child.agentDefaultModel.currentSelection() || {}; } catch { selection = {}; }
    provider = provider || selection.provider;
    model = model || selection.model;
    selectionEffort = selection.reasoningEffort || null;
  }
  if (!provider || !model) return { ok: false, reason: 'no_model_configured', text: '' };

  // 推理型模型会把输出预算花在思考上；侧边对话只做解释，优先选最低推理档。
  if (!reasoningEffort && child.llm && typeof child.llm.resolveModelInfo === 'function') {
    try {
      const info = await child.llm.resolveModelInfo(provider, model, signal);
      const least = info && info.reasoning && Array.isArray(info.reasoning.efforts) ? info.reasoning.efforts[0] : null;
      if (least && least.id) reasoningEffort = least.id;
    } catch { /* 模型未暴露推理档时按路由默认处理 */ }
  }
  if (!reasoningEffort) reasoningEffort = selectionEffort;

  const options = {
    provider,
    model,
    system: buildSystemPrompt(rules, { analysis, blocked, engineError, history, evidence, draft }),
    messages: buildMessages(question),
    maxTokens: cfg.maxTokens,
    temperature: cfg.temperature,
    signal,
  };
  if (reasoningEffort) options.reasoningEffort = reasoningEffort;

  let text = '';
  let blockText = '';
  let finish = null;
  const counts = {};
  try {
    for await (const chunk of child.llm.stream(options)) {
      if (signal.aborted) return { ok: false, reason: 'aborted', text };
      if (!chunk || typeof chunk !== 'object') continue;
      counts[chunk.type] = (counts[chunk.type] || 0) + 1;
      if (chunk.type === 'text-delta') text += chunk.text;
      else if (chunk.type === 'block-end' && chunk.block && chunk.block.type === 'text') blockText += chunk.block.text;
      else if (chunk.type === 'finish') finish = chunk.reason;
    }
  } catch (error) {
    return { ok: false, reason: (error && error.code) || 'stream_failed', text, detail: String(error && error.message || error) };
  }
  if (finish && (finish.kind === 'error' || finish.kind === 'aborted')) {
    const failure = finish.failure || {};
    return { ok: false, reason: failure.code || finish.kind, detail: failure.message || '', text };
  }
  const answerText = text.trim() ? text : blockText;
  if (!answerText.trim()) {
    return {
      ok: false,
      reason: 'empty_output',
      text: '',
      detail: `finish=${finish ? finish.kind : 'none'}；chunks=${JSON.stringify(counts)}`,
    };
  }
  return { ok: true, text: answerText, route: `${provider}/${model}` };
}

function ruleSummary(analysis, blocked) {
  if (blocked) return { level: 'blocked', label: '质量门禁未通过', delta_t_c: null };
  if (analysis && analysis.rule_result) return analysis.rule_result;
  return null;
}

async function handleChat(child, cfg, req, res) {
  if (req.method !== 'POST') {
    res.writeHead(405, { allow: 'POST', 'content-type': 'text/plain; charset=utf-8' });
    res.end('method not allowed');
    return;
  }
  const origin = req.headers.origin;
  let expectedOrigin = '';
  try { expectedOrigin = child.webServer.getOrigin(); } catch { expectedOrigin = ''; }
  if (origin && expectedOrigin && !sameLoopbackOrigin(origin, expectedOrigin)) {
    plainReply(res, 403, 'forbidden origin');
    return;
  }

  let body;
  try {
    body = await readJsonBody(req, 128 * 1024);
  } catch (error) {
    plainReply(res, error && error.code === 'payload_too_large' ? 413 : 400, String(error && error.message || 'bad request'));
    return;
  }
  const question = cleanText(body && body.question, 2000);
  if (!question) {
    plainReply(res, 400, 'question required');
    return;
  }

  res.writeHead(200, {
    'content-type': 'text/event-stream; charset=utf-8',
    'cache-control': 'no-cache, no-transform',
    connection: 'keep-alive',
    'x-accel-buffering': 'no',
  });
  if (typeof res.flushHeaders === 'function') res.flushHeaders();

  const abort = new AbortController();
  const onClose = () => {
    if (!res.writableFinished) abort.abort();
  };
  res.on('close', onClose);
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; abort.abort(); }, cfg.timeoutMs + 15000);
  const rules = readRules();
  let measurement = null;
  let analysis = null;
  let blocked = null;
  let engineError = '';
  // 草稿模式下：侧边对话围绕打开的草稿补充/修正详情；客户端在草稿模式下发送草稿内的测量。
  const draft = sanitizeDraftContext(body && body.draft);
  measurement = sanitizeMeasurement(body && body.measurement);

  try {
    measurement = sanitizeMeasurement(body && body.measurement);
    sendEvent(res, { type: 'phase', phase: 'rules', text: measurement ? '正在核对本地规则结果' : '未附带测量，仅做一般性说明' });
    if (measurement) {
      const outcome = await analyzeMeasurement(measurement);
      if (abort.signal.aborted) {
        if (timedOut) throw Object.assign(new Error('规则引擎超时'), { code: 'timeout' });
        return;
      }
      if (outcome.ok) {
        analysis = outcome.raw;
      } else if (outcome.raw && outcome.raw.error && outcome.raw.error.code === 'quality_gate_blocked') {
        blocked = outcome.raw.error;
      } else {
        engineError = (outcome.raw && outcome.raw.error && outcome.raw.error.message) || '本地规则引擎调用失败';
      }
    }

    sendEvent(res, { type: 'phase', phase: 'model', text: '正在按医师角色规则生成' });
    const result = await streamModel(child, cfg, {
      rules,
      analysis,
      blocked,
      engineError,
      history: body && body.history,
      question,
      evidence: readEvidence(),
      draft,
      signal: abort.signal,
    });
    if (abort.signal.aborted) {
      if (timedOut) throw Object.assign(new Error('模型请求超时'), { code: 'timeout' });
      return;
    }

    sendEvent(res, { type: 'phase', phase: 'validate', text: '正在核对回答是否符合医师规则' });
    // 先剥离 <<<DETAIL>>> 详情块再做安全校验：用户陈述的事实不等于助手建议。
    const visible = draft && draft.status !== 'archived'
      ? splitDetailBlock(result.ok ? result.text : '')
      : { text: result.ok ? result.text : '', details: {} };
    const verdict = validateAnswer(visible.text, { rules, analysis });
    const rule = ruleSummary(analysis, blocked);
    const engine = blocked ? 'blocked' : engineError ? 'unavailable' : analysis ? 'local-rules' : 'none';
    const baseMeta = {
      rule, engine, rulesVersion: rules.version, generatedAt: new Date().toISOString(),
      measurementId: measurement ? measurement.measurement_id : null,
      draftId: draft ? draft.draft_id : null,
      detail_updates: visible.details,
    };

    if (!result.ok || !verdict.ok) {
      const violations = result.ok ? verdict.violations : [];
      sendEvent(res, {
        type: 'final',
        ok: true,
        answer: fallbackAnswer({ rules, analysis, blocked, engineError, evidence: readEvidence(), question }),
        meta: {
          ...baseMeta,
          detail_updates: {},
          modelUsed: false,
          reason: result.ok ? 'rule_violation' : result.reason,
          detail: result.detail || '',
          violations,
        },
      });
      return;
    }

    const truncationNote = '（回答超出规则允许的长度，已截断。）';
    let answer = verdict.text;
    if (verdict.truncated) {
      const disclaimer = typeof rules.disclaimer === 'string' ? rules.disclaimer : '';
      answer = disclaimer && answer.endsWith(disclaimer)
        ? `${answer.slice(0, -disclaimer.length).trim()}\n${truncationNote}\n${disclaimer}`
        : `${answer}\n${truncationNote}`;
    }    sendEvent(res, {
      type: 'final',
      ok: true,
      answer,
      meta: { ...baseMeta, modelUsed: true, model: result.route, violations: [], truncated: verdict.truncated },
    });
  } catch (error) {
    if ((timedOut || (error && error.code === 'timeout')) && !res.writableEnded) {
      const engine = blocked ? 'blocked' : engineError ? 'unavailable' : analysis ? 'local-rules' : 'none';
      sendEvent(res, {
        type: 'final',
        ok: true,
        answer: fallbackAnswer({ rules, analysis, blocked, engineError, evidence: readEvidence(), question }),
        meta: {
          rule: ruleSummary(analysis, blocked),
          engine,
          rulesVersion: rules.version,
          generatedAt: new Date().toISOString(),
          measurementId: measurement ? measurement.measurement_id : null,
          draftId: draft ? draft.draft_id : null,
          detail_updates: {},
          modelUsed: false,
          reason: 'timeout',
          detail: String(error && error.message || '请求超时'),
          violations: [],
        },
      });
      return;
    }
    if (!res.writableEnded) {
      sendEvent(res, {
        type: 'error',
        ok: false,
        code: 'assistant_failed',
        message: String(error && error.message || error),
        hint: '检查 Python 规则引擎与 DSH 模型路由；本窗口不会用猜测替代规则结果。',
      });
    }
  } finally {
    clearTimeout(timer);
    res.off('close', onClose);
    if (!res.writableEnded) res.end();
  }
}

function handleRules(child, req, res) {
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    res.writeHead(405, { allow: 'GET, HEAD', 'content-type': 'text/plain; charset=utf-8' });
    res.end('method not allowed');
    return;
  }
  let payload;
  try {
    payload = JSON.stringify({ ok: true, rules: rulesForUi(readRules()) });
  } catch (error) {
    plainReply(res, 500, String(error && error.message || error));
    return;
  }
  res.writeHead(200, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' });
  res.end(req.method === 'HEAD' ? undefined : payload);
}

/** 回环来源校验：与当前 GUI 同源（127.0.0.1 与 localhost 互认），否则 403。 */
function rejectForeignOrigin(child, req, res) {
  const origin = req.headers.origin;
  let expectedOrigin = '';
  try { expectedOrigin = child.webServer.getOrigin(); } catch { expectedOrigin = ''; }
  if (origin && expectedOrigin && !sameLoopbackOrigin(origin, expectedOrigin)) {
    plainReply(res, 403, 'forbidden origin');
    return true;
  }
  return false;
}

/** 草稿工作流与档案读取：统一 JSON 路由，全部落到本地 Python 执行层。 */
async function handleJsonRoute(child, method, action, mapBody, req, res) {
  if (req.method !== method && !(method === 'GET' && req.method === 'HEAD')) {
    res.writeHead(405, { allow: method, 'content-type': 'text/plain; charset=utf-8' });
    res.end('method not allowed');
    return;
  }
  if (rejectForeignOrigin(child, req, res)) return;
  let body = {};
  if (method === 'POST') {
    try {
      body = await readJsonBody(req, 512 * 1024);
    } catch (error) {
      plainReply(res, error && error.code === 'payload_too_large' ? 413 : 400, String(error && error.message || 'bad request'));
      return;
    }
  }
  let payload = {};
  try {
    const url = new URL(req.url || '/', 'http://127.0.0.1');
    payload = mapBody(body || {}, url) || {};
  } catch {
    plainReply(res, 400, 'bad request');
    return;
  }
  let result;
  try {
    result = await callService(action, payload, 90000);
  } catch (error) {
    result = { ok: false, error: { code: 'route_failed', message: String(error && error.message || error) } };
  }
  if (res.writableEnded) return;
  res.writeHead(200, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' });
  res.end(req.method === 'HEAD' ? undefined : JSON.stringify(result));
}

/* ------------------------------------------------------------------ 实时采集
 * 相机由常驻的 live_server.py 独占打开；Node 侧只把它代理成同源路由，
 * 这样浏览器既能用 <img> 播 MJPEG，又不需要跨端口或放开 CORS。
 */
const LIVE_SERVER = path.join(ROOT, 'runtime', 'live_server.py');
let liveChild = null;
let livePort = 0;
let liveStarting = null;
let liveSource = '';
let liveError = '';

function stopLiveServer() {
  const child = liveChild;
  liveChild = null;
  livePort = 0;
  liveStarting = null;
  liveSource = '';
  if (child && child.exitCode === null) {
    try { child.kill(); } catch { /* 进程可能已自行退出 */ }
  }
}

function startLiveServer(timeoutMs = 25000) {
  if (livePort) return Promise.resolve({ ok: true, port: livePort, source: liveSource, error: liveError });
  if (liveStarting) return liveStarting;
  const promise = new Promise((resolve) => {
    let child;
    try {
      child = spawn(PYTHON, [LIVE_SERVER, '--port', '0', '--source', 'auto'], {
        cwd: ROOT, windowsHide: true, env: { ...process.env, PYTHONUTF8: '1' },
      });
    } catch (error) {
      resolve({ ok: false, error: `无法启动实时采集进程：${error.message || error}` });
      return;
    }
    let done = false;
    let timer = null;
    const finish = (value) => {
      if (done) return;
      done = true;
      if (timer) clearTimeout(timer);
      resolve(value);
    };
    timer = setTimeout(() => finish({ ok: false, error: `实时采集服务启动超时（${Math.round(timeoutMs / 1000)} 秒），可能是 opencv-python 未安装或相机被占用` }), timeoutMs);
    child.stdout.setEncoding('utf8');
    child.stdout.on('data', (chunk) => {
      for (const line of String(chunk).split(/\r?\n/)) {
        const text = line.trim();
        if (!text.startsWith('{')) continue;
        let event;
        try { event = JSON.parse(text); } catch { continue; }
        if (event.event === 'ready' || (event.ok === true && event.port)) {
          liveChild = child;
          livePort = Number(event.port) || 0;
          liveSource = String(event.source || '');
          liveError = String(event.error || '');
          finish({ ok: true, port: livePort, source: liveSource, error: liveError });
        } else if (event.event === 'error') {
          finish({ ok: false, error: String(event.message || '实时采集服务启动失败') });
        }
      }
    });
    child.on('error', (error) => finish({ ok: false, error: `实时采集进程错误：${error.message || error}` }));
    child.on('exit', (code) => {
      if (liveChild === child) { liveChild = null; livePort = 0; }
      finish({ ok: false, error: `实时采集服务已退出（code ${code}）` });
    });
  });
  liveStarting = promise;
  promise.then(() => { if (liveStarting === promise) liveStarting = null; });
  return promise;
}

function liveJson(res, status, payload) {
  if (!res || res.writableEnded || res.destroyed) return;
  try {
    const body = JSON.stringify(payload);
    res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' });
    res.end(body);
  } catch {
    // 响应已结束或连接已断开时，不能再写头；忽略重复响应。
  }
}

/** 把请求转发到 127.0.0.1 上的采集服务；MJPEG 直接流式透传。 */
function proxyLive(port, upstreamPath, method, requestBody, req, res) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = () => { if (!settled) { settled = true; resolve(); } };
    const upstream = httpRequest({
      host: '127.0.0.1', port, path: upstreamPath, method,
      headers: method === 'POST' ? { 'content-type': 'application/json', accept: 'application/json' } : { accept: '*/*' },
    }, (up) => {
      const type = String(up.headers['content-type'] || '');
      if (isStreamingType(type)) {
        res.writeHead(up.statusCode || 200, { 'content-type': type, 'cache-control': 'no-store',
          'x-live-source': liveSource || '' });
        up.pipe(res);
        up.on('end', finish);
        up.on('error', finish);
        return;
      }
      let text = '';
      up.setEncoding('utf8');
      up.on('data', (chunk) => { text += chunk; });
      up.on('end', () => {
        if (res.writableEnded || res.destroyed) { finish(); return; }
        res.writeHead(up.statusCode || 502, {
          'content-type': type || 'application/json; charset=utf-8', 'cache-control': 'no-store',
          'x-live-source': liveSource || '',
        });
        res.end(method === 'HEAD' ? undefined : text);
        finish();
      });
      up.on('error', () => {
        if (!res.writableEnded && !res.destroyed) liveJson(res, 502, { ok: false, error: { code: 'live_proxy_failed', message: '采集服务读取失败' } });
        finish();
      });
    });
    upstream.on('error', (error) => {
      if (!res.writableEnded && !res.destroyed) {
        liveJson(res, 503, { ok: false, error: { code: 'live_unavailable',
          message: `实时采集服务不可用：${error.code === 'ECONNREFUSED' ? '进程未就绪' : error.message}` } });
      }
      finish();
    });
    res.on('close', () => { if (!res.writableEnded) upstream.destroy(); finish(); });
    if (method === 'POST') upstream.write(JSON.stringify(requestBody || {}));
    upstream.end();
  });
}

function isStreamingType(type) { return String(type).includes('multipart/x-mixed-replace'); }

const LIVE_ROUTES = [
  ['GET', '/wound-clinic/live/status', '/status'],
  ['GET', '/wound-clinic/live/frame.jpg', '/frame.jpg'],
  ['GET', '/wound-clinic/live/stream', '/stream'],
  ['GET', '/wound-clinic/live/measurement', '/measurement'],
  ['POST', '/wound-clinic/live/config', '/config'],
  ['POST', '/wound-clinic/live/engine', '/engine'],
  ['POST', '/wound-clinic/live/stop', '/stop'],
];

/** 只在回环地址注册对话与草稿路由：避免把无鉴权的医学对话暴露到局域网。 */
function registerAssistantRoutes(ctx, cfg) {  let origin = '';
  try { origin = ctx.webServer.getOrigin(); } catch { origin = ''; }
  if (!isLoopbackOrigin(origin)) {
    ctx.logger?.warn?.(`[wound-clinic] 侧边对话与草稿工作流未启用：Web GUI 绑定在非回环地址 ${origin || '未知'}。`);
    return;
  }
  ctx.effect(() => ctx.webServer.register({
    kind: 'exact',
    path: ROUTE_RULES,
    handler: (req, res) => handleRules(ctx, req, res),
  }), 'wound-clinic: assistant-rules-route');

  ctx.effect(() => ctx.webServer.register({
    kind: 'exact',
    path: ROUTE_CHAT,
    handler: (req, res) => {
      void handleChat(ctx, cfg, req, res).catch((error) => {
        ctx.logger?.warn?.(error instanceof Error ? error : new Error(String(error)));
        plainReply(res, 500, 'assistant failed');
      });
    },
  }), 'wound-clinic: assistant-chat-route');

  for (const [method, path, action, mapBody] of ROUTE_JSON) {
    ctx.effect(() => ctx.webServer.register({
      kind: 'exact',
      path,
      handler: (req, res) => {
        void handleJsonRoute(ctx, method, action, mapBody, req, res).catch((error) => {
          ctx.logger?.warn?.(error instanceof Error ? error : new Error(String(error)));
          plainReply(res, 500, `${action} failed`);
        });
      },
    }), `wound-clinic: ${action}-route`);
  }

  for (const [method, path, upstreamPath] of LIVE_ROUTES) {
    ctx.effect(() => ctx.webServer.register({
      kind: 'exact',
      path,
      handler: (req, res) => {
        if (req.method !== method && !(method === 'GET' && req.method === 'HEAD')) {
          res.writeHead(405, { allow: method, 'content-type': 'text/plain; charset=utf-8' });
          res.end('method not allowed');
          return;
        }
        if (rejectForeignOrigin(ctx, req, res)) return;
        if (upstreamPath === '/stop') {
          stopLiveServer();
          liveJson(res, 200, { ok: true, stopped: true });
          return;
        }
        const run = async () => {
          const state = await startLiveServer();
          if (!state.ok) {
            liveJson(res, 503, { ok: false, error: { code: 'live_unavailable', message: state.error || '实时采集服务未启动' } });
            return;
          }
          let body = null;
          if (method === 'POST') {
            body = await new Promise((resolve) => {
              let raw = '';
              req.setEncoding('utf8');
              req.on('data', (chunk) => { raw += chunk; if (raw.length > 64 * 1024) raw = raw.slice(0, 65536); });
              req.on('end', () => {
                try { resolve(raw ? JSON.parse(raw) : {}); } catch { resolve({}); }
              });
              req.on('error', () => resolve({}));
            });
          }
          await proxyLive(state.port, upstreamPath, method, body, req, res);
        };
        void run().catch((error) => {
          ctx.logger?.warn?.(error instanceof Error ? error : new Error(String(error)));
          if (!res.writableEnded) {
            liveJson(res, 500, { ok: false, error: { code: 'live_route_failed', message: `${path} 处理失败` } });
          }
        });
      },
    }), `wound-clinic: live-${upstreamPath.replace(/\W/g, '') || 'root'}`);
  }
}

export function apply(ctx, config = {}) {
  ctx.effect(() => () => stopLiveServer(), 'wound-clinic: live-server-cleanup');
  ctx.effect(() => ctx.tools.register(clinicalTool({
    name: 'wound_thermal_analyze',
    description: '【创口温度规则分析】对标定、量程、ROI 和参考区进行质量门禁，按本地阈值计算 ΔT 风险等级，并基于审核证据生成解释。只能做感染风险辅助筛查，不能确诊感染或建议抗生素。风险等级由此工具独占，模型不得修改。输入为 measurement JSON，不需要创口照片或患者身份信息。',
    parameters: {
      measurement: { type: 'json', required: true, description: '符合 wound-measurement/v1 的完整测量对象。' },
    },
    run: (args) => callService('thermal.analyze', args.measurement),
  })), 'wound-clinic: thermal-analyze');

  ctx.effect(() => ctx.tools.register(clinicalTool({
    name: 'wound_evidence_search',
    description: '【创口医学证据检索】只检索插件内经项目核对的知识条目，返回证据编号、适用人群、原文摘要、阈值口径和来源链接。回答医学问题时引用 evidence_id；证据外的人群必须提示外推限制，不得编造文献。',
    parameters: {
      query: { type: 'string', description: '检索问题，例如 温差、复测、糖尿病足。' },
      scenario: { type: 'string', description: '可选场景：infection_screening / repeat_monitoring / diabetic_foot。' },
      limit: { type: 'number', description: '最多返回条数，默认 4。' },
    },
    run: (args) => callService('evidence.search', args),
  })), 'wound-clinic: evidence-search');

  ctx.effect(() => ctx.tools.register(clinicalTool({
    name: 'wound_archive',
    description: '【本地患者档案】op=create_patient 建立伪匿名档案；op=add_measurement 追加测量与规则结果；op=history 查询随访；op=list 列出档案。记录只追加不覆盖，读取和写入均进入审计。不要传入身份证号、手机号等直接身份标识。',
    parameters: {
      op: { type: 'string', required: true, description: 'create_patient | add_measurement | history | list' },
      payload: { type: 'json', description: '对应操作的参数；add_measurement 需含 patient_ref、measurement 和 analysis。' },
    },
    run: (args) => callService(`archive.${args.op}`, args.payload || {}),
  })), 'wound-clinic: archive');

  ctx.effect(() => ctx.tools.register(clinicalTool({
    name: 'wound_report',
    description: '【本地筛查报告】op=create_draft 由测量及通过校验的分析结果生成 HTML 草稿并写入报告中心；op=list 查询报告。此工具不能生成 reviewed 正式报告，正式审核必须由医护人员在本地完成。',
    parameters: {
      op: { type: 'string', required: true, description: 'create_draft | list' },
      payload: { type: 'json', description: 'create_draft 需含 patient_ref、measurement 和 analysis。' },
    },
    run: (args) => callService(`report.${args.op}`, args.payload || {}),
  })), 'wound-clinic: report');

  ctx.effect(() => ctx.tools.register(clinicalTool({
    name: 'wound_device_probe',
    description: '【海康 UVC 采集探测】枚举相机并尝试默认/Y16/YUY2/MJPG，报告位深、raw 范围和预览文件。uint8 不能作为原始温度；未取得有效标定前不得输出风险分级。默认只读探测，不启动持续采集。',
    parameters: {
      cameras: { type: 'string', description: '相机索引，例如 0,1；默认 0,1。' },
      frames: { type: 'number', description: '每种模式读取帧数，默认 8。' },
    },
    run: (args) => callService('device.probe', args, 120000),
  })), 'wound-clinic: device-probe');

  const assistantConfig = resolveAssistantConfig(config);
  ctx.inject(['webServer', 'llm', 'agentDefaultModel'], (child) => {
    registerAssistantRoutes(child, assistantConfig);
  });
}
