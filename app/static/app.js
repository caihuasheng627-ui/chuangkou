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
let measureState = "idle";
let lastProbeAt = 0;

const sourceEl = document.querySelector("#source");
const frame = document.querySelector("#frame");
const canvas = document.querySelector("#overlay");
const viewport = document.querySelector("#viewport");
const gradeEl = document.querySelector("#grade");
const stabilityEl = document.querySelector("#stability");
const deltaEl = document.querySelector("#delta");
const regionsEl = document.querySelector("#regions");
const linesEl = document.querySelector("#lines");
const messageEl = document.querySelector("#message");
const savedEl = document.querySelector("#saved");
const scaleEl = document.querySelector("#scale");
const probeEl = document.querySelector("#probe");
const weightWrap = document.querySelector("#weight-wrap");
const measureBtn = document.querySelector("#measure");
const distanceEl = document.querySelector("#distance");
const emissivityEl = document.querySelector("#emissivity");

function post(url, body) {
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((res) => res.json());
}

async function loadDevices() {
  const previous = sourceEl.value;
  const data = await fetch("/api/devices").then((res) => res.json());
  const options = [
    ...data.devices.map((item) => `<option value="${item.id}">${item.label}</option>`),
    `<option value="file">回放测试视频（伪彩，不判定）</option>`,
    `<option value="synthetic">自检合成温度（不接机芯）</option>`,
  ];
  sourceEl.innerHTML = options.join("");
  const names = [...sourceEl.options];
  let state = {};
  try {
    state = await fetch("/api/state").then((res) => res.json());
  } catch (_err) {
    state = {};
  }
  const active = names.find((item) => item.value === state.source);
  const keep = names.find((item) => item.value === previous);
  const thermal = names.find((item) => item.textContent.includes("UVC"));
  if (active) sourceEl.value = active.value;
  else if (keep) sourceEl.value = previous;
  else if (thermal) sourceEl.value = thermal.value;
}

