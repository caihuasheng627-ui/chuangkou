"""Engine 逻辑测试：手动/自动解耦、空 ROI 防护、稳态采帧、点温与完整归档。"""

from __future__ import annotations

import csv
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import numpy as np

import app.engine as eng_mod
import app.server as srv_mod
from app.engine import Engine, _colorize
from app.protocol import DEFAULT_REF, synthetic_frame


def _healthy_hand() -> np.ndarray:
    height, width = 120, 160
    yy, xx = np.mgrid[0:height, 0:width]
    temps = np.full((height, width), 24.0, dtype=np.float32)
    hand = ((xx - 78) ** 2) / (52 ** 2) + ((yy - 62) ** 2) / (34 ** 2) <= 1.0
    temps[hand] = 33.5
    return temps


class EngineTests(unittest.TestCase):
    def test_manual_mode_not_overwritten_and_null_safe(self) -> None:
        engine = Engine()
        temps = synthetic_frame(0.0)
        engine._publish(_colorize(temps), temps, "test")

        s_auto = engine.state()
        self.assertTrue(s_auto["auto"])
        self.assertEqual(s_auto["grade"], 2)
        self.assertGreaterEqual(s_auto["delta"], 2.2)

        normal_wound = {"x": 0.25, "y": 0.35, "w": 0.08, "h": 0.10}
        normal_ref = {"x": 0.36, "y": 0.35, "w": 0.08, "h": 0.10}
        engine.set_rois(normal_wound, normal_ref, manual=True)
        s_manual = engine.state()
        self.assertFalse(s_manual["auto"])
        self.assertLess(abs(s_manual["delta"]), 0.2)
        self.assertEqual(s_manual["grade"], 0)

        # 健康手背（新开一轮采集）下自动清空框后，传 ref=None 也不应崩溃
        healthy = _healthy_hand()
        engine2 = Engine()
        engine2._publish(_colorize(healthy), healthy, "healthy")
        s_clear = engine2.state()
        self.assertIsNone(s_clear["wound_roi"])
        self.assertIsNone(s_clear["ref_roi"])

        engine2.set_rois(normal_wound, None, manual=True)
        s_after_null = engine2.state()
        self.assertFalse(s_after_null["auto"])
        self.assertEqual(s_after_null["ref_roi"], DEFAULT_REF)

    def test_stability_measure_lock_and_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with (
                patch.object(eng_mod, "RECORD_PATH", tmp_path / "records.csv"),
                patch.object(eng_mod, "CAPTURE_DIR", tmp_path / "captures"),
            ):
                engine = Engine()
                engine.running = True
                t0 = synthetic_frame(0.0)
                engine._publish(_colorize(t0), t0, "init")

                jumped = t0.copy()
                jumped[jumped > 30.0] += 0.8
                engine._publish(_colorize(jumped), jumped, "jump")
                st_jump = engine.state()
                self.assertTrue(st_jump["unstable"])
                self.assertFalse(engine.save_record()["ok"])

                base = synthetic_frame(0.0)
                engine._publish(_colorize(base), base, "stable0")
                res = engine.start_measure()
                self.assertTrue(res["ok"])
                self.assertEqual(engine.state()["measure_state"], "collecting")

                for k in range(12):
                    frame = synthetic_frame(k * 0.1)
                    engine._publish(_colorize(frame), frame, "collecting")
                    if engine.state()["measure_state"] == "locked":
                        break

                locked = engine.state()
                self.assertEqual(locked["measure_state"], "locked")
                self.assertEqual(locked["frame_count"], 10)
                self.assertFalse(locked["unstable"])
                self.assertIsNotNone(locked["skin_spread"])
                self.assertLessEqual(locked["skin_spread"], 0.3)

                pt = engine.point_temp(100 / 160, 58 / 120)
                self.assertTrue(pt["ok"])
                self.assertGreater(pt["temp"], 36.0)

                saved = engine.save_record(group="模拟明显温升", ntc_delta=3.1)
                self.assertTrue(saved["ok"])
                self.assertTrue((tmp_path / "records.csv").exists())
                self.assertEqual(len(list((tmp_path / "captures").glob("*.npy"))), 1)
                self.assertEqual(len(list((tmp_path / "captures").glob("*.png"))), 1)
                with (tmp_path / "records.csv").open("r", encoding="utf-8-sig") as f:
                    rows = list(csv.DictReader(f))
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["frames_averaged"], "10")
                self.assertNotEqual(rows[0]["wound_px"], "")
                self.assertNotEqual(rows[0]["ref_px"], "")

                # 再保存一次同组记录以验证重复性极差 (Spread <= 0.3°C) 与 NTC 误差统计
                saved2 = engine.save_record(group="模拟明显温升", ntc_delta=3.3)
                self.assertTrue(saved2["ok"])
                rec_summary = engine.list_records()
                self.assertTrue(rec_summary["ok"])
                self.assertEqual(rec_summary["total"], 2)
                g_stat = rec_summary["groups"]["模拟明显温升"]
                self.assertEqual(g_stat["count"], 2)
                self.assertTrue(g_stat["repeatability_ok"])
                self.assertIsNotNone(g_stat["ntc_mae"])

                # 验证历史 .npy 回载复盘与等温差线视图切换、手部姿态对齐
                with patch.object(eng_mod, "ROOT", tmp_path), patch.object(eng_mod, "CAPTURE_DIR", tmp_path / "captures"):
                    rep_res = engine.load_capture(
                        saved["npy"],
                        wound_px=rows[0]["wound_px"],
                        ref_px=rows[0]["ref_px"],
                    )
                    self.assertTrue(rep_res["ok"])
                    self.assertEqual(rep_res["state"]["source"], "replay")
                    self.assertIsNotNone(rep_res["state"]["physics"])
                    self.assertIsNotNone(rep_res["state"]["pose"])
                    # 拒绝越权路径
                    bad_rep = engine.load_capture("C:/Windows/win.ini")
                    self.assertFalse(bad_rep["ok"])

                engine.set_view("isotherm")
                self.assertEqual(engine.state()["view"], "isotherm")
                aligned = engine.align_rois_to_pose()
                self.assertTrue(aligned["ok"])

                engine.unlock_measure()
                self.assertEqual(engine.state()["measure_state"], "idle")

    def test_drift_instability_jump_reset_and_region_selection(self) -> None:
        # 1. 慢速漂移使 10 帧极差 > 0.3 °C，必须标记 unstable 并拒绝保存
        engine = Engine()
        base = _healthy_hand()
        for step in range(5):
            f = base.copy()
            f[f > 30.0] += step * 0.1  # 相邻跳变 0.1 <= 0.3，但极差 0.4 > 0.3
            engine._publish(None, f, "drift")
        st_drift = engine.state()
        self.assertTrue(st_drift["unstable"])
        self.assertGreater(st_drift["skin_spread"], 0.3)
        self.assertFalse(engine.save_record()["ok"])

        # 2. 突变 (> 0.3°C) 必须清空历史，避免前后混叠拖影
        jumped = base.copy()
        jumped[jumped > 30.0] += 0.8
        engine._publish(None, jumped, "jump")
        self.assertEqual(engine.state()["frame_count"], 1)

        # 3. 健康手背自动无框时拒绝保存
        engine_healthy = Engine()
        engine_healthy._publish(None, _healthy_hand(), "healthy")
        self.assertIsNone(engine_healthy.state()["wound_roi"])
        self.assertFalse(engine_healthy.save_record()["ok"])

        # 4. 多区域 select_region(1) 保留真实 wound_n 与 ref_n
        yy, xx = np.mgrid[0:120, 0:160]
        two = _healthy_hand()
        two[(xx - 100) ** 2 + (yy - 58) ** 2 <= 36] = 36.6
        two[(xx - 52) ** 2 + (yy - 52) ** 2 <= 36] = 35.0
        engine_two = Engine()
        engine_two._publish(None, two, "two")
        self.assertEqual(engine_two.state()["region_count"], 2)
        engine_two.select_region(1)
        s1 = engine_two.state()
        self.assertEqual(s1["selected_region"], 1)
        self.assertGreater(s1["wound"]["n"], 0)
        self.assertGreater(s1["ref"]["n"], 0)


