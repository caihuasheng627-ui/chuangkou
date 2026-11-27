"""全屏温度帧解析、物理温度手部分割，以及创口相对温差的三级判定。"""

from __future__ import annotations

import struct
from typing import Optional

import cv2
import numpy as np

MAGIC = 0x70827773
MAGIC_BYTES = struct.pack("<I", MAGIC)

# 与 static/app.js 里的默认框保持一致。坐标是画面宽高的比例。
DEFAULT_WOUND = {"x": 0.585, "y": 0.433, "w": 0.08, "h": 0.10}
DEFAULT_REF = {"x": 0.28, "y": 0.36, "w": 0.14, "h": 0.20}

GRADE_TEXT = {
    0: "未见明显局部温升",
    1: "局部偏热，建议观察",
    2: "温升明显，建议进一步检查",
}


def grade_delta(delta: float) -> int:
    val = round(float(delta), 4)
    if val < 1.0:
        return 0
    if val < 2.2:
        return 1
    return 2


def _empty_detection(message: str, has_skin: bool = False) -> dict:
    return {
        "regions": [],
        "wound_roi": None,
        "ref_roi": None,
        "wound": None,
        "ref": None,
        "delta": None,
        "delta_max": None,
        "grade": 0 if has_skin else None,
        "grade_text": GRADE_TEXT[0] if has_skin else message,
        "message": message,
    }


def _box_roi(x: float, y: float, w: float, h: float, width: int, height: int) -> dict:
    x0 = min(max(x, 0.0), float(width - 2))
    y0 = min(max(y, 0.0), float(height - 2))
    x1 = min(max(x + w, x0 + 1.0), float(width))
    y1 = min(max(y + h, y0 + 1.0), float(height))
    return {"x": x0 / width, "y": y0 / height, "w": (x1 - x0) / width, "h": (y1 - y0) / height}


def roi_pixel_bounds(shape: tuple[int, ...], roi: Optional[dict]) -> Optional[tuple[int, int, int, int]]:
    """把归一化 ROI 转成 (x0, y0, x1, y1) 整数像素切片范围。"""
    if not roi or len(shape) < 2:
        return None
    height, width = int(shape[0]), int(shape[1])
    if width < 2 or height < 2:
        return None
    x0 = int(np.clip(float(roi["x"]), 0.0, 1.0) * width)
    y0 = int(np.clip(float(roi["y"]), 0.0, 1.0) * height)
    x1 = int(np.clip(float(roi["x"]) + float(roi["w"]), 0.0, 1.0) * width)
    y1 = int(np.clip(float(roi["y"]) + float(roi["h"]), 0.0, 1.0) * height)
    x0 = min(max(x0, 0), width - 1)
    y0 = min(max(y0, 0), height - 1)
    x1 = min(max(x1, x0 + 1), width)
    y1 = min(max(y1, y0 + 1), height)
    return x0, y0, x1, y1


def _roi_mask(shape: tuple[int, int], roi: dict) -> np.ndarray:
    mask = np.zeros(shape, dtype=bool)
    bounds = roi_pixel_bounds(shape, roi)
    if bounds is None:
        return mask
    x0, y0, x1, y1 = bounds
    mask[y0:y1, x0:x1] = True
    return mask


def _ring_reference(
    temps: np.ndarray,
    body: np.ndarray,
    component: np.ndarray,
    wound_roi: Optional[dict] = None,
):
    """在异常热区外围 2~12 像素皮肤环带内选取对照区，并使展示框与参与计算的像素一致。"""
    height, width = temps.shape
    gap_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    outer_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))
    comp_u8 = component.astype(np.uint8)
    inner_excl = cv2.dilate(comp_u8, gap_kernel).astype(bool)
    outer_dilated = cv2.dilate(comp_u8, outer_kernel).astype(bool)

    clean_skin = body & ~inner_excl
    if wound_roi is not None:
        candidate_skin = clean_skin & ~_roi_mask((height, width), wound_roi)
        if int((outer_dilated & candidate_skin).sum()) >= 8:
            clean_skin = candidate_skin

    ring = outer_dilated & clean_skin
    if int(ring.sum()) < 8:
        clean_skin = body & ~component
        ring = outer_dilated & clean_skin
    if int(ring.sum()) < 8:
        ring = clean_skin
    if int(ring.sum()) < 8:
        return None

    side = max(8, int(min(width, height) * 0.09))
    coverage = cv2.boxFilter(
        clean_skin.astype(np.float32),
        -1,
        (side, side),
        normalize=True,
        borderType=cv2.BORDER_CONSTANT,
    )
    ys, xs = np.where(component)
    cy, cx = float(np.mean(ys)), float(np.mean(xs))
    ry, rx = np.where(ring)
    cov = coverage[ry, rx]
    max_cov = float(cov.max())
    good = cov >= max(0.5, max_cov - 0.08)
    if not good.any():
        good = np.ones(rx.shape[0], dtype=bool)

    gx, gy = rx[good], ry[good]
    dist = np.hypot(gx.astype(np.float32) - cx, gy.astype(np.float32) - cy)
    target_d = float(np.percentile(dist, 35))
    best_idx = int(np.argmin(np.abs(dist - target_d)))
    mx = float(gx[best_idx])
    my = float(gy[best_idx])
    ref_roi = _box_roi(mx - side / 2, my - side / 2, side, side, width, height)

    # 优先取“蓝框内且属于皮肤非创口”的像素做对照，确保界面框选与数值严格一致
    box_skin = _roi_mask((height, width), ref_roi) & body & ~component
    if int(box_skin.sum()) >= 6:
        values = temps[box_skin]
    else:
        values = temps[ring]
    return float(np.mean(values)), float(np.max(values)), int(values.size), ref_roi


