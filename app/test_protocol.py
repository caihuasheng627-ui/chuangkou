"""温度帧往返、物理皮肤分割、热区检测与伪彩防漂移测试。"""

import numpy as np

from app.protocol import (
    DEFAULT_REF,
    DEFAULT_WOUND,
    build_test_frame,
    decode_yuyv_temps,
    detect_anomalies,
    evaluate,
    grade_delta,
    locate_hot_bgr,
    next_packet,
    synthetic_frame,
)


def test_grade_edges():
    assert grade_delta(0.99) == 0
    assert grade_delta(1.0) == 1
    assert grade_delta(2.19) == 1
    assert grade_delta(2.2) == 2


def test_roundtrip_and_synthetic():
    original = synthetic_frame(0)
    blob = bytearray(b"\x00\x11" + build_test_frame(original) + b"\xff\xd8\xff\xd9")
    kind, temps = next_packet(blob)
    assert kind == "temp"
    assert temps.shape == original.shape
    assert abs(float(np.mean(temps - original))) < 0.02
    kind, jpg = next_packet(blob)
    assert kind == "jpeg" and jpg.startswith(b"\xff\xd8")

    # YUYV 16-bit 原始温度解码往返
    raw_u16 = np.clip(np.rint((original + 273.15) * 64.0), 0, 65535).astype("<u2")
    decoded = decode_yuyv_temps(raw_u16.tobytes(), width=160, height=120)
    assert decoded is not None
    assert abs(float(np.mean(decoded - original))) < 0.05

    judged = evaluate(original, DEFAULT_WOUND, DEFAULT_REF)
    assert judged["grade"] == 2, judged
    assert judged["delta"] >= 2.2

    cold = dict(DEFAULT_REF)
    cold["x"] = 0.0
    cold["y"] = 0.0
    rejected = evaluate(original, DEFAULT_WOUND, cold)
    assert rejected["grade"] is None


def _hand(spot=None, spot_temp=33.5):
    height, width = 120, 160
    yy, xx = np.mgrid[0:height, 0:width]
    temps = np.full((height, width), 24.0, dtype=np.float32)
    hand = ((xx - 78) ** 2) / (52 ** 2) + ((yy - 62) ** 2) / (34 ** 2) <= 1.0
    temps[hand] = 33.5
    if spot is not None:
        cx, cy, radius = spot
        blob = (xx - cx) ** 2 + (yy - cy) ** 2 <= radius ** 2
        temps[blob] = spot_temp
    return temps


def test_detect_levels():
    quiet = detect_anomalies(_hand())
    assert quiet["grade"] == 0, quiet
    assert quiet["regions"] == []
    assert quiet["wound_roi"] is None
    assert quiet["ref_roi"] is None

    mild = detect_anomalies(_hand((100, 58, 7), 34.9))
    assert mild["grade"] == 1, mild
    assert mild["regions"]
    assert 0.45 < mild["wound_roi"]["x"] < 0.75
    assert mild["ref"]["n"] >= 6
    assert abs(mild["ref"]["max"] - 33.5) < 0.2

    strong = detect_anomalies(_hand((100, 58, 7), 36.6))
    assert strong["grade"] == 2, strong
    assert strong["delta"] >= 2.2

    both = _hand((100, 58, 6), 36.4)
    yy, xx = np.mgrid[0:120, 0:160]
    both[(yy - 40) ** 2 + (xx - 50) ** 2 <= 36] = 34.9
    two = detect_anomalies(both)
    assert two["grade"] == 2, two
    assert len(two["regions"]) == 2

    cold = np.full((120, 160), 22.0, dtype=np.float32)
    none = detect_anomalies(cold)
    assert none["grade"] is None

    desk = np.full((120, 160), 20.0, dtype=np.float32)
    desk[(xx > 8) & (xx < 152) & (yy > 8) & (yy < 112)] = 30.5
    desk[((xx - 80) ** 2) / (40 ** 2) + ((yy - 60) ** 2) / (26 ** 2) <= 1] = 36.5
    plain = detect_anomalies(desk)
    assert plain["regions"] == [], plain
    assert plain["wound_roi"] is None

    hotspot = desk.copy()
    hotspot[(xx - 105) ** 2 + (yy - 55) ** 2 <= 36] = 39.0
    marked = detect_anomalies(hotspot)
    assert marked["grade"] >= 1, marked
    assert marked["wound_roi"]["w"] < 0.25


def test_locate_hot_bgr_ignores_outside_crosshair():
    image = np.zeros((240, 320, 3), dtype=np.uint8)
    skin = np.zeros((240, 320), dtype=bool)
    # 温暖手背在右下
    skin[100:210, 140:280] = True
    image[100:210, 140:280] = (20, 180, 240)
    image[140:160, 200:220] = (120, 240, 255)
    # 左上角画一个不在手部掩膜内的红十字干扰物（例如热笔记本边缘）
    image[30:38, 40:48] = (0, 0, 245)

    res = locate_hot_bgr(image, skin)
    assert res is not None
    wound, ref = res
    # 创口框必须落在手部区域内，而不是左上角干扰红十字
    assert wound["x"] > 0.4 and wound["y"] > 0.35, wound
    assert ref["x"] > 0.4 and ref["y"] > 0.35, ref


if __name__ == "__main__":
    test_grade_edges()
    test_roundtrip_and_synthetic()
    test_detect_levels()
    test_locate_hot_bgr_ignores_outside_crosshair()
    sample = evaluate(synthetic_frame(0), DEFAULT_WOUND, DEFAULT_REF)
    print("synthetic", sample["delta"], sample["grade_text"], sample["wound"], sample["ref"])