function contentBox() {
  const view = viewport.getBoundingClientRect();
  const image = frame.getBoundingClientRect();
  return {
    x: image.left - view.left,
    y: image.top - view.top,
    w: image.width,
    h: image.height,
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
  const rawX = (event.clientX - view.left - full.x) / Math.max(full.w, 1);
  const rawY = (event.clientY - view.top - full.y) / Math.max(full.h, 1);
  let x = rawX;
  if (viewMode === "compare") {
    const imgW = frame.naturalWidth || 1290;
    const gap = 10 / imgW;
    const span = (1 - gap) / 2;
    if (rawX <= span) {
      x = rawX / span;
    } else if (rawX >= span + gap) {
      x = (rawX - span - gap) / span;
    } else {
      x = 0;
    }
  }
  return {
    x: Math.min(1, Math.max(0, x)),
    y: Math.min(1, Math.max(0, rawY)),
  };
}

function paint() {
  const box = panelBox("right");
  canvas.width = viewport.clientWidth;
  canvas.height = viewport.clientHeight;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  stroke(ctx, box, rois.wound, "#ffb020", "创口");
  stroke(ctx, box, rois.ref, "#7ec8ff", "对照");
  if (drag) stroke(ctx, box, drag.roi, drag.color, drag.label);
}

function stroke(ctx, box, roi, color, label) {
  if (!roi || box.w < 2) return;
  const x = box.x + roi.x * box.w;
  const y = box.y + roi.y * box.h;
  const w = roi.w * box.w;
  const h = roi.h * box.h;
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.strokeRect(x + 1, y + 1, w, h);
  ctx.font = "13px Microsoft YaHei, Segoe UI, sans-serif";
  ctx.fillStyle = color;
  ctx.fillText(label, x + 5, Math.max(15, y + 16));
}

function setMode(mode) {
  drawMode = mode;
  document.querySelector("#mode-wound").classList.toggle("is-on", mode === "wound");
  document.querySelector("#mode-ref").classList.toggle("is-on", mode === "ref");
}

canvas.addEventListener("mousedown", (event) => {
  const point = pointerRatio(event);
  drag = {
    mode: drawMode,
    x0: point.x,
    y0: point.y,
    roi: { x: point.x, y: point.y, w: 0, h: 0 },
    color: drawMode === "wound" ? "#ffb020" : "#7ec8ff",
    label: drawMode === "wound" ? "创口" : "对照",
  };
  paint();
});

canvas.addEventListener("mousemove", async (event) => {
  const point = pointerRatio(event);
  if (drag) {
    const x = Math.min(drag.x0, point.x);
    const y = Math.min(drag.y0, point.y);
    drag.roi = {
      x,
      y,
      w: Math.abs(point.x - drag.x0),
      h: Math.abs(point.y - drag.y0),
    };
    paint();
  }
  if (!hasTemperature) {
    probeEl.hidden = true;
    return;
  }
  const now = performance.now();
  if (now - lastProbeAt < 80) return;
  lastProbeAt = now;
  try {
    const res = await fetch(`/api/point?x=${point.x.toFixed(4)}&y=${point.y.toFixed(4)}`).then((r) => r.json());
    if (res.ok) {
      probeEl.hidden = false;
      probeEl.textContent = `点温 ${res.temp.toFixed(2)} °C (${res.px}, ${res.py})`;
    }
  } catch (_err) {
    // 忽略瞬时查询失败
  }
});

canvas.addEventListener("mouseleave", () => {
  probeEl.hidden = true;
  finishDrag();
});

async function finishDrag() {
  if (!drag) return;
  const roi = drag.roi;
  const mode = drag.mode;
  drag = null;
  if (roi.w >= 0.02 && roi.h >= 0.02) {
    rois[mode] = roi;
    const woundPayload = rois.wound || { ...DEFAULT_WOUND };
    const refPayload = rois.ref || { ...DEFAULT_REF };
    rois.wound = woundPayload;
    rois.ref = refPayload;
    const res = await post("/api/roi", { wound: woundPayload, ref: refPayload, manual: true });
    if (res && res.state) renderState(res.state);
  }
  paint();
}

canvas.addEventListener("mouseup", finishDrag);
window.addEventListener("resize", paint);
frame.addEventListener("load", paint);
frame.addEventListener("error", () => {
  setTimeout(() => {
    frame.src = `/stream.mjpg?t=${Date.now()}`;
  }, 1000);
});

function renderRegions(regions, selectedIndex) {
  if (!regions || regions.length <= 1 || !autoFollow) {
    regionsEl.hidden = true;
    regionsEl.innerHTML = "";
    return;
  }
  regionsEl.hidden = false;
  regionsEl.innerHTML = regions
    .map(
      (r, idx) =>
        `<button type="button" class="region-btn ${idx === selectedIndex ? "is-active" : ""}" data-idx="${idx}">#${idx + 1} +${r.delta.toFixed(1)}°C</button>`
    )
    .join("");
}

regionsEl.addEventListener("click", async (event) => {
  const btn = event.target.closest(".region-btn");
  if (!btn) return;
  const idx = Number(btn.dataset.idx);
  const res = await post("/api/region", { index: idx });
  if (res && res.state) renderState(res.state);
});

function renderState(state) {
  hasTemperature = Boolean(state.has_temperature);
  autoFollow = Boolean(state.auto);
  measureState = state.measure_state || "idle";

  if (state.auto && !drag) {
    rois.wound = state.wound_roi || null;
    rois.ref = state.ref_roi || null;
    paint();
  } else if (!state.auto && !drag) {
    rois.wound = state.wound_roi || rois.wound;
    rois.ref = state.ref_roi || rois.ref;
    paint();
  }

  if (state.view) {
    viewMode = state.view;
    const viewEl = document.querySelector("#view");
    if (viewEl.value !== state.view) viewEl.value = state.view;
    document.querySelector("#view-caption").hidden = state.view !== "compare";
  }

  document.querySelector("#auto").classList.toggle("is-on", autoFollow);
  weightWrap.hidden = hasTemperature;
  if (state.weight) {
    const weightEl = document.querySelector("#weight");
    if (weightEl && weightEl.value !== state.weight) weightEl.value = state.weight;
  }
  if (state.source && [...sourceEl.options].some((item) => item.value === state.source)) {
    sourceEl.value = state.source;
  }
  if (document.activeElement !== distanceEl && state.distance_mm) {
    distanceEl.value = state.distance_mm;
  }
  if (document.activeElement !== emissivityEl && state.emissivity) {
    emissivityEl.value = Number(state.emissivity).toFixed(2);
  }

  // 稳定采帧按钮状态
  measureBtn.disabled = !hasTemperature || !state.running;
  measureBtn.classList.toggle("is-locked", measureState === "locked");
  measureBtn.classList.toggle("is-collecting", measureState === "collecting");
  if (measureState === "locked") {
    measureBtn.textContent = "恢复实时";
  } else if (measureState === "collecting") {
    measureBtn.textContent = `采帧 ${state.measure_progress || 0}/${state.measure_target || 10}`;
  } else {
    measureBtn.textContent = "稳定采 10 帧";
  }

  // 稳定性标签
  if (!hasTemperature) {
    stabilityEl.hidden = true;
  } else {
    stabilityEl.hidden = false;
    stabilityEl.classList.remove("is-ok", "is-warn", "is-locked");
    if (measureState === "locked") {
      stabilityEl.classList.add("is-locked");
      stabilityEl.textContent = `已锁定 · 波动 ${(state.skin_spread ?? 0).toFixed(2)}°C`;
    } else if (state.unstable) {
      stabilityEl.classList.add("is-warn");
      stabilityEl.textContent = "波动 > 0.3°C";
    } else {
      stabilityEl.classList.add("is-ok");
      stabilityEl.textContent = state.skin_spread !== null && state.skin_spread !== undefined
        ? `稳定 · 波动 ${state.skin_spread.toFixed(2)}°C`
        : "稳定";
    }
  }

  gradeEl.textContent = state.grade_text || "等待画面";
  const level = state.grade === null || state.grade === undefined ? "none" : String(state.grade);
  deltaEl.dataset.level = level;
  deltaEl.classList.toggle("is-empty", state.delta === null || state.delta === undefined);
  deltaEl.innerHTML = state.delta === null || state.delta === undefined
    ? "暂无温差"
    : `${state.delta >= 0 ? "+" : ""}${state.delta.toFixed(2)}<span>°C</span>`;

  scaleEl.hidden = !hasTemperature;
  renderRegions(state.regions, state.selected_region || 0);

  const woundText = state.wound
    ? `${state.wound.mean.toFixed(2)} °C（峰值 ${state.wound.max.toFixed(2)} °C${state.wound.n ? ` · ${state.wound.n} px` : ""}）`
    : "—";
  const refText = state.ref
    ? `${state.ref.mean.toFixed(2)} °C${state.ref.n ? `（${state.ref.n} px）` : ""}`
    : "—";
  const deltaMaxText = state.delta_max !== null && state.delta_max !== undefined
    ? `${state.delta_max >= 0 ? "+" : ""}${state.delta_max.toFixed(2)} °C`
    : "—";
  const distText = `${state.distance_mm || 300} mm（${state.pixel_mm ? state.pixel_mm.toFixed(2) : "—"} mm/px）`;

  const rows = hasTemperature
    ? [
        ["创口温度", woundText],
        ["对照皮肤", refText],
        ["峰值温差 ΔTmax", deltaMaxText],
        ["工作距离 / 像元", distText],
        ["发射率 / 平均帧", `${Number(state.emissivity || 0.98).toFixed(2)} · ${state.frame_count || 0} 帧`],
        ["异常热区", `${state.region_count || 0} 处`],
        ["全图最高温", state.frame_max !== null && state.frame_max !== undefined ? `${state.frame_max.toFixed(2)} °C` : "—"],
        ["画面帧率", state.fps ? `${state.fps.toFixed(1)} fps` : "—"],
      ]
    : [
        ["分割方式", state.weight_label || "—"],
        ["画面帧率", state.fps ? `${state.fps.toFixed(1)} fps` : "—"],
        ["分割更新", state.model_fps ? `${state.model_fps.toFixed(1)} 次/秒` : "—"],
        ["分割置信度", state.mask_confidence ? state.mask_confidence.toFixed(2) : "—"],
        ["前景占比", state.mask_fraction ? `${Math.round(state.mask_fraction * 100)}%` : "—"],
      ];

  linesEl.innerHTML = rows.map(([name, value]) => `<dt>${name}</dt><dd>${value}</dd>`).join("");
  const extra = [state.message, state.error].filter(Boolean).join(" ");
  messageEl.textContent = extra === state.grade_text ? "" : extra;
}

async function tick() {
  try {
    const state = await fetch("/api/state").then((res) => res.json());
    renderState(state);
  } catch (_err) {
    messageEl.textContent = "页面和本机服务断开了。";
  } finally {
    setTimeout(tick, 220);
  }
}

document.querySelector("#refresh").addEventListener("click", loadDevices);
document.querySelector("#start").addEventListener("click", async () => {
  if (savedEl) savedEl.textContent = "";
  await post("/api/distance", { mm: Number(distanceEl.value) });
  await post("/api/emissivity", { value: Number(emissivityEl.value) });
  const res = await post("/api/start", { source: sourceEl.value });
  if (res && res.state) renderState(res.state);
});
document.querySelector("#auto").addEventListener("click", async () => {
  const res = await post("/api/auto", { enabled: !autoFollow });
  if (res && res.state) renderState(res.state);
});
document.querySelector("#view").addEventListener("change", async (event) => {
  viewMode = event.target.value;
  document.querySelector("#view-caption").hidden = viewMode !== "compare";
  const res = await post("/api/view", { mode: viewMode });
  if (res && res.state) renderState(res.state);
  paint();
});
document.querySelector("#weight").addEventListener("change", (event) => {
  post("/api/weight", { model: event.target.value });
});
document.querySelector("#stop").addEventListener("click", () => post("/api/stop", {}));
document.querySelector("#mode-wound").addEventListener("click", () => setMode("wound"));
document.querySelector("#mode-ref").addEventListener("click", () => setMode("ref"));
distanceEl.addEventListener("change", (event) => {
  post("/api/distance", { mm: Number(event.target.value) });
});
emissivityEl.addEventListener("change", (event) => {
  post("/api/emissivity", { value: Number(event.target.value) });
});
measureBtn.addEventListener("click", async () => {
  if (measureState === "locked") {
    const res = await post("/api/unlock", {});
    if (res && res.state) renderState(res.state);
  } else {
    const res = await post("/api/measure", {});
    if (res && !res.ok && savedEl) savedEl.textContent = res.error || "无法开始采集";
    else if (res && res.state) renderState(res.state);
  }
});
document.querySelector("#save").addEventListener("click", async () => {
  const result = await post("/api/save", {});
  if (savedEl) {
    savedEl.textContent = result.ok
      ? `已归档：${result.path}（含 .npy 与 .png）`
      : (result.error || "这一帧没有温度，不能记录");
  }
});

loadDevices();
tick();
setInterval(paint, 400);
