// 医师角色规则逻辑单测：node runtime/test_assistant.mjs
import assert from 'node:assert/strict';
import {
  loadRules,
  sanitizeMeasurement,
  measurementKey,
  buildSystemPrompt,
  validateAnswer,
  fallbackAnswer,
  formatHistory,
  rulesForUi,
  sanitizeDraftContext,
  splitDetailBlock,
} from './assistant.js';

const rules = loadRules();
const evidence = [
  { evidence_id: 'E002', year: 2023, type: 'diagnostic_cohort', title: 'thermal asymmetry',
    verified_excerpt: '热不对称 ≥2.55°C，敏感度 100%、特异度 64%。', population: '慢性创口人群',
    threshold: { metric: 'periwound_thermal_asymmetry', operator: '>=', value_c: 2.55 }, source_url: 'https://example.org/E002' },
  { evidence_id: 'E004', year: 2024, type: 'clinical_evidence_summary', title: 'repeat assessment',
    verified_excerpt: '单次筛查存在假阳性，重复测量优于单次。', population: '温度监测人群',
    threshold: null, source_url: 'https://example.org/E004' },
];

const analysis = {
  ok: true,
  action: 'thermal.analyze',
  quality_gate: 'passed',
  rule_result: {
    level: 'high', label: '显著热异常 · 感染风险增高', delta_t_c: 2.28,
    threshold_version: 'wound-delta-v1', reason_codes: ['DELTA_ABOVE_WARNING'], absolute_temperature_c: 34.79,
  },
  interpretation: [{ text: 'ΔT=+2.28°C，已超过预警参考值。', evidence_ids: ['E003', 'E004'] }],
  limitations: ['单次测量存在假阳性。'],
};

const measurement = {
  measurement_id: 'MEAS-DEMO-0001', patient_ref: 'DEMO-001', encounter_id: 'ENC-DEMO-0001',
  captured_at: '2026-11-23T10:25:38+08:00',
  device: { model: 'HM-TB421-3XF', capture_mode: 'mock_y16', emissivity: 0.98, distance_m: 0.4, ambient_c: 24,
    calibration: { status: 'valid', calibration_id: 'CAL-DEMO-001' }, raw_path: 'C:/secret/raw.npy' },
  quality: { frames_used: 30, temporal_median_frames: 5, roi_valid: true, reference_valid: true,
    temperature_in_range: true, roi_method: 'automatic_hotspot', warnings: ['模拟数据'] },
  metrics: { t_wound_mean_c: 34.79, t_ref_far_c: 32.51, t_ref_near_c: 32.93, delta_t_c: 2.28,
    t_wound_max_c: 37.96, area_ratio: 0.112, gradient_c: 3.17 },
  thresholds: { version: 'wound-delta-v1', normal_max_c: 0.6, warning_max_c: 2.2, infection_min_c: 2.55 },
  image_bytes: [1, 2, 3],
};

// 1. 规则文件
assert.equal(typeof rules.version, 'string');
assert.ok(rules.sections.length >= 6, '规则章节缺失');
assert.ok(rules.checks.length >= 6, '校验条目缺失');

// 2. 测量脱敏
const safe = sanitizeMeasurement(measurement);
assert.ok(safe);
assert.equal('patient_ref' in safe, false, 'patient_ref 不得进入模型请求');
assert.equal('encounter_id' in safe, false, 'encounter_id 不得进入模型请求');
assert.equal(JSON.stringify(safe).includes('secret'), false, '本地路径不得进入模型请求');
assert.equal(JSON.stringify(safe).includes('image_bytes'), false, '影像字节不得进入模型请求');
assert.equal(JSON.stringify(safe).includes('raw_path'), false, '原始数组路径不得进入模型请求');
assert.equal(safe.metrics.delta_t_c, 2.28);
assert.equal(safe.quality.roi_valid, true);
assert.equal(safe.measurement_id, 'MEAS-DEMO-0001');
assert.equal(sanitizeMeasurement({ metrics: {} }), null, '缺少 measurement_id 必须拒绝');

