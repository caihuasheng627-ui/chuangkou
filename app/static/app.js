const DEFAULT_WOUND = { x: 0.585, y: 0.433, w: 0.08, h: 0.1 };
const DEFAULT_REF = { x: 0.28, y: 0.36, w: 0.14, h: 0.2 };
const DETAIL_LABELS = {
  site: "创口部位",
  duration: "病程 / 持续时间",
  symptoms: "创面表现",
  treatment: "处理与用药史",
  notes: "其他备注",
};
const REASON_LABEL = {
  offline_rule_mode: "离线规则模式",
  rule_violation: "安全校验已拦截",
  AUTH: "API 鉴权失败",
  ACCOUNT_QUOTA: "模型余额不足",
  RATE_LIMIT: "接口限流",
  llm_unavailable: "模型服务不可用",
};

const rois = {
  wound: { ...DEFAULT_WOUND },
  ref: { ...DEFAULT_REF },
};

let drawMode = "wound";
let drag = null;
let autoFollow = true;
let viewMode = "original";
let hasTemperature = false;
let hasEstimatedTemp = false;
let measureState = "idle";
let lastProbeAt = 0;
let isHovering = false;
let probeSeq = 0;
let stateVersion = 0;
let lastState = null;
let lastRecordsData = null;
let lastLiveSource = "synthetic";
let activeReplayPath = "";
let pinnedSpot = null;
let toastTimer = null;

// 5 栏工作站与临床/循证对话状态
let activePage = "screen";
let importedMeasurement = null;
let importedAnalysis = null;
let clinicData = null;
let activeDraft = null;
let activePatientRef = "";
let focusEvidenceId = "";
let assistantRules = null;
let assistantConfig = null;
let assistantMessages = [];
let assistantBusy = false;
let pendingDetails = null;

/* ===== DOM 引用（与 index.html 严格一一对应） ===== */
const connBadgeEl = document.querySelector("#conn-badge");
const sourceEl = document.querySelector("#source");
const distanceEl = document.querySelector("#distance");
const emissivityEl = document.querySelector("#emissivity");
const distBtns = [...document.querySelectorAll(".dist-btn")];
const navBtns = [...document.querySelectorAll(".nav-item")];
const viewBtns = [...document.querySelectorAll("#view-tabs .seg-btn")];
const pages = {
  screen: document.querySelector("#page-screen"),
  reports: document.querySelector("#page-reports"),
  archive: document.querySelector("#page-archive"),
  trend: document.querySelector("#page-trend"),
  evidence: document.querySelector("#page-evidence"),
};

const navDraftsBadgeEl = document.querySelector("#nav-drafts-badge");
const navPatientsBadgeEl = document.querySelector("#nav-patients-badge");
const tabCountEl = document.querySelector("#tab-count");

const topbarSaveDraftBtn = document.querySelector("#topbar-save-draft");
const themeToggleBtn = document.querySelector("#theme-toggle");
const themeLabelEl = document.querySelector("#theme-label");
const assistantToggleBtn = document.querySelector("#assistant-toggle");

const importedBannerEl = document.querySelector("#imported-banner");
const importedBannerTitleEl = document.querySelector("#imported-banner-title");
const importedBannerSubEl = document.querySelector("#imported-banner-sub");
const importedSaveDraftBtn = document.querySelector("#imported-save-draft");
const importedClearBtn = document.querySelector("#imported-clear");
const loadExampleBtn = document.querySelector("#load-example-btn");
const importJsonBtn = document.querySelector("#import-json-btn");
const importJsonFileEl = document.querySelector("#import-json-file");

const frame = document.querySelector("#frame");
const canvas = document.querySelector("#overlay");
const viewport = document.querySelector("#viewport");
const scaleEl = document.querySelector("#scale");
const scaleTopEl = document.querySelector("#scale-top");
const scaleBottomEl = document.querySelector("#scale-bottom");
const scaleBarEl = document.querySelector("#scale-bar");
const scaleTicksEl = document.querySelector("#scale-ticks");
const scaleWoundPin = document.querySelector("#scale-wound");
const scaleRefPin = document.querySelector("#scale-ref");

const probeEl = document.querySelector("#probe");
const poseChipEl = document.querySelector("#pose-chip");
const viewHintEl = document.querySelector("#view-hint");
const toastEl = document.querySelector("#toast");
const weightWrap = document.querySelector("#weight-wrap");
const weightEl = document.querySelector("#weight");
const modeBannerEl = document.querySelector("#mode-banner");
const modeBannerTextEl = document.querySelector("#mode-banner-text");
const resumeLiveBtn = document.querySelector("#resume-live");

const autoBtn = document.querySelector("#auto");
const modeWoundBtn = document.querySelector("#mode-wound");
const modeRefBtn = document.querySelector("#mode-ref");
const alignPoseBtn = document.querySelector("#align-pose");
const measureBtn = document.querySelector("#measure");
const measureLabelEl = document.querySelector("#measure-label");
const labToggleBtn = document.querySelector("#lab-toggle");
const labDrawerEl = document.querySelector("#lab-drawer");
const expGroupEl = document.querySelector("#exp-group");
const ntcDeltaEl = document.querySelector("#ntc-delta");
const expGroupLabEl = document.querySelector("#exp-group-lab");
const ntcDeltaLabEl = document.querySelector("#ntc-delta-lab");
const saveBtn = document.querySelector("#save");
const saveLabBtn = document.querySelector("#save-lab");

const heroCardEl = document.querySelector("#hero-card");
const gradeEl = document.querySelector("#grade");
const stabilityEl = document.querySelector("#stability");
const deltaEl = document.querySelector("#delta");
const deltaMaxBadgeEl = document.querySelector("#delta-max-badge");
const gaugePinEl = document.querySelector("#gauge-pin");
const cardWoundValEl = document.querySelector("#card-wound-val");
const cardWoundSubEl = document.querySelector("#card-wound-sub");
const cardRefValEl = document.querySelector("#card-ref-val");
const cardRefSubEl = document.querySelector("#card-ref-sub");
const kpiExtraValEl = document.querySelector("#kpi-extra-val");
const kpiExtraSubEl = document.querySelector("#kpi-extra-sub");
const clinicalRuleBadgeEl = document.querySelector("#clinical-rule-badge");
const regionsEl = document.querySelector("#regions");
const messageEl = document.querySelector("#message");

const physicsBoxEl = document.querySelector("#physics-box");
const physicsBadgeEl = document.querySelector("#physics-badge");
const physAreaEl = document.querySelector("#phys-area");
const physDiamEl = document.querySelector("#phys-diam");
const physSlopeEl = document.querySelector("#phys-slope");
const physHaloEl = document.querySelector("#phys-halo");
const physElongEl = document.querySelector("#phys-elong");
const radialBarsEl = document.querySelector("#radial-bars");
const matrixTagEl = document.querySelector("#matrix-tag");
const probeBtn = document.querySelector("#probe-btn");
const probeOutputEl = document.querySelector("#probe-output");
const linesEl = document.querySelector("#lines");

// 报告中心 DOM
const reportsListViewEl = document.querySelector("#reports-list-view");
const reportsDetailViewEl = document.querySelector("#reports-detail-view");
const reportsNewDraftBtn = document.querySelector("#reports-new-draft");
const clinicDraftsEl = document.querySelector("#clinic-drafts");
const draftEditTitleEl = document.querySelector("#draft-edit-title");
const draftGatePillEl = document.querySelector("#draft-gate-pill");
const draftBackBtn = document.querySelector("#draft-back-btn");
const draftKpiTwEl = document.querySelector("#draft-kpi-tw");
const draftKpiTrEl = document.querySelector("#draft-kpi-tr");
const draftKpiDtEl = document.querySelector("#draft-kpi-dt");
const draftKpiAreaEl = document.querySelector("#draft-kpi-area");
const draftRuleCardEl = document.querySelector("#draft-rule-card");
const draftRuleTitleEl = document.querySelector("#draft-rule-title");
const draftRuleBadgeEl = document.querySelector("#draft-rule-badge");
const draftGateNoteEl = document.querySelector("#draft-gate-note");
const draftSiteEl = document.querySelector("#draft-site");
const draftDurationEl = document.querySelector("#draft-duration");
const draftSymptomsEl = document.querySelector("#draft-symptoms");
const draftTreatmentEl = document.querySelector("#draft-treatment");
const draftNotesEl = document.querySelector("#draft-notes");
const draftSaveDetailsBtn = document.querySelector("#draft-save-details");
const draftOpenChatBtn = document.querySelector("#draft-open-chat");
const draftSupplementsListEl = document.querySelector("#draft-supplements-list");
const draftArchiveHintEl = document.querySelector("#draft-archive-hint");
const draftArchiveBtn = document.querySelector("#draft-archive");

// 患者档案 & 趋势 & 知识库 DOM
const clinicPatientCountEl = document.querySelector("#clinic-patient-count");
const clinicPatientsEl = document.querySelector("#clinic-patients");
const patientHistoryTitleEl = document.querySelector("#patient-history-title");
const patientHistoryWrapEl = document.querySelector("#patient-history-wrap");
const clinicReportsEl = document.querySelector("#clinic-reports");
const clinicEvidenceEl = document.querySelector("#clinic-evidence");

const trendSummaryEl = document.querySelector("#trend-summary");
const trendChartEl = document.querySelector("#trend-chart");
const historyCountEl = document.querySelector("#history-count");
const historyListEl = document.querySelector("#history-list");
const groupStatsEl = document.querySelector("#group-stats");

// 循证对话抽屉 DOM
const assistantDrawerEl = document.querySelector("#assistant-drawer");
const assistantModeSubEl = document.querySelector("#assistant-mode-sub");
const assistantRulesBtn = document.querySelector("#assistant-rules-btn");
const assistantCfgBtn = document.querySelector("#assistant-cfg-btn");
const assistantCloseBtn = document.querySelector("#assistant-close-btn");
const assistantCtxDraftEl = document.querySelector("#assistant-ctx-draft");
const assistantCtxRuleEl = document.querySelector("#assistant-ctx-rule");
const assistantCtxDeltaEl = document.querySelector("#assistant-ctx-delta");
const assistantChatViewEl = document.querySelector("#assistant-chat-view");
const assistantRulesViewEl = document.querySelector("#assistant-rules-view");
const assistantCfgViewEl = document.querySelector("#assistant-cfg-view");
const assistantRulesBackBtn = document.querySelector("#assistant-rules-back");
const assistantCfgBackBtn = document.querySelector("#assistant-cfg-back");
const assistantRulesBodyEl = document.querySelector("#assistant-rules-body");
const assistantMessagesEl = document.querySelector("#assistant-messages");
const assistantPendingCardEl = document.querySelector("#assistant-pending-card");
const assistantPendingFieldsEl = document.querySelector("#assistant-pending-fields");
const assistantApplyPendingBtn = document.querySelector("#assistant-apply-pending");
const assistantDismissPendingBtn = document.querySelector("#assistant-dismiss-pending");
const assistantQuickEl = document.querySelector("#assistant-quick");
const assistantInputEl = document.querySelector("#assistant-input");
const assistantSendBtn = document.querySelector("#assistant-send-btn");

const llmBaseUrlEl = document.querySelector("#llm-base-url");
const llmModelEl = document.querySelector("#llm-model");
const llmApiKeyEl = document.querySelector("#llm-api-key");
const llmKeyStatusEl = document.querySelector("#llm-key-status");
const llmEnabledEl = document.querySelector("#llm-enabled");
const llmSaveBtn = document.querySelector("#llm-save-btn");
const llmClearKeyBtn = document.querySelector("#llm-clear-key-btn");

// 保存草稿弹窗 DOM
const draftModalEl = document.querySelector("#draft-modal");
const draftModalMetaEl = document.querySelector("#draft-modal-meta");
const draftModalTitleEl = document.querySelector("#draft-modal-title");
const draftModalCancelBtn = document.querySelector("#draft-modal-cancel");
const draftModalConfirmBtn = document.querySelector("#draft-modal-confirm");

/* ===== 工具函数 ===== */
function showToast(text, isError = false) {
  if (!toastEl) return;
  toastEl.textContent = text;
  toastEl.classList.toggle("is-err", isError);
  toastEl.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toastEl.hidden = true;
  }, 3200);
}

function post(url, body) {
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((res) => res.json());
}