def skin_mask(temps: np.ndarray, finite: Optional[np.ndarray] = None) -> np.ndarray:
    """从物理温度矩阵中提取手部皮肤区域（过滤冷桌面、边缘噪声与 >44°C 非皮肤热源）。"""
    if finite is None:
        finite = np.isfinite(temps)
    if int(finite.sum()) < 30:
        return np.zeros(temps.shape[:2], dtype=bool)

    skin_range = finite & (temps >= 28.0) & (temps <= 44.0)
    if int(skin_range.sum()) < 30:
        return np.zeros(temps.shape[:2], dtype=bool)

    values = temps[finite & (temps <= 44.0)]
    low = float(np.percentile(values, 30))
    high = float(np.percentile(values, 90))
    if low >= 28.0 and high - low < 4.0:
        warm = skin_range
    elif low >= 28.0:
        threshold = low + 0.55 * (high - low)
        warm = skin_range & (temps >= threshold)
    else:
        threshold = min(30.0, max(28.0, low + 0.55 * (high - low)))
        warm = skin_range & (temps >= threshold)
        if int(warm.sum()) < 30:
            warm = skin_range & (temps >= max(28.0, low + 0.35 * (high - low)))

    # 用闭运算填补手背内部小孔洞（显式冷边界避免画面四周误封），并按皮肤生理温区似然择优
    close_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    warm_u8 = warm.astype(np.uint8)
    closed = cv2.morphologyEx(
        warm_u8,
        cv2.MORPH_CLOSE,
        close_k,
        borderType=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    cleaned = ((closed > 0) | warm) & skin_range
    count, labels, stats, _ = cv2.connectedComponentsWithStats(cleaned.astype(np.uint8), 8)
    best = None
    minimum = max(30, int(0.02 * temps.size))
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        if area < minimum:
            continue
        component = (labels == index) & finite
        comp_n = int(component.sum())
        if comp_n < minimum:
            continue
        med = float(np.median(temps[component]))
        if not (28.5 <= med <= 41.0):
            continue
        skin_likelihood = float(np.exp(-0.5 * ((med - 34.5) / 2.2) ** 2))
        score = skin_likelihood * float(comp_n)
        if best is None or score > best[0]:
            best = (score, component)
    if best is None:
        return np.zeros(temps.shape[:2], dtype=bool)
    return best[1]


def _masked_opening(temps: np.ndarray, interior: np.ndarray, kernel_size: int) -> np.ndarray:
    """仅在前景掩膜内部执行灰度开运算，避免掩膜外数值或边界填充泄漏到手指。"""
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    erode_in = np.where(interior, temps, 100.0).astype(np.float32)
    eroded = cv2.erode(erode_in, kernel, borderType=cv2.BORDER_CONSTANT, borderValue=100.0)
    dilate_in = np.where(interior, eroded, -100.0).astype(np.float32)
    return cv2.dilate(dilate_in, kernel, borderType=cv2.BORDER_CONSTANT, borderValue=-100.0)


def detect_anomalies(temps: np.ndarray, prior_mask: np.ndarray | None = None) -> dict:
    """只在手的内部找比周围皮肤更热的块。手和桌面的分界不算异常。"""
    height, width = temps.shape[:2]
    finite = np.isfinite(temps)
    if int(finite.sum()) < 40:
        return _empty_detection("没有有效温度")

    if prior_mask is not None and prior_mask.shape == temps.shape and int(prior_mask.sum()) >= 30:
        body = finite & prior_mask.astype(bool)
    else:
        body = skin_mask(temps, finite)
    if int(body.sum()) < 30 or float(np.median(temps[body])) < 28.0:
        return _empty_detection("没有看到成片的皮肤温度")

    # 轻度内缩 1~2 像元避免边界过渡像元干扰，同时保留手指细节
    margin = max(1, int(min(height, width) * 0.015))
    margin_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (margin * 2 + 1, margin * 2 + 1))
    interior = cv2.erode(
        body.astype(np.uint8),
        margin_kernel,
        borderType=cv2.BORDER_CONSTANT,
        borderValue=0,
    ).astype(bool)
    if int(interior.sum()) < 20:
        interior = body

    k_small = max(15, int(min(height, width) * 0.18)) | 1
    k_large = max(29, int(min(height, width) * 0.32)) | 1
    e_small = np.where(interior, temps - _masked_opening(temps, interior, k_small), 0.0)
    e_large = np.where(interior, temps - _masked_opening(temps, interior, k_large), 0.0)
    excess = np.maximum(e_small, e_large).astype(np.float32)
    seeds = (excess >= 0.7).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(seeds, 8)
    min_area = max(4, int(0.0004 * height * width))
    skin_area = int(interior.sum())

    found = []
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        if area < min_area or area > 0.35 * skin_area:
            continue
        component = labels == index
        x, y, w, h = (int(stats[index, 0]), int(stats[index, 1]), int(stats[index, 2]), int(stats[index, 3]))
        roi = _box_roi(x, y, w, h, width, height)
        ref = _ring_reference(temps, interior, component, roi)
        if ref is None:
            continue
        ref_mean, ref_max, ref_n, ref_roi = ref
        spot = temps[component]
        mean = float(np.mean(spot))
        peak = float(np.max(spot))
        delta = mean - ref_mean
        if delta > 8.0:
            continue
        grade = grade_delta(delta)
        found.append(
            {
                "roi": roi,
                "ref_roi": ref_roi,
                "mean": mean,
                "max": peak,
                "n": int(spot.size),
                "ref_mean": ref_mean,
                "ref_max": ref_max,
                "ref_n": ref_n,
                "delta": delta,
                "delta_max": peak - ref_mean,
                "grade": grade,
                "grade_text": GRADE_TEXT[grade],
                "area": area,
            }
        )

    if not found:
        return _empty_detection("手和桌面的温差已排除，没有比周围皮肤更热的一块", has_skin=True)

    found.sort(key=lambda item: item["delta"], reverse=True)
    primary = found[0]
    anomalies = [item for item in found if item["delta"] >= 1.0]
    if not anomalies:
        if primary["delta"] >= 0:
            msg = f"未发现 ≥ 1.0 °C 局部温升（皮肤内最大局部差约 +{primary['delta']:.1f} °C），手和桌面的差距已排除"
        else:
            msg = "未发现 ≥ 1.0 °C 局部温升，手和桌面的差距已排除"
        return _empty_detection(msg, has_skin=True)

    message = f"发现 {len(anomalies)} 处局部温升，最明显的一块 +{primary['delta']:.1f} °C"
    return {
        "regions": [
            {
                "roi": item["roi"],
                "ref_roi": item["ref_roi"],
                "delta": round(item["delta"], 2),
                "delta_max": round(item["delta_max"], 2),
                "wound_mean": round(item["mean"], 2),
                "wound_max": round(item["max"], 2),
                "wound_n": item["n"],
                "ref_mean": round(item["ref_mean"], 2),
                "ref_max": round(item["ref_max"], 2),
                "ref_n": item["ref_n"],
                "grade": item["grade"],
                "grade_text": item["grade_text"],
            }
            for item in anomalies
        ],
        "wound_roi": primary["roi"],
        "ref_roi": primary["ref_roi"],
        "wound": {"mean": primary["mean"], "max": primary["max"], "n": primary["n"]},
        "ref": {"mean": primary["ref_mean"], "max": primary["ref_max"], "n": primary["ref_n"]},
        "delta": primary["delta"],
        "delta_max": primary["delta_max"],
        "grade": primary["grade"],
        "grade_text": primary["grade_text"],
        "message": message,
    }


def roi_patch(temps: np.ndarray, roi: dict) -> np.ndarray:
    bounds = roi_pixel_bounds(temps.shape, roi)
    if bounds is None:
        return temps[:1, :1]
    x0, y0, x1, y1 = bounds
    return temps[y0:y1, x0:x1]


def _finite_stats(patch: np.ndarray) -> Optional[dict]:
    values = patch[np.isfinite(patch)]
    if values.size < 4:
        return None
    return {
        "mean": float(np.mean(values)),
        "max": float(np.max(values)),
        "n": int(values.size),
        "cold_ratio": float(np.mean(values < 28.0)),
    }


def evaluate(temps: np.ndarray, wound: Optional[dict], ref: Optional[dict]) -> dict:
    """用创口区均值减对照区均值。对照区或创口区混入过多冷背景或超出测温范围时不出档。"""
    result = {
        "wound": None,
        "ref": None,
        "delta": None,
        "delta_max": None,
        "grade": None,
        "grade_text": "框太小或没有有效温度",
        "message": "",
    }
    if wound is None or ref is None:
        result["message"] = "请先在画面上框选创口区和对照皮肤区。"
        return result

    wound_stats = _finite_stats(roi_patch(temps, wound))
    ref_stats = _finite_stats(roi_patch(temps, ref))
    result["wound"] = (
        None if wound_stats is None else {"mean": wound_stats["mean"], "max": wound_stats["max"], "n": wound_stats["n"]}
    )
    result["ref"] = (
        None if ref_stats is None else {"mean": ref_stats["mean"], "max": ref_stats["max"], "n": ref_stats["n"]}
    )
    if wound_stats is None or ref_stats is None:
        return result

    delta = wound_stats["mean"] - ref_stats["mean"]
    delta_max = wound_stats["max"] - ref_stats["mean"]
    result["delta"] = float(delta)
    result["delta_max"] = float(delta_max)

    if ref_stats["cold_ratio"] > 0.15:
        result["grade_text"] = "对照框混入低温背景"
        result["message"] = "对照框边缘混入了超过 15% 的低温背景（< 28 °C），请把蓝框完整移到健康皮肤内部。"
        return result
    if not (28.0 <= ref_stats["mean"] <= 42.0):
        result["grade_text"] = "对照框不在皮肤上"
        result["message"] = "对照区要落在旁边的皮肤上。桌面往往低于 30 °C，不能拿来做差。"
        return result
    if wound_stats["cold_ratio"] > 0.15:
        result["grade_text"] = "创口框混入低温背景"
        result["message"] = "创口框边缘混入了超过 15% 的低温背景（< 28 °C），请把橙框收窄并完整落在皮肤内部。"
        return result
    if not (28.0 <= wound_stats["mean"] <= 48.0):
        result["grade_text"] = "创口框不在测温范围内"
        result["message"] = "这台机芯的测温档是 30–45 °C。把创口框移到手背上。"
        return result

    grade = grade_delta(delta)
    result["grade"] = grade
    result["grade_text"] = GRADE_TEXT[grade]

    wb = roi_pixel_bounds(temps.shape, wound)
    rb = roi_pixel_bounds(temps.shape, ref)
    if wb is not None and rb is not None:
        ix0, iy0 = max(wb[0], rb[0]), max(wb[1], rb[1])
        ix1, iy1 = min(wb[2], rb[2]), min(wb[3], rb[3])
        if ix1 > ix0 and iy1 > iy0:
            inter = (ix1 - ix0) * (iy1 - iy0)
            min_box = min((wb[2] - wb[0]) * (wb[3] - wb[1]), (rb[2] - rb[0]) * (rb[3] - rb[1]))
            if min_box > 0 and inter > 0.25 * min_box:
                result["message"] = "创口框与对照框重叠较多，建议把蓝框移到创口旁约 2 cm 的正常皮肤上。"
    return result