// 3. 提示词
const blockedMeasurement = sanitizeMeasurement({ ...measurement, device: { ...measurement.device, calibration: { status: 'invalid' } } });
assert.notEqual(measurementKey(safe), measurementKey(blockedMeasurement), '质量状态变化必须使规则结果缓存失效');
const prompt = buildSystemPrompt(rules, { analysis, evidence, history: [{ role: 'user', text: '先看这个' }] });
assert.ok(prompt.includes('显著热异常 · 感染风险增高'), '提示词必须带入本地等级');
assert.ok(prompt.includes('E002'), '提示词必须带入证据编号');
assert.ok(prompt.includes('禁止确诊') || prompt.includes('禁止“确诊'), '提示词必须包含禁止确诊规则');
assert.ok(prompt.includes('不套用固定四段模板'), '提示词必须要求简明、针对回答');
assert.ok(prompt.includes('正文无需重复'), '界面固定免责声明时不应要求逐条重复');
assert.equal(prompt.includes('DEMO-001'), false, '提示词不得包含档案号');

// 4. 合规回答
const good = '结论：本地规则判定为显著热异常 · 感染风险增高，ΔT +2.28°C，属于辅助筛查结果。\n'
  + '依据：创周热不对称达到研究参考值（E002），提示感染风险增高。\n'
  + '局限：单次测量存在假阳性，参考区与环境会影响 ΔT（E004）。\n'
  + '下一步：同条件复测并由医护人员结合创面评估。\n'
  + '辅助筛查，不替代临床诊断。';
const goodVerdict = validateAnswer(good, { rules, analysis });
assert.equal(goodVerdict.ok, true, `合规回答被误杀：${JSON.stringify(goodVerdict.violations)}`);

// 5. 确诊/排除/用药/病原体/绝对化
for (const [label, text] of [
  ['确诊', '结论：该创口已确诊感染。依据：E002。'],
  ['排除', '结论：可以排除感染，无需处理。依据：E004。'],
  ['用药', '结论：建议使用头孢类抗生素。依据：E002。'],
  ['病原体', '结论：考虑金黄色葡萄球菌感染。依据：E002。'],
  ['绝对化', '结论：一定不会恶化。依据：E004。'],
  ['隐私', '结论：请提供患者姓名和身份证号。依据：E004。'],
]) {
  const verdict = validateAnswer(text, { rules, analysis });
  assert.equal(verdict.ok, false, `${label} 未被拦截`);
  assert.ok(verdict.violations.length > 0);
}

// 6. 否定句不误伤
const cautious = '结论：不能排除感染，也不建议使用抗生素，需要复测。依据：E004。\n'
  + '局限：单次测量存在假阳性。\n下一步：同条件复测。';
assert.equal(validateAnswer(cautious, { rules, analysis }).ok, true, '否定句被误判');

// 7. 等级篡改与等级错配
const mismatch = '结论：本地规则判定为未见明显热异常，ΔT +2.28°C。依据：E002。';
const mismatchVerdict = validateAnswer(mismatch, { rules, analysis });
assert.equal(mismatchVerdict.ok, false);
assert.ok(mismatchVerdict.violations.some(item => item.code === 'level_mismatch'));

const inventedLevel = '结论：本次属于高风险，ΔT +2.28°C。依据：E002。';
assert.equal(validateAnswer(inventedLevel, { rules, analysis }).ok, false);

// 研究人群描述里的“高风险”不算本次等级
const populationLevel = '结论：本地规则判定为显著热异常 · 感染风险增高，ΔT +2.28°C。\n'
  + '依据：2.2°C 是糖尿病足溃疡复发高风险人群的预警阈值（E003）。\n'
  + '局限：单次测量存在假阳性（E004）。\n下一步：同条件复测。';
assert.equal(validateAnswer(populationLevel, { rules, analysis }).ok, true,
  `人群描述被误杀：${JSON.stringify(validateAnswer(populationLevel, { rules, analysis }).violations)}`);

// 讨论阈值/界值时提到别的等级名称不算篡改
const cautiousLevel = '结论：本地规则判定为显著热异常 · 感染风险增高，ΔT +2.28°C。\n'
  + '依据：2.2°C 是预警参考值，而非所有创口的通用高风险判定标准（E003）。\n'
  + '局限：单次测量存在假阳性，不一定代表感染（E004）。\n下一步：同条件复测。';
assert.equal(validateAnswer(cautiousLevel, { rules, analysis }).ok, true,
  `阈值讨论被误杀：${JSON.stringify(validateAnswer(cautiousLevel, { rules, analysis }).violations)}`);

// 8. 引用研究却没有编号
const noId = '结论：研究表明温度筛查有效。依据：相关文献。';
const noIdVerdict = validateAnswer(noId, { rules, analysis });
assert.ok(noIdVerdict.violations.some(item => item.code === 'evidence_missing'));

