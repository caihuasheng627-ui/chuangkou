// Lightweight render smoke test for the DSH client bundle (no browser required).
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

let clientModule;
let Workstation;
let NavigationIcon;
let registeredSlots = [];
let stateIndex = 0;
let initialTab = 'screen';
let assistantOpen = false;
let assistantMessages = [];
let assistantRules = null;
let assistantRulesOpen = false;
let drafts = [];
let draftView = 'list';
let activeDraft = null;
let saveDialog = false;
let pendingDetails = null;
let patients = [];
let activePatient = null;
let liveStatus = null;
let liveConnected = false;
const React = {
  Fragment: 'Fragment',
  createElement(type, props, ...children) {
    const next = { ...(props || {}), children };
    if (typeof type === 'function') return type(next);
    return { type, props: next };
  },
  useState(initial) {
    const index = stateIndex++;
    let value = typeof initial === 'function' ? initial() : initial;
    if (index === 0) value = true; // native main panels render regardless of the legacy modal state
    if (index === 1) value = initialTab;
    if (index === 4) value = drafts; // 报告中心草稿列表
    if (index === 7) value = assistantOpen; // optional assistant side panel
    if (index === 8) value = assistantMessages;
    if (index === 11) value = assistantRules;
    if (index === 12) value = assistantRulesOpen;
    if (index === 17) value = draftView;
    if (index === 18) value = activeDraft;
    if (index === 19) value = saveDialog;
    if (index === 21) value = pendingDetails;
    if (index === 22) value = patients;
    if (index === 23) value = activePatient;
    if (index === 28) value = liveStatus; // 实时采集状态
    if (index === 29) value = liveConnected; // 是否已连接相机
    return [value, () => {}];
  },
  useRef: (value) => ({ current: value }),
  useEffect: () => {},
};

const sandbox = {
  console,
  window: {
    __ModuleLoader__: { load(definition) { clientModule = definition.factory(() => React); } },
    setTimeout: () => 0,
    addEventListener: () => {},
    removeEventListener: () => {},
  },
};
vm.createContext(sandbox);
const source = fs.readFileSync(path.join(__dirname, '..', 'client.js'), 'utf8');
vm.runInContext(source, sandbox, { filename: 'client.js' });

const ctx = {
  effect: (fn) => fn(),
  locale: { register: () => {}, bind: () => key => key },
  slots: {
    inject: (_name, callback) => callback(),
    register: (meta, component) => {
      registeredSlots.push(meta.name);
      if (meta.name === 'main') Workstation = component;
      if (meta.name === 'sidebar.panellist') NavigationIcon = component;
    },
  },
};
clientModule.apply(ctx);
if (typeof Workstation !== 'function' || typeof NavigationIcon !== 'function') throw new Error('Native panel or navigation icon was not registered');
if (!registeredSlots.includes('main') || !registeredSlots.includes('sidebar.panellist')
  || registeredSlots.includes('conversation.input.dock') || registeredSlots.includes('shell.overlay')) {
  throw new Error(`Unexpected slot registration: ${registeredSlots.join(', ')}`);
}
console.log('SLOT_OK native-main-and-sidebar-navigation');

for (const tab of ['screen', 'archive', 'trend', 'reports', 'evidence']) {
  stateIndex = 0;
  initialTab = tab;
  assistantOpen = false;
  const tree = Workstation();
  if (!tree) throw new Error(`Empty render for ${tab}`);
  console.log(`RENDER_OK ${tab}`);
}

