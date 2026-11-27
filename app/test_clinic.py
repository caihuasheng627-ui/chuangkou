# -*- coding: utf-8 -*-
"""整合回归测试：编码/中文路径安全、相机枚举与解码回退、临床草稿→档案→HTML报告全链路。"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import numpy as np

import app.clinic as clinic_mod
import app.engine as eng_mod
import app.server as srv_mod
from app.engine import Engine, _colorize
from app.probe_camera import decode_console_bytes
from app.protocol import synthetic_frame
from app.window_capture import crop_thermal_content


class EncodingAndCaptureTests(unittest.TestCase):
    def test_decode_console_bytes_utf8_and_gbk(self) -> None:
        utf8_bytes = '  "热成像摄像头" (video)\r\n'.encode("utf-8")
        gbk_bytes = '  "热成像摄像头" (video)\r\n'.encode("gbk")
        self.assertIn("热成像摄像头", decode_console_bytes(utf8_bytes))
        self.assertIn("热成像摄像头", decode_console_bytes(gbk_bytes))

    def test_list_cameras_ignores_audio_alt_and_preserves_video_alt(self) -> None:
        fake_stderr = (
            '[dshow @ 000] "Integrated Webcam" (video)\r\n'
            '[dshow @ 000]   Alternative name "@device_pnp_video0"\r\n'
            '[dshow @ 000] "UVC Camera" (video)\r\n'
            '[dshow @ 000]   Alternative name "@device_pnp_vid_2bdf"\r\n'
            '[dshow @ 000] "Microphone" (audio)\r\n'
            '[dshow @ 000]   Alternative name "@device_cm_audio0"\r\n'
        ).encode("utf-8")

        class _Proc:
            stderr = fake_stderr

        with patch.object(eng_mod.subprocess, "run", return_value=_Proc()):
            cams = eng_mod.list_cameras()
        self.assertEqual(len(cams), 2)
        self.assertEqual(cams[1]["label"], "UVC Camera")
        self.assertEqual(cams[1]["dshow"], "@device_pnp_vid_2bdf")
        self.assertEqual(cams[1]["backend"], "dshow")

    def test_crop_thermal_content_detects_green_border(self) -> None:
        # 模拟 Windows 相机窗口黑边 + 海康绿框热像区域
        canvas = np.zeros((480, 640, 3), dtype=np.uint8)
        canvas[60:380, 200:440] = (90, 20, 120)
        canvas[60, 200:440] = (0, 255, 0)
        canvas[379, 200:440] = (0, 255, 0)
        canvas[60:380, 200] = (0, 255, 0)
        canvas[60:380, 439] = (0, 255, 0)
        cropped = crop_thermal_content(canvas)
        self.assertEqual(cropped.shape[:2], (320, 240))

    def test_bat_launcher_utf8_and_codepage(self) -> None:
        bat = (Path(__file__).resolve().parents[1] / "启动平台.bat").read_text(encoding="utf-8")
        self.assertIn("chcp 65001", bat)
        self.assertIn("PYTHONUTF8=1", bat)
        self.assertIn("python -m app.server", bat)

    def test_u16_raw_decode(self) -> None:
        eng = Engine()
        t = synthetic_frame(0.0)
        raw_k64 = np.clip(np.rint((t + 273.15) * 64.0), 0, 65535).astype(np.uint16)
        decoded = eng._decode_raw_u16_frame(raw_k64)
        self.assertIsNotNone(decoded)
        assert decoded is not None
        self.assertLess(abs(float(np.mean(decoded - t))), 0.05)


class ClinicWorkflowTests(unittest.TestCase):
    def test_draft_gate_archive_and_http_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_patch = {
                "WOUND_CLINIC_DB": str(tmp_path / "clinic.db"),
                "WOUND_CLINIC_REPORTS": str(tmp_path / "reports"),
            }
            fresh = Engine()
            with patch.dict(os.environ, env_patch), patch.object(srv_mod, "ENGINE", fresh):
                server = ThreadingHTTPServer(("127.0.0.1", 0), srv_mod.Handler)
                port = server.server_address[1]
                th = threading.Thread(target=server.serve_forever, daemon=True)
                th.start()
                base = f"http://127.0.0.1:{port}"
                try:
                    def get_json(path: str):
                        with urllib.request.urlopen(base + path, timeout=5) as r:
                            return r.status, json.loads(r.read().decode("utf-8"))

                    def post_json(path: str, payload: dict):
                        req = urllib.request.Request(
                            base + path,
                            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        with urllib.request.urlopen(req, timeout=5) as r:
                            return r.status, json.loads(r.read().decode("utf-8"))

                    # 1. 伪彩帧（无温度矩阵）可存草稿，但质量门禁阻断归档
                    pseudo = np.full((320, 240, 3), (120, 40, 140), dtype=np.uint8)
                    fresh._publish(pseudo, None, "pseudo")
                    _, d_pseudo = post_json("/api/clinic/draft/create", {"title": "伪彩定位草稿"})
                    self.assertTrue(d_pseudo["ok"])
                    self.assertIsNone(d_pseudo["draft"]["quality_gate"])
                    _, arch_blocked = post_json("/api/clinic/draft/archive", {"draft_id": d_pseudo["draft"]["draft_id"]})
                    self.assertFalse(arch_blocked["ok"])
                    self.assertEqual(arch_blocked["error"]["code"], "analysis_not_validated")

                    # 2. 真实温度矩阵（≥5 帧稳定）通过质量门禁并成功归档为 患者01 / PT-0001 + HTML 报告
                    for k in range(6):
                        t_frame = synthetic_frame(k * 0.05, "strong")
                        fresh._publish(_colorize(t_frame), t_frame, "temp")

                    _, d_real = post_json("/api/clinic/draft/create", {"title": "右手背创口初筛"})
                    self.assertTrue(d_real["ok"])
                    draft = d_real["draft"]
                    self.assertEqual(draft["quality_gate"], "passed")
                    self.assertEqual(draft["rule_result"]["level"], "high")

                    # 3. 补充临床详情（身份字段自动丢弃，空白清除）
                    _, upd = post_json(
                        "/api/clinic/draft/update",
                        {
                            "draft_id": draft["draft_id"],
                            "details": {
                                "site": "右手背",
                                "duration": "4天",
                                "symptoms": "轻微红肿",
                                "patient_name": "张三",
                            },
                        },
                    )
                    self.assertTrue(upd["ok"])
                    self.assertEqual(upd["draft"]["details"], {"site": "右手背", "duration": "4天", "symptoms": "轻微红肿"})

                    # 4. 归档并读取生成的 HTML 报告
                    _, arch = post_json("/api/clinic/draft/archive", {"draft_id": draft["draft_id"]})
                    self.assertTrue(arch["ok"])
                    self.assertEqual(arch["patient_ref"], "PT-0001")
                    self.assertEqual(arch["display_name"], "患者01")
                    report_id = arch["report_id"]
                    self.assertTrue(report_id.startswith("RPT-"))

                    with urllib.request.urlopen(f"{base}/api/clinic/report/{report_id}", timeout=5) as r:
                        html_text = r.read().decode("utf-8")
                    self.assertIn("创口温度异常辅助筛查报告", html_text)
                    self.assertIn("患者01", html_text)
                    self.assertIn("右手背", html_text)

                    # 5. 归档后锁定不可修改/重复归档
                    _, locked = post_json("/api/clinic/draft/archive", {"draft_id": draft["draft_id"]})
                    self.assertFalse(locked["ok"])
                    self.assertEqual(locked["error"]["code"], "draft_locked")

                    # 6. 汇总接口返回草稿、患者、报告与 4 条循证证据
                    _, summary = get_json("/api/clinic/summary")
                    self.assertTrue(summary["ok"])
                    self.assertEqual(len(summary["patients"]), 1)
                    self.assertEqual(len(summary["reports"]), 1)
                    self.assertEqual(len(summary["evidence"]), 4)
                finally:
                    fresh.stop()
                    server.shutdown()
                    server.server_close()


if __name__ == "__main__":
    unittest.main()