// 8.1 界面已固定显示免责声明时，逐条回答不再重复追加
const noDisclaimer = '本地规则判定为显著热异常 · 感染风险增高，ΔT +2.28°C。阈值来自研究（E003）。';
const disclaimVerdict = validateAnswer(noDisclaimer, { rules, analysis });
assert.equal(disclaimVerdict.ok, true, JSON.stringify(disclaimVerdict.violations));
assert.equal(disclaimVerdict.text.endsWith(rules.disclaimer), false, '界面固定免责声明时不应逐条追加');
assert.ok(disclaimVerdict.text.length <= rules.output_contract.max_chars);

// 8.2 报告边界：声称已审核/可写入正式报告要被拦截，否定表述放行
const reportClaim = '结论：该结果已审核通过，可以写入正式报告。依据：E004。';
assert.equal(validateAnswer(reportClaim, { rules, analysis }).ok, false);
const reportCautious = '结论：本次不能写入正式报告，报告已生成但尚未审核，需医护人员复核。依据：E004。';
assert.equal(validateAnswer(reportCautious, { rules, analysis }).ok, true,
  `报告边界否定句被误杀：${JSON.stringify(validateAnswer(reportCautious, { rules, analysis }).violations)}`);

const reportConditional = '结论：报告须经审核通过后才能写入正式报告，当前仅为草稿。依据：E004。';
assert.equal(validateAnswer(reportConditional, { rules, analysis }).ok, true,
  `条件式报告表述被误杀：${JSON.stringify(validateAnswer(reportConditional, { rules, analysis }).violations)}`);
const reportDone = '结论：报告已经审核通过，已出具正式版本。依据：E004。';
assert.equal(validateAnswer(reportDone, { rules, analysis }).ok, false);

// 单字“需/应”不能成为绕过报告边界的窗口
assert.equal(validateAnswer('结论：需注意，本结果可以写入正式报告。依据：E004。', { rules, analysis }).ok, false);
assert.equal(validateAnswer('结论：应关注，本结果可以写入正式报告。依据：E004。', { rules, analysis }).ok, false);

// 未审核不再作为全局否定词，避免削弱确诊拦截
assert.equal(validateAnswer('结论：报告未审核，但已确诊感染。依据：E004。', { rules, analysis }).ok, false);

// 近似免责声明不重复叠加
const partialDisclaimer = '结论：本地规则判定为显著热异常 · 感染风险增高，ΔT +2.28°C。依据：研究阈值（E003）。\n辅助筛查，不替代临床诊断。';
const partialVerdict = validateAnswer(partialDisclaimer, { rules, analysis });
assert.equal((partialVerdict.text.match(/不替代临床诊断/gu) || []).length, 1, '免责声明不应重复');

// 9. 空回答
assert.equal(validateAnswer('   ', { rules, analysis }).ok, false);

// 10. 超长截断
const long = `${good}\n${'补充说明。'.repeat(400)}`;
const longVerdict = validateAnswer(long, { rules, analysis });
assert.equal(longVerdict.truncated, true);
assert.ok(longVerdict.text.length <= rules.output_contract.max_chars);

// 11. 规则模板兜底：按问题给短答案，不再固定四段
const fb = fallbackAnswer({ rules, analysis, evidence });
assert.ok(fb.includes('显著热异常'), '兜底必须带本地等级');
assert.ok(fb.includes('E004'), '兜底必须带证据编号');
assert.equal(fb.includes(rules.disclaimer), false, '界面固定免责声明时兜底不应重复');
assert.equal(fb.includes('结论：') || fb.includes('下一步：'), false, '兜底不应套用固定四段模板');
assert.ok(fb.length <= rules.output_contract.max_chars);
assert.equal(fb.includes('DEMO-001'), false);

const recheckAnswer = fallbackAnswer({ rules, analysis, evidence, question: '需要复测吗？间隔多久' });
assert.ok(recheckAnswer.startsWith('需要复测'), '复测问题必须先直接回答');
assert.ok(recheckAnswer.includes('没有给出统一复测间隔'), '复测间隔必须说明证据边界');
assert.equal(recheckAnswer.includes('下一步：'), false);

const evidenceAnswer = fallbackAnswer({ rules, analysis, evidence, question: '这些结论有哪些证据和局限' });
assert.ok(evidenceAnswer.includes('E002') && evidenceAnswer.includes('E004'));
assert.ok(evidenceAnswer.includes('不能外推'));

const reportAnswer = fallbackAnswer({ rules, analysis, evidence, question: '这份结果能不能写进正式报告' });
assert.ok(reportAnswer.includes('报告草稿'));
assert.ok(reportAnswer.includes('仍需医护人员复核'));