def _plausible(temps: np.ndarray) -> bool:
    if temps.size == 0 or not np.isfinite(temps).any():
        return False
    med = float(np.nanmedian(temps))
    hot = float(np.nanpercentile(temps, 95))
    return -20.0 < med < 80.0 and hot < 120.0


def _decode_u16(raw: np.ndarray, scale: int, offset: int) -> Optional[np.ndarray]:
    raw_f = raw.astype(np.float32)
    if scale > 1:
        kelvin = raw_f / float(scale) + float(offset) - 273.15
        if _plausible(kelvin):
            return kelvin
        celsius = raw_f / float(scale) + float(offset)
        if _plausible(celsius):
            return celsius
    for item in (64, 100, 10, 16, 32, 128, 256, 1):
        if item == scale and scale > 1:
            continue
        temps = raw_f / float(item) + float(offset) - 273.15
        if _plausible(temps):
            return temps
    return None


def _decode_f32(raw: np.ndarray) -> Optional[np.ndarray]:
    temps = raw.astype(np.float32, copy=True)
    if _plausible(temps):
        return temps
    kelvin = temps - 273.15
    if _plausible(kelvin):
        return kelvin
    return None


def decode_yuyv_temps(raw_bytes: bytes, width: int = 160, height: int = 120) -> Optional[np.ndarray]:
    """尝试把 16-bit 原始温度帧（海康部分 UVC 原始流固件格式）解码为摄氏度矩阵。"""
    expected = width * height * 2
    if len(raw_bytes) < expected:
        return None
    raw = np.frombuffer(raw_bytes[:expected], dtype="<u2").reshape(height, width)
    for scale in (64.0, 100.0, 10.0):
        c = raw.astype(np.float32) / scale - 273.15
        if _plausible(c):
            return c
    return None


def parse_at(buf: bytes, index: int):
    """从 magic 位置解析一帧。

    返回 ("ok", temps, consumed)、("wait_header", None, 0)、("wait_payload", None, 0) 或 ("skip", None, 0)。
    头布局按 HM-TB 的 132 字节 STREAM_FARME_INFO_TEMP。
    """
    if len(buf) < index + 80:
        return "wait_header", None, 0
    header_size, _stream_type, stream_len = struct.unpack_from("<III", buf, index + 4)
    if not (80 <= header_size <= 8192):
        return "skip", None, 0
    width, height, data_len = struct.unpack_from("<III", buf, index + 44)
    mode, scale, offset = struct.unpack_from("<III", buf, index + 64)
    if width not in range(80, 401) or height not in range(60, 401):
        return "skip", None, 0
    if mode == 0:
        count_bytes = width * height * 4
    elif mode == 1:
        count_bytes = width * height * 2
    else:
        return "skip", None, 0
    if data_len not in (count_bytes, count_bytes + 2, count_bytes + 4, 0):
        if not (count_bytes <= data_len <= count_bytes + 16):
            return "skip", None, 0
    if stream_len and stream_len < count_bytes:
        return "skip", None, 0
    total = max(header_size + count_bytes, header_size + data_len if data_len >= count_bytes else 0)
    if len(buf) < index + total:
        return "wait_payload", None, 0
    payload = buf[index + header_size : index + header_size + count_bytes]
    if mode == 0:
        raw = np.frombuffer(payload, dtype="<f4").reshape(height, width)
        temps = _decode_f32(raw)
    else:
        raw = np.frombuffer(payload, dtype="<u2").reshape(height, width)
        temps = _decode_u16(raw, int(scale), int(offset))
    if temps is None:
        return "skip", None, 0
    return "ok", temps, total


def next_packet(buf: bytearray):
    """从字节流取出一帧温度矩阵，或一张完整 JPEG。

    先按完整结构长度解析温度头；若温度头位于完整 JPEG 之前则优先取出，
    避免压缩图像内碰巧撞到 magic 把图像截断。
    """
    while True:
        jpeg_at = buf.find(b"\xff\xd8")
        limit = jpeg_at if jpeg_at >= 0 else len(buf)
        index = buf.find(MAGIC_BYTES, 0, limit)
        if index >= 0:
            status, temps, consumed = parse_at(buf, index)
            jpeg_end = buf.find(b"\xff\xd9", jpeg_at + 2) if jpeg_at >= 0 else -1
            if status == "wait_header" and jpeg_end >= 0:
                status = "skip"
            if status in ("wait_header", "wait_payload"):
                return None
            if status == "skip":
                del buf[index : index + 4]
                continue
            del buf[: index + consumed]
            return "temp", temps
        if jpeg_at < 0:
            if len(buf) > 1_500_000:
                del buf[:-4]
            return None
        end = buf.find(b"\xff\xd9", jpeg_at + 2)
        if end < 0:
            if jpeg_at:
                del buf[:jpeg_at]
            if len(buf) > 2_000_000:
                del buf[:-2]
            return None
        jpg = bytes(buf[jpeg_at : end + 2])
        del buf[: end + 2]
        return "jpeg", jpg


def synthetic_frame(t: float = 0.0, scenario: str = "strong") -> np.ndarray:
    """120×160 的自检温度场：支持 strong（+3.3°C 档2）、mild（+1.4°C 档1）、baseline（空手基线 档0）。"""
    height, width = 120, 160
    yy, xx = np.mgrid[0:height, 0:width]
    temps = np.full((height, width), 26.0, dtype=np.float32)
    hand = ((xx - 78) ** 2) / (52 ** 2) + ((yy - 62) ** 2) / (34 ** 2) <= 1.0
    temps[hand] = 33.5 + 0.04 * np.sin(t)
    if scenario == "baseline":
        return temps
    spot = (xx - 100) ** 2 + (yy - 58) ** 2 <= 9 ** 2
    temps[spot] = 34.9 if scenario == "mild" else 36.8
    return temps


def _roi_from_box(x: int, y: int, w: int, h: int, width: int, height: int) -> dict:
    pad_x = max(2, int(w * 0.2))
    pad_y = max(2, int(h * 0.2))
    x0 = max(0, x - pad_x)
    y0 = max(0, y - pad_y)
    x1 = min(width, x + w + pad_x)
    y1 = min(height, y + h + pad_y)
    return {
        "x": x0 / width,
        "y": y0 / height,
        "w": max(0.03, (x1 - x0) / width),
        "h": max(0.03, (y1 - y0) / height),
    }