async function sendAction(url, body) {
  const ver = ++stateVersion;
  const res = await post(url, body);
  if (res && res.state && ver === stateVersion) {
    renderState(res.state);
  }
  return res;
}

function fmtDelta(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}°C`;
}

function fmtTime(s) {
  return String(s || "").replace("T", " ").slice(0, 16) || "—";
}

function applyTheme(theme) {
  const next = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  if (themeLabelEl) {
    themeLabelEl.textContent = next === "dark" ? "亮色" : "暗色";
  }
  try {
    localStorage.setItem("chuangkou_theme", next);
  } catch (_err) {
    // 忽略隐私模式
  }
}

function initTheme() {
  let saved = "light";
  try {
    saved = localStorage.getItem("chuangkou_theme") || "light";
  } catch (_err) {
    saved = "light";
  }
  applyTheme(saved);
}

function syncDistPresets(mm) {
  const val = Math.round(Number(mm) || 300);
  for (const btn of distBtns) {
    btn.classList.toggle("is-on", Number(btn.dataset.mm) === val);
  }
}

function syncViewTabs(mode) {
  for (const btn of viewBtns) {
    btn.classList.toggle("is-on", btn.dataset.view === mode);
  }
}

function setActivePage(name) {
  if (!pages[name]) return;
  activePage = name;
  for (const btn of navBtns) {
    btn.classList.toggle("is-on", btn.dataset.page === name);
  }
  for (const [key, panel] of Object.entries(pages)) {
    panel.classList.toggle("is-on", key === name);
  }
  if (name === "reports" || name === "archive" || name === "evidence") {
    loadClinic(false);
  }
  if (name === "trend") {
    loadRecords(false);
  }
  if (name === "screen") {
    setTimeout(paint, 30);
  }
  updateAssistantContext();
}

function jumpToEvidence(evId) {
  focusEvidenceId = evId || "";
  setActivePage("evidence");
  renderEvidenceList((clinicData && clinicData.evidence) || []);
}

/* ===== 设备枚举 ===== */
async function loadDevices(notify = false) {
  const previous = sourceEl.value;
  try {
    const data = await fetch("/api/devices").then((res) => res.json());
    const devices = data.devices || [];
    const presets = [
      ...devices.map((item) => ({ value: item.id, label: item.label })),
      { value: "window:camera", label: "抓拍 Windows 相机窗口（兜底）" },
      { value: "file", label: "回放测试视频（伪彩 + OSD 双锚点反演）" },
      { value: "synthetic", label: "自检合成温度（+3.3 °C · 档 2）" },
      { value: "synthetic:mild", label: "自检模拟偏热（+1.4 °C · 档 1）" },
      { value: "synthetic:baseline", label: "自检空手基线（档 0）" },
    ];
    sourceEl.replaceChildren();
    for (const item of presets) {
      const opt = document.createElement("option");
      opt.value = item.value;
      opt.textContent = item.label;
      sourceEl.appendChild(opt);
    }
    const names = [...sourceEl.options];
    let state = {};
    try {
      state = await fetch("/api/state").then((res) => res.json());
    } catch (_err) {
      state = {};
    }
    const active = names.find((item) => item.value === state.source);
    const keep = names.find((item) => item.value === previous);
    const thermal = names.find((item) => /UVC|HIK|THERMAL/i.test(item.textContent));
    if (active) sourceEl.value = active.value;
    else if (keep) sourceEl.value = previous;
    else if (thermal) sourceEl.value = thermal.value;
    if (notify) {
      showToast(`已刷新来源列表（检测到 ${devices.length} 路摄像头）`);
    }
  } catch (_err) {
    if (notify) showToast("刷新设备列表失败，请检查本机服务", true);
  }
}

/* ===== 画布坐标、ROI 拖拽缩放与点温查询 ===== */
function contentBox() {
  const view = viewport.getBoundingClientRect();
  const image = frame.getBoundingClientRect();
  const nw = frame.naturalWidth || 0;
  const nh = frame.naturalHeight || 0;
  if (nw <= 0 || nh <= 0 || image.width <= 0 || image.height <= 0) {
    return { x: 0, y: 0, w: 0, h: 0 };
  }
  const scale = Math.min(image.width / nw, image.height / nh);
  const rw = nw * scale;
  const rh = nh * scale;
  return {
    x: image.left - view.left + (image.width - rw) / 2,
    y: image.top - view.top + (image.height - rh) / 2,
    w: rw,
    h: rh,
  };
}

function panelBox(side = "right") {
  const box = contentBox();
  if (viewMode !== "compare" || box.w < 10) return box;
  const imgW = frame.naturalWidth || 1290;
  const gap = 10 / imgW;
  const span = (1 - gap) / 2;
  if (side === "left") return { x: box.x, y: box.y, w: box.w * span, h: box.h };
  return { x: box.x + box.w * (span + gap), y: box.y, w: box.w * span, h: box.h };
}

function pointerRatio(event) {
  const full = contentBox();
  const view = viewport.getBoundingClientRect();
  if (full.w <= 1 || full.h <= 1) return { x: 0, y: 0, inside: false, panel: full };
  const px = event.clientX - view.left;
  const py = event.clientY - view.top;
  const rawX = (px - full.x) / full.w;
  const rawY = (py - full.y) / full.h;
  let inside = rawX >= 0 && rawX <= 1 && rawY >= 0 && rawY <= 1;
  let x = rawX;
  let activePanel = full;
  if (viewMode === "compare") {
    const imgW = frame.naturalWidth || 1290;
    const gap = 10 / imgW;
    const span = (1 - gap) / 2;
    if (rawX <= span) {
      x = rawX / span;
      activePanel = panelBox("left");
    } else if (rawX >= span + gap) {
      x = (rawX - span - gap) / span;
      activePanel = panelBox("right");
    } else {
      x = 0;
      inside = false;
    }
  }
  return {
    x: Math.min(1, Math.max(0, x)),
    y: Math.min(1, Math.max(0, rawY)),
    px,
    py,
    inside,
    panel: activePanel,
  };
}

function roiRectPx(roi, panel) {
  return {
    x: panel.x + roi.x * panel.w,
    y: panel.y + roi.y * panel.h,
    w: roi.w * panel.w,
    h: roi.h * panel.h,
  };
}

function hitTestRois(px, py, panel) {
  if (!panel || panel.w < 10) return null;
  const handleR = 11;
  for (const key of ["wound", "ref"]) {
    const roi = rois[key];
    if (!roi) continue;
    const r = roiRectPx(roi, panel);
    const corners = [
      ["nw", r.x, r.y],
      ["ne", r.x + r.w, r.y],
      ["sw", r.x, r.y + r.h],
      ["se", r.x + r.w, r.y + r.h],
    ];
    for (const [corner, cx, cy] of corners) {
      if (Math.hypot(px - cx, py - cy) <= handleR) {
        return { kind: "resize", target: key, corner };
      }
    }
    if (px >= r.x && px <= r.x + r.w && py >= r.y && py <= r.y + r.h) {
      return { kind: "move", target: key };
    }
  }
  return null;
}

function cursorForHit(hit) {
  if (!hit) return "crosshair";
  if (hit.kind === "move") return "grab";
  if (hit.corner === "nw" || hit.corner === "se") return "nwse-resize";
  return "nesw-resize";
}

function clampRoi(r) {
  const w = Math.min(1, Math.max(0.03, r.w));
  const h = Math.min(1, Math.max(0.03, r.h));
  const x = Math.min(1 - w, Math.max(0, r.x));
  const y = Math.min(1 - h, Math.max(0, r.y));
  return { x, y, w, h };
}

function drawBoxOn(ctx, box, roi, color, tag, showHandles) {
  if (!roi || box.w < 10) return;
  const x = box.x + roi.x * box.w;
  const y = box.y + roi.y * box.h;
  const w = roi.w * box.w;
  const h = roi.h * box.h;

  ctx.save();
  ctx.strokeStyle = "rgba(0,0,0,0.75)";
  ctx.lineWidth = 4;
  ctx.strokeRect(x, y, w, h);

  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.strokeRect(x, y, w, h);

  ctx.font = "600 11.5px 'Segoe UI', 'Microsoft YaHei', sans-serif";
  const textW = ctx.measureText(tag).width + 10;
  const pillY = y >= 22 ? y - 20 : y + 4;
  ctx.fillStyle = "rgba(10, 18, 24, 0.86)";
  ctx.fillRect(x, pillY, textW, 18);
  ctx.fillStyle = color;
  ctx.fillText(tag, x + 5, pillY + 13);

  if (showHandles) {
    const hs = 6;
    ctx.fillStyle = "#ffffff";
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.6;
    for (const [cx, cy] of [
      [x, y],
      [x + w, y],
      [x, y + h],
      [x + w, y + h],
    ]) {
      ctx.fillRect(cx - hs / 2, cy - hs / 2, hs, hs);
      ctx.strokeRect(cx - hs / 2, cy - hs / 2, hs, hs);
    }
  }
  ctx.restore();
}

function paint() {
  const rect = viewport.getBoundingClientRect();
  if (rect.width < 10 || rect.height < 10) return;
  const dpr = window.devicePixelRatio || 1;
  const cw = Math.round(rect.width * dpr);
  const ch = Math.round(rect.height * dpr);
  if (canvas.width !== cw || canvas.height !== ch) {
    canvas.width = cw;
    canvas.height = ch;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);

  const box = panelBox("right");
  if (box.w < 10) return;

  const showHandles = !autoFollow;
  const woundLabel =
    lastState?.wound?.mean !== undefined
      ? `创口 ${hasTemperature ? "" : "≈"}${lastState.wound.mean.toFixed(1)}°C`
      : "创口";
  const refLabel =
    lastState?.ref?.mean !== undefined
      ? `对照 ${hasTemperature ? "" : "≈"}${lastState.ref.mean.toFixed(1)}°C`
      : "对照";

  drawBoxOn(ctx, box, rois.ref, "#6bc2ff", refLabel, showHandles);
  drawBoxOn(ctx, box, rois.wound, "#ffb020", woundLabel, showHandles);
  if (drag && drag.kind === "draw" && drag.roi) {
    drawBoxOn(ctx, box, drag.roi, drag.target === "wound" ? "#ffb020" : "#6bc2ff", drag.target === "wound" ? "新建创口" : "新建对照", false);
  }

  if (pinnedSpot && (hasTemperature || hasEstimatedTemp)) {
    const px = box.x + pinnedSpot.x * box.w;
    const py = box.y + pinnedSpot.y * box.h;
    ctx.save();
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    ctx.arc(px, py, 6, 0, Math.PI * 2);
    ctx.moveTo(px - 10, py);
    ctx.lineTo(px + 10, py);
    ctx.moveTo(px, py - 10);
    ctx.lineTo(px, py + 10);
    ctx.stroke();
    const label = `${pinnedSpot.estimated ? "≈" : ""}${pinnedSpot.temp.toFixed(2)}°C`;
    ctx.font = "600 11.5px 'Segoe UI', sans-serif";
    const lw = ctx.measureText(label).width + 10;
    ctx.fillStyle = "rgba(8, 17, 24, 0.88)";
    ctx.fillRect(px + 10, py - 11, lw, 19);
    ctx.fillStyle = "#5eead4";
    ctx.fillText(label, px + 15, py + 2);
    ctx.restore();
  }
}

function setMode(target) {
  drawMode = target;
  modeWoundBtn.classList.toggle("is-on", target === "wound");
  modeRefBtn.classList.toggle("is-on", target === "ref");
}

canvas.addEventListener("mousedown", (event) => {
  if (event.button !== 0) return;
  const pt = pointerRatio(event);
  if (!pt.inside) return;
  const hit = hitTestRois(pt.px, pt.py, pt.panel);
  if (hit) {
    const orig = { ...rois[hit.target] };
    drag = {
      kind: hit.kind,
      target: hit.target,
      corner: hit.corner || "",
      x0: pt.x,
      y0: pt.y,
      orig,
      moved: false,
    };
    canvas.style.cursor = hit.kind === "move" ? "grabbing" : cursorForHit(hit);
  } else {
    drag = { kind: "draw", target: drawMode, x0: pt.x, y0: pt.y, roi: null, moved: false };
  }
});

canvas.addEventListener("mousemove", async (event) => {
  isHovering = true;
  const pt = pointerRatio(event);
  if (!drag) {
    canvas.style.cursor = pt.inside ? cursorForHit(hitTestRois(pt.px, pt.py, pt.panel)) : "default";
    if (!pt.inside || (!hasTemperature && !hasEstimatedTemp)) {
      probeEl.hidden = true;
      return;
    }
    const now = performance.now();
    if (now - lastProbeAt < 90) return;
    lastProbeAt = now;
    const seq = ++probeSeq;
    try {
      const res = await fetch(`/api/point?x=${pt.x.toFixed(4)}&y=${pt.y.toFixed(4)}`).then((r) => r.json());
      if (seq !== probeSeq || !isHovering) return;
      if (res && res.ok) {
        probeEl.hidden = false;
        probeEl.textContent = `${res.estimated ? "反演点温 ≈" : "点温 "}${res.temp.toFixed(2)} °C  (${res.px}, ${res.py})`;
      } else {
        probeEl.hidden = true;
      }
    } catch (_err) {
      // 忽略
    }
    return;
  }

  const dx = pt.x - drag.x0;
  const dy = pt.y - drag.y0;
  if (Math.hypot(dx, dy) > 0.008) drag.moved = true;

  if (drag.kind === "draw") {
    const x = Math.min(drag.x0, pt.x);
    const y = Math.min(drag.y0, pt.y);
    const w = Math.abs(pt.x - drag.x0);
    const h = Math.abs(pt.y - drag.y0);
    if (w >= 0.025 && h >= 0.025) drag.roi = clampRoi({ x, y, w, h });
  } else if (drag.kind === "move") {
    rois[drag.target] = clampRoi({
      x: drag.orig.x + dx,
      y: drag.orig.y + dy,
      w: drag.orig.w,
      h: drag.orig.h,
    });
  } else if (drag.kind === "resize") {
    const o = drag.orig;
    let x0 = o.x;
    let y0 = o.y;
    let x1 = o.x + o.w;
    let y1 = o.y + o.h;
    if (drag.corner.includes("w")) x0 = Math.min(x1 - 0.03, Math.max(0, pt.x));
    if (drag.corner.includes("e")) x1 = Math.max(x0 + 0.03, Math.min(1, pt.x));
    if (drag.corner.includes("n")) y0 = Math.min(y1 - 0.03, Math.max(0, pt.y));
    if (drag.corner.includes("s")) y1 = Math.max(y0 + 0.03, Math.min(1, pt.y));
    rois[drag.target] = clampRoi({ x: x0, y: y0, w: x1 - x0, h: y1 - y0 });
  }
  paint();
});

canvas.addEventListener("mouseleave", () => {
  isHovering = false;
  probeSeq += 1;
  probeEl.hidden = true;
  finishDrag(false);
});

async function commitManualRois() {
  const woundPayload = rois.wound || { ...DEFAULT_WOUND };
  const refPayload = rois.ref || { ...DEFAULT_REF };
  rois.wound = woundPayload;
  rois.ref = refPayload;
  await sendAction("/api/roi", { wound: woundPayload, ref: refPayload, manual: true });
}

async function finishDrag(allowPin = true) {
  if (!drag) return;
  const current = drag;
  drag = null;
  canvas.style.cursor = "crosshair";

  if (current.kind === "draw" && current.moved && current.roi) {
    rois[current.target] = current.roi;
    await commitManualRois();
  } else if ((current.kind === "move" || current.kind === "resize") && current.moved) {
    await commitManualRois();
  } else if (allowPin && current.kind === "draw" && (hasTemperature || hasEstimatedTemp)) {
    if (pinnedSpot && Math.hypot(pinnedSpot.x - current.x0, pinnedSpot.y - current.y0) < 0.04) {
      pinnedSpot = null;
    } else {
      try {
        const res = await fetch(`/api/point?x=${current.x0.toFixed(4)}&y=${current.y0.toFixed(4)}`).then((r) => r.json());
        if (res && res.ok) {
          pinnedSpot = { x: current.x0, y: current.y0, temp: res.temp, estimated: Boolean(res.estimated) };
        }
      } catch (_err) {
        // 忽略
      }
    }
  }
  paint();
}

canvas.addEventListener("mouseup", () => finishDrag(true));
window.addEventListener("resize", paint);
frame.addEventListener("load", paint);
frame.addEventListener("error", () => {
  setTimeout(() => {
    frame.src = `/stream.mjpg?t=${Date.now()}`;
  }, 1000);
});

/* ===== 实时筛查渲染 ===== */
function updateScaleBar(state) {
  const showScale = hasTemperature || viewMode === "isotherm";
  scaleEl.hidden = !showScale;
  if (!showScale) return;

  if (viewMode === "isotherm") {
    scaleBarEl.classList.add("is-isotherm");
    scaleTopEl.textContent = "+2.2°C";
    scaleBottomEl.textContent = "0°C";
    scaleTicksEl.replaceChildren();
    const t1 = document.createElement("span");
    t1.textContent = "+1.0";
    scaleTicksEl.appendChild(t1);
    scaleWoundPin.hidden = true;
    scaleRefPin.hidden = true;
    return;
  }

  scaleBarEl.classList.remove("is-isotherm");
  scaleTopEl.textContent = "40°C";
  scaleBottomEl.textContent = "28°C";
  scaleTicksEl.replaceChildren();
  for (const val of ["36", "32"]) {
    const sp = document.createElement("span");
    sp.textContent = val;
    scaleTicksEl.appendChild(sp);
  }
  const setPin = (el, temp) => {
    if (temp === null || temp === undefined) {
      el.hidden = true;
      return;
    }
    const pct = Math.min(100, Math.max(0, ((40 - temp) / 12) * 100));
    el.hidden = false;
    el.style.top = `${pct.toFixed(1)}%`;
  };
  setPin(scaleWoundPin, state.wound?.mean);
  setPin(scaleRefPin, state.ref?.mean);
}

function renderRegions(regions, selectedIndex) {
  if (!regions || regions.length <= 1 || !autoFollow) {
    regionsEl.hidden = true;
    regionsEl.replaceChildren();
    return;
  }
  regionsEl.hidden = false;
  regionsEl.replaceChildren();
  regions.forEach((r, idx) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `region-btn ${idx === selectedIndex ? "is-active" : ""}`;
    btn.dataset.idx = String(idx);
    btn.textContent = `热区 #${idx + 1} (+${r.delta.toFixed(1)}°C)`;
    regionsEl.appendChild(btn);
  });
}