const urgentAnswer = fallbackAnswer({ rules, analysis, evidence, question: '哪些情况需要尽快就医' });
assert.ok(urgentAnswer.includes('红肿扩大'));
assert.ok(urgentAnswer.includes('不等于已经感染'));

const coldAnalysis = {
  ...analysis,
  rule_result: { ...analysis.rule_result, level: 'cold', label: '局部低温（警惕灌注不足）', delta_t_c: -0.82 },
};
const coldExplain = fallbackAnswer({ rules, analysis: coldAnalysis, evidence, question: '这组数值怎么解读' });
assert.ok(coldExplain.includes('灌注不足'));
assert.equal(coldExplain.includes('比远端参考皮肤高'), false, '低温不能套用感染升温解释');
const coldRecheck = fallbackAnswer({ rules, analysis: coldAnalysis, evidence, question: '需要复测吗' });
assert.ok(coldRecheck.includes('灌注'));

const blockedAnswer = fallbackAnswer({ rules, blocked: { code: 'quality_gate_blocked', message: '标定无效或缺失' }, evidence });
assert.ok(blockedAnswer.includes('质量门禁'));
assert.ok(blockedAnswer.includes('标定'));

const noEngine = fallbackAnswer({ rules, engineError: 'python_start_failed' });
assert.ok(noEngine.includes('规则引擎'));

const noMeasurement = fallbackAnswer({ rules, evidence });
assert.ok(noMeasurement.includes('还没有本次测量'));

// 12. 历史裁剪
const history = Array.from({ length: 20 }, (_, index) => ({ role: index % 2 ? 'assistant' : 'user', text: `第${index}轮` }));
const formatted = formatHistory(history);
assert.ok(formatted.split('\n').length <= 6, '历史必须裁剪');
assert.equal(formatted.includes('第0轮'), false);

// 13. 界面规则摘要不泄露校验正则
const ui = rulesForUi(rules);
assert.equal('checks' in ui, false);
assert.ok(Array.isArray(ui.sections));
assert.ok(ui.quick_prompts.length >= 3);

// 14. 草稿模式：详情块剥离、白名单清洗、提示词带入草稿
const draftPrompt = buildSystemPrompt(rules, { analysis, evidence, draft: sanitizeDraftContext({
  draft_id: 'DRF-1', title: '左小腿创口筛查', status: 'draft', details: { site: '左小腿外侧', patient_name: '张三' },
  supplements: [{ text: '两周，有渗液' }, '正在用碘伏换药'],
}) });
assert.ok(draftPrompt.includes('左小腿创口筛查') && draftPrompt.includes('创口部位：左小腿外侧'), '提示词必须带入草稿标题与详情');
assert.equal(draftPrompt.includes('张三'), false, '草稿上下文不得带入身份字段');
assert.ok(draftPrompt.includes('正在用碘伏换药'), '补充记录应进入提示词');
assert.equal(sanitizeDraftContext({ title: '无编号' }), null, '缺少 draft_id 不进入草稿模式');

const split = splitDetailBlock('好的，已记录创口位置与病程。\n<<<DETAIL>>>{"site":"左小腿外侧","duration":"两周","patient_name":"张三"}<</DETAIL>>>');
assert.equal(split.text, '好的，已记录创口位置与病程。');
assert.deepEqual(split.details, { site: '左小腿外侧', duration: '两周' }, '只保留白名单字段');
const unclosed = splitDetailBlock('已记录。\n<<<DETAIL>>>{"site":"足背"');
assert.equal(unclosed.text, '已记录。', '未闭合的详情块必须整体剥离');
assert.equal(JSON.stringify(unclosed.details), '{}');
const fenced = splitDetailBlock('已记录。\n<<<DETAIL>>>```json\n{"symptoms":"渗液"}\n```<</DETAIL>>>');
assert.deepEqual(fenced.details, { symptoms: '渗液' }, '容忍代码围栏');
// 详情块不进入安全校验：用户陈述“正在用头孢”不应导致回答被拦截
const withBlock = validateAnswer(splitDetailBlock('了解，继续观察即可。\n<<<DETAIL>>>{"treatment":"正在用头孢"}<</DETAIL>>>').text, { rules, analysis });
assert.equal(withBlock.ok, true, JSON.stringify(withBlock.violations));
// 无草稿块时原文不受影响
assert.equal(splitDetailBlock('普通回答，不涉及提取。').text, '普通回答，不涉及提取。');

console.log('ASSISTANT_RULES_TESTS_OK');
