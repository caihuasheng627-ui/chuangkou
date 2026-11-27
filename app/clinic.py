# -*- coding: utf-8 -*-
"""临床草稿、患者档案、HTML 筛查报告与循证规则引擎。

整合自 dsh-wound-clinic v0.7.2（plugin_service.py + live_server.py 测量转换），
使 chuangkou 独立浏览器工作站无需 DSH 宿主也能完整运行：
实时筛查 → 质量门禁与循证规则分析 → 临床草稿（补充结构化创口详情） → 自动编号患者档案（患者01 / PT-0001） → 可追溯 HTML 报告。
"""
from __future__ import annotations

import base64
import contextlib
import datetime as dt
import hashlib
import html
import json
import math
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
REPORTS_DIR = DATA_DIR / "reports"
EVIDENCE_PATH = APP_DIR / "clinical_data" / "evidence.json"
RULES_PATH = APP_DIR / "clinical_data" / "physician_rules.json"

LABELS = {
    "normal": "未见明显热异常",
    "suspicious": "可疑炎症（建议复测）",
    "high": "显著热异常（感染风险增高）",
    "cold": "局部低温（警惕灌注不足）",
}
DISCLAIMER = "本结果仅用于创口感染风险辅助筛查，不替代医护人员结合创面、实验室及病原学结果作出的临床诊断。"

DETAIL_FIELDS = {
    "site": "创口部位",
    "duration": "病程/持续时间",
    "symptoms": "创面表现",
    "treatment": "处理与用药史",
    "notes": "其他备注",
}

_REPORT_ID_RE = re.compile(r"^RPT-[0-9A-Za-z-]+$")


def get_db_path() -> Path:
    env = os.environ.get("WOUND_CLINIC_DB", "").strip()
    return Path(env) if env else (DATA_DIR / "wound_archive.db")


def get_reports_dir() -> Path:
    env = os.environ.get("WOUND_CLINIC_REPORTS", "").strip()
    return Path(env) if env else REPORTS_DIR


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def evidence_all() -> list[dict]:
    if not EVIDENCE_PATH.exists():
        return []
    return _load_json(EVIDENCE_PATH)


def evidence_map() -> dict[str, dict]:
    return {item["evidence_id"]: item for item in evidence_all()}


def rules_summary() -> dict:
    if not RULES_PATH.exists():
        return {"version": "fallback", "role": "创口热成像辅助筛查医师助手", "sections": []}
    data = _load_json(RULES_PATH)
    return {
        "version": data.get("version"),
        "role": data.get("role"),
        "identity": data.get("identity"),
        "disclaimer": DISCLAIMER,
        "sections": [{"id": s.get("id"), "title": s.get("title")} for s in (data.get("sections") or [])],
    }


def _ok(action: str, **fields) -> dict:
    return {"ok": True, "action": action, **fields}


def _fail(code: str, message: str, hint: str = "") -> dict:
    return {"ok": False, "error": {"code": code, "message": message, "hint": hint}}


def _finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def clean_details(raw) -> dict[str, str]:
    """只保留白名单结构化临床字段，丢弃任何直接身份信息（姓名/证件/联系方式等）。"""
    out: dict[str, str] = {}
    if not isinstance(raw, dict):
        return out
    for key in DETAIL_FIELDS:
        value = raw.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            out[key] = text[:120]
    return out


def clean_chat(items) -> Optional[list[dict]]:
    if not isinstance(items, list):
        return None
    cleaned = []
    for item in items:
        if not isinstance(item, dict) or item.get("role") not in ("user", "assistant"):
            continue
        text = str(item.get("text") or "").strip()
        if text:
            cleaned.append({"role": item["role"], "text": text[:2000]})
    return cleaned[-40:]


