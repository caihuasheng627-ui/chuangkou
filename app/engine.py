"""实时画面与温度矩阵处理引擎：摄像头/视频/合成场、物理皮肤分割、10 帧稳态采集与归档。"""

from __future__ import annotations

import csv
import json
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
    analyze_hand_pose,
    analyze_thermal_physics,
    decode_yuyv_temps,
    detect_anomalies,
    encode_anatomical_rois,
    evaluate,
    invert_pseudocolor_temps,
    locate_hot_bgr,
    next_packet,
    pixel_mm,
    project_anatomical_rois,
    render_isotherm_view,
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
    if np.isfinite(temps).any():
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
        self._save_lock = threading.Lock()
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

        self.model_id = "thermal"
        self.mask_confidence = 0.0
        self.mask_fraction = 0.0
        self.mask_label = "热像伪彩分割"
        self.model_fps = 0.0
        self._model_fps_count = 0
        self._model_fps_t = time.monotonic()

        self._last_image: Optional[np.ndarray] = None
        self._last_mask: Optional[np.ndarray] = None
        self._est_temps: Optional[np.ndarray] = None
        self._osd_info: Optional[dict] = None
        self._pose: Optional[dict] = None
        self._anatomical_anchor: Optional[dict] = None
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
                if self._pose is not None:
                    self._anatomical_anchor = encode_anatomical_rois(self._pose, self.wound, self.ref)
            self._cond.notify_all()

    def align_rois_to_pose(self) -> dict:
        """根据当前手掌质心与主轴倾角，把创口框和对照框自动对齐到手背同一解剖位置。"""
        with self._cond:
            if self._pose is None:
                return {"ok": False, "error": "当前画面未检测到清晰的手部轮廓，无法按姿态对齐"}
            if self._anatomical_anchor is None:
                if self.wound and self.ref:
                    self._anatomical_anchor = encode_anatomical_rois(self._pose, self.wound, self.ref)
                else:
                    return {"ok": False, "error": "尚未记录基准框选位置，请先框选一次创口和对照区"}
            projected = project_anatomical_rois(self._pose, self._anatomical_anchor)
            if projected is None:
                return {"ok": False, "error": "无法投影到当前手部姿态"}
            self.wound = _clean_roi(projected[0])
            self.ref = _clean_roi(projected[1])
            self.auto = False
            self._tracked = False
            self.selected_region = 0
            self.note = f"已按当前手掌质心与主轴（{self._pose['angle_deg']:+.0f}°）对齐创口框与对照框。"
            self._cond.notify_all()
        return {"ok": True, "state": self.state()}

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
        if mode not in ("original", "removed", "compare", "isotherm"):
            return
        with self._cond:
            self.view = mode
            image = None if self._last_image is None else self._last_image.copy()
            mask = None if self._last_mask is None else self._last_mask.copy()
            temps = None if self.temps is None else self.temps.copy()
            est_temps = None if self._est_temps is None else self._est_temps.copy()
            ref_roi = None if self.ref is None else dict(self.ref)
        if image is not None:
            t_field = temps if temps is not None else est_temps
            ref_temp = None
            if t_field is not None and ref_roi is not None:
                ev = evaluate(t_field, self.wound, ref_roi)
                if ev.get("ref"):
                    ref_temp = float(ev["ref"]["mean"])
            shown = self._compose(image, mask, mode, temps=t_field, ref_temp=ref_temp)
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
            estimated = False
            if temps is None:
                temps = self._est_temps
                estimated = True
            if temps is None:
                return {"ok": False, "error": "无温度矩阵"}
            h, w = temps.shape[:2]
            px = min(max(int(float(x_ratio) * w), 0), w - 1)
            py = min(max(int(float(y_ratio) * h), 0), h - 1)
            val = float(temps[py, px])
            if not np.isfinite(val):
                return {"ok": False, "error": "无效像素"}
            return {"ok": True, "temp": round(val, 2), "px": px, "py": py, "estimated": estimated}

    def _snapshot(self) -> dict:
        with self._lock:
            return {
                "temps": None if self.temps is None else self.temps.copy(),
                "est_temps": None if self._est_temps is None else self._est_temps.copy(),
                "osd_info": None if self._osd_info is None else dict(self._osd_info),
                "pose": None if self._pose is None else dict(self._pose),
                "has_anchor": self._anatomical_anchor is not None,
                "last_mask": None if self._last_mask is None else self._last_mask.copy(),
                "wound": None if self.wound is None else dict(self.wound),
                "ref": None if self.ref is None else dict(self.ref),
                "detection": None if self.detection is None else dict(self.detection),
                "auto": self.auto,
                "selected_region": self.selected_region,
                "running": self.running,
                "source": self.source,
                "source_label": self.source_label,
                "distance_mm": self.distance_mm,
                "emissivity": self.emissivity,
                "fps": self.fps,
                "frame_count": self.frame_count,
                "skin_spread": self.skin_spread,
                "unstable": self._unstable,
                "measure_state": self.measure_state,
                "measure_progress": len(self._measure_frames),
                "measure_target": self.measure_target,
                "error": self.error,
                "note": self.note,
                "view": self.view,
                "model_id": self.model_id,
                "mask_label": self.mask_label,
                "mask_confidence": self.mask_confidence,
                "mask_fraction": self.mask_fraction,
                "model_fps": self.model_fps,
            }

    def _build_state(self, snap: dict) -> dict:
        temps = snap["temps"]
        est_temps = snap["est_temps"]
        osd_info = snap["osd_info"]
        pose = snap["pose"]
        wound = snap["wound"]
        ref = snap["ref"]
        detection = snap["detection"]
        auto = snap["auto"]
        selected_region = snap["selected_region"]
        distance = snap["distance_mm"]
        emissivity = snap["emissivity"]
        unstable = snap["unstable"]
        base = {
            "running": snap["running"],
            "source": snap["source"],
            "source_label": snap["source_label"],
            "has_temperature": temps is not None,
            "distance_mm": distance,
            "emissivity": emissivity,
            "pixel_mm": round(pixel_mm(distance), 2),
            "fps": round(snap["fps"], 1),
            "frame_count": snap["frame_count"],
            "skin_spread": snap["skin_spread"],
            "unstable": unstable,
            "measure_state": snap["measure_state"],
            "measure_progress": snap["measure_progress"],
            "measure_target": snap["measure_target"],
            "error": snap["error"],
            "note": snap["note"],
            "matrix": None if temps is None else {"width": int(temps.shape[1]), "height": int(temps.shape[0])},
            "wound_roi": wound,
            "ref_roi": ref,
            "auto": auto,
            "selected_region": selected_region,
            "regions": [] if detection is None else list(detection.get("regions") or []),
            "view": snap["view"],
            "weight": snap["model_id"],
            "weight_label": "物理温度分割" if temps is not None else snap["mask_label"],
            "mask_confidence": snap["mask_confidence"],
            "mask_fraction": snap["mask_fraction"],
            "model_fps": round(snap["model_fps"], 1),
            "region_count": 0 if detection is None else len(detection.get("regions") or []),
            "pose": pose,
            "has_anchor": snap["has_anchor"],
            "osd": osd_info,
            "physics": None,
        }
        if temps is None:
            physics = (
                analyze_thermal_physics(est_temps, wound, ref, distance, body_mask=snap["last_mask"])
                if est_temps is not None
                else None
            )
            base.update(
                {
                    "wound": None if not osd_info else osd_info.get("est_wound"),
                    "ref": None if not osd_info else osd_info.get("est_ref"),
                    "delta": None if not osd_info else osd_info.get("est_delta"),
                    "delta_max": None if not osd_info else osd_info.get("est_delta_max"),
                    "grade": None,
                    "grade_text": "伪彩 OSD 双锚点反演（半定量）" if osd_info else "伪彩图像定位（无温度矩阵）",
                    "message": base["note"],
                    "frame_max": None if not osd_info else osd_info.get("osd_max"),
                    "physics": physics,
                }
            )
            for side in ("wound", "ref"):
                stats = base.get(side)
                if stats:
                    stats["mean"] = round(stats["mean"], 2)
                    stats["max"] = round(stats["max"], 2)
            return base

        # 手动模式严格只按用户框出的 wound/ref 计算，绝不被自动检测结果覆盖
        if not auto:
            judged = evaluate(temps, wound, ref)
        else:
            regions = base["regions"]
            if regions and 0 <= selected_region < len(regions) and selected_region > 0:
                chosen = regions[selected_region]
                judged = {
                    "wound": {
                        "mean": chosen["wound_mean"],
                        "max": chosen["wound_max"],
                        "n": int(chosen.get("wound_n", 0)),
                    },
                    "ref": {
                        "mean": chosen["ref_mean"],
                        "max": chosen.get("ref_max", chosen["ref_mean"]),
                        "n": int(chosen.get("ref_n", 0)),
                    },
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
        judged["physics"] = analyze_thermal_physics(temps, wound, ref, distance)
        if unstable and judged.get("grade") is not None:
            judged["message"] = "皮肤区域帧间跳变或极差超过 0.3 °C，可能是快门校正或手还在动，本帧请勿采信。"
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

    def state(self) -> dict:
        return self._build_state(self._snapshot())

    def _render_snapshot(self, temps: np.ndarray, wound: Optional[dict], ref: Optional[dict], current: dict) -> np.ndarray:
        canvas = _colorize(temps)
        h, w = canvas.shape[:2]
        for roi, color, tag in ((wound, (32, 176, 255), "W"), (ref, (255, 200, 126), "R")):
            bounds = roi_pixel_bounds((h, w), roi)
            if bounds is None:
                continue
            x0, y0, x1, y1 = bounds
            cv2.rectangle(canvas, (x0, y0), (x1, y1), (0, 0, 0), 4)
            cv2.rectangle(canvas, (x0, y0), (x1, y1), color, 2)
            ty = max(42, y0 - 4)
            cv2.putText(canvas, tag, (x0 + 4, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(canvas, tag, (x0 + 4, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
        tw = f"{current['wound']['mean']:.2f}" if current.get("wound") else "--"
        tr = f"{current['ref']['mean']:.2f}" if current.get("ref") else "--"
        grade_tag = current["grade"] if current.get("grade") is not None else "-"
        bar = (
            f"Tw={tw}C Tr={tr}C dT={current['delta']:+.2f}C G{grade_tag} "
            f"L={current['distance_mm']}mm eps={current['emissivity']:.2f} n={current['frame_count']}"
        )
        cv2.rectangle(canvas, (0, 0), (w, 26), (12, 14, 17), -1)
        cv2.putText(canvas, bar, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (240, 240, 240), 1, cv2.LINE_AA)
        return canvas

    def save_record(self, group: str = "日常初筛", ntc_delta: Optional[float] = None) -> dict:
        snap = self._snapshot()
        current = self._build_state(snap)
        temps = snap["temps"]
        wound = snap["wound"]
        ref = snap["ref"]

        if not current["has_temperature"] or current["delta"] is None:
            return {"ok": False, "error": "现在没有可记录的温差"}
        if current["unstable"]:
            return {"ok": False, "error": "当前画面波动超过 0.3 °C（手抖或快门校正），请稳定后再保存"}
        if temps is None:
            return {"ok": False, "error": "温度矩阵为空"}
        if wound is None or ref is None:
            return {"ok": False, "error": "当前尚未选定创口框与对照框，无法保存"}

        clean_group = str(group or "日常初筛").strip() or "日常初筛"
        clean_ntc: Optional[float] = None
        if ntc_delta is not None and str(ntc_delta).strip() != "":
            try:
                clean_ntc = round(float(ntc_delta), 2)
            except (TypeError, ValueError):
                clean_ntc = None

        with self._save_lock:
            CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
            RECORD_PATH.parent.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            npy_path = CAPTURE_DIR / f"{ts}_temps.npy"
            png_path = CAPTURE_DIR / f"{ts}_view.png"
            np.save(npy_path, temps)
            snap_img = self._render_snapshot(temps, wound, ref, current)
            ok, buf = cv2.imencode(".png", snap_img)
            if ok:
                png_path.write_bytes(buf.tobytes())

            write_header = not RECORD_PATH.exists()
            if not write_header:
                first_line = RECORD_PATH.read_text(encoding="utf-8-sig", errors="replace").splitlines()[0:1]
                if not first_line or "wound_px" not in first_line[0]:
                    target_csv = RECORD_PATH.with_name("records_v2.csv")
                    write_header = not target_csv.exists()
                else:
                    target_csv = RECORD_PATH
            else:
                target_csv = RECORD_PATH

            rel_npy = str(npy_path.relative_to(ROOT)) if npy_path.is_relative_to(ROOT) else str(npy_path)
            rel_png = str(png_path.relative_to(ROOT)) if png_path.is_relative_to(ROOT) else str(png_path)
            iso_time = datetime.now().isoformat(timespec="seconds")

            with target_csv.open("a", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                if write_header:
                    writer.writerow(RECORD_HEADERS)
                writer.writerow(
                    [
                        iso_time,
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
                        rel_npy,
                        rel_png,
                    ]
                )

            meta_path = RECORD_PATH.with_name("records_meta.json")
            meta_map: dict = {}
            if meta_path.exists():
                try:
                    loaded = json.loads(meta_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        meta_map = loaded
                except Exception:
                    meta_map = {}
            phys = current.get("physics") or {}
            meta_map[rel_npy] = {
                "group": clean_group,
                "ntc_delta": clean_ntc,
                "hot_area_mm2": phys.get("hot_area_mm2"),
                "equiv_diam_mm": phys.get("equiv_diam_mm"),
                "decay_slope": phys.get("decay_slope"),
                "pattern": phys.get("pattern"),
            }
            meta_path.write_text(json.dumps(meta_map, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "ok": True,
            "path": str(target_csv),
            "npy": str(npy_path),
            "png": str(png_path),
            "group": clean_group,
            "ntc_delta": clean_ntc,
        }

    def list_records(self, limit: int = 30) -> dict:
        """读取历史记录，生成纵向病程趋势预警以及课程验收分组重复性（Spread <= 0.3°C）/ NTC 对标统计。"""
        with self._save_lock:
            meta_path = RECORD_PATH.with_name("records_meta.json")
            meta_map: dict = {}
            if meta_path.exists():
                try:
                    loaded = json.loads(meta_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        meta_map = loaded
                except Exception:
                    meta_map = {}

            rows: list[dict] = []
            for csv_file in (RECORD_PATH, RECORD_PATH.with_name("records_v2.csv")):
                if not csv_file.exists():
                    continue
                try:
                    with csv_file.open("r", encoding="utf-8-sig", errors="replace") as handle:
                        for row in csv.DictReader(handle):
                            npy_key = str(row.get("npy_path") or "")
                            extra = meta_map.get(npy_key) or {}
                            try:
                                delta_val = float(row.get("delta") or 0.0)
                            except ValueError:
                                continue
                            try:
                                tw_val = float(row.get("t_wound") or 0.0)
                                tr_val = float(row.get("t_ref") or 0.0)
                            except ValueError:
                                tw_val, tr_val = 0.0, 0.0
                            try:
                                grade_val = int(row.get("grade")) if str(row.get("grade", "")).strip() != "" else None
                            except ValueError:
                                grade_val = None
                            rows.append(
                                {
                                    "time": str(row.get("time") or ""),
                                    "source": str(row.get("source") or ""),
                                    "distance_mm": int(float(row.get("distance_mm") or 300)),
                                    "frames_averaged": int(float(row.get("frames_averaged") or 1)),
                                    "wound_px": str(row.get("wound_px") or ""),
                                    "ref_px": str(row.get("ref_px") or ""),
                                    "t_wound": round(tw_val, 2),
                                    "t_ref": round(tr_val, 2),
                                    "delta": round(delta_val, 2),
                                    "grade": grade_val,
                                    "grade_text": str(row.get("grade_text") or ""),
                                    "npy_path": npy_key,
                                    "group": str(extra.get("group") or "日常初筛"),
                                    "ntc_delta": extra.get("ntc_delta"),
                                    "hot_area_mm2": extra.get("hot_area_mm2"),
                                    "pattern": extra.get("pattern"),
                                }
                            )
                except OSError:
                    continue

        rows.sort(key=lambda item: item["time"])
        # 纵向病程趋势评估（按最近 5 条时间顺序）
        trend = {"direction": "none", "change_c": 0.0, "alert": False, "summary": "尚无足够历史记录（至少保存 2 次以追踪趋势）"}
        if len(rows) >= 2:
            recent = rows[-5:]
            d_last = recent[-1]["delta"]
            d_prev = recent[-2]["delta"]
            diff = round(d_last - d_prev, 2)
            span = round(max(r["delta"] for r in recent) - min(r["delta"] for r in recent), 2)
            monotonic_up = len(recent) >= 3 and (recent[-3]["delta"] < recent[-2]["delta"] < recent[-1]["delta"])
            if diff >= 0.35 or (monotonic_up and (recent[-1]["delta"] - recent[-3]["delta"]) >= 0.4):
                trend = {
                    "direction": "up",
                    "change_c": diff,
                    "alert": True,
                    "summary": f"↑ 温差呈上升趋势（较上次 {diff:+.2f} °C，近期极差 {span:.2f} °C，警惕炎症进展）",
                }
            elif diff <= -0.35:
                trend = {
                    "direction": "down",
                    "change_c": diff,
                    "alert": False,
                    "summary": f"↓ 温差呈回落趋势（较上次 {diff:+.2f} °C，局部偏热消退）",
                }
            else:
                trend = {
                    "direction": "stable",
                    "change_c": diff,
                    "alert": False,
                    "summary": f"→ 温差平稳（较上次 {diff:+.2f} °C，近期散布 {span:.2f} °C）",
                }

        # 分组重复性（Spread <= 0.3 °C）与 NTC 标定统计
        by_group: dict[str, list[dict]] = {"全部": rows}
        for item in rows:
            g = item["group"]
            by_group.setdefault(g, []).append(item)

        group_stats = {}
        for g_name, items in by_group.items():
            if not items:
                continue
            deltas = [x["delta"] for x in items]
            n = len(deltas)
            mean_d = round(float(np.mean(deltas)), 2)
            sd_d = round(float(np.std(deltas)), 3) if n >= 2 else 0.0
            spread_d = round(float(max(deltas) - min(deltas)), 2) if n >= 2 else 0.0
            ntc_errs = [
                abs(x["delta"] - float(x["ntc_delta"]))
                for x in items
                if x.get("ntc_delta") is not None
            ]
            group_stats[g_name] = {
                "count": n,
                "mean": mean_d,
                "sd": sd_d,
                "spread": spread_d,
                "repeatability_ok": (spread_d <= 0.3) if n >= 2 else None,
                "ntc_count": len(ntc_errs),
                "ntc_mae": round(float(np.mean(ntc_errs)), 2) if ntc_errs else None,
            }

        recent_desc = list(reversed(rows[-max(1, int(limit)) :]))
        return {
            "ok": True,
            "total": len(rows),
            "records": recent_desc,
            "trend": trend,
            "groups": group_stats,
        }

    def load_capture(self, npy_rel_path: str, wound_px: str = "", ref_px: str = "") -> dict:
        """从 data/captures/*.npy 回载历史物理温度矩阵，支持事后重画框、切等温差线视图与点温复盘。"""
        if not npy_rel_path or not str(npy_rel_path).endswith(".npy"):
            return {"ok": False, "error": "无效的 .npy 归档路径"}
        candidate = (ROOT / npy_rel_path).resolve() if not Path(npy_rel_path).is_absolute() else Path(npy_rel_path).resolve()
        allowed_root = (ROOT / "data").resolve()
        if not (candidate.is_relative_to(allowed_root) or candidate.is_relative_to(CAPTURE_DIR.resolve())):
            return {"ok": False, "error": "仅允许加载 data 目录下的归档温度帧"}
        if not candidate.exists():
            return {"ok": False, "error": f"找不到归档文件: {candidate.name}"}
        try:
            temps = np.load(candidate).astype(np.float32)
        except Exception as exc:
            return {"ok": False, "error": f"加载 .npy 失败: {exc}"}
        if temps.ndim != 2 or temps.size < 40:
            return {"ok": False, "error": "温度矩阵维度无效"}

        self.stop()
        h, w = temps.shape[:2]

        def _parse_px_box(px_str: str) -> Optional[dict]:
            parts = [p.strip() for p in str(px_str or "").split(",") if p.strip()]
            if len(parts) != 4:
                return None
            try:
                x0, y0, x1, y1 = [int(float(v)) for v in parts]
            except ValueError:
                return None
            if x1 <= x0 or y1 <= y0:
                return None
            return _clean_roi({"x": x0 / w, "y": y0 / h, "w": (x1 - x0) / w, "h": (y1 - y0) / h})

        body = skin_mask(temps)
        detection = detect_anomalies(temps, prior_mask=body)
        pose = analyze_hand_pose(body)
        restored_w = _parse_px_box(wound_px) or detection.get("wound_roi") or dict(DEFAULT_WOUND)
        restored_r = _parse_px_box(ref_px) or detection.get("ref_roi") or dict(DEFAULT_REF)
        color_img = _colorize(temps)
        mask = (
            cv2.resize(body.astype(np.uint8), (color_img.shape[1], color_img.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
            if int(body.sum()) >= 30
            else None
        )
        ev = evaluate(temps, restored_w, restored_r)
        ref_t = float(ev["ref"]["mean"]) if ev.get("ref") else None
        with self._cond:
            view_mode = self.view
        rendered = self._compose(color_img, mask, view_mode, temps=temps, ref_temp=ref_t)
        jpeg = _encode_jpeg(rendered)

        with self._cond:
            self.running = False
            self.source = "replay"
            self.source_label = f"历史复盘 ({candidate.name})"
            self.error = ""
            self.raw_temps = temps
            self.temps = temps
            self._est_temps = None
            self._osd_info = None
            self._pose = pose
            self.frame_count = 10
            self.skin_spread = 0.0
            self._unstable = False
            self.measure_state = "locked"
            self.detection = detection
            self.wound = restored_w
            self.ref = restored_r
            self.auto = False
            self._anatomical_anchor = encode_anatomical_rois(pose, restored_w, restored_r)
            self.mask_confidence = 1.0 if mask is not None else 0.0
            self.mask_fraction = round(float(body.mean()), 3) if body.size else 0.0
            self.mask_label = "物理温度分割"
            self.jpeg = jpeg
            self._last_image = color_img
            self._last_mask = mask
            self.note = f"已回载历史温度矩阵 {candidate.name}：可自由切换等温差线视图、查点温或重新拖框复盘。"
            self.seq += 1
            self._cond.notify_all()
        return {"ok": True, "state": self.state()}

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
        elif source == "synthetic" or source.startswith("synthetic:"):
            scenario = source.split(":", 1)[1] if ":" in source else "strong"
            if scenario not in ("strong", "mild", "baseline"):
                with self._cond:
                    self.running = False
                    self.error = "未知自检场景"
                return
            labels = {
                "strong": "自检合成温度（+3.3 °C · 档 2）",
                "mild": "自检模拟偏热（+1.4 °C · 档 1）",
                "baseline": "自检空手基线（档 0）",
            }
            target = lambda: self._run_synthetic(stop_event, scenario)
            label = labels[scenario]
        elif source.startswith("cam:"):
            idx = int(source.split(":", 1)[1])
            target = lambda: self._run_camera(idx, stop_event)
            label = source
        else:
            with self._cond:
                self.running = False
                self.error = "未知来源"
            return

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
            stop = self._stop
            if not stop.is_set() and (self._infer_thread is None or not self._infer_thread.is_alive()):
                self._infer_thread = threading.Thread(
                    target=self._infer_loop,
                    args=(stop,),
                    name="segment",
                    daemon=True,
                )
                self._infer_thread.start()
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
        direct_mask = report.get("mask")
        confidence = float(report.get("confidence") or 0.0)
        if pred is None and direct_mask is None:
            with self._cond:
                self._prob_ema = None
                self._cached_mask = None
                self.mask_confidence = 0.0
                self.mask_fraction = 0.0
                self.mask_label = report.get("label") or self.mask_label
            return
        if pred is not None:
            covered = float((pred >= 0.42).mean())
            usable = confidence >= 0.45 and 0.03 <= covered <= 0.75
        else:
            usable = direct_mask is not None and confidence >= 0.45
        with self._cond:
            if report.get("corrected") or report.get("model") == "thermal":
                # 热像物理分割或纠偏掩膜直接平滑更新，立刻清除旧的错误冷背景缓存
                if pred is not None and self._prob_ema is not None and self._prob_ema.shape == pred.shape:
                    blended = self._prob_ema * 0.25 + pred.astype(np.float32) * 0.75
                else:
                    blended = None if pred is None else pred.astype(np.float32)
                self._prob_ema = blended
                mask = direct_mask if direct_mask is not None else (None if blended is None else solid_mask(blended, shape[1], shape[0]))
            else:
                if not usable:
                    self._prob_ema = None
                    mask = None
                elif self._prob_ema is None or self._prob_ema.shape != pred.shape:
                    self._prob_ema = pred.astype(np.float32)
                    mask = solid_mask(self._prob_ema, shape[1], shape[0])
                else:
                    self._prob_ema = self._prob_ema * 0.35 + pred.astype(np.float32) * 0.65
                    mask = solid_mask(self._prob_ema, shape[1], shape[0])
            now = time.monotonic()
            if mask is not None:
                self._cached_mask = mask
                self._mask_hold_until = now + 0.8
            elif now > self._mask_hold_until or not usable:
                self._cached_mask = None
            shown = self._cached_mask
            self.mask_confidence = round(confidence, 3) if shown is not None else 0.0
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

    def _publish(self, image: Optional[np.ndarray], temps: Optional[np.ndarray], note: str) -> None:
        if self._stop.is_set():
            return
        now = time.monotonic()
        if temps is None:
            assert image is not None
            # 仅无温度矩阵的伪彩视频流才送给 U²-Net 分割
            self._offer_frame(image)
            if now - self._shown_at < 0.08:
                return
            self._shown_at = now
            with self._cond:
                if self._stop.is_set():
                    return
                mask = None if self._cached_mask is None else self._cached_mask.copy()
                view_mode = self.view
                cur_auto = self.auto
                cur_wound = None if self.wound is None else dict(self.wound)
                cur_ref = None if self.ref is None else dict(self.ref)
            found = locate_hot_bgr(image, mask)
            active_w, active_r = (found if found else (None, None)) if cur_auto else (cur_wound, cur_ref)
            osd_info = invert_pseudocolor_temps(image, mask, active_w, active_r)
            est_temps = osd_info.pop("est_temps", None)
            ref_t = osd_info["est_ref"]["mean"] if osd_info.get("est_ref") else None
            pose = analyze_hand_pose(mask)
            rendered = self._compose(image, mask, view_mode, temps=est_temps, ref_temp=ref_t)
            jpeg = _encode_jpeg(rendered)
            with self._cond:
                if self._stop.is_set():
                    return
                auto = self.auto
                self.detection = None
                self.temps = None
                self.raw_temps = None
                self._est_temps = est_temps
                self._osd_info = osd_info
                self._pose = pose
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
                    if pose is not None and self._anatomical_anchor is None:
                        self._anatomical_anchor = encode_anatomical_rois(pose, self.wound, self.ref)
                    d_str = f"，反演 ΔT ≈ {osd_info['est_delta']:+.2f} °C" if osd_info.get("est_delta") is not None else ""
                    note = f"已从伪彩图像框出高温区（橙框）与对照区（蓝框）[{osd_info['anchor_mode']}{d_str}]。"
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
            if self._stop.is_set():
                return
            if self.measure_state == "locked":
                self._touch_fps()
                return

        cur_skin = skin_mask(temps)
        if int(cur_skin.sum()) >= 30:
            cur_skin_mean = float(np.mean(temps[cur_skin]))
        else:
            finite_vals = temps[np.isfinite(temps)]
            cur_skin_mean = float(np.mean(finite_vals)) if finite_vals.size else 0.0

        just_locked = False
        with self._cond:
            if self._stop.is_set():
                return
            if self.measure_state == "locked":
                self._touch_fps()
                return
            view_mode = self.view
            prev_mean = self._prev_skin_mean
            jump = 0.0 if prev_mean is None else abs(cur_skin_mean - prev_mean)
            self._prev_skin_mean = cur_skin_mean

            if jump > 0.3 or (self.history and self.history[-1].shape != temps.shape):
                self.history.clear()
                self._skin_means.clear()

            self.history.append(temps)
            self._skin_means.append(cur_skin_mean)
            smoothed = np.mean(np.stack(self.history, axis=0), axis=0).astype(np.float32)
            frame_count = len(self.history)
            if jump > 0.3:
                spread = jump
                unstable = True
            else:
                spread = (
                    float(max(self._skin_means) - min(self._skin_means))
                    if len(self._skin_means) >= 2
                    else 0.0
                )
                unstable = spread > 0.3

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
                            just_locked = True
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
        pose = analyze_hand_pose(body)
        detection = detect_anomalies(smoothed, prior_mask=body)
        found = None
        if detection.get("wound_roi") and detection.get("ref_roi"):
            found = (detection["wound_roi"], detection["ref_roi"])
        ref_t = detection["ref"]["mean"] if detection.get("ref") else None
        color_img = _colorize(smoothed)
        mask = None
        if int(body.sum()) >= 30:
            mask = (
                cv2.resize(
                    body.astype(np.uint8),
                    (color_img.shape[1], color_img.shape[0]),
                    interpolation=cv2.INTER_NEAREST,
                )
                > 0
            )
        rendered = self._compose(color_img, mask, view_mode, temps=smoothed, ref_temp=ref_t)
        jpeg = _encode_jpeg(rendered)

        with self._cond:
            if self._stop.is_set():
                return
            if self.measure_state == "locked" and not just_locked:
                return
            auto = self.auto
            selected_region = self.selected_region
            self.raw_temps = temps
            self.temps = smoothed
            self._est_temps = None
            self._osd_info = None
            self._pose = pose
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
                    if pose is not None:
                        self._anatomical_anchor = encode_anatomical_rois(pose, self.wound, self.ref)
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

    def _compose(
        self,
        image: np.ndarray,
        mask: Optional[np.ndarray],
        view_mode: Optional[str] = None,
        temps: Optional[np.ndarray] = None,
        ref_temp: Optional[float] = None,
    ) -> np.ndarray:
        mode = view_mode or self.view
        if mode == "isotherm":
            return render_isotherm_view(image, temps, mask, ref_temp=ref_temp)
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
                    with self._cond:
                        self._prob_ema = None
                        self._cached_mask = None
                        self._mask_hold_until = 0.0
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

    def _run_synthetic(self, stop: threading.Event, scenario: str = "strong") -> None:
        note = "自检用的合成温度，不是机芯。用 10 帧稳态平均与物理皮肤分割验证三级判定。"
        t = 0.0
        try:
            while not stop.is_set():
                temps = synthetic_frame(t, scenario=scenario)
                self._publish(None, temps, note)
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
                    self._publish(None, latest_temps, note_temp)
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
