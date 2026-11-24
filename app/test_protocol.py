"""温度帧往返、物理皮肤分割、热区检测与伪彩防漂移测试。"""

from pathlib import Path

import cv2
import numpy as np

from app.foreground import foreground_report, solid_mask
from app.protocol import (
    DEFAULT_REF,
    DEFAULT_WOUND,
    _warm_score,
    analyze_hand_pose,
    analyze_thermal_physics,
    build_test_frame,
    decode_yuyv_temps,
    detect_anomalies,
    encode_anatomical_rois,
    evaluate,
    grade_delta,
    invert_pseudocolor_temps,
    locate_hot_bgr,
    next_packet,
    project_anatomical_rois,
    render_isotherm_view,
    skin_mask,
    synthetic_frame,
)


def test_grade_edges():
    assert grade_delta(0.99) == 0
    assert grade_delta(1.0) == 1
    assert grade_delta(2.19) == 1
    assert grade_delta(2.2) == 2
    assert grade_delta(float(np.float32(33.2) - np.float32(31.0))) == 2
    assert grade_delta(float(np.float32(32.0) - np.float32(31.0))) == 1


def test_roundtrip_and_synthetic():
    original = synthetic_frame(0)
    blob = bytearray(b"\x00\x11" + build_test_frame(original) + b"\xff\xd8\xff\xd9")
    kind, temps = next_packet(blob)
    assert kind == "temp"
    assert temps.shape == original.shape
    assert abs(float(np.mean(temps - original))) < 0.02
    kind, jpg = next_packet(blob)
    assert kind == "jpeg" and jpg.startswith(b"\xff\xd8")
    assert len(blob) == 0

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

    # 边界混入 >15% 冷背景拒判
    mixed_ref = {"x": 0.14, "y": 0.36, "w": 0.14, "h": 0.20}
    mixed_rejected = evaluate(original, DEFAULT_WOUND, mixed_ref)
    assert mixed_rejected["grade"] is None
    assert "低温背景" in mixed_rejected["grade_text"]

    # 两框重叠 >25% 时正常算分并给出提示
    overlap_ref = {"x": 0.56, "y": 0.42, "w": 0.10, "h": 0.12}
    overlapped = evaluate(original, DEFAULT_WOUND, overlap_ref)
    assert overlapped["grade"] is not None
    assert "重叠" in overlapped["message"]

    # 三档合成温度场验证
    assert detect_anomalies(synthetic_frame(0, "baseline"))["grade"] == 0
    assert detect_anomalies(synthetic_frame(0, "mild"))["grade"] == 1
    assert detect_anomalies(synthetic_frame(0, "strong"))["grade"] == 2


def test_stream_edge_cases():
    # 直接摄氏度 * 100 编码（offset=0, scale=100）
    original = synthetic_frame(0)
    raw_c100 = np.clip(np.rint(original * 100.0), 0, 65535).astype("<u2")
    header = bytearray(132)
    import struct
    from app.protocol import MAGIC

    struct.pack_into("<I", header, 0, MAGIC)
    struct.pack_into("<I", header, 4, 132)
    struct.pack_into("<I", header, 8, 2)
    struct.pack_into("<I", header, 12, raw_c100.nbytes)
    struct.pack_into("<I", header, 44, 160)
    struct.pack_into("<I", header, 48, 120)
    struct.pack_into("<I", header, 52, raw_c100.nbytes)
    struct.pack_into("<I", header, 64, 1)
    struct.pack_into("<I", header, 68, 100)
    struct.pack_into("<I", header, 72, 0)
    packet_c = bytes(header) + raw_c100.tobytes()

    # 分包到达且载荷前半段恰含伪造 JPEG 起止符，不能被误跳过
    mutated = bytearray(b"\xaa\xbb\xcc" + packet_c)
    mutated[3 + 132 + 50 : 3 + 132 + 54] = b"\xff\xd8\xff\xd9"
    half = bytearray(mutated[: 3 + 132 + 500])
    assert next_packet(half) is None
    half.extend(mutated[3 + 132 + 500 :])
    kind, decoded = next_packet(half)
    assert kind == "temp"
    assert len(half) == 0
    assert decoded.shape == original.shape
    skin_vals = decoded[(decoded > 30.0) & (decoded < 40.0)]
    assert abs(float(np.median(skin_vals)) - 33.5) < 0.2
    assert abs(float(np.median(decoded)) - 26.0) < 0.2


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
    for reg in two["regions"]:
        assert reg["wound_n"] >= 4
        assert reg["ref_n"] >= 6
        assert reg["ref_max"] >= reg["ref_mean"]

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


