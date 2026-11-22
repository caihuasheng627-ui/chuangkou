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
    if delta < 1.0:
        return 0
    if delta < 2.2:
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


def _ring_reference(temps: np.ndarray, body: np.ndarray, component: np.ndarray):
    """在异常热区外围 2~10 像素皮肤环带内选取对照区，并使展示框与参与计算的像素一致。"""
    height, width = temps.shape
    gap_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    outer_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21))
    comp_u8 = component.astype(np.uint8)
    inner_excl = cv2.dilate(comp_u8, gap_kernel).astype(bool)
    outer_dilated = cv2.dilate(comp_u8, outer_kernel).astype(bool)

    ring = outer_dilated & body & ~inner_excl
    if int(ring.sum()) < 8:
        ring = outer_dilated & body & ~component
    if int(ring.sum()) < 8:
        ring = body & ~component
    if int(ring.sum()) < 8:
        return None

    ys, xs = np.where(component)
    cy, cx = float(np.mean(ys)), float(np.mean(xs))
    ry, rx = np.where(ring)
    dx = rx.astype(np.float32) - cx
    dy = ry.astype(np.float32) - cy
    quads = (
        (dy < 0) & (np.abs(dy) >= np.abs(dx)),
        (dy > 0) & (np.abs(dy) >= np.abs(dx)),
        (dx < 0) & (np.abs(dx) > np.abs(dy)),
        (dx > 0) & (np.abs(dx) > np.abs(dy)),
    )
    chosen = max(quads, key=lambda mask: int(mask.sum()))
    if int(chosen.sum()) < 6:
        chosen = np.ones(rx.shape[0], dtype=bool)

    mx = float(np.median(rx[chosen]))
    my = float(np.median(ry[chosen]))
    side = max(8, int(min(width, height) * 0.09))
    ref_roi = _box_roi(mx - side / 2, my - side / 2, side, side, width, height)

    # 优先取“蓝框内且属于皮肤非创口”的像素做对照，确保界面框选与数值严格一致
    box_skin = _roi_mask((height, width), ref_roi) & body & ~component
    if int(box_skin.sum()) >= 6:
        values = temps[box_skin]
    else:
        quad_mask = np.zeros((height, width), dtype=bool)
        quad_mask[ry[chosen], rx[chosen]] = True
        values = temps[quad_mask]
    return float(np.mean(values)), float(np.max(values)), int(values.size), ref_roi