// 侧边对话面板：空态 + 带问答与规则抽屉
stateIndex = 0;
initialTab = 'screen';
assistantOpen = true;
assistantMessages = [];
assistantRules = null;
assistantRulesOpen = false;
const panelTree = Workstation();
if (!panelTree) throw new Error('Empty render for assistant panel');
function findNode(node, predicate, parent = null) {
  if (!node || typeof node !== 'object') return null;
  if (predicate(node)) return { node, parent };
  const children = node.props && node.props.children;
  for (const child of Array.isArray(children) ? children : [children]) {
    const found = findNode(child, predicate, node);
    if (found) return found;
  }
  return null;
}
const workspaceResult = findNode(panelTree, node => node.props && node.props['aria-label'] === '创口热成像工作站');
if (!workspaceResult || workspaceResult.node.props.role !== 'region'
  || workspaceResult.node.props.style.width !== '100%' || workspaceResult.node.props.style.height !== '100%'
  || workspaceResult.node.props.style.boxShadow !== 'none' || workspaceResult.node.props.style.borderRadius !== 0) {
  throw new Error('Workstation is not rendered as a borderless native main region');
}
const modalMask = findNode(panelTree, node => node.props && node.props.style && node.props.style.position === 'fixed' && node.props.style.inset === 0);
if (modalMask) throw new Error('Native workstation must not render a fixed modal mask');
const legacyLauncher = findNode(panelTree, node => node.props && node.props.title === '在当前对话中展开创口热成像工作站');
if (legacyLauncher) throw new Error('Native workstation must not render the conversation dock launcher');
console.log('NATIVE_OK full-height-borderless-main-region');
const asideResult = findNode(panelTree, node => node.props && node.props.id === 'wound-clinic-assistant');
const mainResult = findNode(panelTree, node => node.type === 'main');
if (!asideResult || !mainResult || asideResult.parent !== mainResult.parent) {
  throw new Error('Assistant aside must be a sibling of main, not nested inside the scrolling content');
}
console.log('LAYOUT_OK assistant-aside-is-main-sibling');
console.log('RENDER_OK assistant-empty');

assistantOpen = false;
stateIndex = 0;
const closedTree = Workstation();
const opener = findNode(closedTree, node => node.props && node.props['aria-label'] === '展开循证对话');
if (!opener || opener.node.type !== 'button') throw new Error('Collapsed right-edge assistant opener is missing');
console.log('LAYOUT_OK collapsed-right-edge-opener');
assistantOpen = true;

assistantMessages = [
  { id: 'u1', role: 'user', text: '这个 ΔT 说明什么？' },
  {
    id: 'a1', role: 'assistant',
    text: '结论：本地规则判定为显著热异常 · 感染风险增高，ΔT +2.28°C。\n依据：温度不能替代病原学（E002）。\n局限：单次测量存在假阳性。\n下一步：同条件复测。',
    meta: {
      rule: { level: 'high', label: '显著热异常 · 感染风险增高', delta_t_c: 2.28 },
      modelUsed: false, reason: 'rule_violation', engine: 'local-rules',
      violations: [{ code: 'diagnosis', message: '出现确诊性结论', snippet: '已确诊感染' }],
    },
  },
];
assistantRules = {
  version: 'physician-side-chat-v1', updated_at: '2026-11-23', role: '创口热成像辅助筛查医师助手',
  identity: '只解释不确诊。', scope: '创口温度筛查。',
  sections: [{ id: 'authority', title: '判断归属', items: ['等级只能引用本地结果。', '不得改写等级。'] }],
  quick_prompts: ['解释当前 ΔT', '需要复测吗'], enforcement: ['提示词', '服务端校验'], disclaimer: '辅助筛查，不替代临床诊断。',
};
assistantRulesOpen = true;
stateIndex = 0;
const fullTree = Workstation();
if (!fullTree) throw new Error('Empty render for assistant messages + rules');
console.log('RENDER_OK assistant-messages-rules');

// 原生导航图标必须可渲染，且原生主页面不包含“关闭/收起工作站”的弹窗控制。
const navIconTree = NavigationIcon({ size: 20, active: true });
if (!navIconTree) throw new Error('Native sidebar navigation icon did not render');
const legacyClose = findNode(fullTree, node => node.props && (node.props.title === '关闭工作站' || node.props.title === '收起工作站'));
if (legacyClose) throw new Error('Native main panel must not contain modal close controls');
console.log('NATIVE_OK sidebar-icon-and-no-modal-controls');