def _reference_beside(score: np.ndarray, box: tuple[int, int, int, int]) -> dict:
    """在热点旁边找一块仍偏暖、但没那么亮的区域，当作对照皮肤。"""
    height, width = score.shape
    x, y, w, h = box
    hot = float(score[y : y + h, x : x + w].mean()) if w and h else 0.0
    brightness = float(np.nanmax(score)) > 80
    side = max(w, h, int(0.1 * min(width, height)))
    cx, cy = x + w / 2, y + h / 2
    best = None
    for dx, dy in ((-1.8, 0), (1.8, 0), (0, -1.8), (0, 1.8), (-1.3, -1.3), (1.3, 1.3)):
        nx = int(min(max(cx + dx * max(w, 8) - side / 2, 0), width - side))
        ny = int(min(max(cy + dy * max(h, 8) - side / 2, 0), height - side))
        patch = score[ny : ny + side, nx : nx + side]
        if patch.size < 10:
            continue
        mean = float(patch.mean())
        if brightness:
            if mean < hot * 0.55 or mean > hot * 0.92:
                continue
        elif mean < hot - 8 or mean > hot - 0.3:
            continue
        if best is None or mean > best[0]:
            best = (mean, nx, ny)
    if best is None:
        nx = int(min(max(cx - 1.8 * max(w, 8) - side / 2, 0), width - side))
        ny = int(min(max(cy - side / 2, 0), height - side))
    else:
        _, nx, ny = best
    return {
        "x": nx / width,
        "y": ny / height,
        "w": side / width,
        "h": side / height,
    }


def _crosshair(image: np.ndarray):
    """机芯用高饱和纯红十字标出全图最高温。返回 (x, y) 像素，找不到则 None。"""
    blue, green, red = (c.astype(np.int16) for c in cv2.split(image))
    chroma = red - np.maximum(green, blue)
    mask = (red > 175) & (green < 50) & (blue < 50) & (chroma >= 155)
    height, width = mask.shape
    mask[:8, :] = False
    mask[-8:, :] = False
    mask[:, :8] = False
    mask[:, -8:] = False
    mask[int(height * 0.82) :, : int(width * 0.35)] = False
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    best = None
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        bw = int(stats[index, cv2.CC_STAT_WIDTH])
        bh = int(stats[index, cv2.CC_STAT_HEIGHT])
        if not (4 <= area <= 100 and max(bw, bh) <= 36):
            continue
        peak_chroma = int(chroma[labels == index].max())
        if peak_chroma < 170:
            continue
        cx, cy = centroids[index]
        rank = (peak_chroma, area)
        if best is None or rank > best[0]:
            best = (rank, float(cx), float(cy))
    if best is None:
        return None
    return best[1], best[2]