@contextlib.contextmanager
def connect():
    db_file = get_db_path()
    db_file.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(db_file)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS patients(
              patient_ref TEXT PRIMARY KEY,
              display_name TEXT,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS encounters(
              encounter_id TEXT PRIMARY KEY,
              patient_ref TEXT NOT NULL,
              captured_at TEXT,
              device_json TEXT NOT NULL,
              quality_json TEXT NOT NULL,
              FOREIGN KEY(patient_ref) REFERENCES patients(patient_ref)
            );
            CREATE TABLE IF NOT EXISTS measurements(
              measurement_id TEXT PRIMARY KEY,
              encounter_id TEXT,
              patient_ref TEXT NOT NULL,
              captured_at TEXT,
              metrics_json TEXT NOT NULL,
              rule_json TEXT NOT NULL,
              analysis_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY(patient_ref) REFERENCES patients(patient_ref)
            );
            CREATE TABLE IF NOT EXISTS reports(
              report_id TEXT PRIMARY KEY,
              patient_ref TEXT NOT NULL,
              measurement_id TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('draft','reviewed','void')),
              path TEXT NOT NULL,
              content_hash TEXT NOT NULL,
              versions_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              reviewed_by TEXT
            );
            CREATE TABLE IF NOT EXISTS drafts(
              draft_id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('draft','archived')),
              patient_ref TEXT,
              measurement_id TEXT,
              measurement_json TEXT NOT NULL,
              analysis_json TEXT NOT NULL,
              details_json TEXT NOT NULL,
              supplements_json TEXT NOT NULL,
              chat_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_events(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              at TEXT NOT NULL,
              actor TEXT NOT NULL,
              action TEXT NOT NULL,
              object_ref TEXT,
              result TEXT NOT NULL,
              detail_json TEXT NOT NULL
            );
            """
        )
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _audit(db: sqlite3.Connection, action: str, object_ref: Optional[str], result: str = "success", detail=None) -> None:
    db.execute(
        "INSERT INTO audit_events(at,actor,action,object_ref,result,detail_json) VALUES(?,?,?,?,?,?)",
        (now_iso(), "local-workstation", action, object_ref, result, json.dumps(detail or {}, ensure_ascii=False)),
    )


def measurement_from_engine(engine, include_image: bool = True) -> dict:
    """将 chuangkou Engine 当前实时帧转换为 wound-measurement/v1 结构。"""
    st = engine.state()
    with engine._lock:
        jpeg = engine.jpeg
        last_img = engine._last_image
    if not jpeg:
        raise RuntimeError("尚未取得画面帧，无法生成临床测量")

    width = (st.get("matrix") or {}).get("width")
    height = (st.get("matrix") or {}).get("height")
    if (not width or not height) and last_img is not None:
        height, width = int(last_img.shape[0]), int(last_img.shape[1])

    has_temp = bool(st.get("has_temperature"))
    src = str(st.get("source") or "")
    is_mock = src.startswith("synthetic")
    mode = "mock_y16" if is_mock else ("y16_raw" if has_temp else "pseudo")

    wound = st.get("wound") or {}
    ref = st.get("ref") or {}
    warnings = []
    if is_mock:
        warnings.append("合成温度源仅用于联调自检，不构成临床测量")
    if not has_temp:
        warnings.append(st.get("grade_text") or "当前仅为伪彩画面，未获得 16bit 全屏温度矩阵，质量门禁将阻断归档")
    if st.get("unstable"):
        warnings.append(st.get("message") or "当前温度波动超过 0.3 °C，请保持静止后复测")

    mid = "MEAS-LIVE-" + hashlib.sha1(jpeg + f"{time.time():.6f}".encode("ascii")).hexdigest()[:16]
    captured_at = now_iso()

    t_w = wound.get("mean") if has_temp else None
    t_w_max = wound.get("max") if has_temp else None
    t_r = ref.get("mean") if has_temp else None
    delta = st.get("delta") if has_temp else None

    m = {
        "schema_version": "1.0",
        "measurement_id": mid,
        "captured_at": captured_at,
        "patient_ref": None,
        "device": {
            "model": st.get("source_label") or src or "HM-TB421-3XF",
            "capture_mode": mode,
            "capture_backend": st.get("capture_backend") or "",
            "emissivity": st.get("emissivity", 0.98),
            "distance_m": round((st.get("distance_mm") or 300) / 1000.0, 3),
            "ambient_c": None,
            "calibration": {
                "status": "valid" if has_temp else "invalid",
                "method": "chuangkou_temperature_matrix" if has_temp else "no_temperature_matrix",
                "raw_scale": st.get("raw_scale", 0.01),
                "raw_offset": st.get("raw_offset", 0.0),
            },
        },
        "quality": {
            "frames_used": int(st.get("frame_count") or 0),
            "temporal_median_frames": 10,
            "roi_valid": bool(st.get("wound_roi") and wound),
            "reference_valid": bool(st.get("ref_roi") and ref),
            "temperature_in_range": has_temp and not bool(st.get("unstable")) and st.get("grade") is not None,
            "warnings": warnings,
        },
        "metrics": {
            "t_wound_mean_c": t_w,
            "t_wound_max_c": t_w_max,
            "t_ref_far_c": t_r,
            "t_ref_near_c": t_r,
            "delta_t_c": delta,
            "area_ratio": st.get("mask_fraction"),
            "t_min_c": None,
            "t_max_c": st.get("frame_max"),
            "temperature_unit": "degC",
            "estimated_delta_t_c": None if has_temp else st.get("delta"),
        },
        "thresholds": {
            "version": "wound-delta-v1",
            "normal_max_c": 0.6,
            "warning_max_c": 2.2,
            "infection_min_c": 2.55,
        },
        "note": "ΔT = 创口区均温 − 参考皮温，仅作创口感染风险辅助筛查，不能用于确诊感染。",
    }
    if include_image:
        m["frame_image"] = {
            "mime": "image/jpeg",
            "base64": base64.b64encode(jpeg).decode("ascii"),
            "width": width,
            "height": height,
        }
    return m


def quality_gate(m: dict) -> list[str]:
    if not isinstance(m, dict):
        return ["测量输入必须是 JSON 对象"]
    problems: list[str] = []
    calibration = (m.get("device") or {}).get("calibration") or {}
    if calibration.get("status") != "valid":
        problems.append("标定无效或缺失（当前无真实温度矩阵）")
    q = m.get("quality") or {}
    if not _finite_number(q.get("frames_used")) or q.get("frames_used") < 5:
        problems.append("有效稳定帧数不足（需 ≥ 5 帧）")
    if q.get("roi_valid") is not True:
        problems.append("创口 ROI 无效")
    if q.get("reference_valid") is not True:
        problems.append("参考皮肤区无效")
    if q.get("temperature_in_range") is not True:
        problems.append("温度超出设备有效量程、画面不稳定或存在饱和")
    metrics = m.get("metrics") or {}
    for key in ("t_wound_mean_c", "t_ref_far_c", "delta_t_c"):
        if not _finite_number(metrics.get(key)):
            problems.append(f"缺少有效指标 {key}")
    if not problems:
        computed = metrics["t_wound_mean_c"] - metrics["t_ref_far_c"]
        if abs(computed - metrics["delta_t_c"]) > 0.15:
            problems.append("ΔT 与创口/参考区温度不一致")
    if not m.get("measurement_id"):
        problems.append("缺少 measurement_id")
    return problems


def thermal_analyze(m: dict) -> dict:
    problems = quality_gate(m)
    if problems:
        return _fail(
            "quality_gate_blocked",
            "；".join(problems),
            "重新标定或采集真实温度矩阵；质量门禁未通过时不得归档为正式患者测量。",
        )

    metrics = m["metrics"]
    delta = float(metrics["delta_t_c"])
    th = m.get("thresholds") or {}
    normal_max = float(th.get("normal_max_c", 0.6))
    warn_max = float(th.get("warning_max_c", 2.2))
    infect_min = float(th.get("infection_min_c", 2.55))

    reason_codes: list[str] = []
    interpretation: list[dict] = []
    if delta < -normal_max:
        level = "cold"
        reason_codes.append("DELTA_BELOW_REFERENCE")
        interpretation.append(
            {
                "text": f"创口区较参考皮肤低 {-delta:.2f}°C，需考虑局部灌注不足，不能按感染升温逻辑解释。",
                "evidence_ids": [],
            }
        )
    elif delta < normal_max:
        level = "normal"
        reason_codes.append("DELTA_WITHIN_NORMAL")
        interpretation.append(
            {"text": f"ΔT={delta:+.2f}°C，未达到本规则的热异常提示区间。", "evidence_ids": ["E004"]}
        )
    elif delta < warn_max:
        level = "suspicious"
        reason_codes.append("DELTA_SUSPICIOUS")
        interpretation.append(
            {
                "text": f"ΔT={delta:+.2f}°C，提示轻度热异常；单次测量不能确认感染，应复测并结合创面表现。",
                "evidence_ids": ["E004"],
            }
        )
    else:
        level = "high"
        reason_codes.append("DELTA_ABOVE_WARNING")
        if delta >= infect_min:
            reason_codes.append("DELTA_ABOVE_2_55")
            interpretation.append(
                {
                    "text": f"ΔT={delta:+.2f}°C，达到研究中的创周热不对称参考值；该结果提示感染风险增高，但不是病原学诊断。",
                    "evidence_ids": ["E002"],
                }
            )
        else:
            interpretation.append(
                {
                    "text": f"ΔT={delta:+.2f}°C，已超过预警参考值，需复测并尽快进行临床评估；2.2°C 的研究场景不是所有创口的通用确诊界值。",
                    "evidence_ids": ["E003", "E004"],
                }
            )

    near = metrics.get("t_ref_near_c")
    if _finite_number(near) and near - metrics["t_ref_far_c"] > 0.4:
        reason_codes.append("PERIWOUND_INVOLVED")
        interpretation.append(
            {"text": "近端创周温度高于远端参考皮肤，说明热异常可能已波及创周；参考区选择会影响 ΔT。", "evidence_ids": ["E002"]}
        )

    abs_temp = metrics["t_wound_mean_c"]
    limitations = [
        "单次红外测温存在假阳性，重复测量和趋势确认比单次读数更可靠。",
        "当前证据的人群、创口类型和测量条件并不完全一致，阈值不能直接外推为通用诊断标准。",
    ]
    if (m.get("device") or {}).get("capture_mode") == "pseudo":
        limitations.append("当前为伪彩反演温度，精度受限，应优先使用原始温度帧。")
    if (m.get("quality") or {}).get("warnings"):
        limitations.extend(m["quality"]["warnings"])

    recommendations = [
        {"text": "在相同环境、距离和参考区条件下复测，并比较连续趋势。", "evidence_ids": ["E004"], "priority": "routine"}
    ]
    if level in ("high", "cold"):
        recommendations.append(
            {
                "text": "建议由医护人员结合创面外观、灌注情况及必要的实验室/病原学检查评估。",
                "evidence_ids": ["E002"],
                "priority": "clinical_review",
            }
        )
    else:
        recommendations.append(
            {
                "text": "继续常规观察；若出现红肿扩大、渗液增多、疼痛加重或全身不适，应及时就医。",
                "evidence_ids": ["E004"],
                "priority": "routine",
            }
        )

    evidence_ids = sorted({eid for item in interpretation + recommendations for eid in item["evidence_ids"]})
    emap = evidence_map()
    result = {
        "level": level,
        "label": LABELS[level],
        "delta_t_c": delta,
        "threshold_version": th.get("version", "wound-delta-v1"),
        "reason_codes": reason_codes,
        "absolute_temperature_c": abs_temp,
    }
    return _ok(
        "thermal.analyze",
        measurement_id=m["measurement_id"],
        quality_gate="passed",
        rule_result=result,
        summary=f"本地规则判定：{LABELS[level]}。这是风险筛查结果，不是感染确诊。",
        interpretation=interpretation,
        recommendations=recommendations,
        limitations=limitations,
        evidence=[emap[eid] for eid in evidence_ids if eid in emap],
        model_used=False,
        clinician_review_required=True,
        disclaimer=DISCLAIMER,
    )


def evidence_search(query: str = "", scenario: str = "", limit: int = 10) -> dict:
    q = str(query or "").strip().lower()
    sc = str(scenario or "").strip()
    lim = max(1, min(int(limit or 10), 20))
    records = []
    for item in evidence_all():
        if sc and sc not in item.get("scenario", []):
            continue
        haystack = " ".join(
            [
                item.get("title", ""),
                item.get("verified_excerpt", ""),
                item.get("population", ""),
                " ".join(item.get("scenario", [])),
            ]
        ).lower()
        if q and q not in haystack:
            continue
        records.append(item)
    return _ok("evidence.search", count=len(records[:lim]), evidence=records[:lim])


def archive_create_patient(patient_ref: str, display_name: Optional[str] = None) -> dict:
    ref = str(patient_ref or "").strip()
    if not ref:
        return _fail("missing_patient_ref", "请提供伪匿名 patient_ref")
    dname = str(display_name or "").strip() or None
    with connect() as db:
        exists = db.execute("SELECT 1 FROM patients WHERE patient_ref=?", (ref,)).fetchone()
        if not exists:
            db.execute("INSERT INTO patients(patient_ref,display_name,created_at) VALUES(?,?,?)", (ref, dname, now_iso()))
        _audit(db, "archive.create_patient", ref, detail={"already_existed": bool(exists)})
    return _ok("archive.create_patient", patient_ref=ref, created=not bool(exists))


def archive_add_measurement(patient_ref: str, measurement: dict, analysis: dict) -> dict:
    ref = str(patient_ref or "").strip()
    if not ref or not isinstance(measurement, dict) or not isinstance(analysis, dict):
        return _fail("invalid_archive_input", "需含 patient_ref、measurement、analysis")
    if not analysis.get("ok") or analysis.get("quality_gate") != "passed":
        return _fail("analysis_not_validated", "只有通过质量门禁的分析结果才能归档")
    with connect() as db:
        if not db.execute("SELECT 1 FROM patients WHERE patient_ref=?", (ref,)).fetchone():
            return _fail("patient_not_found", "请先建档", ref)
        mid = measurement["measurement_id"]
        if db.execute("SELECT 1 FROM measurements WHERE measurement_id=?", (mid,)).fetchone():
            return _fail("measurement_exists", "测量编号已存在；记录只追加，不覆盖", mid)
        encounter_id = measurement.get("encounter_id") or f"ENC-{mid}"
        captured_at = measurement.get("captured_at") or now_iso()
        db.execute(
            "INSERT OR IGNORE INTO encounters VALUES(?,?,?,?,?)",
            (
                encounter_id,
                ref,
                captured_at,
                json.dumps(measurement.get("device") or {}, ensure_ascii=False),
                json.dumps(measurement.get("quality") or {}, ensure_ascii=False),
            ),
        )
        db.execute(
            "INSERT INTO measurements VALUES(?,?,?,?,?,?,?,?)",
            (
                mid,
                encounter_id,
                ref,
                captured_at,
                json.dumps(measurement.get("metrics") or {}, ensure_ascii=False),
                json.dumps(analysis.get("rule_result") or {}, ensure_ascii=False),
                json.dumps(analysis, ensure_ascii=False),
                now_iso(),
            ),
        )
        _audit(db, "archive.add_measurement", mid, detail={"patient_ref": ref})
    return _ok("archive.add_measurement", patient_ref=ref, measurement_id=mid)


def archive_list() -> dict:
    with connect() as db:
        rows = db.execute(
            """SELECT p.patient_ref,p.display_name,p.created_at,
               COUNT(m.measurement_id) AS measurement_count
               FROM patients p LEFT JOIN measurements m ON p.patient_ref=m.patient_ref
               GROUP BY p.patient_ref,p.display_name,p.created_at ORDER BY p.created_at DESC"""
        ).fetchall()
    return _ok("archive.list", patients=[dict(r) for r in rows])


def archive_history(patient_ref: str, limit: int = 20) -> dict:
    ref = str(patient_ref or "").strip()
    lim = max(1, min(int(limit or 20), 100))
    with connect() as db:
        rows = db.execute(
            "SELECT measurement_id,captured_at,metrics_json,rule_json,created_at FROM measurements WHERE patient_ref=? ORDER BY captured_at DESC LIMIT ?",
            (ref, lim),
        ).fetchall()
    items = [
        {
            "measurement_id": r["measurement_id"],
            "captured_at": r["captured_at"],
            "metrics": json.loads(r["metrics_json"]),
            "rule_result": json.loads(r["rule_json"]),
            "archived_at": r["created_at"],
        }
        for r in rows
    ]
    return _ok("archive.history", patient_ref=ref, count=len(items), measurements=items)


def _render_report_html(patient_ref: str, display_name: str, m: dict, analysis: dict, details: dict, report_id: str) -> str:
    rule = analysis["rule_result"]
    metrics = m.get("metrics") or {}
    esc = html.escape
    metric_rows = "".join(
        f"<tr><th>{esc(str(k))}</th><td>{esc(str(v))}</td></tr>"
        for k, v in metrics.items()
        if v is not None
    )
    detail_rows = "".join(
        f"<tr><th>{esc(DETAIL_FIELDS[k])}</th><td>{esc(str(v))}</td></tr>"
        for k, v in (details or {}).items()
        if k in DETAIL_FIELDS and v
    )
    detail_section = f"<h2>临床补充信息</h2><table>{detail_rows}</table>" if detail_rows else ""
    img_block = ""
    frame_img = m.get("frame_image") or {}
    if frame_img.get("base64"):
        mime = esc(str(frame_img.get("mime") or "image/jpeg"))
        b64 = esc(str(frame_img["base64"]))
        img_block = f"<h2>采集热像快照</h2><p><img src='data:{mime};base64,{b64}' style='max-width:460px;border-radius:10px;border:1px solid #dce5e8' alt='热像快照'/></p>"
    reasons = "".join(
        f"<li>{esc(x['text'])} <small>{esc(','.join(x.get('evidence_ids', [])))}</small></li>"
        for x in analysis.get("interpretation") or []
    )
    recommendations = "".join(
        f"<li>{esc(x['text'])} <small>{esc(','.join(x.get('evidence_ids', [])))}</small></li>"
        for x in analysis.get("recommendations") or []
    )
    refs = "".join(
        f"<li>{esc(e['evidence_id'])} · {esc(e['title'])} ({e['year']})<br><a href='{esc(e['source_url'])}' target='_blank' rel='noreferrer'>{esc(e['source_url'])}</a></li>"
        for e in analysis.get("evidence") or []
    )
    lims = "".join(f"<li>{esc(x)}</li>" for x in analysis.get("limitations") or [])
    return (
        f"<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        f"<title>创口筛查报告 {esc(report_id)}</title>"
        "<style>body{font-family:'Microsoft YaHei',sans-serif;background:#f3f6f8;color:#18313b;margin:0;padding:32px}"
        "main{max-width:860px;margin:auto;background:#fff;padding:32px;border-radius:16px;box-shadow:0 6px 24px rgba(15,23,42,.08)}"
        "h1{font-size:24px;margin-top:0}h2{font-size:16px;margin-top:24px;border-left:4px solid #0f766e;padding-left:10px}"
        ".badge{padding:12px 16px;background:#fff7ed;border-left:4px solid #ea580c;border-radius:8px}"
        "table{width:100%;border-collapse:collapse}th,td{padding:8px;border:1px solid #dce5e8;text-align:left}"
        "th{width:42%;background:#f5f8f9}li{margin:8px 0;line-height:1.6}small{color:#64748b}"
        ".note{background:#f0fdfa;padding:14px;border-radius:8px;font-size:13px;margin-top:20px}</style></head><body><main>"
        f"<h1>创口温度异常辅助筛查报告</h1>"
        f"<p>报告 {esc(report_id)} · 档案 {esc(display_name)} ({esc(patient_ref)}) · 状态：草稿</p>"
        f"<div class='badge'><b>{esc(rule['label'])}</b><br>ΔT {rule['delta_t_c']:+.2f}°C · 规则 {esc(rule['threshold_version'])}</div>"
        f"{img_block}{detail_section}"
        f"<h2>测量指标</h2><table>{metric_rows}</table>"
        f"<h2>判定解释</h2><ul>{reasons}</ul>"
        f"<h2>建议</h2><ul>{recommendations}</ul>"
        f"<h2>证据来源</h2><ul>{refs}</ul>"
        f"<h2>局限性</h2><ul>{lims}</ul>"
        f"<p class='note'>{esc(DISCLAIMER)} 本报告未经医护复核，仅作草稿。</p></main></body></html>"
    )


def report_create_draft(patient_ref: str, display_name: str, m: dict, analysis: dict, details: Optional[dict] = None) -> dict:
    ref = str(patient_ref or "").strip()
    if not ref or not isinstance(m, dict) or not isinstance(analysis, dict):
        return _fail("invalid_report_input", "需含 patient_ref、measurement、analysis")
    if not analysis.get("ok") or analysis.get("quality_gate") != "passed":
        return _fail("analysis_not_validated", "未通过校验的分析不能生成报告")
    reports_dir = get_reports_dir()
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_id = "RPT-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = reports_dir / f"{report_id}.html"
    content = _render_report_html(ref, display_name or ref, m, analysis, details or {}, report_id)
    path.write_text(content, encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    versions = {
        "rules": analysis["rule_result"]["threshold_version"],
        "knowledge": "project-evidence-2026-11-22",
        "model": "local-template-v1",
    }
    with connect() as db:
        db.execute(
            "INSERT INTO reports VALUES(?,?,?,?,?,?,?,?,?)",
            (
                report_id,
                ref,
                m["measurement_id"],
                "draft",
                str(path),
                digest,
                json.dumps(versions, ensure_ascii=False),
                now_iso(),
                None,
            ),
        )
        _audit(db, "report.create_draft", report_id, detail={"patient_ref": ref, "sha256": digest})
    return _ok("report.create_draft", report_id=report_id, status="draft", path=str(path), sha256=digest)


def report_list(patient_ref: str = "") -> dict:
    ref = str(patient_ref or "").strip()
    with connect() as db:
        if ref:
            rows = db.execute("SELECT * FROM reports WHERE patient_ref=? ORDER BY created_at DESC", (ref,)).fetchall()
        else:
            rows = db.execute("SELECT * FROM reports ORDER BY created_at DESC").fetchall()
    return _ok("report.list", reports=[dict(r) for r in rows])


def read_report_html(report_id: str) -> Optional[bytes]:
    rid = str(report_id or "").strip()
    if not _REPORT_ID_RE.match(rid):
        return None
    reports_dir = get_reports_dir().resolve()
    candidate = (reports_dir / f"{rid}.html").resolve()
    if not candidate.is_relative_to(reports_dir) or not candidate.exists():
        return None
    return candidate.read_bytes()


def _draft_row(row, full: bool = False) -> dict:
    details = json.loads(row["details_json"])
    supplements = json.loads(row["supplements_json"])
    analysis = json.loads(row["analysis_json"])
    measurement = json.loads(row["measurement_json"])
    rule = analysis.get("rule_result") if isinstance(analysis, dict) else None
    blocked = analysis.get("error") if isinstance(analysis, dict) else None
    metrics = measurement.get("metrics") or {}
    item = {
        "draft_id": row["draft_id"],
        "title": row["title"],
        "status": row["status"],
        "patient_ref": row["patient_ref"],
        "patient_name": row["patient_name"] if "patient_name" in row.keys() else None,
        "measurement_id": row["measurement_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "quality_gate": analysis.get("quality_gate") if isinstance(analysis, dict) else None,
        "blocked_message": blocked.get("message") if isinstance(blocked, dict) else None,
        "rule_result": rule,
        "delta_t_c": metrics.get("delta_t_c"),
        "estimated_delta_t_c": metrics.get("estimated_delta_t_c"),
        "details": details,
        "detail_count": len(details),
        "supplement_count": len(supplements),
        "chat_count": len(json.loads(row["chat_json"])),
    }
    if full:
        # 完整详情避免把大块 base64 重复传到列表里，详情接口返回完整对象
        item.update(
            measurement=measurement,
            analysis=analysis,
            supplements=supplements,
            chat=json.loads(row["chat_json"]),
        )
    return item


def draft_create(title: str, measurement: dict, details: Optional[dict] = None) -> dict:
    clean_title = str(title or "").strip()[:60] or f"筛查草稿 {dt.datetime.now().strftime('%m-%d %H:%M')}"
    if not isinstance(measurement, dict) or not measurement.get("measurement_id"):
        return _fail("invalid_draft_input", "草稿需含 measurement 与 measurement_id")
    analysis = thermal_analyze(measurement)
    draft_id = "DRF-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    stamp = now_iso()
    with connect() as db:
        db.execute(
            "INSERT INTO drafts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                draft_id,
                clean_title,
                "draft",
                None,
                measurement["measurement_id"],
                json.dumps(measurement, ensure_ascii=False),
                json.dumps(analysis, ensure_ascii=False),
                json.dumps(clean_details(details), ensure_ascii=False),
                "[]",
                "[]",
                stamp,
                stamp,
            ),
        )
        _audit(
            db,
            "draft.create",
            draft_id,
            detail={
                "title": clean_title,
                "measurement_id": measurement["measurement_id"],
                "quality_gate": analysis.get("quality_gate"),
            },
        )
    return _ok("draft.create", draft=draft_get(draft_id)["draft"])


def draft_list() -> dict:
    with connect() as db:
        rows = db.execute(
            """SELECT d.*, p.display_name AS patient_name FROM drafts d
               LEFT JOIN patients p ON p.patient_ref=d.patient_ref ORDER BY d.updated_at DESC"""
        ).fetchall()
    return _ok("draft.list", drafts=[_draft_row(r, full=False) for r in rows])


def draft_get(draft_id: str) -> dict:
    did = str(draft_id or "").strip()
    with connect() as db:
        row = db.execute(
            """SELECT d.*, p.display_name AS patient_name FROM drafts d
               LEFT JOIN patients p ON p.patient_ref=d.patient_ref WHERE d.draft_id=?""",
            (did,),
        ).fetchone()
    if not row:
        return _fail("draft_not_found", "草稿不存在", did)
    return _ok("draft.get", draft=_draft_row(row, full=True))


def draft_update(payload: dict) -> dict:
    draft_id = str(payload.get("draft_id") or "").strip()
    with connect() as db:
        row = db.execute("SELECT * FROM drafts WHERE draft_id=?", (draft_id,)).fetchone()
        if not row:
            return _fail("draft_not_found", "草稿不存在", draft_id)
        if row["status"] != "draft":
            return _fail("draft_locked", "已归档草稿已锁定，不能再修改")
        title = row["title"]
        if payload.get("title") is not None:
            new_title = str(payload.get("title") or "").strip()[:60]
            title = new_title or title
        details = json.loads(row["details_json"])
        applied: list[str] = []
        cleared: list[str] = []
        incoming = payload.get("details")
        if isinstance(incoming, dict):
            for key in DETAIL_FIELDS:
                if key not in incoming:
                    continue
                text = str(incoming.get(key) or "").strip()
                if text:
                    details[key] = text[:120]
                    applied.append(key)
                elif key in details:
                    details.pop(key)
                    cleared.append(key)
        supplements = json.loads(row["supplements_json"])
        added = 0
        for item in payload.get("supplements") or []:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()[:300]
            if not text:
                continue
            supplements.append(
                {
                    "at": now_iso(),
                    "text": text,
                    "source": str(item.get("source") or "form")[:20],
                    "fields": [k for k in (item.get("fields") or []) if k in DETAIL_FIELDS],
                }
            )
            added += 1
        supplements = supplements[-50:]
        chat = clean_chat(payload.get("chat"))
        db.execute(
            "UPDATE drafts SET title=?,details_json=?,supplements_json=?,chat_json=?,updated_at=? WHERE draft_id=?",
            (
                title,
                json.dumps(details, ensure_ascii=False),
                json.dumps(supplements, ensure_ascii=False),
                json.dumps(chat if chat is not None else json.loads(row["chat_json"]), ensure_ascii=False),
                now_iso(),
                draft_id,
            ),
        )
        _audit(
            db,
            "draft.update",
            draft_id,
            detail={"applied": applied, "cleared": cleared, "supplements_added": added},
        )
    return _ok(
        "draft.update",
        draft=draft_get(draft_id)["draft"],
        applied_fields=applied,
        cleared_fields=cleared,
        supplements_added=added,
    )


def _next_patient_number(db: sqlite3.Connection) -> tuple[str, str]:
    nums = []
    for row in db.execute("SELECT patient_ref FROM patients WHERE patient_ref LIKE 'PT-%'").fetchall():
        try:
            nums.append(int(row["patient_ref"][3:]))
        except ValueError:
            continue
    n = (max(nums) if nums else 0) + 1
    return f"PT-{n:04d}", f"患者{n:02d}"


def draft_archive(draft_id: str) -> dict:
    did = str(draft_id or "").strip()
    with connect() as db:
        row = db.execute("SELECT * FROM drafts WHERE draft_id=?", (did,)).fetchone()
        if not row:
            return _fail("draft_not_found", "草稿不存在", did)
        if row["status"] != "draft":
            return _fail("draft_locked", "该草稿已归档，不能重复写入")
        analysis = json.loads(row["analysis_json"])
        if not analysis.get("ok") or analysis.get("quality_gate") != "passed":
            return _fail(
                "analysis_not_validated",
                "质量门禁未通过的草稿不能存入患者档案；请获取真实温度矩阵并重采",
                (analysis.get("error") or {}).get("message", ""),
            )
        m = dict(json.loads(row["measurement_json"]))
        details = json.loads(row["details_json"])
        mid = m["measurement_id"]
        if db.execute("SELECT 1 FROM measurements WHERE measurement_id=?", (mid,)).fetchone():
            return _fail("measurement_exists", "该测量已写入其他档案；记录只追加，不覆盖", mid)
        ref, display = _next_patient_number(db)

    m["patient_ref"] = ref
    patient = archive_create_patient(ref, display)
    if not patient.get("ok"):
        return patient
    added = archive_add_measurement(ref, m, analysis)
    if not added.get("ok"):
        with connect() as db:
            _audit(db, "draft.archive", did, result="failed", detail={"stage": "add_measurement", "error": added.get("error")})
        return added
    report = report_create_draft(ref, display, m, analysis, details=details)
    with connect() as db:
        db.execute(
            "UPDATE drafts SET status='archived',patient_ref=?,updated_at=? WHERE draft_id=?",
            (ref, now_iso(), did),
        )
        _audit(
            db,
            "draft.archive",
            did,
            detail={
                "patient_ref": ref,
                "display_name": display,
                "measurement_id": mid,
                "report_id": report.get("report_id"),
                "report_ok": bool(report.get("ok")),
            },
        )
    return _ok(
        "draft.archive",
        draft=draft_get(did)["draft"],
        patient_ref=ref,
        display_name=display,
        measurement_id=mid,
        report_id=report.get("report_id"),
        report_status=report.get("status"),
    )


def clinic_summary() -> dict:
    return _ok(
        "clinic.summary",
        drafts=draft_list()["drafts"],
        patients=archive_list()["patients"],
        reports=report_list()["reports"],
        evidence=evidence_all(),
        rules=rules_summary(),
        detail_fields=DETAIL_FIELDS,
        disclaimer=DISCLAIMER,
    )
