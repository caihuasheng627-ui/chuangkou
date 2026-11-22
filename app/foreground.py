"""去背景权重。三套都是 Xuebin Qin 等的 U²-Net，Apache-2.0。

- u2netp：小模型，快
- u2net：标准显著目标分割，边缘更完整
- human：人体分割，专门把人从背景里分开

ONNX 由 rembg 发布：https://github.com/danielgatis/rembg/releases/tag/v0.0.0
热像伪彩不是这些模型的训练域。置信度不够时返回空，后面的热区框就不会画。
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent / "weights"
MODELS = {
    "u2netp": {"file": "u2netp.onnx", "label": "U2-Net 小"},
    "u2net": {"file": "u2net.onnx", "label": "U2-Net 标准"},
    "human": {"file": "u2net_human_seg.onnx", "label": "人体分割"},
}
_SESSIONS: dict = {}
_FAILED: set[str] = set()
_ACTIVE = "u2netp"


def available_models() -> list[dict]:
    items = []
    for key, spec in MODELS.items():
        path = ROOT / spec["file"]
        items.append({"id": key, "label": spec["label"], "ready": path.exists() and key not in _FAILED})
    return items


def set_model(model_id: str) -> str:
    global _ACTIVE
    if model_id in MODELS and (ROOT / MODELS[model_id]["file"]).exists():
        _ACTIVE = model_id
    return _ACTIVE


def current_model() -> str:
    return _ACTIVE


def _session(model_id: str):
    if model_id in _FAILED:
        return None
    path = ROOT / MODELS[model_id]["file"]
    if not path.exists():
        return None
    if model_id not in _SESSIONS:
        try:
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            _SESSIONS[model_id] = ort.InferenceSession(
                str(path),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
        except Exception:
            _FAILED.add(model_id)
            return None
    return _SESSIONS[model_id]


def _predict(session, image_bgr: np.ndarray) -> np.ndarray:
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    resized = cv2.resize(rgb, (320, 320), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    blob = ((resized - mean) / std).transpose(2, 0, 1)[None]
    pred = session.run(None, {session.get_inputs()[0].name: blob})[0][0, 0]
    return pred


def foreground_report(image_bgr: np.ndarray, model_id: str | None = None, min_confidence: float = 0.5) -> dict:
    """跑当前权重。拿不准时 mask 为 None，并带上置信度和前景占比。"""
    chosen = model_id or _ACTIVE
    empty = {
        "model": chosen,
        "label": MODELS.get(chosen, {}).get("label", chosen),
        "confidence": 0.0,
        "fraction": 0.0,
        "mask": None,
        "prob": None,
    }
    if image_bgr is None or image_bgr.size == 0:
        return empty
    session = _session(chosen)
    if session is None:
        return empty
    pred = _predict(session, image_bgr)
    confidence = float(pred.max())
    binary = pred >= min_confidence
    fraction = float(binary.mean())
    height, width = image_bgr.shape[:2]
    mask = None
    if confidence >= min_confidence and 0.04 <= fraction <= 0.8:
        mask = cv2.resize(binary.astype(np.uint8), (width, height), interpolation=cv2.INTER_NEAREST) > 0
    return {
        "model": chosen,
        "label": MODELS[chosen]["label"],
        "confidence": round(confidence, 3),
        "fraction": round(fraction, 3),
        "mask": mask,
        "prob": pred.astype(np.float32),
    }


def solid_mask(prob: np.ndarray, width: int, height: int) -> np.ndarray | None:
    """把 320×320 的概率收成一整块前景。碎点、细丝和突然撑满画面的结果丢掉。"""
    if prob is None or prob.size == 0 or width < 2 or height < 2:
        return None
    binary = (prob >= 0.42).astype(np.uint8)
    opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(opened, 8)
    if count <= 1:
        return None
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    keep = np.uint8(labels == largest)
    keep = cv2.morphologyEx(keep, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)))
    fraction = float(keep.mean())
    if fraction < 0.04 or fraction > 0.75:
        return None
    lifted = cv2.resize(keep, (width, height), interpolation=cv2.INTER_LINEAR)
    return lifted >= 0.5


def foreground_mask(image_bgr: np.ndarray, min_confidence: float = 0.5) -> np.ndarray | None:
    return foreground_report(image_bgr, min_confidence=min_confidence)["mask"]
