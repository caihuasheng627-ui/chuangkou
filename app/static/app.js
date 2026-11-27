const DEFAULT_WOUND = { x: 0.585, y: 0.433, w: 0.08, h: 0.1 };
const DEFAULT_REF = { x: 0.28, y: 0.36, w: 0.14, h: 0.2 };

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

// DOM refs
const connBadgeEl = document.querySelector("#conn-badge");
const sourceEl = document.querySelector("#source");
const distanceEl = document.querySelector("#distance");
const emissivityEl = document.querySelector("#emissivity");
const distBtns = [...document.querySelectorAll(".dist-btn")];
const viewBtns = [...document.querySelectorAll("#view-tabs .seg-btn")];
const tabBtns = [...document.querySelectorAll(".side-tabs .tab-btn")];
const tabPanels = {
  live: document.querySelector("#tab-live"),
  trend: document.querySelector("#tab-trend"),
  lab: document.querySelector("#tab-lab"),
  clinic: document.querySelector("#tab-clinic"),
};
const tabCountEl = document.querySelector("#tab-count");
const clinicCountEl = document.querySelector("#clinic-count");

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

const trendSummaryEl = document.querySelector("#trend-summary");
const trendChartEl = document.querySelector("#trend-chart");
const historyCountEl = document.querySelector("#history-count");
const historyListEl = document.querySelector("#history-list");
const groupStatsEl = document.querySelector("#group-stats");

const draftTitleEl = document.querySelector("#draft-title");
const saveDraftBtn = document.querySelector("#save-draft");
const clinicDraftsEl = document.querySelector("#clinic-drafts");
const draftEditorEl = document.querySelector("#draft-editor");
const draftEditorTitleEl = document.querySelector("#draft-editor-title");
const draftGatePillEl = document.querySelector("#draft-gate-pill");
const draftGateNoteEl = document.querySelector("#draft-gate-note");
const draftSiteEl = document.querySelector("#draft-site");
const draftDurationEl = document.querySelector("#draft-duration");
const draftSymptomsEl = document.querySelector("#draft-symptoms");
const draftTreatmentEl = document.querySelector("#draft-treatment");
const draftNotesEl = document.querySelector("#draft-notes");
const draftSaveDetailsBtn = document.querySelector("#draft-save-details");
const draftArchiveBtn = document.querySelector("#draft-archive");
const clinicPatientCountEl = document.querySelector("#clinic-patient-count");
const clinicPatientsEl = document.querySelector("#clinic-patients");
const clinicReportsEl = document.querySelector("#clinic-reports");
const clinicEvidenceEl = document.querySelector("#clinic-evidence");

let activeDraftId = "";
let clinicData = null;

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

function setActiveTab(name) {
  for (const btn of tabBtns) {
    btn.classList.toggle("is-on", btn.dataset.tab === name);
  }
  for (const [key, panel] of Object.entries(tabPanels)) {
    panel.classList.toggle("is-on", key === name);
  }
  if (name === "trend" || name === "lab") {
    loadRecords();
  } else if (name === "clinic") {
    loadClinic();
  }
}

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

/* ===== 画布坐标与智能命中检测（平移 + 四角缩放 + 新建） ===== */
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
  if (side === "left") {
    return { x: box.x, y: box.y, w: box.w * span, h: box.h };
  }
  return { x: box.x + box.w * (span + gap), y: box.y, w: box.w * span, h: box.h };
}