function renderPhysics(physics) {
  if (!physics || !physics.radial_profile || physics.radial_profile.length === 0) {
    physicsBoxEl.hidden = true;
    return;
  }
  physicsBoxEl.hidden = false;
  physicsBadgeEl.textContent = physics.pattern || "—";
  physAreaEl.textContent = `${physics.fwhm_area_mm2.toFixed(1)} mm²`;
  physDiamEl.textContent = `等效直径 Ø ${physics.equiv_diam_mm.toFixed(1)} mm`;
  physSlopeEl.textContent = `${physics.decay_slope.toFixed(2)} °C/mm`;
  physHaloEl.textContent = `${physics.halo_ratio.toFixed(2)} ×`;
  physElongEl.textContent = `${physics.elongation.toFixed(2)}`;

  radialBarsEl.replaceChildren();
  const maxDt = Math.max(1.5, ...physics.radial_profile.map((p) => Math.max(0, p.delta)));
  for (const item of physics.radial_profile) {
    const row = document.createElement("div");
    row.className = "radial-row";
    const rLabel = document.createElement("span");
    rLabel.textContent = `r=${item.r_mm.toFixed(1)}mm`;
    const track = document.createElement("div");
    track.className = "radial-track";
    const fill = document.createElement("div");
    fill.className = "radial-fill";
    const pct = Math.min(100, Math.max(2, (Math.max(0, item.delta) / maxDt) * 100));
    fill.style.width = `${pct.toFixed(1)}%`;
    track.appendChild(fill);
    const dLabel = document.createElement("span");
    dLabel.textContent = `${item.delta >= 0 ? "+" : ""}${item.delta.toFixed(2)}°C`;
    row.append(rLabel, track, dLabel);
    radialBarsEl.appendChild(row);
  }
}

function renderClinicalPreview(state) {
  clinicalRuleBadgeEl.classList.remove("is-pass", "is-warn", "is-block");
  if (importedAnalysis) {
    if (importedAnalysis.ok && importedAnalysis.rule_result) {
      const lv = importedAnalysis.rule_result.level;
      clinicalRuleBadgeEl.classList.add(lv === "normal" ? "is-pass" : "is-warn");
      clinicalRuleBadgeEl.textContent = importedAnalysis.rule_result.label;
    } else {
      clinicalRuleBadgeEl.classList.add("is-block");
      clinicalRuleBadgeEl.textContent = "门禁阻断";
    }
    return;
  }
  if (!state.has_temperature || state.delta === null || state.delta === undefined) {
    clinicalRuleBadgeEl.classList.add("is-block");
    clinicalRuleBadgeEl.textContent = "无温度矩阵（门禁阻断）";
    return;
  }
  if (state.unstable || (state.frame_count || 0) < 5) {
    clinicalRuleBadgeEl.classList.add("is-block");
    clinicalRuleBadgeEl.textContent = state.unstable ? "画面波动（阻断）" : `稳态累积 ${state.frame_count || 0}/5 帧`;
    return;
  }
  const d = Number(state.delta);
  if (d < -0.6) {
    clinicalRuleBadgeEl.classList.add("is-warn");
    clinicalRuleBadgeEl.textContent = "局部低温（警惕灌注不足）";
  } else if (d < 0.6) {
    clinicalRuleBadgeEl.classList.add("is-pass");
    clinicalRuleBadgeEl.textContent = "未见明显热异常";
  } else if (d < 2.2) {
    clinicalRuleBadgeEl.classList.add("is-warn");
    clinicalRuleBadgeEl.textContent = "可疑炎症（建议复测）";
  } else {
    clinicalRuleBadgeEl.classList.add("is-warn");
    clinicalRuleBadgeEl.textContent = "显著热异常（感染风险增高）";
  }
}

function renderImportedBanner() {
  if (!importedMeasurement) {
    importedBannerEl.hidden = true;
    return;
  }
  importedBannerEl.hidden = false;
  const m = importedMeasurement.metrics || {};
  const ruleLabel = importedAnalysis?.rule_result?.label || "质量门禁未通过";
  importedBannerTitleEl.textContent = `${importedMeasurement.measurement_id || "导入测量"} · ${ruleLabel}`;
  importedBannerSubEl.textContent = `Tw ${Number(m.t_wound_mean_c || 0).toFixed(2)}°C · Tref ${Number(m.t_ref_far_c || 0).toFixed(2)}°C · ΔT ${fmtDelta(m.delta_t_c)}`;
}