def _warm_score(image: np.ndarray) -> np.ndarray:
    blue, green, red = cv2.split(image)
    red_i = red.astype(np.int16)
    green_i = green.astype(np.int16)
    blue_i = blue.astype(np.int16)
    # 屏蔽机芯叠加的绿色文字、绿框、纯红十字及其 JPEG 压缩边缘振铃
    text = (green_i > 110) & (green_i > red_i + 15) & (blue_i < 140)
    chroma = red_i - np.maximum(green_i, blue_i)
    marker = (red_i > 175) & (green_i < 55) & (blue_i < 55) & (chroma >= 150)
    osd = cv2.dilate((text | marker).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    # 沿铁红/白热伪彩色标单调递增：黑->紫->红->橙->黄->白热(255)
    score = (
        red.astype(np.float32) * 0.45
        + green.astype(np.float32) * 0.45
        + np.minimum(green, blue).astype(np.float32) * 0.10
    )
    score[osd] = 0
    h, w = score.shape
    score[: max(6, int(h * 0.08)), :] = 0
    score[-6:, :] = 0
    score[:, :6] = 0
    score[:, -6:] = 0
    score[int(h * 0.82) :, : int(w * 0.38)] = 0
    return score


def _hottest_pixel(score: np.ndarray, skin: np.ndarray) -> tuple[int, int] | None:
    """前景里颜色最热的一点。只做很轻的模糊，避免单点噪声，不把峰值拉到区域中心。"""
    if int(skin.sum()) < 20:
        return None
    field = np.where(skin, score, 0).astype(np.float32)
    smooth = cv2.GaussianBlur(field, (0, 0), 1.2)
    smooth = np.where(skin, smooth, -1e6)
    py, px = np.unravel_index(int(np.argmax(smooth)), smooth.shape)
    if not skin[py, px]:
        return None
    inside = score[skin]
    if float(inside.max()) - float(np.median(inside)) < 8:
        return None
    return int(px), int(py)


def locate_hot_bgr(image: np.ndarray, prior_mask: np.ndarray | None = None):
    """橙框锁在前景里的最高温（红十字在前景内时优先采信），蓝框留在较凉皮肤内。"""
    height, width = image.shape[:2]
    score = _warm_score(image)
    has_prior = prior_mask is not None and prior_mask.shape[:2] == score.shape and int(prior_mask.sum()) >= 40
    if has_prior:
        skin = prior_mask.astype(bool)
    else:
        low = float(np.percentile(score, 35))
        high = float(np.percentile(score, 80))
        if high - low < 12:
            return None
        warm = score >= (low + high) / 2
        count, labels, stats, _ = cv2.connectedComponentsWithStats(warm.astype(np.uint8), 8)
        hand = None
        minimum = max(40, int(0.03 * score.size))
        for index in range(1, count):
            area = int(stats[index, cv2.CC_STAT_AREA])
            if area < minimum:
                continue
            component = labels == index
            brightness = float(score[component].mean())
            if hand is None or brightness > hand[0]:
                hand = (brightness, component)
        if hand is None:
            return None
        skin = hand[1]

    # 先按颜色筛选掉前景里混入的冷背景/指缝，但对红十字判定使用未剔除 marker 的 skin 膨胀区
    inside_scores = score[skin]
    skin_floor = float(np.percentile(inside_scores, 25))
    solid_skin = skin & (score >= skin_floor)
    if int(solid_skin.sum()) < 40:
        solid_skin = skin
    skin_zone = cv2.dilate(skin.astype(np.uint8), np.ones((15, 15), np.uint8)) > 0

    side = max(18, int(min(height, width) * 0.08))
    cov = cv2.boxFilter(
        solid_skin.astype(np.float32),
        -1,
        (side, side),
        normalize=True,
        borderType=cv2.BORDER_CONSTANT,
    )
    nz_mask = (score > 0).astype(np.float32)
    nz_sum = cv2.boxFilter(score, -1, (side, side), normalize=False, borderType=cv2.BORDER_CONSTANT)
    nz_cnt = cv2.boxFilter(nz_mask, -1, (side, side), normalize=False, borderType=cv2.BORDER_CONSTANT)
    box_mean = nz_sum / np.maximum(nz_cnt, 1.0)

    cross = _crosshair(image)
    point = None
    if cross is not None:
        cx, cy = int(round(cross[0])), int(round(cross[1]))
        if 0 <= cy < height and 0 <= cx < width and skin_zone[cy, cx]:
            r0, r1 = max(0, cy - side // 2), min(height, cy + side // 2)
            c0, c1 = max(0, cx - side // 2), min(width, cx + side // 2)
            patch = score[r0:r1, c0:c1]
            nz_patch = patch[patch > 0]
            if nz_patch.size >= 8 and float(nz_patch.mean()) >= float(np.percentile(inside_scores, 70)):
                point = (cx, cy)
    if point is None:
        cand = solid_skin & (cov >= 0.80) & (nz_cnt >= max(8.0, side * side * 0.5))
        if int(cand.sum()) < 10:
            cand = solid_skin & (cov >= 0.65)
        if int(cand.sum()) < 10:
            cand = solid_skin
        if int(cand.sum()) > 0:
            masked_mean = np.where(cand, box_mean, -1.0)
            py_idx, px_idx = np.unravel_index(int(np.argmax(masked_mean)), masked_mean.shape)
            point = (int(px_idx), int(py_idx))
        else:
            point = _hottest_pixel(score, solid_skin)
    if point is None:
        return None
    px, py = point
    wound = _box_roi(px - side / 2, py - side / 2, side, side, width, height)
    wound_box_score = float(box_mean[py, px])

    # 用滑窗前景覆盖率约束蓝框选点，防止掉进指缝冷背景
    ys, xs = np.where(solid_skin)
    dist = np.hypot(xs.astype(np.float32) - px, ys.astype(np.float32) - py)
    valid = (dist >= side * 1.15) & (dist <= max(height, width) * 0.45) & (cov[ys, xs] >= 0.85)
    if int(valid.sum()) < 10:
        valid = (dist >= side * 0.9) & (cov[ys, xs] >= 0.65)
    if int(valid.sum()) < 10:
        valid = dist >= side * 0.8
    if int(valid.sum()) < 10:
        valid = np.ones(xs.shape[0], dtype=bool)

    vx, vy = xs[valid], ys[valid]
    vscore = box_mean[vy, vx]
    cooler = vscore <= wound_box_score
    if int(cooler.sum()) >= 5:
        vx, vy, vscore = vx[cooler], vy[cooler], vscore[cooler]
    # 在前景皮肤里找中等偏暖但低于热点核心的对照框
    low_q, high_q = np.percentile(vscore, [20, 65])
    band = (vscore >= low_q) & (vscore <= high_q)
    if int(band.sum()) < 5:
        band = np.ones(vx.shape[0], dtype=bool)
    bx, by = vx[band], vy[band]
    best_idx = int(np.argmin(np.abs(vscore[band] - float(np.median(vscore[band])))))
    ref = _box_roi(
        float(bx[best_idx]) - side / 2,
        float(by[best_idx]) - side / 2,
        side,
        side,
        width,
        height,
    )
    return wound, ref


def locate_hot_temps(temps: np.ndarray):
    """用真实温度矩阵框出最热的一块。"""
    finite = temps[np.isfinite(temps)]
    if finite.size < 40:
        return None
    peak = float(np.max(finite))
    floor = float(np.median(finite))
    threshold = peak - 0.8
    if peak < floor + 0.6:
        return None
    mask = np.isfinite(temps) & (temps >= threshold)
    mask_u8 = mask.astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask_u8, 8)
    best = None
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        if area < 4:
            continue
        ys, xs = np.where(labels == index)
        mean_t = float(temps[ys, xs].mean())
        if best is None or mean_t > best[0]:
            best = (mean_t, stats[index])
    if best is None:
        return None
    stat = best[1]
    x, y, w, h = int(stat[0]), int(stat[1]), int(stat[2]), int(stat[3])
    height, width = temps.shape
    wound = _roi_from_box(x, y, w, h, width, height)
    ref = _reference_beside(np.nan_to_num(temps, nan=-1e6), (x, y, w, h))
    return wound, ref


def pixel_mm(distance_mm: float) -> float:
    """50° 视场、160 像元，镜头到掌面 distance_mm 时的中心像元边长。"""
    return float(distance_mm) * float(np.tan(np.deg2rad(50.0 / 160.0)))


def build_test_frame(temps_c: np.ndarray, scale: int = 100) -> bytes:
    height, width = temps_c.shape
    raw = np.clip(np.rint((temps_c + 273.15) * scale), 0, 65535).astype("<u2")
    header = bytearray(132)
    struct.pack_into("<I", header, 0, MAGIC)
    struct.pack_into("<I", header, 4, 132)
    struct.pack_into("<I", header, 8, 2)
    struct.pack_into("<I", header, 12, raw.nbytes)
    struct.pack_into("<I", header, 16, 2)
    struct.pack_into("<I", header, 44, width)
    struct.pack_into("<I", header, 48, height)
    struct.pack_into("<I", header, 52, raw.nbytes)
    struct.pack_into("<I", header, 64, 1)
    struct.pack_into("<I", header, 68, scale)
    struct.pack_into("<I", header, 72, 0)
    return bytes(header) + raw.tobytes()


def _green_crosshair(image: np.ndarray) -> Optional[tuple[float, float]]:
    """机芯用高饱和绿十字标出 Cal 点测温位置。返回 (x, y) 像素，找不到则 None。"""
    blue, green, red = (c.astype(np.int16) for c in cv2.split(image))
    chroma = green - np.maximum(red, blue)
    mask = (green > 140) & (red < 75) & (blue < 75) & (chroma >= 130)
    height, width = mask.shape
    mask[: max(8, int(height * 0.10)), :] = False
    mask[-8:, :] = False
    mask[:, :8] = False
    mask[:, -8:] = False
    mask[int(height * 0.80) :, : int(width * 0.42)] = False
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    best = None
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        bw = int(stats[index, cv2.CC_STAT_WIDTH])
        bh = int(stats[index, cv2.CC_STAT_HEIGHT])
        if not (4 <= area <= 150 and max(bw, bh) <= 42):
            continue
        peak_chroma = int(chroma[labels == index].max())
        if peak_chroma < 150:
            continue
        cx, cy = centroids[index]
        rank = (peak_chroma, area)
        if best is None or rank > best[0]:
            best = (rank, float(cx), float(cy))
    if best is None:
        return None
    return best[1], best[2]


_DIGIT_GLYPHS = {
    0: ["01111100", "11000110", "11000011", "11000011", "11000011", "11000011", "11000110", "01111100"],
    1: ["00011000", "00111000", "00011000", "00011000", "00011000", "00011000", "00011000", "00011000"],
    2: ["01111100", "11000110", "00000110", "00011100", "00110000", "01100000", "11000011", "11111111"],
    3: ["01111100", "11000110", "00000110", "00111100", "00000110", "00000011", "11000110", "01111100"],
    4: ["00001100", "00011100", "00110100", "01100100", "11000100", "11111111", "00000100", "00000100"],
    5: ["11111110", "11000000", "11111100", "00000110", "00000011", "00000011", "11000110", "01111100"],
    6: ["00111100", "01100000", "11000000", "11111100", "11000110", "11000011", "11000110", "01111100"],
    7: ["11111111", "00000110", "00001100", "00011000", "00110000", "00110000", "00110000", "00110000"],
    8: ["01111100", "11000110", "11000110", "01111100", "11000110", "11000011", "11000110", "01111100"],
    9: ["01111100", "11000110", "11000011", "01111111", "00000011", "00000110", "11000110", "01111100"],
}
_DIGIT_TEMPLATES: dict[int, np.ndarray] = {}
for _d, _rows in _DIGIT_GLYPHS.items():
    _arr = np.array([[1.0 if _ch == "1" else 0.0 for _ch in _row] for _row in _rows], dtype=np.float32)
    _arr = _arr - float(_arr.mean())
    _DIGIT_TEMPLATES[_d] = _arr / max(1e-5, float(np.linalg.norm(_arr)))


def _match_digit(cell: np.ndarray, allowed: tuple[int, ...] = tuple(range(10))) -> tuple[int, float]:
    if cell.size == 0 or float(cell.max()) < 14.0:
        return allowed[0], -1.0
    resized = cv2.resize(cell.astype(np.float32), (8, 8), interpolation=cv2.INTER_AREA)
    norm = resized - float(resized.mean())
    denom = float(np.linalg.norm(norm))
    if denom < 1e-4:
        return allowed[0], -1.0
    norm = norm / denom
    best_d = allowed[0]
    best_s = -1.0
    for d in allowed:
        score = float(np.sum(norm * _DIGIT_TEMPLATES[d]))
        if score > best_s:
            best_s = score
            best_d = d
    return best_d, best_s


def _read_osd_number(gr: np.ndarray, is_top: bool) -> Optional[float]:
    """按 HM-TB421-3XF 固件 1/30 等宽网格，从 G-R 差值图中识别左上 Cal 或左下 Max 的 xx.x 温度。"""
    h, w = gr.shape[:2]
    if is_top:
        y0, y1 = max(3, int(round(h * 0.012))), max(8, int(round(h * 0.056)))
        base_x = 0.200
    else:
        y0, y1 = int(round(h * 0.942)), min(h - 3, int(round(h * 0.990)))
        base_x = 0.1667
    cw = 1.0 / 30.0
    x_all0 = int(round(base_x * w))
    x_all1 = int(round((base_x + 4.0 * cw) * w))
    if y1 <= y0 + 3 or x_all1 <= x_all0 + 12:
        return None
    band = gr[y0:y1, x_all0:x_all1]
    if float(band.max()) < 25.0:
        return None
    row_max = band.max(axis=1)
    active_r = np.where(row_max >= max(14.0, float(band.max()) * 0.28))[0]
    if active_r.size < 4:
        return None
    ry0, ry1 = int(active_r[0]), int(active_r[-1]) + 1

    digits = []
    confs = []
    for col_off, allowed in ((0, (1, 2, 3, 4)), (1, tuple(range(10))), (3, tuple(range(10)))):
        cx0 = int(round((base_x + col_off * cw) * w))
        cx1 = int(round((base_x + (col_off + 1.0) * cw) * w))
        d, s = _match_digit(gr[y0 + ry0 : y0 + ry1, cx0:cx1], allowed=allowed)
        digits.append(d)
        confs.append(s)
    if min(confs) < 0.22:
        return None
    val = round(digits[0] * 10.0 + digits[1] + digits[2] * 0.1, 1)
    return val if 15.0 <= val <= 45.0 else None


def invert_pseudocolor_temps(
    image: np.ndarray,
    prior_mask: Optional[np.ndarray] = None,
    wound_roi: Optional[dict] = None,
    ref_roi: Optional[dict] = None,
) -> dict:
    """结合同帧 OSD 双锚点（Max 红十字 + Cal 绿十字）与铁红单调色标反演等效温度场。"""
    h, w = image.shape[:2]
    blue, green, red = cv2.split(image)
    red_i, green_i, blue_i = red.astype(np.int16), green.astype(np.int16), blue.astype(np.int16)
    gr = np.clip(green_i - red_i, 0, 255).astype(np.uint8)

    text = (green_i > 110) & (green_i > red_i + 15) & (blue_i < 140)
    r_chroma = red_i - np.maximum(green_i, blue_i)
    g_chroma = green_i - np.maximum(red_i, blue_i)
    r_marker = (red_i > 175) & (green_i < 55) & (blue_i < 55) & (r_chroma >= 150)
    g_marker = (green_i > 140) & (red_i < 75) & (blue_i < 75) & (g_chroma >= 130)
    osd = cv2.dilate((text | r_marker | g_marker).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0

    red_cross = _crosshair(image)
    green_cross = _green_crosshair(image)
    osd_cal = _read_osd_number(gr, is_top=True)
    osd_max = _read_osd_number(gr, is_top=False)

    # 降采样到 160x120 探测器原生网格执行形态学修复与分位数反演，提速 10 倍以上
    work_w, work_h = (w, h) if (w <= 240 and h <= 240) else (160, 120)
    raw_score_full = (
        red.astype(np.float32) * 0.45
        + green.astype(np.float32) * 0.45
        + np.minimum(green, blue).astype(np.float32) * 0.10
    )
    osd_u8 = (text | r_marker | g_marker).astype(np.uint8)
    if (work_w, work_h) != (w, h):
        raw_score = cv2.resize(raw_score_full, (work_w, work_h), interpolation=cv2.INTER_AREA)
        osd_small = cv2.resize(osd_u8, (work_w, work_h), interpolation=cv2.INTER_NEAREST) > 0
    else:
        raw_score = raw_score_full
        osd_small = cv2.dilate(osd_u8, np.ones((5, 5), np.uint8)) > 0

    clean_field = np.where(osd_small, 0.0, raw_score).astype(np.float32)
    repaired = cv2.dilate(clean_field, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    field = np.where(osd_small, repaired, raw_score).astype(np.float32)

    has_skin = prior_mask is not None and prior_mask.shape[:2] == (h, w) and int(prior_mask.sum()) >= 40
    if has_skin:
        skin = (
            cv2.resize(prior_mask.astype(np.uint8), (work_w, work_h), interpolation=cv2.INTER_NEAREST) > 0
            if (work_w, work_h) != (w, h)
            else prior_mask.astype(bool)
        )
    else:
        low_s, high_s = float(np.percentile(clean_field, 35)), float(np.percentile(clean_field, 85))
        skin = (clean_field >= (low_s + high_s) * 0.5) if (high_s - low_s >= 12) else np.zeros((work_h, work_w), dtype=bool)

    if red_cross is not None:
        rx = int(round(red_cross[0] * work_w / w))
        ry = int(round(red_cross[1] * work_h / h))
        u_max = float(np.percentile(field[max(0, ry - 4) : min(work_h, ry + 5), max(0, rx - 4) : min(work_w, rx + 5)], 92))
    else:
        u_max = float(np.percentile(field[skin] if int(skin.sum()) >= 20 else field, 98))

    if green_cross is not None:
        gx = int(round(green_cross[0] * work_w / w))
        gy = int(round(green_cross[1] * work_h / h))
        u_cal = float(np.median(field[max(0, gy - 4) : min(work_h, gy + 5), max(0, gx - 4) : min(work_w, gx + 5)]))
    else:
        u_cal = float(np.percentile(field, 20))

    # 锚定温度区间：优先结合 OSD Max/Cal 与前景皮肤基准（手在画面时最高温约 35.6°C，冷背景环境约 21.5~25.2°C）
    warm_scene = u_max >= 150.0
    if warm_scene:
        t_peak = float(osd_max) if (osd_max is not None and 30.0 <= osd_max <= 44.0) else 35.6
        if osd_cal is not None and 18.0 <= osd_cal <= t_peak - 1.5 and u_max - u_cal >= 20.0:
            t_cal = float(osd_cal)
            anchor_mode = "OSD 双锚点标定"
        else:
            t_cal = 25.6
            anchor_mode = "OSD 锚点 + 色标反演" if (red_cross is not None or green_cross is not None) else "伪彩色标反演"
    else:
        t_peak = float(osd_max) if (osd_max is not None and 18.0 <= osd_max <= 29.0) else 25.2
        t_cal = float(osd_cal) if (osd_cal is not None and 15.0 <= osd_cal <= t_peak - 1.0) else 21.3
        anchor_mode = "OSD 双锚点标定" if (red_cross is not None and green_cross is not None) else "伪彩色标反演"

    if int(skin.sum()) >= 40 and warm_scene:
        # 在手部前景内按生理温区做分段自标定，消除冷桌面 AGC 压缩导致的皮内温差失真
        u_skin_med = float(np.median(field[skin]))
        t_skin_base = min(t_peak - 1.4, max(32.5, t_peak - 2.1))
        slope_hot = (t_peak - t_skin_base) / max(12.0, u_max - u_skin_med)
        slope_hot = float(np.clip(slope_hot, 0.025, 0.075))
        slope_cold = (t_skin_base - t_cal) / max(25.0, u_skin_med - min(u_cal, u_skin_med - 25.0))
        slope_cold = float(np.clip(slope_cold, 0.03, 0.12))
        est_temps = np.where(
            field >= u_skin_med,
            t_skin_base + (field - u_skin_med) * slope_hot,
            t_skin_base + (field - u_skin_med) * slope_cold,
        ).astype(np.float32)
    else:
        slope = (t_peak - t_cal) / max(25.0, u_max - u_cal)
        slope = float(np.clip(slope, 0.02, 0.12))
        est_temps = (t_peak - (u_max - field) * slope).astype(np.float32)

    est_temps = np.clip(est_temps, 16.0, 46.0)
    est_eval = evaluate(est_temps, wound_roi, ref_roi) if (wound_roi and ref_roi) else {}
    return {
        "est_temps": est_temps,
        "anchor_mode": anchor_mode,
        "osd_cal": round(t_cal, 1),
        "osd_max": round(t_peak, 1),
        "red_cross": None if red_cross is None else {"x": round(red_cross[0] / w, 4), "y": round(red_cross[1] / h, 4)},
        "green_cross": None
        if green_cross is None
        else {"x": round(green_cross[0] / w, 4), "y": round(green_cross[1] / h, 4)},
        "est_wound": est_eval.get("wound"),
        "est_ref": est_eval.get("ref"),
        "est_delta": None if est_eval.get("delta") is None else round(float(est_eval["delta"]), 2),
        "est_delta_max": None if est_eval.get("delta_max") is None else round(float(est_eval["delta_max"]), 2),
        "est_grade": est_eval.get("grade"),
        "est_grade_text": est_eval.get("grade_text"),
    }


def analyze_thermal_physics(
    temps: np.ndarray,
    wound_roi: Optional[dict],
    ref_roi: Optional[dict],
    distance_mm: float = 300.0,
    body_mask: Optional[np.ndarray] = None,
) -> Optional[dict]:
    """计算空间热扩散物理指标：真实热斑面积(mm²)、等效直径、径向热衰减剖面与斜率、热晕比及各向异性。"""
    if temps is None or temps.size < 40:
        return None
    h, w = temps.shape[:2]
    # 针对伪彩高分辨率反演场，按 160 水平像元折算单像元物理尺寸
    scale_factor = 160.0 / float(max(w, 1))
    px_mm = pixel_mm(distance_mm) * scale_factor
    px_area = px_mm * px_mm

    finite = np.isfinite(temps)
    if body_mask is not None and body_mask.size >= 20:
        bm = (
            body_mask.astype(bool)
            if body_mask.shape[:2] == (h, w)
            else (cv2.resize(body_mask.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST) > 0)
        )
        body = bm & finite
    else:
        body = skin_mask(temps, finite)
    if int(body.sum()) < 20:
        body = finite
    if int(body.sum()) < 20:
        return None

    if ref_roi is not None:
        r_patch = roi_patch(temps, ref_roi)
        r_vals = r_patch[np.isfinite(r_patch)]
        ref_t = float(np.mean(r_vals)) if r_vals.size >= 4 else float(np.median(temps[body]))
    else:
        ref_t = float(np.median(temps[body]))

    if wound_roi is not None:
        bounds = roi_pixel_bounds((h, w), wound_roi)
    else:
        bounds = None

    if bounds is not None:
        x0, y0, x1, y1 = bounds
        sub = np.where(np.isfinite(temps[y0:y1, x0:x1]), temps[y0:y1, x0:x1], -1e9)
        s_max = float(np.max(sub))
        top_ys, top_xs = np.where(sub >= s_max - 0.15)
        if top_ys.size > 0:
            py = min(max(y0 + int(round(float(np.mean(top_ys)))), 0), h - 1)
            px = min(max(x0 + int(round(float(np.mean(top_xs)))), 0), w - 1)
        else:
            ry, rx = np.unravel_index(int(np.argmax(sub)), sub.shape)
            py, px = y0 + int(ry), x0 + int(rx)
    else:
        sub = np.where(body, temps, -1e9)
        s_max = float(np.max(sub))
        top_ys, top_xs = np.where(sub >= s_max - 0.15)
        if top_ys.size > 0:
            py = min(max(int(round(float(np.mean(top_ys)))), 0), h - 1)
            px = min(max(int(round(float(np.mean(top_xs)))), 0), w - 1)
        else:
            py, px = np.unravel_index(int(np.argmax(sub)), sub.shape)
            py, px = int(py), int(px)

    peak_t = float(temps[py, px]) if np.isfinite(temps[py, px]) else ref_t
    delta_peak = max(0.0, peak_t - ref_t)

    # 半高宽热斑与 +1.0°C 异常热区
    fwhm_thr = ref_t + max(0.4, 0.5 * delta_peak)
    hot_1c_mask = body & (temps >= ref_t + 1.0)
    halo_05c_mask = body & (temps >= ref_t + 0.5)
    fwhm_mask = body & (temps >= fwhm_thr)

    # 只统计与峰值点所在连通域相连的热斑，避免远处背景噪点计入面积
    cnt, labels, stats, _ = cv2.connectedComponentsWithStats(fwhm_mask.astype(np.uint8), 8)
    peak_label = int(labels[py, px]) if 0 <= py < h and 0 <= px < w else 0
    if peak_label > 0:
        core_mask = labels == peak_label
    elif cnt > 1:
        largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        core_mask = labels == largest
    else:
        core_mask = fwhm_mask

    fwhm_px = int(core_mask.sum())
    hot_1c_px = int(hot_1c_mask.sum())
    halo_05c_px = int(halo_05c_mask.sum())

    fwhm_area_mm2 = round(fwhm_px * px_area, 1)
    hot_area_mm2 = round(hot_1c_px * px_area, 1)
    equiv_diam_mm = round(float(2.0 * np.sqrt(max(fwhm_area_mm2, 0.0) / np.pi)), 1)
    halo_ratio = round(float(halo_05c_px) / float(max(fwhm_px, 1)), 2) if fwhm_px >= 3 else 1.0

    # 二阶中心矩求主轴长宽各向异性比（区分条索状浅表血管与团块状创口炎症）
    elongation = 1.0
    if fwhm_px >= 5:
        m = cv2.moments(core_mask.astype(np.uint8))
        if m["m00"] > 0:
            mu20 = m["mu20"] / m["m00"]
            mu02 = m["mu02"] / m["m00"]
            mu11 = m["mu11"] / m["m00"]
            common = float(np.sqrt(max(0.0, (mu20 - mu02) ** 2 + 4.0 * (mu11 ** 2))))
            l1 = max(1e-3, (mu20 + mu02 + common) * 0.5)
            l2 = max(1e-3, (mu20 + mu02 - common) * 0.5)
            elongation = round(min(9.9, float(np.sqrt(l1 / l2))), 2)

    # 径向同心环温度衰减剖面 (0..24 mm)
    yy, xx = np.mgrid[0:h, 0:w]
    r_mm = np.hypot((xx - px).astype(np.float32), (yy - py).astype(np.float32)) * px_mm
    bands = ((0.0, 3.0), (3.0, 6.0), (6.0, 10.0), (10.0, 16.0), (16.0, 24.0))
    radial_profile = []
    fit_r = []
    fit_dt = []
    for r0, r1 in bands:
        ring = body & (r_mm >= r0) & (r_mm < r1)
        if int(ring.sum()) < 2:
            continue
        dt_ring = float(np.mean(temps[ring]) - ref_t)
        r_mid = round((r0 + r1) * 0.5, 1)
        radial_profile.append({"r_mm": r_mid, "delta": round(dt_ring, 2)})
        fit_r.append(r_mid)
        fit_dt.append(dt_ring)

    if len(fit_r) >= 2:
        slope = float(np.polyfit(np.array(fit_r, dtype=np.float32), np.array(fit_dt, dtype=np.float32), 1)[0])
    else:
        slope = 0.0
    decay_slope = round(slope, 3)

    if delta_peak < 0.9:
        pattern = "正常均匀皮肤"
    elif elongation >= 2.6:
        pattern = "条索状分布（疑似浅表静脉）"
    elif halo_ratio >= 2.4:
        pattern = "弥漫热晕型温升"
    else:
        pattern = "局灶团块型温升"

    return {
        "hot_area_mm2": hot_area_mm2,
        "fwhm_area_mm2": fwhm_area_mm2,
        "equiv_diam_mm": equiv_diam_mm,
        "decay_slope": decay_slope,
        "halo_ratio": halo_ratio,
        "elongation": elongation,
        "pattern": pattern,
        "radial_profile": radial_profile,
    }


def analyze_hand_pose(mask: Optional[np.ndarray]) -> Optional[dict]:
    """计算手部质心、主轴倾角、占空比与手托放置姿态引导提示。"""
    if mask is None or mask.size == 0:
        return None
    binary = mask.astype(np.uint8)
    total = int(binary.sum())
    if total < 25:
        return None
    h, w = binary.shape[:2]
    m = cv2.moments(binary)
    if m["m00"] <= 0:
        return None
    cx = float(m["m10"] / m["m00"]) / float(w)
    cy = float(m["m01"] / m["m00"]) / float(h)
    angle_rad = 0.5 * float(np.arctan2(2.0 * m["mu11"], m["mu20"] - m["mu02"]))
    angle_deg = round(float(np.rad2deg(angle_rad)), 1)
    coverage = round(float(total) / float(h * w), 3)
    border_touch = bool(binary[0, :].any() or binary[-1, :].any() or binary[:, 0].any() or binary[:, -1].any())

    if coverage < 0.06:
        status = "距离偏远"
        hint = "手部占画面偏小（<6%），建议将立柱调至 300 mm 锁紧档。"
    elif coverage > 0.68:
        status = "距离偏近"
        hint = "手部占满画面（>68%），指尖易出画，建议调回 300 mm 标准档。"
    elif abs(cx - 0.5) > 0.22 or abs(cy - 0.5) > 0.22:
        status = "位置偏心"
        hint = "手部偏离 210×110 mm 手托中心，请居中平放手掌。"
    else:
        status = "姿态居中"
        hint = f"手部居中良好（占比 {int(round(coverage * 100))}% · 主轴 {angle_deg:+.0f}°）"

    return {
        "cx": round(cx, 4),
        "cy": round(cy, 4),
        "angle_deg": angle_deg,
        "scale": round(float(np.sqrt(coverage)), 4),
        "coverage": coverage,
        "border_touch": border_touch,
        "status": status,
        "hint": hint,
    }


def encode_anatomical_rois(
    pose: Optional[dict],
    wound_roi: Optional[dict],
    ref_roi: Optional[dict],
) -> Optional[dict]:
    """将当前创口框与对照框编码到手掌质心-主轴局部坐标系下，用于跨次放手自动对齐。"""
    if not pose or not wound_roi or not ref_roi:
        return None
    theta = float(np.deg2rad(pose["angle_deg"]))
    cos_t, sin_t = float(np.cos(theta)), float(np.sin(theta))
    scale = max(0.15, float(pose.get("scale", 0.45)))

    def _enc(roi: dict) -> dict:
        rx = float(roi["x"]) + float(roi["w"]) * 0.5 - float(pose["cx"])
        ry = float(roi["y"]) + float(roi["h"]) * 0.5 - float(pose["cy"])
        u = (rx * cos_t + ry * sin_t) / scale
        v = (-rx * sin_t + ry * cos_t) / scale
        return {"u": u, "v": v, "w": float(roi["w"]) / scale, "h": float(roi["h"]) / scale}

    return {"wound": _enc(wound_roi), "ref": _enc(ref_roi)}


def project_anatomical_rois(pose: Optional[dict], anchor: Optional[dict]) -> Optional[tuple[dict, dict]]:
    """根据新帧的手掌质心与主轴角，将记忆的解剖坐标投射回当前画面 ROI。"""
    if not pose or not anchor or "wound" not in anchor or "ref" not in anchor:
        return None
    theta = float(np.deg2rad(pose["angle_deg"]))
    cos_t, sin_t = float(np.cos(theta)), float(np.sin(theta))
    scale = max(0.15, float(pose.get("scale", 0.45)))

    def _dec(item: dict) -> dict:
        u = float(item["u"]) * scale
        v = float(item["v"]) * scale
        dx = u * cos_t - v * sin_t
        dy = u * sin_t + v * cos_t
        w = min(0.45, max(0.03, float(item["w"]) * scale))
        h = min(0.45, max(0.03, float(item["h"]) * scale))
        x = min(max(float(pose["cx"]) + dx - w * 0.5, 0.0), 1.0 - w)
        y = min(max(float(pose["cy"]) + dy - h * 0.5, 0.0), 1.0 - h)
        return {"x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4)}

    return _dec(anchor["wound"]), _dec(anchor["ref"])


def render_isotherm_view(
    base_bgr: np.ndarray,
    temps: Optional[np.ndarray],
    mask: Optional[np.ndarray],
    ref_temp: Optional[float] = None,
) -> np.ndarray:
    """渲染第 4 种视图：消除正常皮肤本底的 ΔT 显著图，并叠加 +1.0°C (黄) 与 +2.2°C (红) 等温差闭合轮廓线。"""
    if temps is None or temps.size == 0:
        return base_bgr
    h, w = base_bgr.shape[:2]
    # 在低分辨率网格上完成温度色彩合成，再一次性上采样到画面分辨率，降低 90% 计算开销
    th, tw = temps.shape[:2]
    small_temps = (
        temps.astype(np.float32)
        if (tw <= 240 and th <= 240)
        else cv2.resize(temps.astype(np.float32), (160, 120), interpolation=cv2.INTER_AREA)
    )
    sh, sw = small_temps.shape[:2]
    if mask is not None and int(mask.sum()) >= 25:
        fg_small = (
            mask.astype(bool)
            if mask.shape[:2] == (sh, sw)
            else (cv2.resize(mask.astype(np.uint8), (sw, sh), interpolation=cv2.INTER_NEAREST) > 0)
        )
    else:
        sm = skin_mask(small_temps)
        fg_small = sm if int(sm.sum()) >= 20 else np.isfinite(small_temps)

    if ref_temp is not None and 20.0 <= ref_temp <= 44.0:
        t_base = float(ref_temp)
    else:
        fg_vals = small_temps[fg_small & np.isfinite(small_temps)]
        t_base = float(np.median(fg_vals)) if fg_vals.size >= 10 else float(np.nanmedian(small_temps))

    excess_small = np.where(fg_small & np.isfinite(small_temps), small_temps - t_base, -5.0).astype(np.float32)
    small_bgr = cv2.resize(base_bgr, (sw, sh), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    skin_base = np.stack([gray * 0.55 + 32.0, gray * 0.52 + 28.0, gray * 0.48 + 26.0], axis=-1)
    bg = np.full((sh, sw, 3), (18.0, 20.0, 24.0), dtype=np.float32)
    canvas = np.where(fg_small[..., None], skin_base, bg)

    w_mild = np.clip((excess_small - 0.6) / 1.6, 0.0, 1.0)[..., None]
    amber = np.array([28.0, 178.0, 255.0], dtype=np.float32)
    canvas = canvas * (1.0 - 0.65 * w_mild) + amber * (0.65 * w_mild)

    w_hot = np.clip((excess_small - 2.0) / 1.5, 0.0, 1.0)[..., None]
    crimson = np.array([42.0, 56.0, 255.0], dtype=np.float32)
    canvas = canvas * (1.0 - 0.78 * w_hot) + crimson * (0.78 * w_hot)
    out = cv2.resize(np.clip(canvas, 0, 255).astype(np.uint8), (w, h), interpolation=cv2.INTER_LINEAR)

    # 在小网格提取 +1.0°C 与 +2.2°C 等温线轮廓并按比例缩放绘制到输出画布
    sx, sy = float(w) / float(sw), float(h) / float(sh)
    for thr, color in ((1.0, (24, 214, 255)), (2.2, (48, 68, 255))):
        iso_mask = ((excess_small >= thr) & fg_small).astype(np.uint8) * 255
        contours, _ = cv2.findContours(iso_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        scaled_contours = []
        for c in contours:
            if cv2.contourArea(c) >= 2.0:
                sc = c.astype(np.float32)
                sc[:, 0, 0] *= sx
                sc[:, 0, 1] *= sy
                scaled_contours.append(sc.astype(np.int32))
        if scaled_contours:
            cv2.drawContours(out, scaled_contours, -1, (10, 12, 15), 4, cv2.LINE_AA)
            cv2.drawContours(out, scaled_contours, -1, color, 2, cv2.LINE_AA)

    # 左上角绘制等温差线图例
    cv2.rectangle(out, (8, 8), (336, 34), (12, 14, 18), -1)
    cv2.rectangle(out, (8, 8), (336, 34), (52, 57, 68), 1)
    cv2.putText(
        out,
        f"dT Isotherm  Tref={t_base:.1f}C",
        (16, 25),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.44,
        (235, 232, 225),
        1,
        cv2.LINE_AA,
    )
    cv2.circle(out, (205, 21), 4, (24, 214, 255), -1, cv2.LINE_AA)
    cv2.putText(out, "+1.0C", (213, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (24, 214, 255), 1, cv2.LINE_AA)
    cv2.circle(out, (272, 21), 4, (48, 68, 255), -1, cv2.LINE_AA)
    cv2.putText(out, "+2.2C", (280, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (48, 68, 255), 1, cv2.LINE_AA)
    return out