def test_complex_thermal_scenarios_and_repeatability():
    yy, xx = np.mgrid[0:120, 0:160]

    # 1. 角落 45°C / 38°C 笔记本干扰 + 手背
    laptop_hand = _hand((100, 58, 5), 35.8)
    laptop_hand[2:32, 2:34] = 45.0
    res_45 = detect_anomalies(laptop_hand)
    assert res_45["grade"] >= 1, res_45
    assert res_45["wound_roi"]["x"] > 0.4

    # 2. 纯 45°C 笔记本干扰无手背
    lone_laptop = np.full((120, 160), 23.0, dtype=np.float32)
    lone_laptop[2:32, 2:34] = 45.0
    assert detect_anomalies(lone_laptop)["grade"] is None

    # 3. 250 mm 近距大面积手背含偏凉手指（30.8°C）无创口
    close_hand = np.full((120, 160), 24.0, dtype=np.float32)
    close_hand[10:115, 20:155] = 33.5
    close_hand[45:95, 5:45] = 30.8
    res_close = detect_anomalies(close_hand)
    assert res_close["grade"] == 0 and res_close["wound_roi"] is None and res_close["delta"] is None

    # 4. 400 mm 远距小手背（无创口 0 档 / 4px 直径小创口 2 档）
    small_base = np.full((120, 160), 23.0, dtype=np.float32)
    small_mask = ((xx - 80) ** 2) / (22 ** 2) + ((yy - 60) ** 2) / (14 ** 2) <= 1.0
    small_base[small_mask] = 33.5
    assert detect_anomalies(small_base)["grade"] == 0
    small_wound = small_base.copy()
    small_wound[(xx - 86) ** 2 + (yy - 60) ** 2 <= 4] = 35.9
    res_small = detect_anomalies(small_wound)
    assert res_small["grade"] == 2, res_small

    # 5. 偏凉手指（31.0°C）上创口（33.2°C），仍低于手掌（33.5°C）但相对手指 +2.2°C
    finger_case = np.full((120, 160), 23.0, dtype=np.float32)
    palm = ((xx - 82) ** 2) / (34 ** 2) + ((yy - 62) ** 2) / (22 ** 2) <= 1.0
    finger_case[palm] = 33.5
    finger_case[(yy >= 54) & (yy <= 66) & (xx >= 14) & (xx <= 55)] = 31.0
    finger_case[(xx - 28) ** 2 + (yy - 60) ** 2 <= 16] = 33.2
    res_finger = detect_anomalies(finger_case)
    assert res_finger["grade"] == 2, res_finger
    assert res_finger["wound_roi"]["x"] < 0.25

    # 6. 28 px 大炎症创口
    large_case = _hand((90, 60, 14), 36.2)
    res_large = detect_anomalies(large_case)
    assert res_large["grade"] == 2, res_large

    # 7. 1.5°C 健康手背自然平滑梯度：未达 1°C 不画框
    grad_case = np.full((120, 160), 23.0, dtype=np.float32)
    grad_hand = ((xx - 78) ** 2) / (42 ** 2) + ((yy - 62) ** 2) / (28 ** 2) <= 1.0
    grad_case[grad_hand] = 33.8 - 1.5 * ((xx[grad_hand] - 78) / 42.0)
    res_grad = detect_anomalies(grad_case)
    assert res_grad["grade"] == 0
    assert res_grad["delta"] is None
    assert res_grad["wound_roi"] is None
    assert res_grad["ref_roi"] is None

    # 8. 20 次 10 帧含噪（σ=0.12°C）重复性验证：ΔT 散布应 < 0.3°C
    rng = np.random.default_rng(42)
    base = synthetic_frame(0.0, "mild")
    deltas = []
    for _ in range(20):
        stack = base[None, :, :] + rng.normal(0.0, 0.12, size=(10, 120, 160)).astype(np.float32)
        avg = np.mean(stack, axis=0)
        det = detect_anomalies(avg)
        assert det["delta"] is not None
        deltas.append(det["delta"])
    spread = max(deltas) - min(deltas)
    assert spread < 0.3, f"repeatability spread too high: {spread:.3f}"


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


def test_locate_hot_bgr_real_samples():
    data_dir = Path(__file__).resolve().parents[1] / "data"
    samples = ("video_30.jpg", "video_120.jpg", "video_180.jpg", "video_210.jpg", "live_thermal.jpg", "now.jpg")
    for name in samples:
        path = data_dir / name
        if not path.exists():
            continue
        img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        assert img is not None, name
        h, w = img.shape[:2]
        rep = foreground_report(img, "u2netp")
        mask = solid_mask(rep["prob"], w, h) if rep["prob"] is not None else None
        res = locate_hot_bgr(img, mask)
        assert res is not None, name
        wound, ref = res
        score = _warm_score(img)
        wx0, wy0 = int(wound["x"] * w), int(wound["y"] * h)
        wx1, wy1 = int((wound["x"] + wound["w"]) * w), int((wound["y"] + wound["h"]) * h)
        rx0, ry0 = int(ref["x"] * w), int(ref["y"] * h)
        rx1, ry1 = int((ref["x"] + ref["w"]) * w), int((ref["y"] + ref["h"]) * h)
        wp = score[wy0:wy1, wx0:wx1]
        rp = score[ry0:ry1, rx0:rx1]
        w_nz = float(wp[wp > 0].mean()) if (wp > 0).any() else 0.0
        r_nz = float(rp[rp > 0].mean()) if (rp > 0).any() else 0.0
        assert w_nz >= r_nz, f"{name}: w_nz={w_nz:.1f} < r_nz={r_nz:.1f}"