function renderState(state) {
  lastState = state;
  hasTemperature = Boolean(state.has_temperature);
  hasEstimatedTemp = Boolean(!hasTemperature && state.osd);
  autoFollow = Boolean(state.auto);
  measureState = state.measure_state || "idle";

  if (state.source && state.source !== "replay") {
    lastLiveSource = state.source;
    activeReplayPath = "";
  }

  connBadgeEl.classList.remove("is-live", "is-warn", "is-err");
  if (state.error) {
    connBadgeEl.classList.add("is-err");
    connBadgeEl.textContent = `异常 · ${state.error}`;
  } else if (state.source === "replay") {
    connBadgeEl.classList.add("is-warn");
    connBadgeEl.textContent = "离线复盘模式";
  } else if (state.running) {
    connBadgeEl.classList.add("is-live");
    connBadgeEl.textContent = `运行中 · ${state.fps ? state.fps.toFixed(1) : "—"} fps`;
  } else {
    connBadgeEl.textContent = "待机";
  }

  if (state.source === "replay") {
    modeBannerEl.hidden = false;
    modeBannerEl.classList.add("is-replay");
    modeBannerTextEl.textContent = state.source_label || "历史温度帧复盘中";
    resumeLiveBtn.textContent = "返回实时流";
  } else if (measureState === "locked") {
    modeBannerEl.hidden = false;
    modeBannerEl.classList.remove("is-replay");
    modeBannerTextEl.textContent = `已锁定 ${state.frame_count || 10} 帧稳态均值`;
    resumeLiveBtn.textContent = "解除锁定";
  } else {
    modeBannerEl.hidden = true;
  }

  if (state.auto && !drag) {
    rois.wound = state.wound_roi || null;
    rois.ref = state.ref_roi || null;
    paint();
  } else if (!state.auto && !drag) {
    rois.wound = state.wound_roi || rois.wound;
    rois.ref = state.ref_roi || rois.ref;
    paint();
  } else if (drag) {
    paint();
  }

  if (state.view) {
    viewMode = state.view;
    syncViewTabs(state.view);
    if (state.view === "compare") {
      viewHintEl.hidden = false;
      viewHintEl.textContent = "左：原图  |  右：去背景";
    } else if (state.view === "isotherm") {
      viewHintEl.hidden = false;
      viewHintEl.textContent = "黄线 ≥ +1.0°C 关注  ·  红线 ≥ +2.2°C 告警";
    } else {
      viewHintEl.hidden = true;
    }
  }

  autoBtn.classList.toggle("is-on", autoFollow);
  weightWrap.hidden = hasTemperature;
  if (state.weight && weightEl && weightEl.value !== state.weight) {
    weightEl.value = state.weight;
  }
  if (state.source && [...sourceEl.options].some((item) => item.value === state.source)) {
    sourceEl.value = state.source;
  }
  if (document.activeElement !== distanceEl && state.distance_mm) {
    distanceEl.value = state.distance_mm;
    syncDistPresets(state.distance_mm);
  }
  if (document.activeElement !== emissivityEl && state.emissivity) {
    emissivityEl.value = Number(state.emissivity).toFixed(2);
  }

  if (state.pose && state.pose.hint) {
    poseChipEl.hidden = false;
    poseChipEl.textContent = state.pose.hint;
    poseChipEl.classList.toggle("is-warn", state.pose.status !== "姿态居中");
  } else {
    poseChipEl.hidden = true;
  }
  alignPoseBtn.disabled = !state.pose;

  measureBtn.disabled = !hasTemperature || (!state.running && measureState !== "locked");
  measureBtn.classList.toggle("is-locked", measureState === "locked");
  measureBtn.classList.toggle("is-collecting", measureState === "collecting");
  if (measureState === "locked") {
    measureLabelEl.textContent = state.source === "replay" ? "返回实时" : "恢复实时";
  } else if (measureState === "collecting") {
    measureLabelEl.textContent = `采帧 ${state.measure_progress || 0}/${state.measure_target || 10}`;
  } else {
    measureLabelEl.textContent = "稳定采 10 帧";
  }

  const canSave =
    hasTemperature &&
    state.delta !== null &&
    state.delta !== undefined &&
    !state.unstable &&
    Boolean(state.wound_roi) &&
    Boolean(state.ref_roi);
  saveBtn.disabled = !canSave;
  saveLabBtn.disabled = !canSave;

  // 若已导入测量 JSON，顶部 4 格 KPI 优先展示导入的临床测量，方便演示与审阅
  const mImp = importedMeasurement?.metrics || null;
  if (mImp) {
    const dt = Number(mImp.delta_t_c);
    const lv = !importedAnalysis?.ok ? "none" : dt >= 2.2 ? "2" : dt >= 1.0 ? "1" : "0";
    heroCardEl.dataset.level = lv;
    deltaEl.dataset.level = lv;
    deltaEl.classList.toggle("is-empty", !Number.isFinite(dt));
    deltaEl.textContent = Number.isFinite(dt) ? fmtDelta(dt) : "暂无温差";
    deltaMaxBadgeEl.hidden = !Number.isFinite(Number(mImp.t_wound_max_c));
    if (Number.isFinite(Number(mImp.t_wound_max_c))) {
      deltaMaxBadgeEl.textContent = `最高 ${Number(mImp.t_wound_max_c).toFixed(2)}°C`;
    }
    gradeEl.textContent = importedAnalysis?.rule_result?.label || "质量门禁未通过";
    stabilityEl.hidden = false;
    stabilityEl.className = `pill ${importedAnalysis?.ok ? "is-ok" : "is-warn"}`;
    stabilityEl.textContent = importedAnalysis?.ok ? "已导入 · 质控通过" : "已导入 · 门禁阻断";
    cardWoundValEl.textContent = Number.isFinite(Number(mImp.t_wound_mean_c)) ? `${Number(mImp.t_wound_mean_c).toFixed(2)} °C` : "—";
    cardWoundSubEl.textContent = "导入测量 · 创口区";
    cardRefValEl.textContent = Number.isFinite(Number(mImp.t_ref_far_c)) ? `${Number(mImp.t_ref_far_c).toFixed(2)} °C` : "—";
    cardRefSubEl.textContent = "导入测量 · 远端参考";
    kpiExtraValEl.textContent = Number.isFinite(Number(mImp.area_ratio)) ? `${(Number(mImp.area_ratio) * 100).toFixed(1)} %` : "—";
    kpiExtraSubEl.textContent = `${importedMeasurement.device?.model || "HM-TB421-3XF"} · 导入 JSON`;
    const pct = Number.isFinite(dt) ? Math.min(100, Math.max(0, (dt / 4.0) * 100)) : 0;
    gaugePinEl.hidden = !Number.isFinite(dt);
    gaugePinEl.style.left = `${pct.toFixed(1)}%`;
  } else {
    stabilityEl.classList.remove("is-ok", "is-warn", "is-locked");
    if (!hasTemperature) {
      if (state.osd && state.osd.anchor_mode) {
        stabilityEl.hidden = false;
        stabilityEl.classList.add("is-ok");
        stabilityEl.textContent = state.osd.anchor_mode;
      } else {
        stabilityEl.hidden = true;
      }
    } else {
      stabilityEl.hidden = false;
      if (measureState === "locked") {
        stabilityEl.classList.add("is-locked");
        stabilityEl.textContent = `已锁定 · ${(state.skin_spread ?? 0).toFixed(2)}°C`;
      } else if (state.unstable) {
        stabilityEl.classList.add("is-warn");
        stabilityEl.textContent = "波动 > 0.3°C";
      } else {
        stabilityEl.classList.add("is-ok");
        stabilityEl.textContent =
          state.skin_spread !== null && state.skin_spread !== undefined
            ? `稳定 · ${state.skin_spread.toFixed(2)}°C`
            : "稳定";
      }
    }

    gradeEl.textContent = state.grade_text || "等待画面";
    const level = state.grade === null || state.grade === undefined ? "none" : String(state.grade);
    heroCardEl.dataset.level = level;
    deltaEl.dataset.level = level;
    deltaEl.classList.toggle("is-empty", state.delta === null || state.delta === undefined);
    deltaEl.replaceChildren();
    if (state.delta === null || state.delta === undefined) {
      deltaEl.textContent = "暂无温差";
      deltaMaxBadgeEl.hidden = true;
      gaugePinEl.hidden = true;
    } else {
      const approx = hasTemperature ? "" : "≈";
      const sign = state.delta >= 0 ? "+" : "";
      deltaEl.append(document.createTextNode(`${approx}${sign}${state.delta.toFixed(2)}`));
      const unit = document.createElement("span");
      unit.textContent = "°C";
      deltaEl.appendChild(unit);
      if (state.delta_max !== null && state.delta_max !== undefined) {
        deltaMaxBadgeEl.hidden = false;
        deltaMaxBadgeEl.textContent = `峰值 ${approx}${state.delta_max >= 0 ? "+" : ""}${state.delta_max.toFixed(2)}°C`;
      } else {
        deltaMaxBadgeEl.hidden = true;
      }
      const pct = Math.min(100, Math.max(0, (state.delta / 4.0) * 100));
      gaugePinEl.hidden = false;
      gaugePinEl.style.left = `${pct.toFixed(1)}%`;
    }

    const prefix = hasTemperature ? "" : "≈";
    if (state.wound) {
      cardWoundValEl.textContent = `${prefix}${state.wound.mean.toFixed(2)} °C`;
      cardWoundSubEl.textContent = `峰值 ${state.wound.max.toFixed(2)} °C${state.wound.n ? ` · ${state.wound.n} px` : ""}`;
    } else {
      cardWoundValEl.textContent = "—";
      cardWoundSubEl.textContent = "未框选";
    }
    if (state.ref) {
      cardRefValEl.textContent = `${prefix}${state.ref.mean.toFixed(2)} °C`;
      cardRefSubEl.textContent = state.ref.n ? `有效皮肤 ${state.ref.n} px` : "正常皮肤对照";
    } else {
      cardRefValEl.textContent = "—";
      cardRefSubEl.textContent = "未框选";
    }

    kpiExtraValEl.textContent = state.mask_fraction ? `${Math.round(state.mask_fraction * 100)} %` : state.fps ? `${state.fps.toFixed(1)} fps` : "—";
    kpiExtraSubEl.textContent = `${state.capture_backend || state.source_label || "待机"} · ${state.distance_mm || 300}mm`;
  }

  renderImportedBanner();
  renderClinicalPreview(state);
  updateScaleBar(state);
  renderRegions(state.regions, state.selected_region || 0);
  renderPhysics(state.physics);

  matrixTagEl.textContent = state.matrix ? `${state.matrix.width}×${state.matrix.height}` : "伪彩流";
  const distText = `${state.distance_mm || 300} mm（${state.pixel_mm ? state.pixel_mm.toFixed(2) : "—"} mm/px）`;
  const rows = hasTemperature
    ? [
        ["采集后端 / 编码", state.capture_backend || state.source_label || "—"],
        ["工作距离 / 像元", distText],
        ["发射率 / 平均帧", `${Number(state.emissivity || 0.98).toFixed(2)} · ${state.frame_count || 0} 帧`],
        ["异常热区数", `${state.region_count || 0} 处`],
        ["全图最高温", state.frame_max !== null && state.frame_max !== undefined ? `${state.frame_max.toFixed(2)} °C` : "—"],
        ["画面帧率", state.fps ? `${state.fps.toFixed(1)} fps` : "—"],
      ]
    : [
        ["采集后端 / 编码", state.capture_backend || state.source_label || "—"],
        ["OSD 锚点 (Max / Cal)", state.osd ? `${state.osd.osd_max ?? "—"} °C / ${state.osd.osd_cal ?? "—"} °C` : "—"],
        ["分割方式", state.weight_label || "—"],
        ["分割置信度 / 占比", `${state.mask_confidence ? state.mask_confidence.toFixed(2) : "—"} · ${state.mask_fraction ? `${Math.round(state.mask_fraction * 100)}%` : "—"}`],
        ["画面 / 分割帧率", `${state.fps ? `${state.fps.toFixed(1)} fps` : "—"} / ${state.model_fps ? `${state.model_fps.toFixed(1)} fps` : "—"}`],
      ];

  linesEl.replaceChildren();
  for (const [name, value] of rows) {
    const dt = document.createElement("dt");
    dt.textContent = name;
    const dd = document.createElement("dd");
    dd.textContent = value;
    linesEl.append(dt, dd);
  }

  const extra = [state.message, state.error].filter(Boolean).join(" ");
  if (extra && extra !== state.grade_text) {
    messageEl.hidden = false;
    messageEl.textContent = extra;
  } else {
    messageEl.hidden = true;
  }
  updateAssistantContext();
}