def skin_mask(temps: np.ndarray, finite: Optional[np.ndarray] = None) -> np.ndarray:
    """从物理温度矩阵中提取手部皮肤区域（过滤冷桌面与边缘噪声）。"""
    if finite is None:
        finite = np.isfinite(temps)
    if int(finite.sum()) < 30:
        return np.zeros(temps.shape[:2], dtype=bool)

    values = temps[finite]
    low = float(np.percentile(values, 30))
    high = float(np.percentile(values, 82))
    if high - low < 1.2:
        warm = finite & (temps >= 28.0)
        if int(warm.sum()) < 30:
            warm = finite & (temps >= low)
    else:
        threshold = max(28.0, low + 0.55 * (high - low))
        warm = finite & (temps >= threshold)
        if int(warm.sum()) < 30:
            warm = finite & (temps >= max(28.0, low + 0.35 * (high - low)))

    # 用闭运算填补手背内部小孔洞，并取平均温度较高的大块连通域
    close_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    cleaned = cv2.morphologyEx(warm.astype(np.uint8), cv2.MORPH_CLOSE, close_k)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(cleaned, 8)
    best = None
    minimum = max(30, int(0.02 * temps.size))
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        if area < minimum:
            continue
        component = (labels == index) & finite
        if int(component.sum()) < minimum:
            continue
        mean = float(np.mean(temps[component]))
        rank = (mean, area)
        if best is None or rank > best[0]:
            best = (rank, component)
    if best is None:
        return warm
    return best[1]


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
    interior = cv2.erode(body.astype(np.uint8), margin_kernel).astype(bool)
    if int(interior.sum()) < 20:
        interior = body

    body_level = float(np.median(temps[interior]))
    filled = np.where(interior, temps, body_level).astype(np.float32)
    kernel_size = max(15, int(min(height, width) * 0.18))
    if kernel_size % 2 == 0:
        kernel_size += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    baseline = cv2.morphologyEx(filled, cv2.MORPH_OPEN, kernel)
    excess = np.where(interior, temps - baseline, 0.0).astype(np.float32)
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
        ref = _ring_reference(temps, interior, component)
        if ref is None:
            continue
        ref_mean, ref_max, ref_n, ref_roi = ref
        spot = temps[component]
        mean = float(np.mean(spot))
        peak = float(np.max(spot))
        delta = mean - ref_mean
        if delta > 8.0:
            continue
        x, y, w, h = (int(stats[index, 0]), int(stats[index, 1]), int(stats[index, 2]), int(stats[index, 3]))
        grade = grade_delta(delta)
        found.append(
            {
                "roi": _box_roi(x, y, w, h, width, height),
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
    if primary["delta"] >= 1.0:
        message = f"发现 {len(anomalies)} 处局部温升，最明显的一块 +{primary['delta']:.1f} °C"
    else:
        message = f"最热的一块只比旁边皮肤高 {primary['delta']:.1f} °C，手和桌面的差距没有算进去"
    return {
        "regions": [
            {
                "roi": item["roi"],
                "ref_roi": item["ref_roi"],
                "delta": round(item["delta"], 2),
                "delta_max": round(item["delta_max"], 2),
                "wound_mean": round(item["mean"], 2),
                "wound_max": round(item["max"], 2),
                "ref_mean": round(item["ref_mean"], 2),
                "grade": item["grade"],
                "grade_text": item["grade_text"],
            }
            for item in anomalies
        ],
        "wound_roi": primary["roi"] if primary["delta"] >= 1.0 else None,
        "ref_roi": primary["ref_roi"] if primary["delta"] >= 1.0 else None,
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
    }


def evaluate(temps: np.ndarray, wound: Optional[dict], ref: Optional[dict]) -> dict:
    """用创口区均值减对照区均值。对照区不像皮肤时不出档。"""
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
    result["wound"] = wound_stats
    result["ref"] = ref_stats
    if wound_stats is None or ref_stats is None:
        return result

    delta = wound_stats["mean"] - ref_stats["mean"]
    delta_max = wound_stats["max"] - ref_stats["mean"]
    result["delta"] = float(delta)
    result["delta_max"] = float(delta_max)

    if not (28.0 <= ref_stats["mean"] <= 42.0):
        result["grade_text"] = "对照框不在皮肤上"
        result["message"] = "对照区要落在旁边的皮肤上。桌面往往低于 30 °C，不能拿来做差。"
        return result
    if not (28.0 <= wound_stats["mean"] <= 48.0):
        result["grade_text"] = "创口框不在测温范围内"
        result["message"] = "这台机芯的测温档是 30–45 °C。把创口框移到手背上。"
        return result

    grade = grade_delta(delta)
    result["grade"] = grade
    result["grade_text"] = GRADE_TEXT[grade]
    return result


def _plausible(temps: np.ndarray) -> bool:
    if temps.size == 0 or not np.isfinite(temps).any():
        return False
    med = float(np.nanmedian(temps))
    hot = float(np.nanpercentile(temps, 95))
    return -20.0 < med < 80.0 and hot < 120.0


def _decode_u16(raw: np.ndarray, scale: int, offset: int) -> Optional[np.ndarray]:
    scales = []
    if scale not in (0, 1):
        scales.append(int(scale))
    for item in (64, 100, 10, 16, 32, 128, 256, 1):
        if item not in scales:
            scales.append(item)
    for item in scales:
        temps = raw.astype(np.float32) / float(item) + float(offset) - 273.15
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

    返回 ("ok", temps, consumed)、("wait", None, 0) 或 ("skip", None, 0)。
    头布局按 HM-TB 的 132 字节 STREAM_FARME_INFO_TEMP。
    """
    if len(buf) < index + 80:
        return "wait", None, 0
    header_size, _stream_type, stream_len = struct.unpack_from("<III", buf, index + 4)
    if not (80 <= header_size <= 8192):
        return "skip", None, 0
    if len(buf) < index + min(header_size, 80):
        return "wait", None, 0
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
    if len(buf) < index + header_size + count_bytes:
        return "wait", None, 0
    payload = buf[index + header_size : index + header_size + count_bytes]
    if mode == 0:
        raw = np.frombuffer(payload, dtype="<f4").reshape(height, width)
        temps = _decode_f32(raw)
    else:
        raw = np.frombuffer(payload, dtype="<u2").reshape(height, width)
        temps = _decode_u16(raw, int(scale), int(offset))
    if temps is None:
        return "skip", None, 0
    total = max(header_size + count_bytes, header_size + data_len if data_len >= count_bytes else 0)
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
            if status == "wait" and jpeg_end >= 0:
                status = "skip"
            if status == "wait":
                return None
            if status == "skip":
                del buf[index : index + 4]
                continue
            del buf[index : index + consumed]
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


def synthetic_frame(t: float = 0.0) -> np.ndarray:
    """120×160 的自检温度场：手背约 33.5 °C，一小块 36.8 °C。"""
    height, width = 120, 160
    yy, xx = np.mgrid[0:height, 0:width]
    temps = np.full((height, width), 26.0, dtype=np.float32)
    hand = ((xx - 78) ** 2) / (52 ** 2) + ((yy - 62) ** 2) / (34 ** 2) <= 1.0
    temps[hand] = 33.5 + 0.04 * np.sin(t)
    spot = (xx - 100) ** 2 + (yy - 58) ** 2 <= 9 ** 2
    temps[spot] = 36.8
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
    """机芯用红色十字标出全图最高温。返回 (x, y) 像素，找不到则 None。"""
    blue, green, red = cv2.split(image)
    mask = (red > 190) & (green < 90) & (blue < 90)
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
        if not 4 <= area <= 80:
            continue
        cx, cy = centroids[index]
        if best is None or area > best[0]:
            best = (area, float(cx), float(cy))
    if best is None:
        return None
    return best[1], best[2]


def _warm_score(image: np.ndarray) -> np.ndarray:
    blue, green, red = cv2.split(image)
    red_i = red.astype(np.int16)
    green_i = green.astype(np.int16)
    blue_i = blue.astype(np.int16)
    # 屏蔽机芯叠加的绿色文字、绿框、红十字及其 JPEG 压缩边缘振铃
    text = (green_i > 110) & (green_i > red_i + 15) & (blue_i < 140)
    marker = (red_i > 180) & (green_i < 95) & (blue_i < 95)
    osd = cv2.dilate((text | marker).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    score = red.astype(np.float32) * 0.55 + green.astype(np.float32) * 0.45 - blue.astype(np.float32) * 0.15
    score[osd] = 0
    h, w = score.shape
    score[: max(6, int(h * 0.08)), :] = 0
    score[-6:, :] = 0
    score[:, :6] = 0
    score[:, -6:] = 0
    score[int(h * 0.82) :, : int(w * 0.48)] = 0
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
    skin_zone = cv2.dilate(skin.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0

    cross = _crosshair(image)
    point = None
    if cross is not None:
        cx, cy = int(round(cross[0])), int(round(cross[1]))
        if 0 <= cy < height and 0 <= cx < width:
            if not has_prior or skin_zone[cy, cx]:
                point = (cx, cy)
    if point is None:
        point = _hottest_pixel(score, solid_skin)
    if point is None:
        return None
    px, py = point
    side = max(18, int(min(height, width) * 0.08))
    wound = _box_roi(px - side / 2, py - side / 2, side, side, width, height)

    # 蓝框候选点限定在“内缩后的皮肤核心区”，防止掉进指缝冷背景
    erode_r = max(2, side // 2)
    core = cv2.erode(
        solid_skin.astype(np.uint8),
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (erode_r * 2 + 1, erode_r * 2 + 1)),
    ).astype(bool)
    if int(core.sum()) < 20:
        core = solid_skin

    ys, xs = np.where(core)
    dist = np.hypot(xs.astype(np.float32) - px, ys.astype(np.float32) - py)
    # 避开热点自身，同时避免过远边缘
    valid = (dist >= side * 1.1) & (dist <= max(height, width) * 0.45)
    if int(valid.sum()) < 10:
        valid = dist >= side * 0.8
    if int(valid.sum()) < 10:
        valid = np.ones(xs.shape[0], dtype=bool)

    vx, vy, vscore = xs[valid], ys[valid], score[ys[valid], xs[valid]]
    # 在前景皮肤里找中等偏暖但低于热点核心的点
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
