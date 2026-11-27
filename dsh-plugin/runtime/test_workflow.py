# -*- coding: utf-8 -*-
"""草稿工作流回归：python runtime/test_workflow.py（使用临时数据库，不触碰 data/wound_archive.db）"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "runtime" / "plugin_service.py"

MEASUREMENT = {
    "measurement_id": "MEAS-TEST-0001", "patient_ref": "DEMO-001", "encounter_id": "ENC-TEST-0001",
    "captured_at": "2026-11-23T23:00:00+08:00",
    "device": {"model": "HM-TB421-3XF", "capture_mode": "mock_y16", "emissivity": 0.98, "distance_m": 0.4, "ambient_c": 24,
               "calibration": {"status": "valid", "calibration_id": "CAL-TEST-001"}},
    "quality": {"frames_used": 30, "temporal_median_frames": 5, "roi_valid": True, "reference_valid": True,
                "temperature_in_range": True, "roi_method": "automatic_hotspot", "warnings": []},
    "metrics": {"t_wound_mean_c": 34.79, "t_ref_far_c": 32.51, "t_ref_near_c": 32.93, "delta_t_c": 2.28,
                "t_wound_max_c": 37.96, "area_ratio": 0.112, "gradient_c": 3.17},
    "thresholds": {"version": "wound-delta-v1", "normal_max_c": 0.6, "warning_max_c": 2.2, "infection_min_c": 2.55},
}


def call(action, payload):
    env = dict(os.environ, PYTHONUTF8="1", WOUND_CLINIC_DB=DB)
    proc = subprocess.run([sys.executable, str(SERVICE), action], input=json.dumps(payload, ensure_ascii=False),
                          capture_output=True, text=True, encoding="utf-8", cwd=ROOT, env=env, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


with tempfile.TemporaryDirectory() as tmp:
    DB = str(Path(tmp) / "test.db")
    # 1. 保存草稿：本地规则引擎随草稿落库
    created = call("draft.create", {"title": "左小腿创口筛查", "measurement": MEASUREMENT})
    assert created["ok"], created
    draft = created["draft"]
    assert draft["status"] == "draft" and draft["quality_gate"] == "passed", draft
    assert draft["rule_result"]["level"] == "high" and abs(draft["delta_t_c"] - 2.28) < 1e-9
    draft_id = draft["draft_id"]
    print("DRAFT_CREATE_OK", draft_id, draft["rule_result"]["label"])

    # 2. 侧边对话提取的详情经用户确认后写入；空字符串清除字段
    updated = call("draft.update", {"draft_id": draft_id,
                                    "details": {"site": "左小腿外侧", "duration": "两周", "symptoms": "少量渗液", "patient_name": "张三"},
                                    "supplements": [{"text": "创口在左小腿外侧，两周了，有少量渗液", "source": "chat", "fields": ["site", "duration", "symptoms"]}],
                                    "chat": [{"role": "user", "text": "创口在左小腿外侧"}, {"role": "assistant", "text": "已记录。"}]})
    assert updated["ok"], updated
    assert updated["draft"]["details"] == {"site": "左小腿外侧", "duration": "两周", "symptoms": "少量渗液"}, updated["draft"]["details"]
    assert len(updated["draft"]["supplements"]) == 1 and len(updated["draft"]["chat"]) == 2
    cleared = call("draft.update", {"draft_id": draft_id, "details": {"symptoms": "  "}})
    assert "symptoms" not in cleared["draft"]["details"] and cleared["cleared_fields"] == ["symptoms"], cleared
    print("DRAFT_UPDATE_OK details-merged-identity-dropped-field-cleared")

    # 3. 列表与读取
    listed = call("draft.list", {})
    assert listed["ok"] and len(listed["drafts"]) == 1 and listed["drafts"][0]["detail_count"] == 2, listed
    got = call("draft.get", {"draft_id": draft_id})
    assert got["ok"] and got["draft"]["title"] == "左小腿创口筛查"
    print("DRAFT_LIST_GET_OK")

    # 4. 归档：自动编号患者01，写入测量与报告，草稿锁定
    archived = call("draft.archive", {"draft_id": draft_id})
    assert archived["ok"], archived
    assert archived["patient_ref"] == "PT-0001" and archived["display_name"] == "患者01", archived
    assert archived["report_id"] and archived["report_status"] == "draft"
    assert archived["draft"]["status"] == "archived" and archived["draft"]["patient_name"] == "患者01"
    again = call("draft.archive", {"draft_id": draft_id})
    assert not again["ok"] and again["error"]["code"] == "draft_locked", again
    locked = call("draft.update", {"draft_id": draft_id, "details": {"site": "改"}})
    assert not locked["ok"] and locked["error"]["code"] == "draft_locked", locked
    print("ARCHIVE_OK 患者01 PT-0001 locked-after-archive")

    # 5. 同一测量再存草稿不能重复归档；第二份不同测量归档为患者02
    dup = call("draft.create", {"title": "重复测量", "measurement": MEASUREMENT})
    dup_archive = call("draft.archive", {"draft_id": dup["draft"]["draft_id"]})
    assert not dup_archive["ok"] and dup_archive["error"]["code"] == "measurement_exists", dup_archive
    assert len(call("archive.list", {})["patients"]) == 1
    second = call("draft.create", {"title": "第二次筛查", "measurement": {**MEASUREMENT, "measurement_id": "MEAS-TEST-0002", "encounter_id": "ENC-TEST-0002"}})
    second_archive = call("draft.archive", {"draft_id": second["draft"]["draft_id"]})
    assert second_archive["ok"] and second_archive["display_name"] == "患者02" and second_archive["patient_ref"] == "PT-0002", second_archive
    print("NUMBERING_OK second-patient-is-患者02 duplicate-measurement-rejected")

    # 6. 门禁未通过的草稿可以保存，但不能归档
    blocked = call("draft.create", {"title": "标定失效", "measurement": {**MEASUREMENT, "measurement_id": "MEAS-TEST-0003",
                                  "device": {**MEASUREMENT["device"], "calibration": {"status": "invalid"}}}})
    assert blocked["ok"] and blocked["draft"]["quality_gate"] is None and blocked["draft"]["blocked_message"], blocked
    blocked_archive = call("draft.archive", {"draft_id": blocked["draft"]["draft_id"]})
    assert not blocked_archive["ok"] and blocked_archive["error"]["code"] == "analysis_not_validated", blocked_archive
    print("GATE_OK blocked-draft-saved-but-not-archived")

    # 7. 档案与报告读取
    history = call("archive.history", {"patient_ref": "PT-0001"})
    assert history["ok"] and len(history["measurements"]) == 1 and history["measurements"][0]["rule_result"]["level"] == "high"
    assert history["measurements"][0]["patient_ref"] if "patient_ref" in history["measurements"][0] else True
    reports = call("report.list", {"patient_ref": "PT-0001"})
    assert reports["ok"] and len(reports["reports"]) == 1 and reports["reports"][0]["status"] == "draft"
    all_reports = call("report.list", {})
    assert len(all_reports["reports"]) == 2
    final_list = call("draft.list", {})
    by_name = {d["patient_name"]: d for d in final_list["drafts"] if d["status"] == "archived"}
    assert set(by_name) == {"患者01", "患者02"} and by_name["患者02"]["patient_ref"] == "PT-0002", final_list
    print("ARCHIVE_READ_OK history-reports-list")

print("WORKFLOW_TESTS_OK")