/* ===== 趋势图、历史复盘与课程验收台 ===== */
function renderTrendChart(recordsDesc) {
  const ns = "http://www.w3.org/2000/svg";
  trendChartEl.replaceChildren();
  const points = [...(recordsDesc || [])].slice(0, 18).reverse();
  const W = 660;
  const H = 200;
  const padL = 38;
  const padR = 20;
  const padT = 18;
  const padB = 26;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;

  const mk = (tag, attrs = {}) => {
    const el = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
    return el;
  };

  if (points.length === 0) {
    const txt = mk("text", { x: W / 2, y: H / 2 + 4, "text-anchor": "middle", fill: "#7d909b", "font-size": "13" });
    txt.textContent = "采集稳定帧并归档至少 1 条记录后自动生成 ΔT 纵向趋势折线";
    trendChartEl.appendChild(txt);
    return;
  }

  const maxVal = Math.max(3.2, ...points.map((p) => p.delta + 0.4));
  const minVal = Math.min(0.0, ...points.map((p) => p.delta - 0.2));
  const yOf = (v) => padT + ((maxVal - v) / Math.max(0.5, maxVal - minVal)) * plotH;
  const xOf = (i) => (points.length === 1 ? padL + plotW / 2 : padL + (i / (points.length - 1)) * plotW);

  for (const [thr, color, label] of [
    [1.0, "#f59e0b", "1.0°C 关注"],
    [2.2, "#ef4444", "2.2°C 告警"],
  ]) {
    if (thr >= minVal && thr <= maxVal) {
      const y = yOf(thr);
      trendChartEl.appendChild(
        mk("line", { x1: padL, y1: y, x2: W - padR, y2: y, stroke: color, "stroke-opacity": "0.55", "stroke-dasharray": "5 4", "stroke-width": "1.2" })
      );
      const t = mk("text", { x: W - padR - 66, y: y - 5, fill: color, "font-size": "10.5" });
      t.textContent = label;
      trendChartEl.appendChild(t);
    }
  }

  const coords = points.map((p, i) => [xOf(i), yOf(p.delta)]);
  if (coords.length >= 2) {
    const dStr = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
    trendChartEl.appendChild(
      mk("path", { d: dStr, fill: "none", stroke: "#0f766e", "stroke-width": "2.6", "stroke-linejoin": "round", "stroke-linecap": "round" })
    );
  }

  points.forEach((rec, i) => {
    const [cx, cy] = coords[i];
    const color = rec.delta >= 2.2 ? "#ef4444" : rec.delta >= 1.0 ? "#f59e0b" : "#16a34a";
    const isActive = rec.npy_path && rec.npy_path === activeReplayPath;
    const circle = mk("circle", {
      cx: cx.toFixed(1),
      cy: cy.toFixed(1),
      r: isActive ? "6" : "4.5",
      fill: color,
      stroke: "#ffffff",
      "stroke-width": "2",
      style: "cursor:pointer",
    });
    const tip = document.createElementNS(ns, "title");
    tip.textContent = `${fmtTime(rec.time)} [${rec.group}] ΔT ${fmtDelta(rec.delta)}（点击复盘）`;
    circle.appendChild(tip);
    circle.addEventListener("click", () => replayRecord(rec));
    trendChartEl.appendChild(circle);
  });
}

async function replayRecord(rec) {
  const res = await sendAction("/api/replay", {
    npy_path: rec.npy_path,
    wound_px: rec.wound_px,
    ref_px: rec.ref_px,
  });
  if (res && res.ok) {
    activeReplayPath = rec.npy_path || "";
    importedMeasurement = null;
    importedAnalysis = null;
    setActivePage("screen");
    showToast(`已回载历史温度帧：${(rec.npy_path || "").split(/[\\/]/).pop()}`);
  } else {
    showToast(res?.error || "回载历史帧失败", true);
  }
}

async function loadRecords(notify = false) {
  try {
    const data = await fetch("/api/records").then((r) => r.json());
    if (!data || !data.ok) return;
    lastRecordsData = data;
    tabCountEl.textContent = String(data.total || 0);
    historyCountEl.textContent = `${data.total || 0} 条`;

    if (data.trend) {
      trendSummaryEl.textContent = data.trend.summary;
      trendSummaryEl.classList.toggle("is-alert", Boolean(data.trend.alert));
    }
    renderTrendChart(data.records || []);

    groupStatsEl.replaceChildren();
    const entries = Object.entries(data.groups || {});
    if (entries.length === 0) {
      const empty = document.createElement("p");
      empty.className = "empty-note";
      empty.textContent = "暂无实验归档数据。采集稳定温度帧后点击“归档记录”即可自动统计分组极差。";
      groupStatsEl.appendChild(empty);
    } else {
      for (const [gName, st] of entries) {
        const row = document.createElement("div");
        row.className = "group-row";
        const left = document.createElement("span");
        const ntcPart = st.ntc_mae !== null && st.ntc_mae !== undefined ? ` · NTC 误差 ${st.ntc_mae.toFixed(2)}°C` : "";
        left.textContent = `${gName} (n=${st.count}) 均 ${st.mean >= 0 ? "+" : ""}${st.mean.toFixed(2)}°C${ntcPart}`;
        const right = document.createElement("span");
        if (st.repeatability_ok === null || st.repeatability_ok === undefined) {
          right.className = "group-badge";
          right.textContent = "单次";
        } else if (st.repeatability_ok) {
          right.className = "group-badge is-ok";
          right.textContent = `极差 ${st.spread.toFixed(2)}°C 达标`;
        } else {
          right.className = "group-badge is-warn";
          right.textContent = `极差 ${st.spread.toFixed(2)}°C >0.3`;
        }
        row.append(left, right);
        groupStatsEl.appendChild(row);
      }
    }

    historyListEl.replaceChildren();
    const recs = (data.records || []).slice(0, 18);
    if (recs.length === 0) {
      const empty = document.createElement("p");
      empty.className = "empty-note";
      empty.textContent = "暂无 .npy 历史归档文件";
      historyListEl.appendChild(empty);
    } else {
      for (const rec of recs) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = `list-card-btn ${rec.npy_path && rec.npy_path === activeReplayPath ? "is-active" : ""}`;
        const main = document.createElement("div");
        main.className = "list-card-main";
        const title = document.createElement("strong");
        title.textContent = `[${rec.group}]  ${fmtTime(rec.time)}`;
        const sub = document.createElement("small");
        const areaStr = rec.hot_area_mm2 ? ` · 面积 ${rec.hot_area_mm2}mm²` : "";
        const ntcStr = rec.ntc_delta !== null && rec.ntc_delta !== undefined ? ` · NTC ${rec.ntc_delta}°C` : "";
        sub.textContent = `L=${rec.distance_mm}mm · ${rec.frames_averaged}帧${areaStr}${ntcStr}`;
        main.append(title, sub);

        const pill = document.createElement("span");
        pill.className = `gate-pill ${rec.delta >= 2.2 ? "is-block" : rec.delta >= 1.0 ? "is-warn" : "is-pass"}`;
        pill.textContent = `${fmtDelta(rec.delta)} · 复盘`;
        btn.append(main, pill);
        btn.addEventListener("click", () => replayRecord(rec));
        historyListEl.appendChild(btn);
      }
    }
    if (notify) showToast("已刷新历史记录与验收统计");
  } catch (_err) {
    if (notify) showToast("刷新历史记录失败", true);
  }
}

function buildMarkdownReport() {
  const data = lastRecordsData;
  if (!data || !data.total) return "";
  const lines = [
    "### 创口温差初筛 — 课程验收重复性统计表",
    "",
    "| 实验分组 | 样本数 N | ΔT 均值 (°C) | 标准差 SD (°C) | 极差 Spread (°C) | 重复性判定 (≤0.30°C) | NTC 平均偏差 (°C) |",
    "|---|---:|---:|---:|---:|---|---:|",
  ];
  for (const [gName, st] of Object.entries(data.groups || {})) {
    const verdict =
      st.repeatability_ok === null || st.repeatability_ok === undefined ? "单次测量" : st.repeatability_ok ? "达标" : "超差";
    const ntc = st.ntc_mae !== null && st.ntc_mae !== undefined ? st.ntc_mae.toFixed(2) : "—";
    lines.push(
      `| ${gName} | ${st.count} | ${st.mean >= 0 ? "+" : ""}${st.mean.toFixed(2)} | ${st.sd.toFixed(3)} | ${st.spread.toFixed(2)} | ${verdict} | ${ntc} |`
    );
  }
  return lines.join("\n");
}

async function copyMarkdownTable() {
  await loadRecords(false);
  const md = buildMarkdownReport();
  if (!md) {
    showToast("暂无可导出的验收记录，请先归档数据", true);
    return;
  }
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(md);
    } else {
      const ta = document.createElement("textarea");
      ta.value = md;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    showToast("已复制 Markdown 验收统计表到剪贴板");
  } catch (_err) {
    showToast("剪贴板写入受限，请使用“下载 CSV”", true);
  }
}

async function doSave() {
  const ntcRaw = ntcDeltaEl.value.trim();
  const payload = {
    group: expGroupEl.value,
    ntc_delta: ntcRaw === "" ? null : Number(ntcRaw),
  };
  const result = await post("/api/save", payload);
  if (result && result.ok) {
    showToast(`已归档 [${result.group}]（含 .npy 与 .png）`);
    loadRecords(false);
  } else {
    showToast(result?.error || "当前帧无法归档", true);
  }
}

/* ===== 设备编码探测 ===== */
async function runProbe() {
  probeBtn.disabled = true;
  probeOutputEl.hidden = false;
  probeOutputEl.textContent = "正在探测接入摄像头格式、视频编码与 16bit 温度流...";
  try {
    const res = await fetch("/api/probe").then((r) => r.json());
    if (!res || !res.ok) {
      probeOutputEl.textContent = "探测失败";
      return;
    }
    const lines = [res.summary || "探测完成"];
    for (const item of res.dshow_options || []) {
      lines.push(`\n[DirectShow] ${item.label}`);
      if (item.options && item.options.length) {
        for (const opt of item.options.slice(0, 8)) lines.push(`  ${opt}`);
      } else {
        lines.push("  （未列出扩展格式）");
      }
    }
    for (const p of res.opencv_probes || []) {
      if (!p.opened && p.mode_requested !== "default") continue;
      if (p.read_frames > 0) {
        lines.push(
          `[OpenCV cam:${p.camera} ${p.backend}/${p.mode_requested}] ${p.width_actual}×${p.height_actual} fourcc=${p.fourcc_actual} dtype=${p.dtype} range=[${p.raw_min}, ${p.raw_max}]`
        );
      } else if (p.opened) {
        lines.push(`[OpenCV cam:${p.camera} ${p.backend}/${p.mode_requested}] 打开但无帧`);
      }
    }
    probeOutputEl.textContent = lines.join("\n");
  } catch (_err) {
    probeOutputEl.textContent = "探测请求失败，请检查本机服务。";
  } finally {
    probeBtn.disabled = false;
  }
}

/* ===== 导入测量 JSON ===== */
async function loadExampleMeasurement() {
  try {
    const res = await fetch("/api/clinic/example").then((r) => r.json());
    if (!res || !res.ok) {
      showToast(res?.error?.message || "载入示例测量失败", true);
      return;
    }
    importedMeasurement = res.measurement;
    importedAnalysis = res.analysis;
    assistantMessages = [];
    renderAssistantMessages();
    if (lastState) renderState(lastState);
    else renderImportedBanner();
    showToast("已载入示例测量 JSON（MEAS-DEMO-0001），可体验保存草稿、循证对话与归档");
  } catch (_err) {
    showToast("载入示例 JSON 失败", true);
  }
}

async function handleImportJsonFile(file) {
  if (!file) return;
  try {
    const text = await file.text();
    const parsed = JSON.parse(text);
    const analysis = await post("/api/clinic/analyze", { measurement: parsed });
    importedMeasurement = parsed;
    importedAnalysis = analysis;
    assistantMessages = [];
    renderAssistantMessages();
    if (lastState) renderState(lastState);
    else renderImportedBanner();
    showToast(`已导入 ${file.name}（${analysis?.rule_result?.label || "质量门禁未通过"}）`);
  } catch (_err) {
    showToast("导入失败：请确认文件是有效的测量 JSON", true);
  } finally {
    importJsonFileEl.value = "";
  }
}

/* ===== 报告中心、患者档案与医学知识库 ===== */
function renderEvidenceList(items) {
  clinicEvidenceEl.replaceChildren();
  for (const ev of items || []) {
    const card = document.createElement("article");
    card.className = `evidence-card ${ev.evidence_id === focusEvidenceId ? "is-focus" : ""}`;
    const top = document.createElement("div");
    top.className = "list-card-tags";
    const idTag = document.createElement("span");
    idTag.className = "chip-tag is-teal";
    idTag.textContent = ev.evidence_id;
    const typeTag = document.createElement("span");
    typeTag.className = "chip-tag";
    typeTag.textContent = `${ev.type || ""} · ${ev.year || ""}`;
    top.append(idTag, typeTag);

    const h3 = document.createElement("h3");
    h3.textContent = ev.title || "";
    const p = document.createElement("p");
    p.textContent = ev.verified_excerpt || "";
    const pop = document.createElement("small");
    pop.textContent = `适用边界：${ev.population || "按原研究条件"}`;
    const link = document.createElement("a");
    link.href = ev.source_url || "#";
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = "查看原始文献来源 ↗";

    card.append(top, h3, p, pop, link);
    clinicEvidenceEl.appendChild(card);
  }
}