class ServerApiTests(unittest.TestCase):
    def test_http_endpoints_end_to_end(self) -> None:
        fresh = Engine()
        with patch.object(srv_mod, "ENGINE", fresh):
            server = ThreadingHTTPServer(("127.0.0.1", 0), srv_mod.Handler)
            port = server.server_address[1]
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            base = f"http://127.0.0.1:{port}"
            try:
                def req(path: str, data: dict | None = None):
                    if data is None:
                        with urllib.request.urlopen(base + path, timeout=5) as r:
                            return r.status, r.read()
                    body = json.dumps(data).encode("utf-8")
                    request = urllib.request.Request(
                        base + path,
                        data=body,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(request, timeout=5) as r:
                        return r.status, json.loads(r.read().decode("utf-8"))

                st, html = req("/")
                self.assertEqual(st, 200)
                self.assertIn("创口温差初筛", html.decode("utf-8"))

                _, js = req("/static/app.js")
                self.assertIn("/api/measure", js.decode("utf-8"))

                _, start_res = req("/api/start", {"source": "synthetic"})
                self.assertTrue(start_res["ok"])

                # 等待合成温度帧产出
                deadline = time.monotonic() + 3.0
                state = {}
                while time.monotonic() < deadline:
                    _, raw = req("/api/state")
                    state = json.loads(raw.decode("utf-8"))
                    if state.get("has_temperature"):
                        break
                    time.sleep(0.05)
                self.assertTrue(state["has_temperature"])
                self.assertEqual(state["grade"], 2)

                _, pt_raw = req("/api/point?x=0.625&y=0.483")
                pt = json.loads(pt_raw.decode("utf-8"))
                self.assertTrue(pt["ok"])
                self.assertGreater(pt["temp"], 36.0)

                _, roi_res = req(
                    "/api/roi",
                    {
                        "wound": {"x": 0.25, "y": 0.35, "w": 0.08, "h": 0.10},
                        "ref": None,
                        "manual": True,
                    },
                )
                self.assertTrue(roi_res["ok"])
                self.assertFalse(roi_res["state"]["auto"])

                _, m_res = req("/api/measure", {})
                self.assertTrue(m_res["ok"])
                _, u_res = req("/api/unlock", {})
                self.assertTrue(u_res["ok"])
                _, auto_res = req("/api/auto", {"enabled": True})
                self.assertTrue(auto_res["state"]["auto"])

                # 验证 synthetic:baseline (档 0) 与 synthetic:mild (档 1)
                for src, expected_grade in (("synthetic:baseline", 0), ("synthetic:mild", 1)):
                    _, sr = req("/api/start", {"source": src})
                    self.assertTrue(sr["ok"])
                    deadline = time.monotonic() + 3.0
                    st_s = {}
                    while time.monotonic() < deadline:
                        _, raw = req("/api/state")
                        st_s = json.loads(raw.decode("utf-8"))
                        if st_s.get("has_temperature") and st_s.get("source") == src:
                            break
                        time.sleep(0.05)
                    self.assertEqual(st_s.get("grade"), expected_grade, st_s)

                # 验证畸形 JSON、非 dict JSON 与超界 ROI 返回 400
                def post_raw(path: str, payload: bytes):
                    r = urllib.request.Request(
                        base + path,
                        data=payload,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    try:
                        with urllib.request.urlopen(r, timeout=5) as resp:
                            return resp.status
                    except urllib.error.HTTPError as err:
                        return err.code

                self.assertEqual(post_raw("/api/start", b"{bad json"), 400)
                self.assertEqual(post_raw("/api/start", b"[1, 2, 3]"), 400)
                self.assertEqual(post_raw("/api/roi", json.dumps({"wound": {"x": "bad"}}).encode("utf-8")), 400)

                # 验证 /api/view isotherm、/api/align_pose、/api/records、/api/records.csv 与 /favicon.ico
                _, v_res = req("/api/view", {"mode": "isotherm"})
                self.assertEqual(v_res["state"]["view"], "isotherm")
                _, ap_res = req("/api/align_pose", {})
                self.assertTrue(ap_res["ok"])
                _, rec_raw = req("/api/records")
                rec_data = json.loads(rec_raw.decode("utf-8"))
                self.assertTrue(rec_data["ok"])
                st_csv, csv_raw = req("/api/records.csv")
                self.assertEqual(st_csv, 200)
                self.assertIn("wound_px", csv_raw.decode("utf-8-sig"))
                st_ico, ico_raw = req("/favicon.ico")
                self.assertEqual(st_ico, 200)
                self.assertIn(b"<svg", ico_raw)

                # 校验 app.js 中所有 #id 选择器在 index.html 中都真实存在，确保无失效按钮绑定
                import re

                html_text = html.decode("utf-8")
                js_text = js.decode("utf-8")
                html_ids = set(re.findall(r'id="([^"]+)"', html_text))
                js_ids = set(re.findall(r'querySelector\("#([^"\s]+)"\)', js_text))
                missing = js_ids - html_ids
                self.assertEqual(missing, set(), f"Missing HTML IDs referenced by app.js: {missing}")

                _, stop_res = req("/api/stop", {})
                self.assertTrue(stop_res["ok"])
                self.assertFalse(stop_res["state"]["running"])
            finally:
                fresh.stop()
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
