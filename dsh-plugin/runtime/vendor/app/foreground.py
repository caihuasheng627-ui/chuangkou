"""去背景分割模块：热像伪彩自适应分割 + U²-Net 物理温区防漂移门控。

- thermal：热像伪彩分割（推荐），直接沿铁红/白热单调色标执行 Otsu + 连通域分割，零域偏移
- u2netp：U²-Net 小模型，经热像暖区门控与纠偏
- u2net：U²-Net 标准模型，经热像暖区门控与纠偏
- human：U²-Net 人体分割（原训练集为可见光全身人像；对热像手掌置信度不足或误框冷背景时自动热像纠偏）
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent / "weights"
MODELS = {
    "thermal": {"file": None, "label": "热像伪彩分割"},
    "u2netp": {"file": "u2netp.onnx", "label": "U2-Net 小"},
    "u2net": {"file": "u2net.onnx", "label": "U2-Net 标准"},
    "human": {"file": "u2net_human_seg.onnx", "label": "人体分割"},
}
_SESSIONS: dict = {}
_FAILED: set[str] = set()
_ACTIVE = "thermal"


def available_models() -> list[dict]:
    items = []
    for key, spec in MODELS.items():
        if spec["file"] is None:
            ready = True
        else:
            path = ROOT / spec["file"]
            ready = path.exists() and key not in _FAILED
        items.append({"id": key, "label": spec["label"], "ready": ready})
    return items


def set_model(model_id: str) -> str:
    global _ACTIVE
    if model_id in MODELS:
        spec = MODELS[model_id]
        if spec["file"] is None or (ROOT / spec["file"]).exists():
            _ACTIVE = model_id
    return _ACTIVE


def current_model() -> str:
    return _ACTIVE


def _session(model_id: str):
    if model_id in _FAILED or model_id not in MODELS:
        return None
    filename = MODELS[model_id]["file"]
    if filename is None:
        return None
    path = ROOT / filename
    if not path.exists():
        return None
    if model_id not in _SESSIONS:
        try:
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            try:
                _SESSIONS[model_id] = ort.InferenceSession(
                    str(path),
                    sess_options=options,
                    providers=["CPUExecutionProvider"],
                )
            except Exception:
                # Windows 非 ASCII 路径（如中文用户名目录）下退回内存字节加载
                _SESSIONS[model_id] = ort.InferenceSession(
                    path.read_bytes(),
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


def thermal_color_mask(image_bgr: np.ndarray) -> tuple[np.ndarray | None, float]:
    """沿铁红/白热伪彩单调热强度分割手部前景，彻底杜绝把冷紫色背景误判为前景。"""
    from app.protocol import _warm_score

    if image_bgr is None or image_bgr.size == 0:
        return None, 0.0
    score = _warm_score(image_bgr)
    nz = score[score > 0]
    if nz.size < 40:
        return None, 0.0
    low = float(np.percentile(nz, 25))
    high = float(np.percentile(nz, 92))
    if high - low < 18.0:
        return None, 0.0

    otsu_thr, _ = cv2.threshold(
        np.clip(score, 0, 255).astype(np.uint8),
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU,
    )
    thr = max(float(otsu_thr), low + 0.42 * (high - low))
    warm = (score >= thr).astype(np.uint8)
    k_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    k_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    cleaned = cv2.morphologyEx(warm, cv2.MORPH_CLOSE, k_close, borderType=cv2.BORDER_CONSTANT, borderValue=0) | warm
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, k_open)

    count, labels, stats, _ = cv2.connectedComponentsWithStats(cleaned, 8)
    minimum = max(40, int(0.025 * score.size))
    maximum = int(0.75 * score.size)
    best = None
    for idx in range(1, count):
        area = int(stats[idx, cv2.CC_STAT_AREA])
        if area < minimum or area > maximum:
            continue
        comp = labels == idx
        mean_s = float(score[comp].mean())
        rank = mean_s * float(area)
        if best is None or rank > best[0]:
            best = (rank, comp, mean_s)
    if best is None:
        return None, 0.0
    conf = min(0.99, max(0.60, (best[2] - low) / max(1.0, high - low)))
    return best[1], round(conf, 3)


def _mask_to_prob320(mask: np.ndarray) -> np.ndarray:
    u8 = mask.astype(np.uint8) * 255
    resized = cv2.resize(u8, (320, 320), interpolation=cv2.INTER_AREA)
    return (resized.astype(np.float32) / 255.0).astype(np.float32)


def foreground_report(image_bgr: np.ndarray, model_id: str | None = None, min_confidence: float = 0.5) -> dict:
    """运行所选分割方式；对 U²-Net 权重执行热像暖区一致性校验，防止误把冷背景当人体。"""
    chosen = model_id or _ACTIVE
    label = MODELS.get(chosen, {}).get("label", chosen)
    empty = {
        "model": chosen,
        "label": label,
        "confidence": 0.0,
        "fraction": 0.0,
        "mask": None,
        "prob": None,
        "corrected": False,
    }
    if image_bgr is None or image_bgr.size == 0:
        return empty

    height, width = image_bgr.shape[:2]
    t_mask, t_conf = thermal_color_mask(image_bgr)

    if chosen == "thermal":
        if t_mask is None:
            return empty
        return {
            "model": "thermal",
            "label": MODELS["thermal"]["label"],
            "confidence": t_conf,
            "fraction": round(float(t_mask.mean()), 3),
            "mask": t_mask,
            "prob": _mask_to_prob320(t_mask),
            "corrected": False,
        }

    session = _session(chosen)
    if session is None:
        if t_mask is not None:
            return {
                "model": chosen,
                "label": f"{label} · 热像纠偏",
                "confidence": t_conf,
                "fraction": round(float(t_mask.mean()), 3),
                "mask": t_mask,
                "prob": _mask_to_prob320(t_mask),
                "corrected": True,
            }
        return empty

    pred = _predict(session, image_bgr)
    confidence = float(pred.max())
    u_mask = solid_mask(pred, width, height) if confidence >= 0.45 else None

    # 热像物理一致性门控：若 U²-Net（尤其是人体分割）在热像手掌上漏检、错框冷紫背景或吞入大片背景，则自动纠偏/收敛
    if t_mask is not None:
        if u_mask is None:
            return {
                "model": chosen,
                "label": f"{label} · 热像纠偏",
                "confidence": t_conf,
                "fraction": round(float(t_mask.mean()), 3),
                "mask": t_mask,
                "prob": _mask_to_prob320(t_mask),
                "corrected": True,
            }
        inter = int((u_mask & t_mask).sum())
        recall = inter / max(1, int(t_mask.sum()))
        precision = inter / max(1, int(u_mask.sum()))
        t_env = cv2.dilate(t_mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13))) > 0
        if recall < 0.72 or precision < 0.45:
            # U²-Net 漏掉超过 28% 的暖区手掌，或超过 55% 落在冷背景上，直接切回热像手部掩膜
            return {
                "model": chosen,
                "label": f"{label} · 热像纠偏",
                "confidence": t_conf,
                "fraction": round(float(t_mask.mean()), 3),
                "mask": t_mask,
                "prob": _mask_to_prob320(t_mask),
                "corrected": True,
            }
        # 若 U²-Net 吞入了较多冷紫背景边缘，用热像暖区包络裁净边缘
        refined = u_mask & t_env
        if int(refined.sum()) >= max(40, int(0.025 * u_mask.size)) and precision < 0.75:
            return {
                "model": chosen,
                "label": f"{label} · 暖区收敛",
                "confidence": round(max(confidence, t_conf), 3),
                "fraction": round(float(refined.mean()), 3),
                "mask": refined,
                "prob": _mask_to_prob320(refined),
                "corrected": True,
            }

    binary = pred >= min_confidence
    fraction = float(binary.mean())
    mask = u_mask if u_mask is not None else (
        cv2.resize(binary.astype(np.uint8), (width, height), interpolation=cv2.INTER_NEAREST) > 0
        if (confidence >= min_confidence and 0.04 <= fraction <= 0.8)
        else None
    )
    return {
        "model": chosen,
        "label": label,
        "confidence": round(confidence, 3),
        "fraction": round(float(mask.mean()), 3) if mask is not None else round(fraction, 3),
        "mask": mask,
        "prob": pred.astype(np.float32),
        "corrected": False,
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
    # 填平轮廓内部的封闭空洞（防止 U²-Net 把白热创口核心误抠成亮斑空洞），同时保留指缝外凹轮廓
    padded = cv2.copyMakeBorder(keep, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    cv2.floodFill(padded, None, (0, 0), 2)
    keep = np.maximum(keep, (padded[1:-1, 1:-1] == 0).astype(np.uint8))
    fraction = float(keep.mean())
    if fraction < 0.03 or fraction > 0.75:
        return None
    lifted = cv2.resize(keep, (width, height), interpolation=cv2.INTER_LINEAR)
    return lifted >= 0.5


def foreground_mask(image_bgr: np.ndarray, min_confidence: float = 0.5) -> np.ndarray | None:
    return foreground_report(image_bgr, min_confidence=min_confidence)["mask"]