function renderDraftDetail(draft) {
  activeDraft = draft;
  if (!draft) {
    reportsDetailViewEl.hidden = true;
    reportsListViewEl.hidden = false;
    updateAssistantContext();
    return;
  }
  reportsListViewEl.hidden = true;
  reportsDetailViewEl.hidden = false;

  const archived = draft.status === "archived";
  const passed = draft.quality_gate === "passed";
  const m = draft.measurement?.metrics || {};
  const rule = draft.rule_result;

  draftEditTitleEl.value = draft.title || "";
  draftEditTitleEl.disabled = archived;

  draftGatePillEl.className = "gate-pill";
  if (archived) {
    draftGatePillEl.classList.add("is-arch");
    draftGatePillEl.textContent = `已归档 · ${draft.patient_name || draft.patient_ref || ""}`;
  } else if (passed) {
    draftGatePillEl.classList.add("is-pass");
    draftGatePillEl.textContent = "草稿 · 质控通过";
  } else {
    draftGatePillEl.classList.add("is-block");
    draftGatePillEl.textContent = "草稿 · 门禁阻断";
  }

  draftKpiTwEl.textContent = Number.isFinite(Number(m.t_wound_mean_c)) ? `${Number(m.t_wound_mean_c).toFixed(2)} °C` : "—";
  draftKpiTrEl.textContent = Number.isFinite(Number(m.t_ref_far_c)) ? `${Number(m.t_ref_far_c).toFixed(2)} °C` : "—";
  draftKpiDtEl.textContent = Number.isFinite(Number(m.delta_t_c))
    ? fmtDelta(m.delta_t_c)
    : Number.isFinite(Number(m.estimated_delta_t_c))
    ? `≈${fmtDelta(m.estimated_delta_t_c)}`
    : "—";
  draftKpiAreaEl.textContent = Number.isFinite(Number(m.area_ratio)) ? `${(Number(m.area_ratio) * 100).toFixed(1)} %` : "—";

  draftRuleCardEl.classList.toggle("is-normal", rule?.level === "normal");
  if (rule) {
    draftRuleTitleEl.textContent = `${rule.label}  ·  ΔT ${fmtDelta(rule.delta_t_c)}`;
    draftRuleBadgeEl.textContent = "非确诊 · 规则独占";
    draftGateNoteEl.textContent = `规则版本 ${rule.threshold_version || "wound-delta-v1"}；单次热像不构成感染确诊，须结合创面外观并同条件复测。`;
  } else {
    draftRuleTitleEl.textContent = "质量门禁未通过";
    draftRuleBadgeEl.textContent = "禁止归档";
    draftGateNoteEl.textContent = `阻断原因：${draft.blocked_message || "未获得有效温度矩阵或标定失效"}。请采集真实温度矩阵后另存草稿。`;
  }

  const d = draft.details || {};
  draftSiteEl.value = d.site || "";
  draftDurationEl.value = d.duration || "";
  draftSymptomsEl.value = d.symptoms || "";
  draftTreatmentEl.value = d.treatment || "";
  draftNotesEl.value = d.notes || "";
  for (const el of [draftSiteEl, draftDurationEl, draftSymptomsEl, draftTreatmentEl, draftNotesEl]) {
    el.disabled = archived;
  }
  draftSaveDetailsBtn.disabled = archived;
  draftArchiveBtn.disabled = archived ? false : !passed;
  draftArchiveBtn.textContent = archived ? "查看患者档案" : "保存为患者档案";
  draftArchiveHintEl.textContent = archived
    ? `已归档为 ${draft.patient_name || ""}（${draft.patient_ref || ""}），当前草稿只读锁定。`
    : "存入患者档案时自动编号（患者01、患者02…），写入只追加测量记录并生成带 SHA-256 哈希的 HTML 报告；仅质量门禁通过的草稿可归档。";

  draftSupplementsListEl.replaceChildren();
  const sups = draft.supplements || [];
  if (sups.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty-note";
    empty.textContent = "暂无补充记录。点击“打开循证对话”口述创口情况即可自动提取并确认写入。";
    draftSupplementsListEl.appendChild(empty);
  } else {
    for (const item of [...sups].reverse()) {
      const row = document.createElement("div");
      row.className = "list-card-btn";
      const main = document.createElement("div");
      main.className = "list-card-main";
      const title = document.createElement("strong");
      title.textContent = item.text;
      const sub = document.createElement("small");
      const fNames = (item.fields || []).map((k) => DETAIL_LABELS[k] || k).join("、");
      sub.textContent = `${fmtTime(item.at)}${fNames ? ` · 写入：${fNames}` : ""}`;
      main.append(title, sub);
      const tag = document.createElement("span");
      tag.className = "chip-tag";
      tag.textContent = item.source === "chat" ? "对话提取" : "手动";
      row.append(main, tag);
      draftSupplementsListEl.appendChild(row);
    }
  }

  // 加载随草稿保存的对话记录
  assistantMessages = (draft.chat || []).map((m, idx) => ({
    id: `draft-${draft.draft_id}-${idx}`,
    role: m.role,
    text: m.text,
    meta: null,
  }));
  pendingDetails = null;
  renderAssistantMessages();
  renderPendingDetails();
  updateAssistantContext();
}

async function openDraftById(draftId) {
  try {
    const res = await fetch(`/api/clinic/draft?draft_id=${encodeURIComponent(draftId)}`).then((r) => r.json());
    if (!res || !res.ok || !res.draft) {
      showToast(res?.error?.message || "打开草稿失败", true);
      return;
    }
    renderDraftDetail(res.draft);
  } catch (_err) {
    showToast("读取草稿详情失败", true);
  }
}

async function selectPatient(patientRef) {
  activePatientRef = patientRef;
  renderPatientList((clinicData && clinicData.patients) || []);
  patientHistoryTitleEl.textContent = `检测记录 · ${patientRef}`;
  try {
    const res = await fetch(`/api/clinic/patient/history?patient_ref=${encodeURIComponent(patientRef)}`).then((r) => r.json());
    if (!res || !res.ok) return;
    const rows = res.measurements || [];
    patientHistoryWrapEl.replaceChildren();
    if (rows.length === 0) {
      const empty = document.createElement("p");
      empty.className = "empty-note";
      empty.textContent = "该档案暂无测量记录";
      patientHistoryWrapEl.appendChild(empty);
    } else {
      const tbl = document.createElement("table");
      tbl.className = "data-table";
      const thead = document.createElement("thead");
      const hr = document.createElement("tr");
      for (const label of ["测量编号", "采集时间", "ΔT", "本地等级", "状态"]) {
        const th = document.createElement("th");
        th.textContent = label;
        hr.appendChild(th);
      }
      thead.appendChild(hr);
      const tbody = document.createElement("tbody");
      for (const item of rows) {
        const tr = document.createElement("tr");
        const cells = [
          item.measurement_id,
          fmtTime(item.captured_at),
          fmtDelta(item.metrics?.delta_t_c),
          item.rule_result?.label || "—",
          "已归档",
        ];
        cells.forEach((txt, idx) => {
          const td = document.createElement("td");
          if (idx === 4) {
            const pill = document.createElement("span");
            pill.className = `gate-pill ${item.rule_result?.level === "normal" ? "is-pass" : "is-warn"}`;
            pill.textContent = txt;
            td.appendChild(pill);
          } else {
            td.textContent = txt;
          }
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      }
      tbl.append(thead, tbody);
      patientHistoryWrapEl.appendChild(tbl);
    }

    renderReportList(res.reports || []);
  } catch (_err) {
    // 忽略
  }
}

function renderPatientList(patients) {
  clinicPatientsEl.replaceChildren();
  if (!patients.length) {
    const empty = document.createElement("p");
    empty.className = "empty-note";
    empty.textContent = "暂无患者档案。在报告中心归档任意通过质控的草稿即可自动建档（患者01）。";
    clinicPatientsEl.appendChild(empty);
    patientHistoryWrapEl.replaceChildren();
    return;
  }
  for (const p of patients) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `list-card-btn ${p.patient_ref === activePatientRef ? "is-active" : ""}`;
    const main = document.createElement("div");
    main.className = "list-card-main";
    const t = document.createElement("strong");
    t.textContent = `${p.display_name || p.patient_ref}`;
    const s = document.createElement("small");
    s.textContent = `${p.patient_ref} · 建档 ${fmtTime(p.created_at)}`;
    main.append(t, s);
    const pill = document.createElement("span");
    pill.className = "gate-pill is-arch";
    pill.textContent = `${p.measurement_count || 0} 次`;
    btn.append(main, pill);
    btn.addEventListener("click", () => selectPatient(p.patient_ref));
    clinicPatientsEl.appendChild(btn);
  }
}

function renderReportList(reports) {
  clinicReportsEl.replaceChildren();
  if (!reports.length) {
    const empty = document.createElement("p");
    empty.className = "empty-note";
    empty.textContent = "暂无可追溯 HTML 报告";
    clinicReportsEl.appendChild(empty);
    return;
  }
  for (const r of reports) {
    const link = document.createElement("a");
    link.className = "list-card-btn";
    link.href = `/api/clinic/report/${encodeURIComponent(r.report_id)}`;
    link.target = "_blank";
    link.rel = "noreferrer";
    const main = document.createElement("div");
    main.className = "list-card-main";
    const t = document.createElement("strong");
    t.textContent = r.report_id;
    const s = document.createElement("small");
    s.textContent = `${r.patient_ref} · ${r.measurement_id} · ${fmtTime(r.created_at)}`;
    main.append(t, s);
    const pill = document.createElement("span");
    pill.className = "gate-pill is-pass";
    pill.textContent = "打开 HTML 报告 ↗";
    link.append(main, pill);
    clinicReportsEl.appendChild(link);
  }
}

async function loadClinic(notify = false) {
  try {
    const data = await fetch("/api/clinic/summary").then((r) => r.json());
    if (!data || !data.ok) return;
    clinicData = data;
    const drafts = data.drafts || [];
    const patients = data.patients || [];
    const reports = data.reports || [];

    navDraftsBadgeEl.textContent = String(drafts.length);
    navPatientsBadgeEl.textContent = String(patients.length);
    clinicPatientCountEl.textContent = `${patients.length} 位患者`;

    clinicDraftsEl.replaceChildren();
    if (drafts.length === 0) {
      const empty = document.createElement("p");
      empty.className = "empty-note";
      empty.textContent = "报告中心暂无草稿。请在“实时筛查”采集温度帧或点击“示例 JSON”后保存草稿。";
      clinicDraftsEl.appendChild(empty);
    } else {
      for (const item of drafts) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "list-card-btn";
        const main = document.createElement("div");
        main.className = "list-card-main";
        const title = document.createElement("strong");
        title.textContent = item.title;
        const sub = document.createElement("small");
        sub.textContent = `${item.draft_id} · ${item.measurement_id || "—"} · 更新于 ${fmtTime(item.updated_at)}`;
        const tags = document.createElement("div");
        tags.className = "list-card-tags";
        if (item.rule_result) {
          const t1 = document.createElement("span");
          t1.className = `gate-pill ${item.rule_result.level === "normal" ? "is-pass" : "is-warn"}`;
          t1.textContent = `${item.rule_result.label} · ΔT ${fmtDelta(item.delta_t_c)}`;
          tags.appendChild(t1);
        } else {
          const t1 = document.createElement("span");
          t1.className = "gate-pill is-block";
          t1.textContent = "质量门禁未通过";
          tags.appendChild(t1);
        }
        if (item.detail_count > 0) {
          const t2 = document.createElement("span");
          t2.className = "chip-tag";
          t2.textContent = `详情 ${item.detail_count} 项`;
          tags.appendChild(t2);
        }
        main.append(title, sub, tags);

        const right = document.createElement("span");
        right.className = `gate-pill ${item.status === "archived" ? "is-arch" : "is-warn"}`;
        right.textContent = item.status === "archived" ? `已归档 · ${item.patient_name || item.patient_ref}` : "草稿 ›";
        btn.append(main, right);
        btn.addEventListener("click", () => openDraftById(item.draft_id));
        clinicDraftsEl.appendChild(btn);
      }
    }

    renderPatientList(patients);
    if (patients.length > 0) {
      const targetRef = patients.some((p) => p.patient_ref === activePatientRef) ? activePatientRef : patients[0].patient_ref;
      if (activePage === "archive") {
        await selectPatient(targetRef);
      } else {
        activePatientRef = targetRef;
        renderReportList(reports);
      }
    } else {
      renderReportList(reports);
    }

    renderEvidenceList(data.evidence || []);
    if (notify) showToast("已刷新临床草稿与档案");
  } catch (_err) {
    if (notify) showToast("刷新临床数据失败", true);
  }
}