// 模型余额不足应显示中文原因，不把 ACCOUNT_QUOTA 原始错误直接抛给用户。
assistantMessages = [
  ...assistantMessages,
  {
    id: 'a-quota', role: 'assistant',
    text: '结论：本地规则判定为显著热异常。\n依据：E003、E004。\n局限：单次热像存在假阳性。\n下一步：同条件复测。',
    meta: {
      rule: { level: 'high', label: '显著热异常 · 感染风险增高', delta_t_c: 2.28 },
      modelUsed: false, reason: 'ACCOUNT_QUOTA', engine: 'local-rules', detail: 'Insufficient Balance (request_id: test)', violations: [],
    },
  },
];
assistantRulesOpen = false;
stateIndex = 0;
const quotaTree = Workstation();
function collectText(node) {
  if (node === null || node === undefined || typeof node === 'boolean') return '';
  if (Array.isArray(node)) return node.map(collectText).join(' ');
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (!node || typeof node !== 'object') return '';
  const children = node.props && node.props.children;
  return (Array.isArray(children) ? children : [children]).map(collectText).join(' ');
}
const quotaText = collectText(quotaTree);
if (quotaText.includes('ACCOUNT_QUOTA') || !quotaText.includes('模型账户余额不足')) {
  throw new Error('Quota fallback reason was not translated for the user');
}
console.log('QUOTA_OK friendly-model-balance-fallback');

if (!source.includes('assistantBusy || assistantRequestRef.current')) {
  throw new Error('Synchronous duplicate-request guard is missing');
}
console.log('GUARD_OK duplicate-assistant-requests-blocked');

// ===== 草稿工作流：筛查 → 命名草稿 → 报告中心（第 2 位）→ 侧边对话补充 → 患者档案 =====
stateIndex = 0; initialTab = 'screen'; assistantOpen = false; assistantRulesOpen = false; saveDialog = false;
const navTree = Workstation();
const navText = collectText(findNode(navTree, node => node.type === 'nav').node);
const navOrder = ['实时筛查', '报告中心', '患者档案', '随访趋势', '医学知识库'].map(label => navText.indexOf(label));
if (!navOrder.every((at, i) => at >= 0 && (i === 0 || at > navOrder[i - 1]))) throw new Error(`Tab order is wrong: ${navText}`);
if (!findNode(navTree, node => node.type === 'button' && collectText(node) === '保存草稿')) throw new Error('Save-draft button is missing on screening page');
if (findNode(navTree, node => node.type === 'button' && collectText(node) === '生成报告草稿')) throw new Error('Legacy download-draft button must be removed');
console.log('WORKFLOW_OK reports-tab-second-save-draft-button');

saveDialog = true; stateIndex = 0;
const dialogTree = Workstation();
const dialogNode = findNode(dialogTree, node => node.props && node.props.role === 'dialog' && node.props['aria-label'] === '命名并保存草稿');
if (!dialogNode || dialogNode.node.props.style.position === 'fixed') throw new Error('Draft naming dialog missing or rendered as a fixed overlay');
saveDialog = false;

const baseDraft = {
  draft_id: 'DRF-TEST-0001', title: '左小腿创口筛查', status: 'draft', patient_ref: null, patient_name: null,
  measurement_id: 'MEAS-DEMO-0001', created_at: '2026-11-23T23:00:00+08:00', updated_at: '2026-11-23T23:05:00+08:00',
  quality_gate: 'passed', blocked_message: null,
  rule_result: { level: 'high', label: '显著热异常（感染风险增高）', delta_t_c: 2.28, threshold_version: 'wound-delta-v1' },
  delta_t_c: 2.28, detail_count: 2, supplement_count: 1, chat_count: 4,
};
const DEMO_REF = { measurement_id: 'MEAS-DEMO-0001', patient_ref: 'DEMO-001', captured_at: '2026-11-23T10:25:38+08:00',
  device: { model: 'HM-TB421-3XF' }, quality: {},
  metrics: { t_wound_mean_c: 34.79, t_ref_far_c: 32.51, delta_t_c: 2.28, area_ratio: 0.112 } };
drafts = [baseDraft, { ...baseDraft, draft_id: 'DRF-TEST-0000', title: '足背创口复查', status: 'archived', patient_ref: 'PT-0001', patient_name: '患者01' }];
initialTab = 'reports'; draftView = 'list'; activeDraft = null; assistantOpen = false; stateIndex = 0;
const listText = collectText(Workstation());
if (!listText.includes('左小腿创口筛查') || !listText.includes('已归档 · 患者01') || !listText.includes('显著热异常（感染风险增高）')) {
  throw new Error('Draft list did not render titles, archived patient and rule label');
}
console.log('WORKFLOW_OK draft-list-renders-status-and-rule');