def test_innovations_physics_pose_isotherm_and_osd_inversion():
    # 1. 空间热扩散物理特征：局灶团块 vs 条索状浅表血管 & 距离面积换算
    t_strong = synthetic_frame(0.0, "strong")
    det = detect_anomalies(t_strong)
    body = skin_mask(t_strong)
    phys_300 = analyze_thermal_physics(t_strong, det["wound_roi"], det["ref_roi"], 300.0, body)
    phys_400 = analyze_thermal_physics(t_strong, det["wound_roi"], det["ref_roi"], 400.0, body)
    assert phys_300 is not None and phys_400 is not None
    assert phys_300["fwhm_area_mm2"] > 100.0
    assert phys_400["fwhm_area_mm2"] > phys_300["fwhm_area_mm2"] * 1.7
    assert phys_300["radial_profile"][0]["delta"] > 2.5
    assert phys_300["radial_profile"][0]["delta"] > phys_300["radial_profile"][-1]["delta"]
    assert phys_300["decay_slope"] < -0.05
    assert phys_300["pattern"] == "局灶团块型温升"

    # 条索状浅表静脉测试 (elongation >= 2.6)
    vein = _hand()
    vein[56:60, 62:110] = 35.4
    vein_det = detect_anomalies(vein)
    vein_phys = analyze_thermal_physics(vein, vein_det["wound_roi"], vein_det["ref_roi"], 300.0)
    assert vein_phys is not None
    assert vein_phys["elongation"] >= 2.6, vein_phys
    assert "条索状" in vein_phys["pattern"]

    # 2. 手部主轴姿态引导与解剖局部坐标跨帧投影
    pose1 = analyze_hand_pose(body)
    assert pose1 is not None and pose1["status"] == "姿态居中"
    anchor = encode_anatomical_rois(pose1, det["wound_roi"], det["ref_roi"])
    assert anchor is not None
    # 平移手部掩膜 (+12 px X, +6 px Y) 后验证创口框自动跟随平移
    shifted_body = np.roll(np.roll(body, 12, axis=1), 6, axis=0)
    pose2 = analyze_hand_pose(shifted_body)
    projected = project_anatomical_rois(pose2, anchor)
    assert projected is not None
    pw, _ = projected
    assert abs((pw["x"] - det["wound_roi"]["x"]) - (12.0 / 160.0)) < 0.02

    # 3. 等温差线 (Isotherm) 渲染视图
    base_bgr = np.full((480, 640, 3), 40, dtype=np.uint8)
    iso = render_isotherm_view(base_bgr, t_strong, None, det["ref"]["mean"])
    assert iso.shape == (480, 640, 3) and iso.dtype == np.uint8

    # 4. 伪彩 OSD 双锚点（红十字 Max + 绿十字 Cal）同帧温标反演
    data_dir = Path(__file__).resolve().parents[1] / "data"
    for name in ("video_30.jpg", "live_thermal.jpg"):
        path = data_dir / name
        if not path.exists():
            continue
        img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        h, w = img.shape[:2]
        rep = foreground_report(img, "u2netp")
        mask = solid_mask(rep["prob"], w, h) if rep["prob"] is not None else None
        found = locate_hot_bgr(img, mask)
        assert found is not None
        inv = invert_pseudocolor_temps(img, mask, found[0], found[1])
        assert inv["est_temps"].ndim == 2 and inv["est_temps"].size >= 160 * 120
        assert inv["osd_max"] > inv["osd_cal"]
        assert inv["red_cross"] is not None and inv["green_cross"] is not None
        assert inv["est_delta"] is not None and inv["est_delta"] > 0.2

    # 5. 验证热像伪彩分割与人体分割热像防漂移纠偏（冷紫背景 + 暖黄白手掌）
    synth_bgr = np.full((320, 240, 3), (135, 18, 120), dtype=np.uint8)  # 冷紫背景
    cv2.ellipse(synth_bgr, (125, 190), (55, 42), 0, 0, 360, (20, 175, 245), -1)  # 暖橙黄手掌
    cv2.circle(synth_bgr, (135, 188), 14, (190, 248, 255), -1)  # 白热中心
    for mid in ("thermal", "human"):
        rep = foreground_report(synth_bgr, mid)
        assert rep["mask"] is not None, mid
        assert rep["confidence"] >= 0.6, rep
        assert rep["mask"][190, 125], f"{mid} missed warm hand center"
        assert not rep["mask"][30, 40], f"{mid} leaked into cold purple top background"


if __name__ == "__main__":
    test_grade_edges()
    test_roundtrip_and_synthetic()
    test_stream_edge_cases()
    test_detect_levels()
    test_complex_thermal_scenarios_and_repeatability()
    test_locate_hot_bgr_ignores_outside_crosshair()
    test_locate_hot_bgr_real_samples()
    test_innovations_physics_pose_isotherm_and_osd_inversion()
    sample = evaluate(synthetic_frame(0), DEFAULT_WOUND, DEFAULT_REF)
    print("synthetic", sample["delta"], sample["grade_text"], sample["wound"], sample["ref"])