function pointerRatio(event) {
  const full = contentBox();
  const view = viewport.getBoundingClientRect();
  if (full.w <= 1 || full.h <= 1) {
    return { x: 0, y: 0, inside: false, panel: full };
  }
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

function hitTestRoi(point) {
  if (!point.inside || point.panel.w < 10) return null;
  const tolX = 11 / point.panel.w;
  const tolY = 11 / point.panel.h;
  // 优先检测四角缩放手柄（先查当前选中的模式，再查另一个）
  const order = drawMode === "wound" ? ["wound", "ref"] : ["ref", "wound"];
  for (const target of order) {
    const r = rois[target];
    if (!r) continue;
    const corners = [
      { name: "nw", x: r.x, y: r.y, cursor: "nwse-resize" },
      { name: "ne", x: r.x + r.w, y: r.y, cursor: "nesw-resize" },
      { name: "sw", x: r.x, y: r.y + r.h, cursor: "nesw-resize" },
      { name: "se", x: r.x + r.w, y: r.y + r.h, cursor: "nwse-resize" },
    ];
    for (const c of corners) {
      if (Math.abs(point.x - c.x) <= tolX && Math.abs(point.y - c.y) <= tolY) {
        return { kind: "resize", target, corner: c.name, cursor: c.cursor };
      }
    }
  }
  for (const target of order) {
    const r = rois[target];
    if (!r) continue;
    if (point.x >= r.x && point.x <= r.x + r.w && point.y >= r.y && point.y <= r.y + r.h) {
      return { kind: "move", target, cursor: "grab" };
    }
  }
  return null;
}

function roiDimLabel(roi, box) {
  if (!roi || !lastState?.pixel_mm || !box || box.w < 260) return "";
  const wMm = roi.w * 160 * lastState.pixel_mm;
  const hMm = roi.h * 120 * lastState.pixel_mm;
  return ` · ${Math.round(wMm)}×${Math.round(hMm)}mm`;
}

function paint() {
  const dpr = Math.max(1, window.devicePixelRatio || 1);
  const cw = Math.max(1, viewport.clientWidth);
  const ch = Math.max(1, viewport.clientHeight);
  const targetW = Math.round(cw * dpr);
  const targetH = Math.round(ch * dpr);
  if (canvas.width !== targetW || canvas.height !== targetH) {
    canvas.width = targetW;
    canvas.height = targetH;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cw, ch);

  const boxes = viewMode === "compare" ? [panelBox("left"), panelBox("right")] : [panelBox("right")];
  const prefix = hasTemperature ? "" : "≈";
  const wRoi = drag?.kind === "draw" && drag.target === "wound" ? drag.roi : rois.wound;
  const rRoi = drag?.kind === "draw" && drag.target === "ref" ? drag.roi : rois.ref;

  for (const box of boxes) {
    const woundLabel = lastState?.wound
      ? `创口 ${prefix}${lastState.wound.mean.toFixed(1)}°C${roiDimLabel(wRoi, box)}`
      : `创口${roiDimLabel(wRoi, box)}`;
    const refLabel = lastState?.ref
      ? `对照 ${prefix}${lastState.ref.mean.toFixed(1)}°C${roiDimLabel(rRoi, box)}`
      : `对照${roiDimLabel(rRoi, box)}`;
    drawHandAxis(ctx, box, lastState?.pose);
    strokeRoi(ctx, box, wRoi, "#ffb020", woundLabel);
    strokeRoi(ctx, box, rRoi, "#6bc2ff", refLabel);
    if (pinnedSpot) drawPinnedSpot(ctx, box, pinnedSpot);
  }
}

function drawHandAxis(ctx, box, pose) {
  if (!pose || box.w < 24 || box.h < 24) return;
  const cx = box.x + pose.cx * box.w;
  const cy = box.y + pose.cy * box.h;
  const rad = (pose.angle_deg * Math.PI) / 180;
  const len = Math.min(box.w, box.h) * 0.13;
  ctx.save();
  ctx.strokeStyle = "rgba(126, 226, 168, 0.48)";
  ctx.lineWidth = 1.5;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(cx - Math.cos(rad) * len, cy - Math.sin(rad) * len);
  ctx.lineTo(cx + Math.cos(rad) * len, cy + Math.sin(rad) * len);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = "rgba(126, 226, 168, 0.85)";
  ctx.beginPath();
  ctx.arc(cx, cy, 3, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function drawPinnedSpot(ctx, box, spot) {
  if (box.w < 20) return;
  const sx = box.x + spot.x * box.w;
  const sy = box.y + spot.y * box.h;
  ctx.save();
  ctx.strokeStyle = "#0b0d10";
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.moveTo(sx - 7, sy);
  ctx.lineTo(sx + 7, sy);
  ctx.moveTo(sx, sy - 7);
  ctx.lineTo(sx, sy + 7);
  ctx.stroke();
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(sx - 7, sy);
  ctx.lineTo(sx + 7, sy);
  ctx.moveTo(sx, sy - 7);
  ctx.lineTo(sx, sy + 7);
  ctx.stroke();

  const label = `${spot.estimated ? "≈" : ""}${spot.temp.toFixed(2)}°C`;
  ctx.font = "600 11px Microsoft YaHei, Segoe UI, sans-serif";
  const tw = ctx.measureText(label).width;
  const lx = Math.min(box.x + box.w - tw - 10, sx + 9);
  const ly = Math.max(box.y + 18, sy - 6);
  ctx.fillStyle = "rgba(11, 13, 16, 0.88)";
  ctx.fillRect(lx - 4, ly - 11, tw + 8, 15);
  ctx.fillStyle = "#f3f1eb";
  ctx.fillText(label, lx, ly);
  ctx.restore();
}

function strokeRoi(ctx, box, roi, color, label) {
  if (!roi || box.w < 2 || box.h < 2 || roi.w <= 0 || roi.h <= 0) return;
  const x = box.x + roi.x * box.w;
  const y = box.y + roi.y * box.h;
  const w = roi.w * box.w;
  const h = roi.h * box.h;

  ctx.save();
  ctx.strokeStyle = "rgba(11, 13, 16, 0.9)";
  ctx.lineWidth = 4;
  ctx.strokeRect(x + 1, y + 1, w, h);

  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.strokeRect(x + 1, y + 1, w, h);

  // 四角微调手柄
  const hs = 6;
  const pts = [
    [x + 1, y + 1],
    [x + 1 + w, y + 1],
    [x + 1, y + 1 + h],
    [x + 1 + w, y + 1 + h],
  ];
  for (const [cx, cy] of pts) {
    ctx.fillStyle = "#0b0d10";
    ctx.fillRect(cx - hs / 2 - 1, cy - hs / 2 - 1, hs + 2, hs + 2);
    ctx.fillStyle = color;
    ctx.fillRect(cx - hs / 2, cy - hs / 2, hs, hs);
  }

  ctx.font = "600 11.5px Microsoft YaHei, Segoe UI, sans-serif";
  const tw = ctx.measureText(label).width;
  const lx = Math.max(box.x + 2, Math.min(box.x + box.w - tw - 12, x + 2));
  const ly = y >= box.y + 22 ? y - 6 : y + 17;
  ctx.fillStyle = "rgba(11, 13, 16, 0.84)";
  ctx.fillRect(lx - 4, ly - 12, tw + 8, 16);
  ctx.fillStyle = color;
  ctx.fillText(label, lx, ly);
  ctx.restore();
}

function setMode(mode) {
  drawMode = mode;
  modeWoundBtn.classList.toggle("is-on", mode === "wound");
  modeRefBtn.classList.toggle("is-on", mode === "ref");
}

canvas.addEventListener("mouseenter", () => {
  isHovering = true;
});

canvas.addEventListener("mousedown", (event) => {
  const point = pointerRatio(event);
  if (!point.inside) return;
  const hit = hitTestRoi(point);
  if (hit && hit.kind === "resize") {
    setMode(hit.target);
    drag = {
      kind: "resize",
      target: hit.target,
      corner: hit.corner,
      orig: { ...rois[hit.target] },
      moved: false,
    };
    canvas.style.cursor = hit.cursor;
  } else if (hit && hit.kind === "move") {
    setMode(hit.target);
    const r = rois[hit.target];
    drag = {
      kind: "move",
      target: hit.target,
      offsetX: point.x - r.x,
      offsetY: point.y - r.y,
      startX: point.x,
      startY: point.y,
      moved: false,
    };
    canvas.style.cursor = "grabbing";
  } else {
    drag = {
      kind: "draw",
      target: drawMode,
      x0: point.x,
      y0: point.y,
      roi: { x: point.x, y: point.y, w: 0, h: 0 },
      moved: false,
    };
    canvas.style.cursor = "crosshair";
  }
  paint();
});

canvas.addEventListener("mousemove", async (event) => {
  isHovering = true;
  const point = pointerRatio(event);
  if (drag) {
    if (drag.kind === "move") {
      const r = rois[drag.target];
      const nx = Math.min(Math.max(point.x - drag.offsetX, 0), 1 - r.w);
      const ny = Math.min(Math.max(point.y - drag.offsetY, 0), 1 - r.h);
      if (Math.hypot(point.x - drag.startX, point.y - drag.startY) > 0.004) {
        drag.moved = true;
      }
      rois[drag.target] = { x: nx, y: ny, w: r.w, h: r.h };
    } else if (drag.kind === "resize") {
      const o = drag.orig;
      let x0 = o.x;
      let y0 = o.y;
      let x1 = o.x + o.w;
      let y1 = o.y + o.h;
      const minS = 0.03;
      if (drag.corner.includes("w")) x0 = Math.min(point.x, x1 - minS);
      if (drag.corner.includes("e")) x1 = Math.max(point.x, x0 + minS);
      if (drag.corner.includes("n")) y0 = Math.min(point.y, y1 - minS);
      if (drag.corner.includes("s")) y1 = Math.max(point.y, y0 + minS);
      x0 = Math.max(0, x0);
      y0 = Math.max(0, y0);
      x1 = Math.min(1, x1);
      y1 = Math.min(1, y1);
      rois[drag.target] = { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
      drag.moved = true;
    } else if (drag.kind === "draw") {
      const x = Math.min(drag.x0, point.x);
      const y = Math.min(drag.y0, point.y);
      const w = Math.abs(point.x - drag.x0);
      const h = Math.abs(point.y - drag.y0);
      drag.roi = { x, y, w, h };
      if (w >= 0.02 && h >= 0.02) drag.moved = true;
    }
    paint();
  } else {
    const hit = hitTestRoi(point);
    canvas.style.cursor = hit ? hit.cursor : point.inside ? "crosshair" : "default";
  }

  if ((!hasTemperature && !hasEstimatedTemp) || !point.inside) {
    probeEl.hidden = true;
    return;
  }
  const now = performance.now();
  if (now - lastProbeAt < 80) return;
  lastProbeAt = now;
  const reqSeq = ++probeSeq;
  try {
    const res = await fetch(`/api/point?x=${point.x.toFixed(4)}&y=${point.y.toFixed(4)}`).then((r) => r.json());
    if (isHovering && reqSeq === probeSeq && (hasTemperature || hasEstimatedTemp) && res.ok) {
      probeEl.hidden = false;
      const tag = res.estimated ? "反演点温 ≈" : "点温";
      probeEl.textContent = `${tag} ${res.temp.toFixed(2)} °C (${res.px}, ${res.py})`;
    }
  } catch (_err) {
    // 忽略瞬时查询失败
  }
});

canvas.addEventListener("mouseleave", () => {
  isHovering = false;
  probeSeq += 1;
  probeEl.hidden = true;
  finishDrag(false);
});

async function finishDrag(allowPin = true) {
  if (!drag) return;
  const current = drag;
  drag = null;
  canvas.style.cursor = "crosshair";

  if (current.kind === "draw" && current.moved) {
    rois[current.target] = current.roi;
    await commitManualRois();
  } else if ((current.kind === "move" || current.kind === "resize") && current.moved) {
    await commitManualRois();
  } else if (allowPin && current.kind === "draw" && (hasTemperature || hasEstimatedTemp)) {
    // 轻点空白处：固定/清除该点测温标记
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

async function commitManualRois() {
  const woundPayload = rois.wound || { ...DEFAULT_WOUND };
  const refPayload = rois.ref || { ...DEFAULT_REF };
  rois.wound = woundPayload;
  rois.ref = refPayload;
  await sendAction("/api/roi", { wound: woundPayload, ref: refPayload, manual: true });
}

canvas.addEventListener("mouseup", () => finishDrag(true));
window.addEventListener("resize", paint);
frame.addEventListener("load", paint);
frame.addEventListener("error", () => {
  setTimeout(() => {
    frame.src = `/stream.mjpg?t=${Date.now()}`;
  }, 1000);
});

/* ===== 渲染辅助：色标尺、热扩散、多区域、SVG 趋势图 ===== */
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

function renderTrendChart(recordsDesc) {
  const ns = "http://www.w3.org/2000/svg";
  trendChartEl.replaceChildren();
  const points = [...(recordsDesc || [])].slice(0, 14).reverse();
  const W = 340;
  const H = 124;
  const padL = 28;
  const padR = 12;
  const padT = 12;
  const padB = 18;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;

  const mk = (tag, attrs = {}) => {
    const el = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
    return el;
  };

  if (points.length === 0) {
    const txt = mk("text", { x: W / 2, y: H / 2 + 4, "text-anchor": "middle", fill: "#7d838e", "font-size": "11" });
    txt.textContent = "保存至少 1 条记录后自动生成 ΔT 趋势图";
    trendChartEl.appendChild(txt);
    return;
  }

  const maxVal = Math.max(3.2, ...points.map((p) => p.delta + 0.4));
  const minVal = Math.min(0.0, ...points.map((p) => p.delta - 0.2));
  const yOf = (v) => padT + ((maxVal - v) / Math.max(0.5, maxVal - minVal)) * plotH;
  const xOf = (i) => (points.length === 1 ? padL + plotW / 2 : padL + (i / (points.length - 1)) * plotW);

  // 阈值虚线: 1.0°C (关注) 与 2.2°C (告警)
  for (const [thr, color, label] of [
    [1.0, "#f5a524", "1.0"],
    [2.2, "#ff6347", "2.2"],
  ]) {
    if (thr >= minVal && thr <= maxVal) {
      const y = yOf(thr);
      trendChartEl.appendChild(
        mk("line", { x1: padL, y1: y, x2: W - padR, y2: y, stroke: color, "stroke-opacity": "0.45", "stroke-dasharray": "4 3", "stroke-width": "1" })
      );
      const t = mk("text", { x: 2, y: y + 3, fill: color, "font-size": "9.5" });
      t.textContent = label;
      trendChartEl.appendChild(t);
    }
  }

  // 折线与节点
  const coords = points.map((p, i) => [xOf(i), yOf(p.delta)]);
  if (coords.length >= 2) {
    const dStr = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
    trendChartEl.appendChild(
      mk("path", { d: dStr, fill: "none", stroke: "#6bc2ff", "stroke-width": "2", "stroke-linejoin": "round", "stroke-linecap": "round" })
    );
  }

  points.forEach((rec, i) => {
    const [cx, cy] = coords[i];
    const color = rec.delta >= 2.2 ? "#ff6347" : rec.delta >= 1.0 ? "#f5a524" : "#4cc38a";
    const isActive = rec.npy_path && rec.npy_path === activeReplayPath;
    const circle = mk("circle", {
      cx: cx.toFixed(1),
      cy: cy.toFixed(1),
      r: isActive ? "5.5" : "4",
      fill: color,
      stroke: isActive ? "#ffffff" : "#0b0d10",
      "stroke-width": "1.6",
      style: "cursor:pointer",
    });
    const tip = document.createElementNS(ns, "title");
    tip.textContent = `${(rec.time || "").replace("T", " ")} [${rec.group}] ΔT ${rec.delta >= 0 ? "+" : ""}${rec.delta.toFixed(2)}°C（点击复盘）`;
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
    showToast(`已回载历史温度帧：${(rec.npy_path || "").split(/[\\/]/).pop()}`);
    if (lastRecordsData) {
      renderTrendChart(lastRecordsData.records);
      highlightReplayRow();
    }
  } else {
    showToast(res?.error || "回载历史帧失败", true);
  }
}

function highlightReplayRow() {
  for (const btn of historyListEl.querySelectorAll(".history-item")) {
    btn.classList.toggle("is-active", btn.dataset.npy === activeReplayPath && activeReplayPath !== "");
  }
}

/* ===== 主状态渲染 ===== */
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

  // 顶部连接/帧率状态灯
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
    connBadgeEl.textContent = "已停止 / 待机";
  }

  // 模式横幅（锁定或复盘）
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

  // ROI 同步
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

  // 视图同步
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

  // 画布左下角手姿引导胶囊
  if (state.pose && state.pose.hint) {
    poseChipEl.hidden = false;
    poseChipEl.textContent = state.pose.hint;
    poseChipEl.classList.toggle("is-warn", state.pose.status !== "姿态居中");
  } else {
    poseChipEl.hidden = true;
  }
  alignPoseBtn.disabled = !state.pose;

  // 10 帧稳态采集按钮
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

  // 归档保存按钮状态（底部栏 + Tab 3）
  const canSave =
    hasTemperature &&
    state.delta !== null &&
    state.delta !== undefined &&
    !state.unstable &&
    Boolean(state.wound_roi) &&
    Boolean(state.ref_roi);
  saveBtn.disabled = !canSave;
  saveLabBtn.disabled = !canSave;
  if (!hasTemperature) {
    saveBtn.title = "仅温度矩阵模式支持正式归档记录";
  } else if (state.unstable) {
    saveBtn.title = "当前画面波动超过 0.3 °C，稳定后可保存";
  } else if (state.delta === null || state.delta === undefined || !state.wound_roi || !state.ref_roi) {
    saveBtn.title = "请先框选创口与对照区域（或切手动框选）";
  } else {
    saveBtn.title = "快捷键 S：归档保存当前温度矩阵、截图与记录";
  }

  // 稳定性胶囊
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

  // Hero 卡片评级、主数字与三级游标尺
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

    // 游标位置：0..4.0°C 映射到 0%..100%（与 zone-0 25% = 1.0°C, zone-1 30% = 2.2°C 对齐）
    const pct = Math.min(100, Math.max(0, (state.delta / 4.0) * 100));
    gaugePinEl.hidden = false;
    gaugePinEl.style.left = `${pct.toFixed(1)}%`;
  }

  // 创口 vs 对照双卡
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

  updateScaleBar(state);
  renderRegions(state.regions, state.selected_region || 0);
  renderPhysics(state.physics);

  // Tab 1 传感参数表
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
}

/* ===== 历史记录、重复性验收表与 Markdown/CSV 导出 ===== */
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

    // 分组重复性统计表
    groupStatsEl.replaceChildren();
    const groups = data.groups || {};
    const groupEntries = Object.entries(groups);
    if (groupEntries.length === 0) {
      const empty = document.createElement("p");
      empty.className = "empty-note";
      empty.textContent = "暂无归档数据。采集稳定帧后点击“归档记录”即可自动统计各组极差。";
      groupStatsEl.appendChild(empty);
    } else {
      for (const [gName, st] of groupEntries) {
        const row = document.createElement("div");
        row.className = "group-row";
        const left = document.createElement("span");
        const ntcPart = st.ntc_mae !== null && st.ntc_mae !== undefined ? ` · NTC差 ${st.ntc_mae.toFixed(2)}°C` : "";
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

    // 历史列表
    historyListEl.replaceChildren();
    const recs = (data.records || []).slice(0, 15);
    if (recs.length === 0) {
      const empty = document.createElement("p");
      empty.className = "empty-note";
      empty.textContent = "暂无历史归档文件";
      historyListEl.appendChild(empty);
    } else {
      for (const rec of recs) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "history-item";
        btn.dataset.npy = rec.npy_path || "";
        btn.title = "点击回载该帧 .npy 原始温度矩阵做离线复盘";
        const meta = document.createElement("div");
        meta.className = "history-meta";
        const title = document.createElement("span");
        title.textContent = `[${rec.group}]  ${(rec.time || "").replace("T", " ").slice(5, 19)}`;
        const sub = document.createElement("small");
        const areaStr = rec.hot_area_mm2 ? ` · 面积 ${rec.hot_area_mm2}mm²` : "";
        const ntcStr = rec.ntc_delta !== null && rec.ntc_delta !== undefined ? ` · NTC ${rec.ntc_delta}°C` : "";
        sub.textContent = `L=${rec.distance_mm}mm${areaStr}${ntcStr}`;
        meta.append(title, sub);

        const right = document.createElement("div");
        right.className = "history-right";
        const val = document.createElement("strong");
        val.textContent = `${rec.delta >= 0 ? "+" : ""}${rec.delta.toFixed(2)}°C`;
        val.style.color = rec.delta >= 2.2 ? "#ff6347" : rec.delta >= 1.0 ? "#f5a524" : "#7ee2a8";
        const tag = document.createElement("span");
        tag.className = "muted-tag";
        tag.textContent = "复盘";
        right.append(val, tag);

        btn.append(meta, right);
        btn.addEventListener("click", () => replayRecord(rec));
        historyListEl.appendChild(btn);
      }
      highlightReplayRow();
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
      st.repeatability_ok === null || st.repeatability_ok === undefined
        ? "单次测量"
        : st.repeatability_ok
        ? "达标"
        : "超差";
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
    showToast("剪贴板写入受限，请改用“下载 CSV 记录”", true);
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

/* ===== 绑定全部按钮与双向同步事件 ===== */
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
  await sendAction("/api/distance", { mm: Number(distanceEl.value) });
  await sendAction("/api/emissivity", { value: Number(emissivityEl.value) });
  const res = await sendAction("/api/start", { source: sourceEl.value });
  if (res && res.ok) showToast(`已启动：${sourceEl.options[sourceEl.selectedIndex]?.textContent || sourceEl.value}`);
});

document.querySelector("#stop").addEventListener("click", async () => {
  await sendAction("/api/stop", {});
  showToast("已停止采集");
});

for (const btn of viewBtns) {
  btn.addEventListener("click", async () => {
    viewMode = btn.dataset.view;
    syncViewTabs(viewMode);
    await sendAction("/api/view", { mode: viewMode });
    paint();
  });
}

weightEl.addEventListener("change", (event) => {
  sendAction("/api/weight", { model: event.target.value });
});

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

autoBtn.addEventListener("click", async () => {
  await sendAction("/api/auto", { enabled: !autoFollow });
});

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

for (const btn of tabBtns) {
  btn.addEventListener("click", () => setActiveTab(btn.dataset.tab));
}

/* ===== 设备编码探测与临床草稿/档案工作流（整合自 dsh-wound-clinic v0.7.2） ===== */
async function runProbe() {
  if (!probeBtn || !probeOutputEl) return;
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

function renderDraftEditor(draft) {
  if (!draft) {
    draftEditorEl.hidden = true;
    return;
  }
  draftEditorEl.hidden = false;
  const archived = draft.status === "archived";
  const passed = draft.quality_gate === "passed";
  draftEditorTitleEl.textContent = draft.title || "草稿详情";
  draftGatePillEl.classList.remove("is-pass", "is-block", "is-arch");
  if (archived) {
    draftGatePillEl.classList.add("is-arch");
    draftGatePillEl.textContent = `已归档 · ${draft.patient_name || draft.patient_ref || ""}`;
  } else if (passed) {
    draftGatePillEl.classList.add("is-pass");
    draftGatePillEl.textContent = draft.rule_result?.label || "质控通过";
  } else {
    draftGatePillEl.classList.add("is-block");
    draftGatePillEl.textContent = "门禁未通过";
  }

  if (!passed && draft.blocked_message) {
    draftGateNoteEl.hidden = false;
    draftGateNoteEl.textContent = `质控阻断：${draft.blocked_message}`;
  } else {
    draftGateNoteEl.hidden = true;
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
  draftArchiveBtn.disabled = archived || !passed;
}

async function loadClinic(notify = false) {
  try {
    const data = await fetch("/api/clinic/summary").then((r) => r.json());
    if (!data || !data.ok) return;
    clinicData = data;
    const drafts = data.drafts || [];
    const patients = data.patients || [];
    const reports = data.reports || [];
    const evidence = data.evidence || [];

    clinicCountEl.textContent = String(drafts.length);
    clinicPatientCountEl.textContent = `${patients.length} 位`;

    clinicDraftsEl.replaceChildren();
    if (drafts.length === 0) {
      const empty = document.createElement("p");
      empty.className = "empty-note";
      empty.textContent = "暂无临床草稿。启动热像或合成温度源后点击“存为草稿”。";
      clinicDraftsEl.appendChild(empty);
      activeDraftId = "";
      renderDraftEditor(null);
    } else {
      for (const item of drafts) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = `clinic-item ${item.draft_id === activeDraftId ? "is-active" : ""}`;
        const meta = document.createElement("div");
        meta.className = "clinic-item-meta";
        const title = document.createElement("span");
        title.textContent = item.title;
        const sub = document.createElement("small");
        const dtStr =
          item.delta_t_c !== null && item.delta_t_c !== undefined
            ? `ΔT ${item.delta_t_c >= 0 ? "+" : ""}${Number(item.delta_t_c).toFixed(2)}°C`
            : item.estimated_delta_t_c !== null && item.estimated_delta_t_c !== undefined
            ? `伪彩反演 ≈${Number(item.estimated_delta_t_c).toFixed(2)}°C`
            : "无温度矩阵";
        sub.textContent = `${dtStr} · 详情 ${item.detail_count || 0} 项 · ${(item.updated_at || "").slice(5, 16).replace("T", " ")}`;
        meta.append(title, sub);

        const pill = document.createElement("span");
        pill.className = "gate-pill";
        if (item.status === "archived") {
          pill.classList.add("is-arch");
          pill.textContent = item.patient_name || "已归档";
        } else if (item.quality_gate === "passed") {
          pill.classList.add("is-pass");
          pill.textContent = item.rule_result?.level || "通过";
        } else {
          pill.classList.add("is-block");
          pill.textContent = "阻断";
        }
        btn.append(meta, pill);
        btn.addEventListener("click", () => {
          activeDraftId = item.draft_id;
          renderDraftEditor(item);
          loadClinic(false);
        });
        clinicDraftsEl.appendChild(btn);
      }
      const selected = drafts.find((d) => d.draft_id === activeDraftId) || drafts[0];
      activeDraftId = selected.draft_id;
      renderDraftEditor(selected);
    }

    clinicPatientsEl.replaceChildren();
    if (patients.length === 0) {
      const empty = document.createElement("p");
      empty.className = "empty-note";
      empty.textContent = "暂无已归档患者档案";
      clinicPatientsEl.appendChild(empty);
    } else {
      for (const p of patients) {
        const row = document.createElement("div");
        row.className = "clinic-item";
        const meta = document.createElement("div");
        meta.className = "clinic-item-meta";
        const t = document.createElement("span");
        t.textContent = `${p.display_name || p.patient_ref} (${p.patient_ref})`;
        const s = document.createElement("small");
        s.textContent = `建档 ${(p.created_at || "").slice(0, 16).replace("T", " ")}`;
        meta.append(t, s);
        const tag = document.createElement("span");
        tag.className = "gate-pill is-arch";
        tag.textContent = `${p.measurement_count || 0} 次测量`;
        row.append(meta, tag);
        clinicPatientsEl.appendChild(row);
      }
    }

    clinicReportsEl.replaceChildren();
    for (const r of reports.slice(0, 10)) {
      const link = document.createElement("a");
      link.className = "clinic-item";
      link.href = `/api/clinic/report/${encodeURIComponent(r.report_id)}`;
      link.target = "_blank";
      link.rel = "noreferrer";
      const meta = document.createElement("div");
      meta.className = "clinic-item-meta";
      const t = document.createElement("span");
      t.textContent = `HTML 报告 · ${r.report_id}`;
      const s = document.createElement("small");
      s.textContent = `${r.patient_ref} · ${(r.created_at || "").slice(0, 16).replace("T", " ")}`;
      meta.append(t, s);
      const tag = document.createElement("span");
      tag.className = "gate-pill is-pass";
      tag.textContent = "打开报告";
      link.append(meta, tag);
      clinicReportsEl.appendChild(link);
    }

    clinicEvidenceEl.replaceChildren();
    for (const ev of evidence) {
      const box = document.createElement("div");
      box.className = "evidence-item";
      const head = document.createElement("div");
      const idEl = document.createElement("strong");
      idEl.textContent = ev.evidence_id;
      head.append(idEl, document.createTextNode(`${ev.title} (${ev.year})`));
      const p = document.createElement("p");
      p.textContent = ev.verified_excerpt || "";
      box.append(head, p);
      clinicEvidenceEl.appendChild(box);
    }

    if (notify) showToast("已刷新临床草稿与档案");
  } catch (_err) {
    if (notify) showToast("刷新临床档案失败", true);
  }
}

async function createClinicDraft() {
  const title = (draftTitleEl.value || "").trim();
  const res = await post("/api/clinic/draft/create", { title });
  if (res && res.ok && res.draft) {
    draftTitleEl.value = "";
    activeDraftId = res.draft.draft_id;
    const passed = res.draft.quality_gate === "passed";
    showToast(passed ? "已保存草稿（质量门禁通过）" : "已保存草稿（无真实温度矩阵，门禁阻断归档）");
    await loadClinic(false);
  } else {
    showToast(res?.error?.message || res?.error || "保存草稿失败", true);
  }
}

async function saveDraftDetails() {
  if (!activeDraftId) return;
  const res = await post("/api/clinic/draft/update", {
    draft_id: activeDraftId,
    details: {
      site: draftSiteEl.value,
      duration: draftDurationEl.value,
      symptoms: draftSymptomsEl.value,
      treatment: draftTreatmentEl.value,
      notes: draftNotesEl.value,
    },
  });
  if (res && res.ok) {
    showToast("已更新草稿临床详情");
    await loadClinic(false);
  } else {
    showToast(res?.error?.message || "更新草稿详情失败", true);
  }
}

async function archiveActiveDraft() {
  if (!activeDraftId) return;
  const res = await post("/api/clinic/draft/archive", { draft_id: activeDraftId });
  if (res && res.ok) {
    showToast(`已归档为 ${res.display_name} (${res.patient_ref}) 并生成 HTML 报告`);
    await loadClinic(false);
  } else {
    showToast(res?.error?.message || "归档失败", true);
  }
}

document.querySelector("#refresh-records").addEventListener("click", () => loadRecords(true));
document.querySelector("#refresh-clinic").addEventListener("click", () => loadClinic(true));
probeBtn.addEventListener("click", runProbe);
saveDraftBtn.addEventListener("click", createClinicDraft);
draftSaveDetailsBtn.addEventListener("click", saveDraftDetails);
draftArchiveBtn.addEventListener("click", archiveActiveDraft);
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

document.addEventListener("keydown", (event) => {
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.key === "Escape" && pinnedSpot) {
    pinnedSpot = null;
    paint();
    return;
  }
  const tag = document.activeElement?.tagName;
  if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
  const key = event.key.toLowerCase();
  if (key === "1") setMode("wound");
  else if (key === "2") setMode("ref");
  else if (key === "a") autoBtn.click();
  else if (key === "p" && !alignPoseBtn.disabled) alignPoseBtn.click();
  else if (key === "m" && !measureBtn.disabled) measureBtn.click();
  else if (key === "s" && !saveBtn.disabled) saveBtn.click();
});

setMode("wound");
syncDistPresets(300);
loadDevices(false);
loadRecords(false);
loadClinic(false);
tick();
setInterval(paint, 400);