activeDraft = { ...baseDraft, measurement: DEMO_REF, analysis: {},
  details: { site: '左小腿外侧', duration: '两周' },
  supplements: [{ at: '2026-11-23T23:05:00+08:00', text: '创口在左小腿外侧，两周了', source: 'chat', fields: ['site', 'duration'] }], chat: [] };
draftView = 'detail'; pendingDetails = { fields: { symptoms: '少量渗液' }, question: '有少量渗液' }; assistantOpen = true; stateIndex = 0;
const detailTree = Workstation();
const detailText = collectText(detailTree);
for (const expected of ['保存为患者档案', '补充详情', '补充记录', '草稿：左小腿创口筛查', '创面表现：少量渗液', '写入草稿', '对话提取']) {
  if (!detailText.includes(expected)) throw new Error(`Draft detail is missing: ${expected}`);
}
if (!findNode(detailTree, node => node.type === 'button' && collectText(node) === '保存为患者档案')) throw new Error('Archive button missing');
if (findNode(detailTree, node => node.props && node.props['aria-label'] === '展开循证对话')) throw new Error('Assistant opener must be hidden while panel is open');
console.log('WORKFLOW_OK draft-detail-with-extracted-details-card');

activeDraft = { ...activeDraft, status: 'archived', patient_ref: 'PT-0001', patient_name: '患者01' }; pendingDetails = null; stateIndex = 0;
const archivedText = collectText(Workstation());
if (!archivedText.includes('查看患者档案') || !archivedText.includes('已归档（只读）') || archivedText.includes('保存为患者档案')) {
  throw new Error('Archived draft must be read-only with a link to the patient archive');
}
console.log('WORKFLOW_OK archived-draft-readonly');

activeDraft = null; draftView = 'list'; assistantOpen = false; initialTab = 'archive';
patients = [{ patient_ref: 'PT-0001', display_name: '患者01', created_at: '2026-11-23T23:10:00+08:00', measurement_count: 1 }];
activePatient = patients[0]; stateIndex = 0;
const archiveText = collectText(Workstation());
if (!archiveText.includes('患者01') || !archiveText.includes('PT-0001') || !archiveText.includes('暂无测量记录')) throw new Error('Patient archive did not render');
console.log('WORKFLOW_OK patient-archive-renders');

// 实时筛查：未连接时给连接入口，已连接时播 MJPEG 流并显示实时温度。
activeDraft = null; assistantOpen = false; initialTab = 'screen'; liveConnected = false; liveStatus = null; stateIndex = 0;
const liveIdleText = collectText(Workstation());
if (!liveIdleText.includes('连接摄像头') || !liveIdleText.includes('未开始实时采集')) throw new Error('Live placeholder is missing when the camera is not connected');

liveConnected = true;
liveStatus = { ok: true, source: 'y16', has_temperature: true, calibrated: true, width: 640, height: 512, fps: 8.5,
  temperatures: { t_min_c: 31.2, t_max_c: 38.4, delta_t_c: 2.31, t_wound_mean_c: 35.4, t_ref_far_c: 33.1 }, roi: [10, 10, 100, 90] };
stateIndex = 0;
const liveTree = Workstation();
const liveImg = findNode(liveTree, node => node.type === 'img' && String(node.props.src || '').includes('/wound-clinic/live/stream'));
if (!liveImg) throw new Error('Live MJPEG frame is not rendered when connected');
const liveText = collectText(liveTree);
if (!liveText.includes('Y16 · 实时温度') || !liveText.includes('8.5 fps') || !liveText.includes('Tmax 38.4')) throw new Error(`Live status text missing: ${liveText.slice(0, 400)}`);
liveConnected = false; liveStatus = null;
console.log('LIVE_OK placeholder-and-mjpeg-frame');
console.log('CLIENT_RENDER_SMOKE_OK');