/* ===== 保存草稿弹窗 ===== */
function openSaveDraftModal() {
  draftModalMetaEl.replaceChildren();
  const pill = document.createElement("span");
  pill.className = "gate-pill";
  let defaultTitle = `创口筛查 ${new Date().toTimeString().slice(0, 5)}`;
  if (importedMeasurement) {
    const passed = importedAnalysis?.ok && importedAnalysis?.quality_gate === "passed";
    pill.classList.add(passed ? "is-pass" : "is-block");
    pill.textContent = passed ? importedAnalysis.rule_result.label : "门禁未通过";
    const span = document.createElement("span");
    span.textContent = `来源：导入 JSON (${importedMeasurement.measurement_id}) · ΔT ${fmtDelta(importedMeasurement.metrics?.delta_t_c)}`;
    draftModalMetaEl.append(pill, span);
    defaultTitle = `示例创口筛查 ${new Date().toTimeString().slice(0, 5)}`;
  } else {
    const hasT = Boolean(lastState?.has_temperature);
    pill.classList.add(hasT && !lastState?.unstable && (lastState?.frame_count || 0) >= 5 ? "is-pass" : "is-block");
    pill.textContent = hasT ? "实时温度矩阵" : "伪彩预览（门禁阻断）";
    const span = document.createElement("span");
    span.textContent = `来源：${lastState?.source_label || "实时画面"} · ΔT ${fmtDelta(lastState?.delta)}`;
    draftModalMetaEl.append(pill, span);
  }
  draftModalTitleEl.value = defaultTitle;
  draftModalEl.hidden = false;
  draftModalTitleEl.focus();
  draftModalTitleEl.select();
}

async function confirmCreateDraft() {
  const title = (draftModalTitleEl.value || "").trim() || "未命名草稿";
  draftModalConfirmBtn.disabled = true;
  try {
    const payload = importedMeasurement ? { title, measurement: importedMeasurement } : { title };
    const res = await post("/api/clinic/draft/create", payload);
    if (!res || !res.ok || !res.draft) {
      showToast(res?.error?.message || "保存草稿失败", true);
      return;
    }
    draftModalEl.hidden = true;
    showToast(res.draft.quality_gate === "passed" ? "草稿已保存（质量门禁通过）" : "草稿已保存（门禁阻断，需真实温度矩阵方可归档）");
    await loadClinic(false);
    setActivePage("reports");
    renderDraftDetail(res.draft);
  } finally {
    draftModalConfirmBtn.disabled = false;
  }
}

async function saveDraftDetails() {
  if (!activeDraft || activeDraft.status === "archived") return;
  const res = await post("/api/clinic/draft/update", {
    draft_id: activeDraft.draft_id,
    title: draftEditTitleEl.value,
    details: {
      site: draftSiteEl.value,
      duration: draftDurationEl.value,
      symptoms: draftSymptomsEl.value,
      treatment: draftTreatmentEl.value,
      notes: draftNotesEl.value,
    },
  });
  if (res && res.ok && res.draft) {
    showToast("已更新草稿临床详情");
    renderDraftDetail(res.draft);
    await loadClinic(false);
  } else {
    showToast(res?.error?.message || "更新失败", true);
  }
}

async function archiveCurrentDraft() {
  if (!activeDraft) return;
  if (activeDraft.status === "archived") {
    activePatientRef = activeDraft.patient_ref || "";
    setActivePage("archive");
    return;
  }
  const res = await post("/api/clinic/draft/archive", { draft_id: activeDraft.draft_id });
  if (res && res.ok && res.draft) {
    showToast(`已归档为 ${res.display_name} (${res.patient_ref}) 并生成 HTML 报告`);
    activePatientRef = res.patient_ref;
    renderDraftDetail(res.draft);
    await loadClinic(false);
  } else {
    showToast(res?.error?.message || "归档失败", true);
  }
}

/* ===== 循证对话医师助手 ===== */
function setAssistantOpen(open) {
  assistantDrawerEl.hidden = !open;
  assistantToggleBtn.classList.toggle("is-on", open);
  if (open) {
    loadAssistantMeta();
    updateAssistantContext();
    setTimeout(() => assistantInputEl.focus(), 40);
  }
  setTimeout(paint, 40);
}

function showAssistantSubView(mode) {
  assistantChatViewEl.hidden = mode !== "chat";
  assistantRulesViewEl.hidden = mode !== "rules";
  assistantCfgViewEl.hidden = mode !== "cfg";
}

function updateAssistantContext() {
  const inDraft = activePage === "reports" && Boolean(activeDraft);
  if (inDraft) {
    assistantCtxDraftEl.hidden = false;
    assistantCtxDraftEl.textContent = `草稿：${activeDraft.title}`;
    assistantCtxRuleEl.className = "gate-pill";
    if (activeDraft.rule_result) {
      assistantCtxRuleEl.classList.add(activeDraft.rule_result.level === "normal" ? "is-pass" : "is-warn");
      assistantCtxRuleEl.textContent = activeDraft.rule_result.label;
    } else {
      assistantCtxRuleEl.classList.add("is-block");
      assistantCtxRuleEl.textContent = "门禁未通过";
    }
    assistantCtxDeltaEl.textContent = `ΔT ${fmtDelta(activeDraft.delta_t_c)}`;
  } else if (importedMeasurement) {
    assistantCtxDraftEl.hidden = true;
    assistantCtxRuleEl.className = `gate-pill ${importedAnalysis?.ok ? "is-warn" : "is-block"}`;
    assistantCtxRuleEl.textContent = importedAnalysis?.rule_result?.label || "门禁未通过";
    assistantCtxDeltaEl.textContent = `ΔT ${fmtDelta(importedMeasurement.metrics?.delta_t_c)}`;
  } else {
    assistantCtxDraftEl.hidden = true;
    assistantCtxRuleEl.className = `gate-pill ${lastState?.has_temperature ? "is-pass" : "is-block"}`;
    assistantCtxRuleEl.textContent = lastState?.has_temperature ? "实时温度矩阵" : "无温度矩阵";
    assistantCtxDeltaEl.textContent = `ΔT ${fmtDelta(lastState?.delta)}`;
  }

  const usingModel = Boolean(assistantConfig?.enabled && assistantConfig?.has_api_key);
  const modeBase = usingModel ? `模型增强 (${assistantConfig.model})` : "离线规则引擎";
  assistantModeSubEl.textContent = inDraft
    ? `${modeBase} · ${activeDraft.status === "archived" ? "草稿只读" : "可提取草稿详情"}`
    : `${modeBase} · 只解释不确诊`;
}

function renderAssistantMessages() {
  assistantMessagesEl.replaceChildren();
  if (assistantMessages.length === 0) {
    const box = document.createElement("div");
    box.className = "chat-welcome";
    const inDraft = activePage === "reports" && Boolean(activeDraft);
    box.textContent = inDraft
      ? activeDraft.status === "archived"
        ? "这份草稿已归档（只读），可继续围绕当前 ΔT 询问复测、证据与就医指征。"
        : "草稿模式：你可以直接描述创口情况（例如“右手背外伤4天，边缘轻度红肿，正在用碘伏换药”），助手会自动提取结构化字段供你一键写入草稿。"
      : "围绕当前测量数值提问：例如解读 ΔT、是否需要复测、证据与局限或何时就医。风险等级由本地规则独占，回答不构成确诊。";
    assistantMessagesEl.appendChild(box);
    return;
  }

  for (const msg of assistantMessages) {
    const wrap = document.createElement("div");
    wrap.className = `chat-bubble-wrap ${msg.role === "user" ? "is-user" : ""}`;
    const role = document.createElement("span");
    role.className = "chat-role";
    role.textContent = msg.role === "user" ? "你" : "医师助手";
    const bubble = document.createElement("div");
    bubble.className = "chat-bubble";
    bubble.textContent = msg.text;
    wrap.append(role, bubble);

    if (msg.role === "assistant" && msg.meta) {
      const metaRow = document.createElement("div");
      metaRow.className = "chat-meta";
      if (msg.meta.rule) {
        const rBadge = document.createElement("span");
        rBadge.className = `gate-pill ${msg.meta.rule.level === "normal" ? "is-pass" : msg.meta.rule.level === "blocked" ? "is-block" : "is-warn"}`;
        rBadge.textContent = `本地规则：${msg.meta.rule.label}`;
        metaRow.appendChild(rBadge);
      }
      const sBadge = document.createElement("span");
      sBadge.className = "chip-tag";
      sBadge.textContent = msg.meta.modelUsed ? `模型 · ${msg.meta.model}` : REASON_LABEL[msg.meta.reason] || "本地规则模板";
      metaRow.appendChild(sBadge);
      wrap.appendChild(metaRow);

      if (msg.meta.violations && msg.meta.violations.length > 0) {
        const vBox = document.createElement("div");
        vBox.className = "chat-violation";
        vBox.textContent = `已拦截模型违规表述并回退本地规则：${msg.meta.violations.map((v) => v.message).join("；")}`;
        wrap.appendChild(vBox);
      }
    }
    assistantMessagesEl.appendChild(wrap);
  }
  assistantMessagesEl.scrollTop = assistantMessagesEl.scrollHeight;
}

function renderPendingDetails() {
  const fields = pendingDetails?.fields || {};
  const entries = Object.entries(fields);
  if (entries.length === 0 || !activeDraft || activeDraft.status === "archived") {
    assistantPendingCardEl.hidden = true;
    return;
  }
  assistantPendingCardEl.hidden = false;
  assistantPendingFieldsEl.replaceChildren();
  for (const [k, v] of entries) {
    const div = document.createElement("div");
    div.textContent = `${DETAIL_LABELS[k] || k}：${v}`;
    assistantPendingFieldsEl.appendChild(div);
  }
}

async function loadAssistantMeta() {
  try {
    const res = await fetch("/api/assistant/rules").then((r) => r.json());
    if (!res || !res.ok) return;
    assistantRules = res.rules;
    assistantConfig = res.config;

    assistantQuickEl.replaceChildren();
    for (const q of assistantRules.quick_prompts || []) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "quick-chip";
      btn.textContent = q;
      btn.addEventListener("click", () => sendAssistantQuestion(q));
      assistantQuickEl.appendChild(btn);
    }

    assistantRulesBodyEl.replaceChildren();
    for (const sec of assistantRules.sections || []) {
      const box = document.createElement("div");
      box.className = "rule-sec";
      const h4 = document.createElement("h4");
      h4.textContent = sec.title || "";
      const ul = document.createElement("ul");
      for (const item of sec.items || []) {
        const li = document.createElement("li");
        li.textContent = item;
        ul.appendChild(li);
      }
      box.append(h4, ul);
      assistantRulesBodyEl.appendChild(box);
    }

    llmBaseUrlEl.value = assistantConfig.base_url || "https://api.deepseek.com/v1";
    llmModelEl.value = assistantConfig.model || "deepseek-chat";
    llmEnabledEl.checked = Boolean(assistantConfig.enabled || !assistantConfig.has_api_key);
    llmKeyStatusEl.textContent = assistantConfig.has_api_key ? `已配置 (${assistantConfig.api_key_preview})` : "未配置 · 离线模式";
    updateAssistantContext();
  } catch (_err) {
    // 忽略
  }
}

