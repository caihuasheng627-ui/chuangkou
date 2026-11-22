"""实时画面与温度矩阵处理引擎：摄像头/视频/合成场、物理皮肤分割、10 帧稳态采集与归档。"""

from __future__ import annotations

import csv
import os
import re
import subprocess
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from app.foreground import available_models, foreground_report, set_model, solid_mask
from app.protocol import (
    DEFAULT_REF,
    DEFAULT_WOUND,
    GRADE_TEXT,
    detect_anomalies,
    evaluate,
    locate_hot_bgr,
    next_packet,
    pixel_mm,
    roi_pixel_bounds,
    skin_mask,
    synthetic_frame,
)

ROOT = Path(__file__).resolve().parents[1]
RECORD_PATH = ROOT / "data" / "records.csv"
CAPTURE_DIR = ROOT / "data" / "captures"

RECORD_HEADERS = [
    "time",
    "source",
    "distance_mm",
    "emissivity",
    "frames_averaged",
    "skin_spread_c",
    "unstable",
    "mode",
    "wound_px",
    "wound_n",
    "t_wound",
    "t_wound_max",
    "ref_px",
    "ref_n",
    "t_ref",
    "delta",
    "delta_max",
    "grade",
    "grade_text",
    "npy_path",
    "png_path",
]


def _resolve_video_path() -> Path:
    env = os.environ.get("CHUANGKOU_VIDEO", "").strip()
    candidates = []
    if env:
        candidates.append(Path(env))
    candidates.extend(
        [
            ROOT / "data" / "WIN_20261119_15_25_55_Pro.mp4",
            Path.home() / "Pictures" / "Camera Roll" / "WIN_20261119_15_25_55_Pro.mp4",
        ]
    )
    for item in candidates:
        if item.exists():
            return item
    return candidates[-1]


def list_cameras() -> list[dict]:
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-list_devices",
                "true",
                "-f",
                "dshow",
                "-i",
                "dummy",
            ],
            capture_output=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    text = proc.stderr.decode("utf-8", errors="replace")
    if "(video)" not in text:
        text = proc.stderr.decode("gbk", errors="replace")
    devices: list[dict] = []
    for line in text.splitlines():
        if "(video)" in line and '"' in line:
            name = line.split('"', 2)[1]
            devices.append({"id": f"cam:{len(devices)}", "label": name, "dshow": name})
        elif "Alternative name" in line and '"' in line and devices:
            alt = line.split('"', 2)[1]
            if not devices[-1].get("alt"):
                devices[-1]["alt"] = alt
                devices[-1]["dshow"] = alt
    return devices


