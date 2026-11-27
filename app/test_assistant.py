# -*- coding: utf-8 -*-
"""循证对话医师助手与新增工作站 API 回归测试。"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import app.assistant as asst
import app.server as srv_mod
from app.engine import Engine


SAMPLE_MEASUREMENT = {
    "schema_version": "1.0",
    "measurement_id": "MEAS-DEMO-0001",
    "patient_ref": "SECRET-PATIENT-999",
    "captured_at": "2026-11-23T10:25:38+08:00",
    "device": {
        "model": "HM-TB421-3XF",
        "capture_mode": "mock_y16",
        "emissivity": 0.98,
        "distance_m": 0.4,
        "calibration": {"status": "valid", "calibration_id": "CAL-1"},
    },
    "quality": {
        "frames_used": 30,
        "roi_valid": True,
        "reference_valid": True,
        "temperature_in_range": True,
        "warnings": [],
    },
    "metrics": {
        "t_wound_mean_c": 34.79,
        "t_ref_far_c": 32.51,
        "t_ref_near_c": 32.93,
        "delta_t_c": 2.28,
        "t_wound_max_c": 37.96,
        "area_ratio": 0.112,
    },
    "thresholds": {"version": "wound-delta-v1", "normal_max_c": 0.6, "warning_max_c": 2.2, "infection_min_c": 2.55},
    "frame_image": {"mime": "image/jpeg", "base64": "AAAA"},
}


class AssistantLogicTests(unittest.TestCase):
    def test_sanitize_strips_identity_and_image(self) -> None:
        clean = asst.sanitize_measurement(SAMPLE_MEASUREMENT)
        self.assertIsNotNone(clean)
        assert clean is not None
        self.assertNotIn("patient_ref", clean)
        self.assertNotIn("frame_image", clean)
        self.assertEqual(clean["metrics"]["delta_t_c"], 2.28)

    def test_split_detail_block_and_offline_extract(self) -> None:
        raw = '已记录。\n<<<DETAIL>>>{"site":"左手背","duration":"3天","patient_name":"张三"}<</DETAIL>>>'
        visible, det = asst.split_detail_block(raw)
        self.assertEqual(visible, "已记录。")
        self.assertEqual(det, {"site": "左手背", "duration": "3天"})

        draft = {"draft_id": "DRF-1", "status": "draft", "details": {}}
        ext = asst.extract_details_offline("创口位于右手背，外伤后4天，边缘轻度红肿和少量渗液，正在用碘伏换药", draft)
        self.assertIn("site", ext)
        self.assertIn("duration", ext)
        self.assertIn("symptoms", ext)
        self.assertIn("treatment", ext)

    def test_safety_validator_blocks_diagnosis_and_antibiotics(self) -> None:
        rules = asst.load_rules()
        analysis = {"rule_result": {"level": "high", "label": "显著热异常（感染风险增高）", "delta_t_c": 2.28}}
        bad1 = asst.validate_answer("患者已确诊感染，建议立即口服头孢类抗生素。", rules, analysis)
        self.assertFalse(bad1["ok"])
        codes = {v["code"] for v in bad1["violations"]}
        self.assertIn("diagnosis", codes)
        self.assertIn("antibiotic", codes)

        bad2 = asst.validate_answer("研究阈值显示 2.2°C 很危险，属于高风险。", rules, analysis)
        self.assertFalse(bad2["ok"])

        good = asst.validate_answer(
            "ΔT +2.28°C 达到预警参考值（E003），提示感染风险增高但不能确诊感染；建议同条件复测（E004）并交由医护复核后再决定正式报告。",
            rules,
            analysis,
        )
        self.assertTrue(good["ok"], good)


class AssistantHttpTests(unittest.TestCase):
    def test_assistant_and_example_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_patch = {
                "WOUND_CLINIC_DB": str(tmp_path / "clinic.db"),
                "WOUND_CLINIC_REPORTS": str(tmp_path / "reports"),
                "WOUND_ASSISTANT_CONFIG": str(tmp_path / "assistant_config.json"),
                "WOUND_LLM_API_KEY": "",
                "DEEPSEEK_API_KEY": "",
                "OPENAI_API_KEY": "",
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

                    # 1. 示例 JSON 载入与分析
                    st, ex = get_json("/api/clinic/example")
                    self.assertEqual(st, 200)
                    self.assertTrue(ex["ok"])
                    self.assertEqual(ex["analysis"]["rule_result"]["level"], "high")

                    # 2. 获取规则与脱敏模型配置
                    _, rules_res = get_json("/api/assistant/rules")
                    self.assertTrue(rules_res["ok"])
                    self.assertFalse(rules_res["config"]["has_api_key"])
                    self.assertGreater(len(rules_res["rules"]["sections"]), 0)

                    # 3. 离线规则模式问答
                    _, reply = post_json(
                        "/api/assistant/chat",
                        {"question": "这组数值怎么解读？", "measurement": ex["measurement"]},
                    )
                    self.assertTrue(reply["ok"])
                    self.assertFalse(reply["meta"]["modelUsed"])
                    self.assertIn("E004", reply["answer"])

                    # 4. 保存 API Key 后仅返回脱敏摘要，且违规模型输出会被拦截并回退本地模板
                    _, cfg_res = post_json(
                        "/api/assistant/config",
                        {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat", "api_key": "sk-test1234567890", "enabled": True},
                    )
                    self.assertTrue(cfg_res["config"]["has_api_key"])
                    self.assertNotIn("sk-test1234567890", json.dumps(cfg_res))

                    with patch.object(
                        asst,
                        "_call_openai_compatible",
                        return_value=("患者已确诊感染，立刻吃头孢抗生素。", None),
                    ):
                        _, intercepted = post_json(
                            "/api/assistant/chat",
                            {"question": "请确诊并开抗生素", "measurement": ex["measurement"]},
                        )
                    self.assertTrue(intercepted["ok"])
                    self.assertFalse(intercepted["meta"]["modelUsed"])
                    self.assertEqual(intercepted["meta"]["reason"], "rule_violation")
                    self.assertGreater(len(intercepted["meta"]["violations"]), 0)
                    self.assertNotIn("头孢", intercepted["answer"])
                finally:
                    fresh.stop()
                    server.shutdown()
                    server.server_close()


if __name__ == "__main__":
    unittest.main()
