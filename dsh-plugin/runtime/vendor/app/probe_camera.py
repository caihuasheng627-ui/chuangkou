# -*- coding: utf-8 -*-
"""UVC 热像仪格式、视频编码与 16bit 温度流探测工具。

整合自 dsh-wound-clinic v0.7.2，并补全：
1) FFmpeg DirectShow 设备与支持格式枚举（严格 UTF-8 → GBK 解码，避免中文乱码）
2) OpenCV DSHOW + MSMF 双后端多编码（default / MJPG / YUY2 / Y16）位深探测
3) 全程使用 Path.write_bytes / np.save，彻底避免中文用户名路径下的 OpenCV 写文件失败
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def decode_console_bytes(raw: bytes) -> str:
    """优先严格 UTF-8 解码，失败再按中文 Windows GBK 解码，避免中文设备名乱码。"""
    if not raw:
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("gbk")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


def fourcc_to_str(value) -> str:
    try:
        v = int(value)
        chars = "".join(chr((v >> (8 * i)) & 0xFF) for i in range(4))
        return chars if chars.isprintable() else f"0x{v:08x}"
    except Exception:
        return str(value)


def _visualize(raw: np.ndarray) -> np.ndarray:
    norm = cv2.normalize(raw.astype(np.float32), None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    return cv2.applyColorMap(norm, cv2.COLORMAP_INFERNO)


def guess_raw_unit(mean_value: float, dtype) -> str:
    if str(dtype) != "uint16":
        return "当前为 8bit 伪彩/彩色帧，不是 16bit 原始温度矩阵；需切全屏测温流或使用厂商 SDK。"
    if 2500 <= mean_value <= 5000:
        return "均值落在 2500~5000，疑似 0.01°C 编码（如 3350≈33.50°C），需已知温点校验。"
    if 250 <= mean_value <= 500:
        return "均值落在 250~500，疑似 0.1°C 编码（如 335≈33.5°C），需已知温点校验。"
    if 18000 <= mean_value <= 21500:
        return "均值落在 18000~21500，疑似 Kelvin×64 编码（raw/64 - 273.15），需已知温点校验。"
    if 28500 <= mean_value <= 32500:
        return "均值落在 28500~32500，疑似 Kelvin×100 编码（raw/100 - 273.15），需已知温点校验。"
    return "16bit 数值范围非常规直接编码，需对照 SDK 文档或两点标定。"


def probe_ffmpeg_dshow_options(device_target: str) -> list[str]:
    """用 ffmpeg -list_options 查询 DirectShow 相机原生支持的编码/像素格式与分辨率。"""
    if platform.system() != "Windows":
        return []
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-f", "dshow", "-list_options", "true", "-i", f"video={device_target}"],
            capture_output=True,
            timeout=6,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    text = decode_console_bytes(proc.stderr)
    options: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if any(k in s for k in ("pixel_format=", "vcodec=", "min s=")):
            idx = s.find("]")
            options.append(s[idx + 1 :].strip() if idx >= 0 else s)
    return options[:24]


def probe_opencv_once(
    index: int,
    backend_name: str,
    backend: int,
    mode: Optional[str],
    frames: int,
    out_dir: Optional[Path] = None,
    width: int = 0,
    height: int = 0,
) -> dict:
    cap = cv2.VideoCapture(index, backend)
    if not cap.isOpened():
        return {
            "camera": index,
            "backend": backend_name,
            "mode_requested": mode or "default",
            "opened": False,
            "read_frames": 0,
            "error": "无法打开相机",
        }

    if mode:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*mode))
    if width > 0:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    if height > 0:
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    if mode and mode.strip().upper() == "Y16":
        try:
            cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
        except Exception:
            pass

    last = None
    read_ok = 0
    for _ in range(max(1, frames)):
        ok, frame = cap.read()
        if ok and frame is not None and frame.size > 0:
            last = frame
            read_ok += 1

    info: dict = {
        "camera": index,
        "backend": backend_name,
        "mode_requested": mode or "default",
        "opened": True,
        "read_frames": read_ok,
        "fourcc_actual": fourcc_to_str(cap.get(cv2.CAP_PROP_FOURCC)),
        "width_actual": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height_actual": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "fps_actual": round(float(cap.get(cv2.CAP_PROP_FPS)), 2),
    }
    cap.release()

    if last is None:
        info["error"] = "打开成功但没有读到帧（可能被占用、权限受限或编码不匹配）"
        return info

    raw = last if last.ndim == 2 else last[:, :, 0]
    info.update(
        {
            "frame_shape": list(last.shape),
            "dtype": str(last.dtype),
            "channels": 1 if last.ndim == 2 else int(last.shape[2]),
            "raw_min": float(np.min(raw)),
            "raw_max": float(np.max(raw)),
            "raw_mean": round(float(np.mean(raw)), 2),
            "raw_std": round(float(np.std(raw)), 2),
            "is_16bit_candidate": str(last.dtype) == "uint16" and float(np.max(raw)) > 255.0,
            "hint": guess_raw_unit(float(np.mean(raw)), last.dtype),
        }
    )

    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        tag = f"cam{index}_{backend_name}_{(mode.strip() if mode else 'default')}"
        npy_path = out_dir / f"{tag}_raw.npy"
        np.save(npy_path, raw)
        ok, buf = cv2.imencode(".png", _visualize(raw))
        if ok:
            (out_dir / f"{tag}_preview.png").write_bytes(buf.tobytes())
        info["saved_raw"] = str(npy_path)
    return info


def probe_devices(
    cameras: Optional[list[int]] = None,
    frames: int = 6,
    out_dir: Optional[Path] = None,
) -> dict:
    """探测已枚举的 DirectShow 设备格式以及 OpenCV 各后端实际返回帧的编码/位深。"""
    from app.engine import list_cameras

    enumerated = list_cameras()
    dshow_options: list[dict] = []
    for dev in enumerated:
        target = dev.get("dshow") or dev.get("label") or ""
        if target and dev.get("backend") == "dshow":
            dshow_options.append(
                {
                    "id": dev["id"],
                    "label": dev["label"],
                    "options": probe_ffmpeg_dshow_options(target),
                }
            )

    if cameras is None:
        if enumerated:
            cameras = list(range(min(len(enumerated), 3)))
        else:
            cameras = [0, 1]

    backends = (
        [("DSHOW", cv2.CAP_DSHOW), ("MSMF", cv2.CAP_MSMF)]
        if platform.system() == "Windows"
        else [("V4L2", cv2.CAP_V4L2)]
    )

    results: list[dict] = []
    for idx in cameras:
        for b_name, b_id in backends:
            for mode in (None, "MJPG", "Y16 "):
                results.append(probe_opencv_once(idx, b_name, b_id, mode, frames, out_dir=out_dir))

    has_16bit = any(item.get("is_16bit_candidate") for item in results)
    summary = (
        "检测到 16bit 候选原始帧，可进一步验证温度换算系数。"
        if has_16bit
        else "当前探测到的 OpenCV 流均为 8bit 伪彩/彩色或无帧；若需真实全屏温度矩阵，请确认模组切至全屏测温流或使用海康微影 SDK。"
    )
    payload = {
        "ok": True,
        "devices": enumerated,
        "dshow_options": dshow_options,
        "opencv_probes": results,
        "has_16bit_candidate": has_16bit,
        "summary": summary,
    }
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "probe_result.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return payload


def main() -> int:
    _configure_stdio()
    ap = argparse.ArgumentParser(description="UVC 热像仪编码与位深探测")
    ap.add_argument("--cameras", type=int, nargs="+", default=None)
    ap.add_argument("--frames", type=int, default=8)
    ap.add_argument("--out", default="data/probe_output")
    args = ap.parse_args()

    out_dir = Path(args.out)
    payload = probe_devices(cameras=args.cameras, frames=args.frames, out_dir=out_dir)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