def _encode_jpeg(image: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not ok:
        raise RuntimeError("JPEG 编码失败")
    return buf.tobytes()


def _colorize(temps: np.ndarray, vmin: float = 28.0, vmax: float = 40.0) -> np.ndarray:
    scaled = np.clip((temps - vmin) / (vmax - vmin), 0.0, 1.0)
    gray = (np.nan_to_num(scaled, nan=0.0) * 255).astype(np.uint8)
    color = cv2.applyColorMap(gray, cv2.COLORMAP_INFERNO)
    view = cv2.resize(color, (640, 480), interpolation=cv2.INTER_NEAREST)
    flat = np.nan_to_num(temps, nan=-1e9)
    index = int(np.argmax(flat))
    row, col = divmod(index, temps.shape[1])
    sx = int((col + 0.5) * view.shape[1] / temps.shape[1])
    sy = int((row + 0.5) * view.shape[0] / temps.shape[0])
    cv2.drawMarker(view, (sx, sy), (255, 255, 255), cv2.MARKER_CROSS, 18, 1, cv2.LINE_AA)
    return view


def _format_box_px(shape: tuple[int, ...], roi: Optional[dict]) -> str:
    bounds = roi_pixel_bounds(shape, roi)
    if bounds is None:
        return ""
    x0, y0, x1, y1 = bounds
    return f"{x0},{y0},{x1},{y1}"


class Engine:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.jpeg = _encode_jpeg(np.full((480, 640, 3), 18, np.uint8))
        self.seq = 0

        self.temps: Optional[np.ndarray] = None
        self.raw_temps: Optional[np.ndarray] = None
        self.history: deque[np.ndarray] = deque(maxlen=10)
        self._skin_means: deque[float] = deque(maxlen=10)
        self._prev_skin_mean: Optional[float] = None
        self.skin_spread: Optional[float] = None
        self.frame_count = 0

        self.wound: Optional[dict] = dict(DEFAULT_WOUND)
        self.ref: Optional[dict] = dict(DEFAULT_REF)
        self.distance_mm = 300
        self.emissivity = 0.98
        self.source = ""
        self.source_label = ""
        self.running = False
        self.error = ""
        self.note = "选择来源后点开始。机芯插上后先点刷新。"

        self.fps = 0.0
        self._fps_count = 0
        self._fps_t = time.monotonic()
        self._unstable = False

        self.auto = True
        self._tracked = False
        self.detection: Optional[dict] = None
        self.selected_region = 0
        self.view = "original"

        self.measure_state = "idle"  # idle | collecting | locked
        self.measure_target = 10
        self._measure_frames: list[np.ndarray] = []
        self._measure_means: list[float] = []

        self.model_id = "u2netp"
        self.mask_confidence = 0.0
        self.mask_fraction = 0.0
        self.mask_label = "U2-Net 小"
        self.model_fps = 0.0
        self._model_fps_count = 0
        self._model_fps_t = time.monotonic()

        self._last_image: Optional[np.ndarray] = None
        self._last_mask: Optional[np.ndarray] = None
        self._pending_lock = threading.Lock()
        self._pending_frame: Optional[np.ndarray] = None
        self._frame_ready = threading.Event()
        self._infer_thread: Optional[threading.Thread] = None
        self._cached_mask: Optional[np.ndarray] = None
        self._prob_ema: Optional[np.ndarray] = None
        self._mask_hold_until = 0.0
        self._mask_generation = 0
        self._shown_at = 0.0

    def wait_jpeg(self, last_seq: int, timeout: float = 0.5):
        with self._cond:
            if self.seq == last_seq:
                self._cond.wait(timeout)
            return self.jpeg, self.seq

    def set_rois(self, wound: Optional[dict], ref: Optional[dict], manual: bool = False) -> None:
        with self._cond:
            if wound is not None:
                self.wound = _clean_roi(wound)
            elif self.wound is None:
                self.wound = dict(DEFAULT_WOUND)
            if ref is not None:
                self.ref = _clean_roi(ref)
            elif self.ref is None:
                self.ref = dict(DEFAULT_REF)
            if manual:
                self.auto = False
                self._tracked = False
                self.selected_region = 0
            self._cond.notify_all()

    def set_auto(self, enabled: bool) -> None:
        with self._cond:
            self.auto = bool(enabled)
            self._tracked = False
            self.selected_region = 0
            temps = None if self.temps is None else self.temps.copy()
            if self.auto and temps is not None:
                detection = detect_anomalies(temps)
                self.detection = detection
                if detection.get("wound_roi") and detection.get("ref_roi"):
                    self.wound = _clean_roi(detection["wound_roi"])
                    self.ref = _clean_roi(detection["ref_roi"])
                    self._tracked = True
                else:
                    self.wound = None
                    self.ref = None
            elif not self.auto:
                if self.wound is None:
                    self.wound = dict(DEFAULT_WOUND)
                if self.ref is None:
                    self.ref = dict(DEFAULT_REF)
            self._cond.notify_all()

    def select_region(self, index: int) -> None:
        with self._cond:
            regions = (self.detection or {}).get("regions") or []
            if 0 <= index < len(regions):
                region = regions[index]
                self.selected_region = index
                if region.get("roi"):
                    self.wound = _clean_roi(region["roi"])
                if region.get("ref_roi"):
                    self.ref = _clean_roi(region["ref_roi"])
                self.auto = True
            self._cond.notify_all()

    def set_weight(self, model_id: str) -> None:
        chosen = set_model(model_id)
        with self._cond:
            self.model_id = chosen
            self._prob_ema = None
            self._cached_mask = None
            self._mask_hold_until = 0.0
            self._mask_generation += 1
            self._tracked = False
            self._cond.notify_all()

    def set_view(self, mode: str) -> None:
        if mode not in ("original", "removed", "compare"):
            return
        with self._cond:
            self.view = mode
            image = None if self._last_image is None else self._last_image.copy()
            mask = None if self._last_mask is None else self._last_mask.copy()
        if image is not None:
            shown = self._compose(image, mask, mode)
            jpeg = _encode_jpeg(shown)
            with self._cond:
                self.jpeg = jpeg
                self.seq += 1
                self._cond.notify_all()

    def set_distance(self, mm: float) -> None:
        with self._lock:
            self.distance_mm = int(min(400, max(250, round(mm))))

    def set_emissivity(self, eps: float) -> None:
        with self._lock:
            self.emissivity = round(min(1.0, max(0.5, float(eps))), 2)

    def start_measure(self) -> dict:
        with self._cond:
            if not self.running or self.temps is None:
                return {"ok": False, "error": "当前没有实时温度矩阵，无法开始 10 帧稳态采集"}
            self.measure_state = "collecting"
            self._measure_frames.clear()
            self._measure_means.clear()
            self.note = "正在连续采集 10 帧温度矩阵，请保持手部静止..."
            self._cond.notify_all()
        return {"ok": True, "state": self.state()}

    def unlock_measure(self) -> dict:
        with self._cond:
            self.measure_state = "idle"
            self._measure_frames.clear()
            self._measure_means.clear()
            self.note = "已恢复实时温度流。"
            self._cond.notify_all()
        return {"ok": True, "state": self.state()}

    def point_temp(self, x_ratio: float, y_ratio: float) -> dict:
        with self._lock:
            temps = self.temps
            if temps is None:
                return {"ok": False, "error": "无温度矩阵"}
            h, w = temps.shape[:2]
            px = min(max(int(float(x_ratio) * w), 0), w - 1)
            py = min(max(int(float(y_ratio) * h), 0), h - 1)
            val = float(temps[py, px])
            if not np.isfinite(val):
                return {"ok": False, "error": "无效像素"}
            return {"ok": True, "temp": round(val, 2), "px": px, "py": py}

    def state(self) -> dict:
        with self._lock:
            temps = None if self.temps is None else self.temps.copy()
            wound = None if self.wound is None else dict(self.wound)
            ref = None if self.ref is None else dict(self.ref)
            detection = None if self.detection is None else dict(self.detection)
            auto = self.auto
            selected_region = self.selected_region
            distance = self.distance_mm
            emissivity = self.emissivity
            unstable = self._unstable
            base = {
                "running": self.running,
                "source": self.source,
                "source_label": self.source_label,
                "has_temperature": temps is not None,
                "distance_mm": distance,
                "emissivity": emissivity,
                "pixel_mm": round(pixel_mm(distance), 2),
                "fps": round(self.fps, 1),
                "frame_count": self.frame_count,
                "skin_spread": self.skin_spread,
                "unstable": unstable,
                "measure_state": self.measure_state,
                "measure_progress": len(self._measure_frames),
                "measure_target": self.measure_target,
                "error": self.error,
                "note": self.note,
                "matrix": None if temps is None else {"width": int(temps.shape[1]), "height": int(temps.shape[0])},
                "wound_roi": wound,
                "ref_roi": ref,
                "auto": auto,
                "selected_region": selected_region,
                "regions": [] if detection is None else list(detection.get("regions") or []),
                "view": self.view,
                "weight": self.model_id,
                "weight_label": "物理温度分割" if temps is not None else self.mask_label,
                "mask_confidence": self.mask_confidence,
                "mask_fraction": self.mask_fraction,
                "model_fps": round(self.model_fps, 1),
                "region_count": 0 if detection is None else len(detection.get("regions") or []),
            }
        if temps is None:
            base.update(
                {
                    "wound": None,
                    "ref": None,
                    "delta": None,
                    "delta_max": None,
                    "grade": None,
                    "grade_text": "伪彩图像定位（无温度矩阵）",
                    "message": base["note"],
                    "frame_max": None,
                }
            )
            return base

        # 核心修复：手动模式严格只按用户框出的 wound/ref 计算，绝不被自动检测结果覆盖
        if not auto:
            judged = evaluate(temps, wound, ref)
        else:
            regions = base["regions"]
            if regions and 0 <= selected_region < len(regions) and selected_region > 0:
                chosen = regions[selected_region]
                judged = {
                    "wound": {"mean": chosen["wound_mean"], "max": chosen["wound_max"], "n": 0},
                    "ref": {"mean": chosen["ref_mean"], "max": chosen["ref_mean"], "n": 0},
                    "delta": chosen["delta"],
                    "delta_max": chosen["delta_max"],
                    "grade": chosen["grade"],
                    "grade_text": chosen["grade_text"],
                    "message": f"已选中第 {selected_region + 1} 处异常区域（+{chosen['delta']:.2f} °C）",
                }
            elif detection and detection.get("delta") is not None:
                judged = dict(detection)
                if judged.get("wound"):
                    judged["wound"] = dict(judged["wound"])
                if judged.get("ref"):
                    judged["ref"] = dict(judged["ref"])
            elif detection and detection.get("message"):
                judged = dict(detection)
            else:
                judged = evaluate(temps, wound, ref)

        finite = temps[np.isfinite(temps)]
        judged.update(base)
        judged["frame_max"] = None if finite.size == 0 else round(float(np.max(finite)), 2)
        if unstable and judged.get("grade") is not None:
            judged["message"] = "皮肤区域帧间跳变超过 0.3 °C，可能是快门校正或手还在动，本帧请勿采信。"
        elif not auto and not judged.get("message"):
            judged["message"] = "手动框选模式：直接拖动或重画橙/蓝框即可实时重算温差。"
        for key in ("delta", "delta_max"):
            if isinstance(judged.get(key), float):
                judged[key] = round(judged[key], 2)
        for side in ("wound", "ref"):
            stats = judged.get(side)
            if stats:
                stats["mean"] = round(stats["mean"], 2)
                stats["max"] = round(stats["max"], 2)
        return judged

    def _render_snapshot(self, temps: np.ndarray, wound: Optional[dict], ref: Optional[dict], current: dict) -> np.ndarray:
        canvas = _colorize(temps)
        h, w = canvas.shape[:2]
        for roi, color, tag in ((wound, (32, 176, 255), "W"), (ref, (255, 200, 126), "R")):
            bounds = roi_pixel_bounds((h, w), roi)
            if bounds is None:
                continue
            x0, y0, x1, y1 = bounds
            cv2.rectangle(canvas, (x0, y0), (x1, y1), color, 2)
            cv2.putText(canvas, tag, (x0 + 4, max(16, y0 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
        bar = f"dT={current['delta']:+.2f}C  L={current['distance_mm']}mm  eps={current['emissivity']:.2f}  n={current['frame_count']}"
        cv2.rectangle(canvas, (0, 0), (w, 26), (12, 14, 17), -1)
        cv2.putText(canvas, bar, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (240, 240, 240), 1, cv2.LINE_AA)
        return canvas

    def save_record(self) -> dict:
        current = self.state()
        if not current["has_temperature"] or current["delta"] is None:
            return {"ok": False, "error": "现在没有可记录的温差"}
        if current["unstable"]:
            return {"ok": False, "error": "当前画面波动超过 0.3 °C（手抖或快门校正），请稳定后再保存"}

        with self._lock:
            temps = None if self.temps is None else self.temps.copy()
            wound = None if self.wound is None else dict(self.wound)
            ref = None if self.ref is None else dict(self.ref)
        if temps is None:
            return {"ok": False, "error": "温度矩阵为空"}

        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        RECORD_PATH.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        npy_path = CAPTURE_DIR / f"{ts}_temps.npy"
        png_path = CAPTURE_DIR / f"{ts}_view.png"
        np.save(npy_path, temps)
        snap = self._render_snapshot(temps, wound, ref, current)
        ok, buf = cv2.imencode(".png", snap)
        if ok:
            png_path.write_bytes(buf.tobytes())

        write_header = not RECORD_PATH.exists()
        if not write_header:
            first_line = RECORD_PATH.read_text(encoding="utf-8-sig", errors="replace").splitlines()[0:1]
            if not first_line or "wound_px" not in first_line[0]:
                # 兼容旧表头时另起带版本列的新文件，避免字段错位
                target_csv = RECORD_PATH.with_name("records_v2.csv")
                write_header = not target_csv.exists()
            else:
                target_csv = RECORD_PATH
        else:
            target_csv = RECORD_PATH

        with target_csv.open("a", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            if write_header:
                writer.writerow(RECORD_HEADERS)
            writer.writerow(
                [
                    datetime.now().isoformat(timespec="seconds"),
                    current["source_label"],
                    current["distance_mm"],
                    current["emissivity"],
                    current["frame_count"],
                    current["skin_spread"] if current["skin_spread"] is not None else "",
                    int(bool(current["unstable"])),
                    "auto" if current["auto"] else "manual",
                    _format_box_px(temps.shape, wound),
                    current["wound"]["n"] if current["wound"] else "",
                    current["wound"]["mean"] if current["wound"] else "",
                    current["wound"]["max"] if current["wound"] else "",
                    _format_box_px(temps.shape, ref),
                    current["ref"]["n"] if current["ref"] else "",
                    current["ref"]["mean"] if current["ref"] else "",
                    current["delta"],
                    current["delta_max"],
                    current["grade"] if current["grade"] is not None else "",
                    current["grade_text"],
                    str(npy_path.relative_to(ROOT)) if npy_path.is_relative_to(ROOT) else str(npy_path),
                    str(png_path.relative_to(ROOT)) if png_path.is_relative_to(ROOT) else str(png_path),
                ]
            )
        return {"ok": True, "path": str(target_csv), "npy": str(npy_path), "png": str(png_path)}

    def stop(self) -> None:
        self._stop.set()
        self._frame_ready.set()
        thread = self._thread
        infer = self._infer_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=3)
        if infer and infer.is_alive() and infer is not threading.current_thread():
            infer.join(timeout=4)
        with self._cond:
            self.running = False
            self._thread = None
            self._infer_thread = None
            self.measure_state = "idle"
            self._measure_frames.clear()
            self._measure_means.clear()
            self._cond.notify_all()

    def start(self, source: str) -> None:
        self.stop()
        stop_event = threading.Event()
        with self._cond:
            self._stop = stop_event
            self.error = ""
            self.temps = None
            self.raw_temps = None
            self.history.clear()
            self._skin_means.clear()
            self._prev_skin_mean = None
            self.skin_spread = None
            self.frame_count = 0
            self._unstable = False
            self.measure_state = "idle"
            self._measure_frames.clear()
            self._measure_means.clear()
            self.running = True
            self.source = source
            self._tracked = False
            self.selected_region = 0
            self.detection = None
            self._pending_frame = None
            self._prob_ema = None
            self._cached_mask = None
            self._mask_hold_until = 0.0
            self._mask_generation += 1
            self.model_fps = 0.0
            self._model_fps_count = 0
            self._model_fps_t = time.monotonic()
            self._shown_at = 0.0
            self.seq += 1
            self._cond.notify_all()
        self._frame_ready.clear()

        if source == "file":
            target = lambda: self._run_file(stop_event)
            label = "测试视频"
        elif source == "synthetic":
            target = lambda: self._run_synthetic(stop_event)
            label = "自检合成温度"
        elif source.startswith("cam:"):
            idx = int(source.split(":", 1)[1])
            target = lambda: self._run_camera(idx, stop_event)
            label = source
        else:
            with self._cond:
                self.running = False
                self.error = "未知来源"
            return

        self._infer_thread = threading.Thread(target=self._infer_loop, args=(stop_event,), name="segment", daemon=True)
        self._infer_thread.start()
        with self._lock:
            self.source_label = label
        self._thread = threading.Thread(target=target, name="capture", daemon=True)
        self._thread.start()

    def _touch_fps(self) -> None:
        self._fps_count += 1
        now = time.monotonic()
        if now - self._fps_t >= 1.0:
            self.fps = self._fps_count / (now - self._fps_t)
            self._fps_count = 0
            self._fps_t = now

    def _offer_frame(self, image: np.ndarray) -> None:
        with self._pending_lock:
            self._pending_frame = image
        self._frame_ready.set()

    def _infer_loop(self, stop: threading.Event) -> None:
        while not stop.is_set():
            with self._pending_lock:
                frame = self._pending_frame
                self._pending_frame = None
                if frame is None:
                    self._frame_ready.clear()
            if frame is None:
                self._frame_ready.wait(0.1)
                continue
            model_id = self.model_id
            generation = self._mask_generation
            report = foreground_report(frame, model_id)
            if stop.is_set() or generation != self._mask_generation:
                continue
            self._apply_prediction(frame.shape, report)
            self._touch_model_fps()

    def _apply_prediction(self, shape: tuple, report: dict) -> None:
        pred = report.get("prob")
        if pred is None:
            return
        confidence = float(pred.max())
        covered = float((pred >= 0.42).mean())
        usable = confidence >= 0.45 and 0.04 <= covered <= 0.75
        with self._cond:
            if self._prob_ema is None or self._prob_ema.shape != pred.shape:
                blended = pred.astype(np.float32) if usable else None
            elif not usable:
                blended = self._prob_ema * 0.55
            else:
                blended = self._prob_ema * 0.35 + pred.astype(np.float32) * 0.65
            self._prob_ema = blended
            mask = None if blended is None else solid_mask(blended, shape[1], shape[0])
            now = time.monotonic()
            if mask is not None:
                self._cached_mask = mask
                self._mask_hold_until = now + 1.5
            elif now > self._mask_hold_until:
                self._cached_mask = None
            shown = self._cached_mask
            shown_prob = pred if blended is None else blended
            self.mask_confidence = round(float(shown_prob.max()), 3)
            self.mask_fraction = 0.0 if shown is None else round(float(shown.mean()), 3)
            self.mask_label = report.get("label") or self.mask_label

    def _touch_model_fps(self) -> None:
        self._model_fps_count += 1
        now = time.monotonic()
        with self._cond:
            if now - self._model_fps_t >= 1.0:
                self.model_fps = self._model_fps_count / (now - self._model_fps_t)
                self._model_fps_count = 0
                self._model_fps_t = now

    def _publish(self, image: np.ndarray, temps: Optional[np.ndarray], note: str) -> None:
        now = time.monotonic()
        if temps is None:
            # 仅无温度矩阵的伪彩视频流才送给 U²-Net 分割
            self._offer_frame(image)
            if now - self._shown_at < 0.08:
                return
            self._shown_at = now
            with self._cond:
                mask = None if self._cached_mask is None else self._cached_mask.copy()
                view_mode = self.view
                auto = self.auto
            detection = None
            found = locate_hot_bgr(image, mask)
            rendered = self._compose(image, mask, view_mode)
            jpeg = _encode_jpeg(rendered)
            with self._cond:
                self.detection = None
                self.temps = None
                self.raw_temps = None
                self.history.clear()
                self._skin_means.clear()
                self._prev_skin_mean = None
                self.skin_spread = None
                self.frame_count = 0
                self._unstable = False
                if auto and found:
                    wound, ref = found
                    self.wound = _clean_roi(wound)
                    self.ref = _clean_roi(ref)
                    self._tracked = True
                    note = "已从伪彩图像直接框出高温区（橙框）和旁边皮肤（蓝框）；本模式仅做定位展示，不计算精确 °C。"
                elif auto:
                    self.wound = None
                    self.ref = None
                    self._tracked = False
                self.jpeg = jpeg
                self._last_image = image
                self._last_mask = mask
                self.note = note
                self.seq += 1
                self._touch_fps()
                self._cond.notify_all()
            return

        # 真温度矩阵路径：先在皮肤区域内判稳并做 10 帧时序平均，再执行物理温度分割与热区检测
        with self._cond:
            measure_state = self.measure_state
            view_mode = self.view
            auto = self.auto
            selected_region = self.selected_region

        if measure_state == "locked":
            with self._cond:
                self._touch_fps()
            return

        cur_skin = skin_mask(temps)
        if int(cur_skin.sum()) >= 30:
            cur_skin_mean = float(np.mean(temps[cur_skin]))
        else:
            finite_vals = temps[np.isfinite(temps)]
            cur_skin_mean = float(np.mean(finite_vals)) if finite_vals.size else 0.0

        with self._cond:
            prev_mean = self._prev_skin_mean
            jump = 0.0 if prev_mean is None else abs(cur_skin_mean - prev_mean)
            unstable = jump > 0.3
            self._prev_skin_mean = cur_skin_mean

            if self.history and self.history[-1].shape != temps.shape:
                self.history.clear()
                self._skin_means.clear()
            self.history.append(temps)
            self._skin_means.append(cur_skin_mean)
            smoothed = np.mean(np.stack(self.history, axis=0), axis=0).astype(np.float32)
            frame_count = len(self.history)
            spread = float(max(self._skin_means) - min(self._skin_means)) if len(self._skin_means) >= 2 else 0.0

            if self.measure_state == "collecting":
                if unstable:
                    self._measure_frames.clear()
                    self._measure_means.clear()
                    note = "检测到画面波动 > 0.3 °C，已重置采集，请保持手部静止..."
                else:
                    self._measure_frames.append(temps.copy())
                    self._measure_means.append(cur_skin_mean)
                    if len(self._measure_frames) >= self.measure_target:
                        m_spread = float(max(self._measure_means) - min(self._measure_means))
                        if m_spread <= 0.3:
                            smoothed = np.mean(np.stack(self._measure_frames, axis=0), axis=0).astype(np.float32)
                            frame_count = len(self._measure_frames)
                            spread = m_spread
                            unstable = False
                            self.measure_state = "locked"
                            note = f"已锁定 {frame_count} 帧均值（皮肤波动 {m_spread:.2f} °C ≤ 0.3 °C），可微调框选并保存。"
                        else:
                            # 滑窗丢弃最老一半，继续等待平稳段
                            self._measure_frames = self._measure_frames[5:]
                            self._measure_means = self._measure_means[5:]
                            note = f"10 帧波动 {m_spread:.2f} °C 偏大，继续等待稳定..."
                    else:
                        note = f"正在稳定采帧 {len(self._measure_frames)}/{self.measure_target}..."

        # 在锁外执行物理皮肤分割、热区检测、热图着彩与 JPEG 编码
        body = skin_mask(smoothed)
        body_fraction = float(body.mean()) if body.size else 0.0
        mask = None
        if int(body.sum()) >= 30:
            mask = cv2.resize(body.astype(np.uint8), (image.shape[1], image.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
        detection = detect_anomalies(smoothed)
        found = None
        if detection.get("wound_roi") and detection.get("ref_roi"):
            found = (detection["wound_roi"], detection["ref_roi"])
        color_img = _colorize(smoothed)
        rendered = self._compose(color_img, mask, view_mode)
        jpeg = _encode_jpeg(rendered)

        with self._cond:
            self.raw_temps = temps
            self.temps = smoothed
            self.frame_count = frame_count
            self.skin_spread = round(spread, 3)
            self._unstable = unstable
            self.detection = detection
            self.mask_confidence = 1.0 if mask is not None else 0.0
            self.mask_fraction = round(body_fraction, 3)
            self.mask_label = "物理温度分割"
            if auto:
                if found:
                    regions = detection.get("regions") or []
                    if 0 <= selected_region < len(regions):
                        chosen = regions[selected_region]
                        self.wound = _clean_roi(chosen["roi"])
                        self.ref = _clean_roi(chosen["ref_roi"])
                    else:
                        self.selected_region = 0
                        self.wound = _clean_roi(found[0])
                        self.ref = _clean_roi(found[1])
                    self._tracked = True
                else:
                    self.selected_region = 0
                    self.wound = None
                    self.ref = None
                    self._tracked = False
                if self.measure_state == "idle" and detection.get("message"):
                    note = detection["message"]
            self.jpeg = jpeg
            self._last_image = color_img
            self._last_mask = mask
            self.note = note
            self.seq += 1
            self._touch_fps()
            self._cond.notify_all()

    def _cutout(self, image: np.ndarray, mask: Optional[np.ndarray]) -> np.ndarray:
        if mask is None or mask.shape[:2] != image.shape[:2]:
            return image
        soft = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 2.2)
        soft = np.clip(soft, 0.0, 1.0)[..., None]
        background = np.array([24, 24, 24], dtype=np.float32)
        return (image.astype(np.float32) * soft + background * (1.0 - soft)).astype(np.uint8)

    def _compose(self, image: np.ndarray, mask: Optional[np.ndarray], view_mode: Optional[str] = None) -> np.ndarray:
        mode = view_mode or self.view
        removed = self._cutout(image, mask)
        if mode == "removed":
            return removed if mask is not None else image
        if mode == "compare":
            gap = np.full((image.shape[0], 10, 3), 12, np.uint8)
            right = removed if mask is not None else np.full_like(image, 24)
            return np.concatenate([image, gap, right], axis=1)
        return image

    def _run_file(self, stop: threading.Event) -> None:
        video_path = _resolve_video_path()
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            with self._cond:
                self.error = f"打不开测试视频: {video_path}"
                self.running = False
            return
        note = "这是测试视频的伪彩预览。颜色会自动拉对比度，不能换算成温差。"
        source_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        step = max(1, int(round(float(source_fps) / 12.0)))
        index = 0
        tick = time.monotonic()
        try:
            while not stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    index = 0
                    continue
                index += 1
                if index % step:
                    continue
                self._publish(frame, None, note)
                tick += 1 / 12
                delay = tick - time.monotonic()
                if delay > 0:
                    if stop.wait(delay):
                        break
                else:
                    tick = time.monotonic()
        finally:
            cap.release()
            with self._cond:
                self.running = False

    def _run_synthetic(self, stop: threading.Event) -> None:
        note = "自检用的合成温度，不是机芯。用 10 帧稳态平均与物理皮肤分割验证三级判定。"
        t = 0.0
        try:
            while not stop.is_set():
                temps = synthetic_frame(t)
                self._publish(_colorize(temps), temps, note)
                t += 0.3
                if stop.wait(0.1):
                    break
        finally:
            with self._cond:
                self.running = False

    def _run_camera(self, index: int, stop: threading.Event) -> None:
        cameras = list_cameras()
        if index < 0 or index >= len(cameras):
            with self._cond:
                self.error = "没有这路摄像头。插上机芯后点刷新。"
                self.running = False
            return
        cam = cameras[index]
        name = cam["label"]
        dshow_target = cam.get("dshow") or name
        with self._lock:
            self.source_label = name
        if stop.is_set() or self._run_ffmpeg(dshow_target, stop):
            return
        if stop.is_set():
            return
        self._run_opencv(index, name, stop)

    def _run_ffmpeg(self, dshow_target: str, stop: threading.Event) -> bool:
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-fflags",
            "nobuffer",
            "-f",
            "dshow",
            "-vcodec",
            "mjpeg",
            "-rtbufsize",
            "8M",
            "-i",
            f"video={dshow_target}",
            "-an",
            "-c:v",
            "copy",
            "-f",
            "mjpeg",
            "pipe:1",
        ]
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError:
            return False
        assert proc.stdout is not None
        chunks: deque[Optional[bytes]] = deque(maxlen=128)
        chunks_lock = threading.Lock()
        chunks_ready = threading.Condition(chunks_lock)

        def _read() -> None:
            fd = proc.stdout.fileno()
            try:
                while not stop.is_set():
                    block = os.read(fd, 16384)
                    with chunks_ready:
                        chunks.append(None if not block else block)
                        chunks_ready.notify()
                    if not block:
                        break
            except OSError:
                with chunks_ready:
                    chunks.append(None)
                    chunks_ready.notify()

        threading.Thread(target=_read, daemon=True).start()
        buf = bytearray()
        got_any = False
        deadline = time.monotonic() + 5.0
        note_preview = "机芯当前输出为伪彩预览（无全屏温度矩阵）。请用上位机/XU 开启全屏测温码流后再做 ΔT 判定。"
        note_temp = "正在用全屏温度矩阵做差。色标固定在 28–40 °C，白十字是矩阵最高温。"
        try:
            while not stop.is_set():
                with chunks_ready:
                    if not chunks:
                        chunks_ready.wait(0.2)
                    block = chunks.popleft() if chunks else b""
                if block is None:
                    break
                if not block:
                    if not got_any and time.monotonic() > deadline:
                        break
                    continue
                buf.extend(block)
                latest_temps = None
                latest_jpeg = None
                while True:
                    packet = next_packet(buf)
                    if packet is None:
                        break
                    kind, payload = packet
                    got_any = True
                    if kind == "temp":
                        latest_temps = payload
                    else:
                        latest_jpeg = payload
                if latest_temps is not None:
                    self._publish(_colorize(latest_temps), latest_temps, note_temp)
                elif latest_jpeg is not None:
                    image = cv2.imdecode(np.frombuffer(latest_jpeg, np.uint8), cv2.IMREAD_COLOR)
                    if image is not None:
                        self._publish(image, None, note_preview)
            return got_any
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
            with self._cond:
                if got_any:
                    self.running = False

    def _run_opencv(self, index: int, name: str, stop: threading.Event) -> None:
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not cap.isOpened():
            with self._cond:
                self.error = f"打不开 {name}"
                self.running = False
            return
        note = "实时预览里没有温度矩阵。这路画面只能看，不能出温差判定。"
        try:
            while not stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    if stop.wait(0.05):
                        break
                    continue
                self._publish(frame, None, note)
        finally:
            cap.release()
            with self._cond:
                self.running = False


def _clean_roi(roi: dict) -> dict:
    x = float(roi["x"])
    y = float(roi["y"])
    w = float(roi["w"])
    h = float(roi["h"])
    x = min(max(x, 0.0), 0.98)
    y = min(max(y, 0.0), 0.98)
    w = min(max(w, 0.02), 1.0 - x)
    h = min(max(h, 0.02), 1.0 - y)
    return {"x": x, "y": y, "w": w, "h": h}
