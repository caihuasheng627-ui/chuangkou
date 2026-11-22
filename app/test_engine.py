"""Engine 逻辑测试：手动/自动解耦、空 ROI 防护、稳态采帧、点温与完整归档。"""

from __future__ import annotations

import csv
import json
import tempfile
import threading
import time
import unittest
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

                saved = engine.save_record()
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

                engine.unlock_measure()
                self.assertEqual(engine.state()["measure_state"], "idle")


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
                _, stop_res = req("/api/stop", {})
                self.assertTrue(stop_res["ok"])
            finally:
                fresh.stop()
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