async function sendAssistantQuestion(rawText) {
  const q = String(rawText ?? assistantInputEl.value).trim();
  if (!q || assistantBusy) return;
  assistantBusy = true;
  assistantSendBtn.disabled = true;
  assistantInputEl.value = "";
  assistantMessages.push({ id: `u-${Date.now()}`, role: "user", text: q });
  renderAssistantMessages();

  const inDraft = activePage === "reports" && Boolean(activeDraft);
  const payload = {
    question: q,
    history: assistantMessages.slice(-8).map((m) => ({ role: m.role, text: m.text })),
  };
  if (inDraft) {
    payload.draft_id = activeDraft.draft_id;
  } else if (importedMeasurement) {
    payload.measurement = importedMeasurement;
  }

  try {
    const res = await post("/api/assistant/chat", payload);
    if (res && res.ok) {
      assistantMessages.push({
        id: `a-${Date.now()}`,
        role: "assistant",
        text: res.answer || "",
        meta: res.meta || null,
      });
      if (inDraft && activeDraft.status !== "archived") {
        // 同步保存本草稿的对话记录
        await post("/api/clinic/draft/update", {
          draft_id: activeDraft.draft_id,
          chat: assistantMessages.map((m) => ({ role: m.role, text: m.text })),
        });
        if (res.extracted_details && Object.keys(res.extracted_details).length > 0) {
          pendingDetails = { fields: res.extracted_details, sourceText: q };
          renderPendingDetails();
        }
      }
    } else {
      assistantMessages.push({
        id: `e-${Date.now()}`,
        role: "assistant",
        text: res?.error?.message || "请求失败，请稍后重试。",
      });
    }
    renderAssistantMessages();
  } catch (_err) {
    assistantMessages.push({ id: `e-${Date.now()}`, role: "assistant", text: "无法连接本地服务。" });
    renderAssistantMessages();
  } finally {
    assistantBusy = false;
    assistantSendBtn.disabled = false;
    assistantInputEl.focus();
  }
}

async function applyPendingDetails() {
  if (!pendingDetails || !activeDraft || activeDraft.status === "archived") return;
  const fields = pendingDetails.fields || {};
  const res = await post("/api/clinic/draft/update", {
    draft_id: activeDraft.draft_id,
    details: fields,
    supplements: [
      {
        text: pendingDetails.sourceText || Object.values(fields).join("；"),
        source: "chat",
        fields: Object.keys(fields),
      },
    ],
  });
  pendingDetails = null;
  renderPendingDetails();
  if (res && res.ok && res.draft) {
    showToast("已将对话提取的创口详情写入草稿");
    renderDraftDetail(res.draft);
    await loadClinic(false);
  }
}

async function saveLlmConfig(clearKey = false) {
  const payload = clearKey
    ? { clear_key: true }
    : {
        base_url: llmBaseUrlEl.value,
        model: llmModelEl.value,
        api_key: llmApiKeyEl.value,
        enabled: llmEnabledEl.checked,
      };
  const res = await post("/api/assistant/config", payload);
  if (res && res.ok) {
    llmApiKeyEl.value = "";
    assistantConfig = res.config;
    llmKeyStatusEl.textContent = assistantConfig.has_api_key ? `已配置 (${assistantConfig.api_key_preview})` : "未配置 · 离线模式";
    updateAssistantContext();
    showToast(clearKey ? "已清除本机 API Key，切回离线规则模式" : "已保存大模型配置（仅存于本机）");
  }
}

/* ===== 定时状态轮询 ===== */
async function tick() {
  const ver = stateVersion;
  try {
    const state = await fetch("/api/state").then((res) => res.json());
    if (ver === stateVersion) {
      renderState(state);
    }
  } catch (_err) {
    connBadgeEl.classList.remove("is-live", "is-warn");
    connBadgeEl.classList.add("is-err");
    connBadgeEl.textContent = "与本机服务断开";
  } finally {
    setTimeout(tick, 220);
  }
}

/* ===== 绑定全部事件 ===== */
for (const btn of navBtns) {
  btn.addEventListener("click", () => setActivePage(btn.dataset.page));
}

for (const btn of distBtns) {
  btn.addEventListener("click", async () => {
    const mm = Number(btn.dataset.mm);
    distanceEl.value = mm;
    syncDistPresets(mm);
    await sendAction("/api/distance", { mm });
    showToast(`已设置立柱高度 ${mm} mm`);
  });
}

distanceEl.addEventListener("change", async (event) => {
  const res = await sendAction("/api/distance", { mm: Number(event.target.value) });
  if (res && res.state && res.state.distance_mm) {
    distanceEl.value = res.state.distance_mm;
    syncDistPresets(res.state.distance_mm);
  }
});

emissivityEl.addEventListener("change", async (event) => {
  const res = await sendAction("/api/emissivity", { value: Number(event.target.value) });
  if (res && res.state && res.state.emissivity) {
    emissivityEl.value = Number(res.state.emissivity).toFixed(2);
  }
});

document.querySelector("#refresh").addEventListener("click", () => loadDevices(true));

document.querySelector("#start").addEventListener("click", async () => {
  activeReplayPath = "";
  pinnedSpot = null;
  importedMeasurement = null;
  importedAnalysis = null;
  await sendAction("/api/distance", { mm: Number(distanceEl.value) });
  await sendAction("/api/emissivity", { value: Number(emissivityEl.value) });
  const res = await sendAction("/api/start", { source: sourceEl.value });
  if (res && res.ok) showToast(`已启动：${sourceEl.options[sourceEl.selectedIndex]?.textContent || sourceEl.value}`);
});

document.querySelector("#stop").addEventListener("click", async () => {
  await sendAction("/api/stop", {});
  showToast("已停止采集");
});

themeToggleBtn.addEventListener("click", () => {
  const cur = document.documentElement.dataset.theme;
  applyTheme(cur === "dark" ? "light" : "dark");
});

topbarSaveDraftBtn.addEventListener("click", openSaveDraftModal);
reportsNewDraftBtn.addEventListener("click", openSaveDraftModal);
importedSaveDraftBtn.addEventListener("click", openSaveDraftModal);
importedClearBtn.addEventListener("click", () => {
  importedMeasurement = null;
  importedAnalysis = null;
  if (lastState) renderState(lastState);
  showToast("已切回实时热像测量");
});
loadExampleBtn.addEventListener("click", loadExampleMeasurement);
importJsonBtn.addEventListener("click", () => importJsonFileEl.click());
importJsonFileEl.addEventListener("change", (event) => handleImportJsonFile(event.target.files?.[0]));

draftModalCancelBtn.addEventListener("click", () => {
  draftModalEl.hidden = true;
});
draftModalConfirmBtn.addEventListener("click", confirmCreateDraft);
draftModalTitleEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter") confirmCreateDraft();
});
draftModalEl.addEventListener("mousedown", (event) => {
  if (event.target === draftModalEl) draftModalEl.hidden = true;
});

for (const btn of viewBtns) {
  btn.addEventListener("click", async () => {
    viewMode = btn.dataset.view;
    syncViewTabs(viewMode);
    await sendAction("/api/view", { mode: viewMode });
    paint();
  });
}

weightEl.addEventListener("change", (event) => sendAction("/api/weight", { model: event.target.value }));

resumeLiveBtn.addEventListener("click", async () => {
  if (lastState?.source === "replay") {
    activeReplayPath = "";
    pinnedSpot = null;
    const target = lastLiveSource || sourceEl.value || "synthetic";
    await sendAction("/api/start", { source: target });
    showToast("已返回实时信号流");
  } else {
    await sendAction("/api/unlock", {});
    showToast("已解除 10 帧锁定");
  }
});

autoBtn.addEventListener("click", () => sendAction("/api/auto", { enabled: !autoFollow }));
modeWoundBtn.addEventListener("click", () => setMode("wound"));
modeRefBtn.addEventListener("click", () => setMode("ref"));

alignPoseBtn.addEventListener("click", async () => {
  const res = await sendAction("/api/align_pose", {});
  if (res && res.ok) showToast("已按当前手掌质心与主轴对齐框选");
  else showToast(res?.error || "无法按手姿对齐", true);
});

measureBtn.addEventListener("click", async () => {
  if (lastState?.source === "replay") {
    resumeLiveBtn.click();
    return;
  }
  const ver = ++stateVersion;
  if (measureState === "locked") {
    const res = await post("/api/unlock", {});
    if (res && res.state && ver === stateVersion) renderState(res.state);
    showToast("已恢复实时温度流");
  } else {
    const res = await post("/api/measure", {});
    if (res && !res.ok) showToast(res.error || "无法开始采集", true);
    else if (res && res.state && ver === stateVersion) {
      renderState(res.state);
      showToast("正在采集 10 帧稳态温度矩阵...");
    }
  }
});

labToggleBtn.addEventListener("click", () => {
  const opening = labDrawerEl.hidden;
  labDrawerEl.hidden = !opening;
  labToggleBtn.classList.toggle("is-on", opening);
});

expGroupEl.addEventListener("change", () => {
  expGroupLabEl.value = expGroupEl.value;
});
expGroupLabEl.addEventListener("change", () => {
  expGroupEl.value = expGroupLabEl.value;
});
ntcDeltaEl.addEventListener("input", () => {
  ntcDeltaLabEl.value = ntcDeltaEl.value;
});
ntcDeltaLabEl.addEventListener("input", () => {
  ntcDeltaEl.value = ntcDeltaLabEl.value;
});

saveBtn.addEventListener("click", doSave);
saveLabBtn.addEventListener("click", doSave);

regionsEl.addEventListener("click", async (event) => {
  const btn = event.target.closest(".region-btn");
  if (!btn) return;
  await sendAction("/api/region", { index: Number(btn.dataset.idx) });
});

for (const btn of document.querySelectorAll(".ev-jump-btn")) {
  btn.addEventListener("click", () => jumpToEvidence(btn.dataset.ev));
}

probeBtn.addEventListener("click", runProbe);
document.querySelector("#refresh-records").addEventListener("click", () => loadRecords(true));
document.querySelector("#refresh-clinic").addEventListener("click", () => loadClinic(true));
document.querySelector("#copy-md").addEventListener("click", copyMarkdownTable);
document.querySelector("#export-csv").addEventListener("click", () => {
  const link = document.createElement("a");
  link.href = `/api/records.csv?t=${Date.now()}`;
  link.download = "chuangkou_records.csv";
  document.body.appendChild(link);
  link.click();
  link.remove();
  showToast("已开始下载 CSV 归档记录");
});

draftBackBtn.addEventListener("click", () => renderDraftDetail(null));
draftSaveDetailsBtn.addEventListener("click", saveDraftDetails);
draftArchiveBtn.addEventListener("click", archiveCurrentDraft);
draftOpenChatBtn.addEventListener("click", () => setAssistantOpen(true));

assistantToggleBtn.addEventListener("click", () => setAssistantOpen(assistantDrawerEl.hidden));
assistantCloseBtn.addEventListener("click", () => setAssistantOpen(false));
assistantRulesBtn.addEventListener("click", () => showAssistantSubView(assistantRulesViewEl.hidden ? "rules" : "chat"));
assistantCfgBtn.addEventListener("click", () => showAssistantSubView(assistantCfgViewEl.hidden ? "cfg" : "chat"));
assistantRulesBackBtn.addEventListener("click", () => showAssistantSubView("chat"));
assistantCfgBackBtn.addEventListener("click", () => showAssistantSubView("chat"));
assistantSendBtn.addEventListener("click", () => sendAssistantQuestion());
assistantInputEl.addEventListener("keydown", (event) => {
  if (event.isComposing || event.keyCode === 229) return;
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendAssistantQuestion();
  }
});
assistantApplyPendingBtn.addEventListener("click", applyPendingDetails);
assistantDismissPendingBtn.addEventListener("click", () => {
  pendingDetails = null;
  renderPendingDetails();
});
llmSaveBtn.addEventListener("click", () => saveLlmConfig(false));
llmClearKeyBtn.addEventListener("click", () => saveLlmConfig(true));

document.addEventListener("keydown", (event) => {
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.key === "Escape") {
    if (!draftModalEl.hidden) {
      draftModalEl.hidden = true;
      return;
    }
    if (!assistantDrawerEl.hidden) {
      setAssistantOpen(false);
      return;
    }
    if (pinnedSpot) {
      pinnedSpot = null;
      paint();
      return;
    }
  }
  const tag = document.activeElement?.tagName;
  if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
  if (activePage !== "screen") return;
  const key = event.key.toLowerCase();
  if (key === "1") setMode("wound");
  else if (key === "2") setMode("ref");
  else if (key === "a") autoBtn.click();
  else if (key === "p" && !alignPoseBtn.disabled) alignPoseBtn.click();
  else if (key === "m" && !measureBtn.disabled) measureBtn.click();
  else if (key === "s" && !saveBtn.disabled) saveBtn.click();
});

initTheme();
setMode("wound");
syncDistPresets(300);
loadDevices(false);
loadRecords(false);
loadClinic(false);
loadAssistantMeta();
renderAssistantMessages();
tick();
setInterval(paint, 400);
