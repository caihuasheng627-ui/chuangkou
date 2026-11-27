# -*- coding: utf-8 -*-
"""DSH wound-clinic local worker.

All clinical thresholds and archive writes stay local. The DSH model receives only
structured tool receipts; it never supplies the measurements or overrides rules.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import html
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
DB_PATH = Path(os.environ.get("WOUND_CLINIC_DB", DATA / "wound_archive.db"))
EVIDENCE_PATH = RUNTIME / "evidence.json"

LABELS = {
    "normal": "未见明显热异常",
    "suspicious": "可疑炎症（建议复测）",
    "high": "显著热异常（感染风险增高）",
    "cold": "局部低温（警惕灌注不足）",
}
DISCLAIMER = "本结果仅用于创口感染风险辅助筛查，不替代医护人员结合创面、实验室及病原学结果作出的临床诊断。"

# 草稿可补充的结构化详情：只接受这些键，值均为短文本，不接收身份标识。
DETAIL_FIELDS = {
    "site": "创口部位",
    "duration": "病程/持续时间",
    "symptoms": "创面表现",
    "treatment": "处理与用药史",
    "notes": "其他备注",
}


def clean_details(raw):
    """只保留白名单字段与短文本。"""
    out = {}
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


def clean_chat(items):
    """对话记录只保留 role/text，截断到 40 条。"""
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


def now_iso():
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evidence_all():
    return load_json(EVIDENCE_PATH)


def evidence_map():
    return {item["evidence_id"]: item for item in evidence_all()}


def ok(action, **fields):
    return {"ok": True, "action": action, **fields}


def fail(code, message, hint=""):
    return {"ok": False, "error": {"code": code, "message": message, "hint": hint}}


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@contextlib.contextmanager
def connect():
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        db.executescript("""
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
        """)
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def audit(db, action, object_ref, result="success", detail=None):
    db.execute(
        "INSERT INTO audit_events(at,actor,action,object_ref,result,detail_json) VALUES(?,?,?,?,?,?)",
        (now_iso(), "dsh-local-user", action, object_ref, result,
         json.dumps(detail or {}, ensure_ascii=False)),
    )


def quality_gate(m):
    if not isinstance(m, dict):
        return ["测量输入必须是 JSON 对象"]
    problems = []
    calibration = (m.get("device") or {}).get("calibration") or {}
    if calibration.get("status") != "valid":
        problems.append("标定无效或缺失")
    q = m.get("quality") or {}
    if not finite_number(q.get("frames_used")) or q.get("frames_used") < 5:
        problems.append("有效帧数不足")
    if q.get("roi_valid") is not True:
        problems.append("创口 ROI 无效")
    if q.get("reference_valid") is not True:
        problems.append("参考皮肤区无效")
    if q.get("temperature_in_range") is not True:
        problems.append("温度超出设备有效量程或存在饱和")
    metrics = m.get("metrics") or {}
    for key in ("t_wound_mean_c", "t_ref_far_c", "delta_t_c"):
        if not finite_number(metrics.get(key)):
            problems.append(f"缺少有效指标 {key}")
    if not problems:
        computed = metrics["t_wound_mean_c"] - metrics["t_ref_far_c"]
        if abs(computed - metrics["delta_t_c"]) > 0.15:
            problems.append("ΔT 与创口/参考区温度不一致")
    if not m.get("measurement_id"):
        problems.append("缺少 measurement_id")
    return problems


def thermal_analyze(m):
    problems = quality_gate(m)
    if problems:
        return fail("quality_gate_blocked", "；".join(problems),
                    "重新标定或采集；质量门禁未通过时不得生成感染风险解释。")

    metrics = m["metrics"]
    delta = float(metrics["delta_t_c"])
    th = m.get("thresholds") or {}
    normal_max = float(th.get("normal_max_c", 0.6))
    warn_max = float(th.get("warning_max_c", 2.2))
    infect_min = float(th.get("infection_min_c", 2.55))

    reason_codes = []
    interpretation = []
    if delta < -normal_max:
        level = "cold"
        reason_codes.append("DELTA_BELOW_REFERENCE")
        interpretation.append({"text": f"创口区较参考皮肤低 {-delta:.2f}°C，需考虑局部灌注不足，不能按感染升温逻辑解释。", "evidence_ids": []})
    elif delta < normal_max:
        level = "normal"
        reason_codes.append("DELTA_WITHIN_NORMAL")
        interpretation.append({"text": f"ΔT={delta:+.2f}°C，未达到本规则的热异常提示区间。", "evidence_ids": ["E004"]})
    elif delta < warn_max:
        level = "suspicious"
        reason_codes.append("DELTA_SUSPICIOUS")
        interpretation.append({"text": f"ΔT={delta:+.2f}°C，提示轻度热异常；单次测量不能确认感染，应复测并结合创面表现。", "evidence_ids": ["E004"]})
    else:
        level = "high"
        reason_codes.append("DELTA_ABOVE_WARNING")
        if delta >= infect_min:
            reason_codes.append("DELTA_ABOVE_2_55")
            interpretation.append({"text": f"ΔT={delta:+.2f}°C，达到研究中的创周热不对称参考值；该结果提示感染风险增高，但不是病原学诊断。", "evidence_ids": ["E002"]})
        else:
            interpretation.append({"text": f"ΔT={delta:+.2f}°C，已超过预警参考值，需复测并尽快进行临床评估；2.2°C 的研究场景不是所有创口的通用确诊界值。", "evidence_ids": ["E003", "E004"]})

    near = metrics.get("t_ref_near_c")
    if finite_number(near) and near - metrics["t_ref_far_c"] > 0.4:
        reason_codes.append("PERIWOUND_INVOLVED")
        interpretation.append({"text": "近端创周温度高于远端参考皮肤，说明热异常可能已波及创周；参考区选择会影响 ΔT。", "evidence_ids": ["E002"]})

    abs_temp = metrics["t_wound_mean_c"]
    limitations = [
        "单次红外测温存在假阳性，重复测量和趋势确认比单次读数更可靠。",
        "当前证据的人群、创口类型和测量条件并不完全一致，阈值不能直接外推为通用诊断标准。",
    ]
    if m.get("device", {}).get("capture_mode") == "pseudo":
        limitations.append("当前为伪彩反演温度，精度受限，应优先使用原始温度帧。")
    if m.get("quality", {}).get("warnings"):
        limitations.extend(m["quality"]["warnings"])

    recommendations = [
        {"text": "在相同环境、距离和参考区条件下复测，并比较连续趋势。", "evidence_ids": ["E004"], "priority": "routine"},
    ]
    if level in ("high", "cold"):
        recommendations.append({"text": "建议由医护人员结合创面外观、灌注情况及必要的实验室/病原学检查评估。", "evidence_ids": ["E002"], "priority": "clinical_review"})
    else:
        recommendations.append({"text": "继续常规观察；若出现红肿扩大、渗液增多、疼痛加重或全身不适，应及时就医。", "evidence_ids": ["E004"], "priority": "routine"})

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
    return ok(
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


def evidence_search(payload):
    query = str(payload.get("query") or "").strip().lower()
    scenario = str(payload.get("scenario") or "").strip()
    limit = max(1, min(int(payload.get("limit") or 4), 10))
    records = []
    for item in evidence_all():
        if scenario and scenario not in item.get("scenario", []):
            continue
        haystack = " ".join([
            item.get("title", ""), item.get("verified_excerpt", ""),
            item.get("population", ""), " ".join(item.get("scenario", [])),
        ]).lower()
        if query and query not in haystack:
            continue
        records.append(item)
    return ok("evidence.search", count=len(records[:limit]), evidence=records[:limit],
              constraint="只能引用返回的 evidence_id；适用人群之外需提示外推限制。")


def archive_create_patient(payload):
    ref = str(payload.get("patient_ref") or "").strip()
    if not ref:
        return fail("missing_patient_ref", "请提供伪匿名 patient_ref")
    display_name = str(payload.get("display_name") or "").strip() or None
    with connect() as db:
        exists = db.execute("SELECT 1 FROM patients WHERE patient_ref=?", (ref,)).fetchone()
        if not exists:
            db.execute("INSERT INTO patients(patient_ref,display_name,created_at) VALUES(?,?,?)",
                       (ref, display_name, now_iso()))
        audit(db, "archive.create_patient", ref, detail={"already_existed": bool(exists)})
    return ok("archive.create_patient", patient_ref=ref, created=not bool(exists))


def archive_add_measurement(payload):
    ref = str(payload.get("patient_ref") or "").strip()
    m = payload.get("measurement")
    analysis = payload.get("analysis")
    if not ref or not isinstance(m, dict) or not isinstance(analysis, dict):
        return fail("invalid_archive_input", "需含 patient_ref、measurement、analysis")
    if not analysis.get("ok") or analysis.get("quality_gate") != "passed":
        return fail("analysis_not_validated", "只有通过质量门禁的分析结果才能归档")
    with connect() as db:
        if not db.execute("SELECT 1 FROM patients WHERE patient_ref=?", (ref,)).fetchone():
            return fail("patient_not_found", "请先 create_patient", ref)
        mid = m["measurement_id"]
        if db.execute("SELECT 1 FROM measurements WHERE measurement_id=?", (mid,)).fetchone():
            return fail("measurement_exists", "测量编号已存在；记录只追加，不覆盖", mid)
        encounter_id = m.get("encounter_id") or f"ENC-{mid}"
        db.execute("INSERT OR IGNORE INTO encounters VALUES(?,?,?,?,?)",
                   (encounter_id, ref, m.get("captured_at"),
                    json.dumps(m.get("device") or {}, ensure_ascii=False),
                    json.dumps(m.get("quality") or {}, ensure_ascii=False)))
        db.execute("INSERT INTO measurements VALUES(?,?,?,?,?,?,?,?)",
                   (mid, encounter_id, ref, m.get("captured_at"),
                    json.dumps(m.get("metrics") or {}, ensure_ascii=False),
                    json.dumps(analysis.get("rule_result") or {}, ensure_ascii=False),
                    json.dumps(analysis, ensure_ascii=False), now_iso()))
        audit(db, "archive.add_measurement", mid, detail={"patient_ref": ref})
    return ok("archive.add_measurement", patient_ref=ref, measurement_id=mid)


def archive_history(payload):
    ref = str(payload.get("patient_ref") or "").strip()
    limit = max(1, min(int(payload.get("limit") or 20), 100))
    with connect() as db:
        audit(db, "archive.history", ref)
        rows = db.execute(
            "SELECT measurement_id,captured_at,metrics_json,rule_json,created_at FROM measurements WHERE patient_ref=? ORDER BY captured_at DESC LIMIT ?",
            (ref, limit)).fetchall()
    items = [{"measurement_id": r["measurement_id"], "captured_at": r["captured_at"],
              "metrics": json.loads(r["metrics_json"]), "rule_result": json.loads(r["rule_json"]),
              "archived_at": r["created_at"]} for r in rows]
    return ok("archive.history", patient_ref=ref, count=len(items), measurements=items)


def archive_list(_payload):
    with connect() as db:
        audit(db, "archive.list", None)
        rows = db.execute("""SELECT p.patient_ref,p.display_name,p.created_at,
          COUNT(m.measurement_id) AS measurement_count
          FROM patients p LEFT JOIN measurements m ON p.patient_ref=m.patient_ref
          GROUP BY p.patient_ref,p.display_name,p.created_at ORDER BY p.created_at DESC""").fetchall()
    return ok("archive.list", patients=[dict(r) for r in rows])


def report_html(patient_ref, m, analysis, report_id):
    rule = analysis["rule_result"]
    metrics = m["metrics"]
    esc = html.escape
    metric_rows = "".join(f"<tr><th>{esc(k)}</th><td>{esc(str(v))}</td></tr>" for k, v in metrics.items())
    reasons = "".join(f"<li>{esc(x['text'])} <small>{esc(','.join(x.get('evidence_ids', [])))}</small></li>" for x in analysis["interpretation"])
    recommendations = "".join(f"<li>{esc(x['text'])} <small>{esc(','.join(x.get('evidence_ids', [])))}</small></li>" for x in analysis["recommendations"])
    refs = "".join(f"<li>{esc(e['evidence_id'])} · {esc(e['title'])} ({e['year']})<br><a href='{esc(e['source_url'])}'>{esc(e['source_url'])}</a></li>" for e in analysis.get("evidence", []))
    return f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>创口筛查报告 {esc(report_id)}</title>
<style>body{{font-family:'Microsoft YaHei',sans-serif;background:#f3f6f8;color:#18313b;margin:0;padding:32px}}main{{max-width:860px;margin:auto;background:white;padding:32px;border-radius:16px}}h1{{font-size:24px}}h2{{font-size:16px;margin-top:26px;border-left:4px solid #0f766e;padding-left:10px}}.badge{{padding:12px 16px;background:#fff7ed;border-left:4px solid #ea580c;border-radius:8px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:8px;border:1px solid #dce5e8;text-align:left}}th{{width:46%;background:#f5f8f9}}li{{margin:8px 0;line-height:1.6}}small{{color:#64748b}}.note{{background:#f0fdfa;padding:14px;border-radius:8px;font-size:13px}}</style></head><body><main>
<h1>创口温度异常辅助筛查报告</h1><p>报告 {esc(report_id)} · 档案 {esc(patient_ref)} · 状态：草稿</p>
<div class='badge'><b>{esc(rule['label'])}</b><br>ΔT {rule['delta_t_c']:+.2f}°C · 规则 {esc(rule['threshold_version'])}</div>
<h2>测量指标</h2><table>{metric_rows}</table><h2>判定解释</h2><ul>{reasons}</ul>
<h2>建议</h2><ul>{recommendations}</ul><h2>证据来源</h2><ul>{refs}</ul>
<h2>局限性</h2><ul>{''.join('<li>'+esc(x)+'</li>' for x in analysis['limitations'])}</ul>
<p class='note'>{esc(DISCLAIMER)} 本报告未经医护复核，仅作草稿。</p></main></body></html>"""


def report_create_draft(payload):
    ref = str(payload.get("patient_ref") or "").strip()
    m = payload.get("measurement")
    analysis = payload.get("analysis")
    if not ref or not isinstance(m, dict) or not isinstance(analysis, dict):
        return fail("invalid_report_input", "需含 patient_ref、measurement、analysis")
    if not analysis.get("ok") or analysis.get("quality_gate") != "passed":
        return fail("analysis_not_validated", "未通过校验的分析不能生成报告")
    REPORTS.mkdir(parents=True, exist_ok=True)
    report_id = "RPT-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = REPORTS / f"{report_id}.html"
    content = report_html(ref, m, analysis, report_id)
    path.write_text(content, encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    versions = {"rules": analysis["rule_result"]["threshold_version"],
                "knowledge": "project-evidence-2026-11-22", "model": "local-template-v1"}
    with connect() as db:
        db.execute("INSERT INTO reports VALUES(?,?,?,?,?,?,?,?,?)",
                   (report_id, ref, m["measurement_id"], "draft", str(path), digest,
                    json.dumps(versions, ensure_ascii=False), now_iso(), None))
        audit(db, "report.create_draft", report_id, detail={"patient_ref": ref, "sha256": digest})
    return ok("report.create_draft", report_id=report_id, status="draft", path=str(path), sha256=digest)


def report_list(payload):
    ref = str(payload.get("patient_ref") or "").strip()
    with connect() as db:
        audit(db, "report.list", ref or None)
        if ref:
            rows = db.execute("SELECT * FROM reports WHERE patient_ref=? ORDER BY created_at DESC", (ref,)).fetchall()
        else:
            rows = db.execute("SELECT * FROM reports ORDER BY created_at DESC").fetchall()
    return ok("report.list", reports=[dict(r) for r in rows])


# ------------------------------------------------------------------ 草稿工作流

def _draft_row(row, full=False):
    details = json.loads(row["details_json"])
    supplements = json.loads(row["supplements_json"])
    analysis = json.loads(row["analysis_json"])
    measurement = json.loads(row["measurement_json"])
    rule = analysis.get("rule_result") if isinstance(analysis, dict) else None
    blocked = analysis.get("error") if isinstance(analysis, dict) else None
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
        "delta_t_c": (measurement.get("metrics") or {}).get("delta_t_c"),
        "detail_count": len(details),
        "supplement_count": len(supplements),
        "chat_count": len(json.loads(row["chat_json"])),
    }
    if full:
        item.update(measurement=measurement, analysis=analysis, details=details,
                    supplements=supplements, chat=json.loads(row["chat_json"]))
    return item


def draft_create(payload):
    """实时筛查保存草稿：本地规则引擎先算等级并一起落库；门禁未通过也允许存草稿，但归档前必须重采。"""
    title = str(payload.get("title") or "").strip()[:60] or "未命名草稿"
    m = payload.get("measurement")
    if not isinstance(m, dict) or not m.get("measurement_id"):
        return fail("invalid_draft_input", "草稿需含 measurement 与 measurement_id")
    analysis = thermal_analyze(m)
    draft_id = "DRF-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    stamp = now_iso()
    with connect() as db:
        db.execute("INSERT INTO drafts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (draft_id, title, "draft", None, m["measurement_id"],
                    json.dumps(m, ensure_ascii=False), json.dumps(analysis, ensure_ascii=False),
                    json.dumps(clean_details(payload.get("details")), ensure_ascii=False),
                    "[]", "[]", stamp, stamp))
        audit(db, "draft.create", draft_id,
              detail={"title": title, "measurement_id": m["measurement_id"],
                      "quality_gate": analysis.get("quality_gate")})
    return ok("draft.create", draft=draft_get({"draft_id": draft_id})["draft"])


def draft_list(_payload):
    with connect() as db:
        rows = db.execute("""SELECT d.*, p.display_name AS patient_name FROM drafts d
          LEFT JOIN patients p ON p.patient_ref=d.patient_ref ORDER BY d.updated_at DESC""").fetchall()
    return ok("draft.list", drafts=[_draft_row(r) for r in rows])


def draft_get(payload):
    draft_id = str(payload.get("draft_id") or "").strip()
    with connect() as db:
        row = db.execute("""SELECT d.*, p.display_name AS patient_name FROM drafts d
          LEFT JOIN patients p ON p.patient_ref=d.patient_ref WHERE d.draft_id=?""", (draft_id,)).fetchone()
    if not row:
        return fail("draft_not_found", "草稿不存在", draft_id)
    return ok("draft.get", draft=_draft_row(row, full=True))


def draft_update(payload):
    """合并详情字段（传空字符串表示清除）、追加补充记录、同步对话记录。已归档草稿锁定。"""
    draft_id = str(payload.get("draft_id") or "").strip()
    with connect() as db:
        row = db.execute("SELECT * FROM drafts WHERE draft_id=?", (draft_id,)).fetchone()
        if not row:
            return fail("draft_not_found", "草稿不存在", draft_id)
        if row["status"] != "draft":
            return fail("draft_locked", "已归档草稿不能再修改")
        title = row["title"]
        if payload.get("title") is not None:
            new_title = str(payload.get("title") or "").strip()[:60]
            title = new_title or title
        details = json.loads(row["details_json"])
        applied, cleared = [], []
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
            supplements.append({"at": now_iso(), "text": text,
                                "source": str(item.get("source") or "chat")[:20],
                                "fields": [k for k in (item.get("fields") or []) if k in DETAIL_FIELDS]})
            added += 1
        supplements = supplements[-50:]
        chat = clean_chat(payload.get("chat"))
        db.execute("UPDATE drafts SET title=?,details_json=?,supplements_json=?,chat_json=?,updated_at=? WHERE draft_id=?",
                   (title, json.dumps(details, ensure_ascii=False), json.dumps(supplements, ensure_ascii=False),
                    json.dumps(chat if chat is not None else json.loads(row["chat_json"]), ensure_ascii=False),
                    now_iso(), draft_id))
        audit(db, "draft.update", draft_id,
              detail={"applied": applied, "cleared": cleared, "supplements_added": added})
    return ok("draft.update", draft=draft_get({"draft_id": draft_id})["draft"],
              applied_fields=applied, cleared_fields=cleared, supplements_added=added)


def next_patient_number(db):
    """患者编号按现有 PT-xxxx 最大值递增，首个为 PT-0001 / 患者01。"""
    nums = []
    for row in db.execute("SELECT patient_ref FROM patients WHERE patient_ref LIKE 'PT-%'").fetchall():
        try:
            nums.append(int(row["patient_ref"][3:]))
        except ValueError:
            continue
    n = (max(nums) if nums else 0) + 1
    return f"PT-{n:04d}", f"患者{n:02d}"


def draft_archive(payload):
    """草稿存入患者档案：自动编号 → 建档 → 追加测量 → 生成可追溯报告 → 锁定草稿。"""
    draft_id = str(payload.get("draft_id") or "").strip()
    with connect() as db:
        row = db.execute("SELECT * FROM drafts WHERE draft_id=?", (draft_id,)).fetchone()
        if not row:
            return fail("draft_not_found", "草稿不存在", draft_id)
        if row["status"] != "draft":
            return fail("draft_locked", "该草稿已归档，不能重复写入")
        analysis = json.loads(row["analysis_json"])
        if not analysis.get("ok") or analysis.get("quality_gate") != "passed":
            return fail("analysis_not_validated", "质量门禁未通过的草稿不能存入患者档案；请重新采集并另存草稿",
                        analysis.get("error", {}).get("message", ""))
        m = dict(json.loads(row["measurement_json"]))
        mid = m["measurement_id"]
        if db.execute("SELECT 1 FROM measurements WHERE measurement_id=?", (mid,)).fetchone():
            return fail("measurement_exists", "该测量已写入其他档案；记录只追加，不覆盖", mid)
        ref, display = next_patient_number(db)
    m["patient_ref"] = ref
    patient = archive_create_patient({"patient_ref": ref, "display_name": display})
    if not patient.get("ok"):
        return patient
    added = archive_add_measurement({"patient_ref": ref, "measurement": m, "analysis": analysis})
    if not added.get("ok"):
        audit_only = connect()
        with audit_only as db:
            audit(db, "draft.archive", draft_id, result="failed", detail={"stage": "add_measurement", "error": added.get("error")})
        return added
    report = report_create_draft({"patient_ref": ref, "measurement": m, "analysis": analysis})
    with connect() as db:
        db.execute("UPDATE drafts SET status='archived',patient_ref=?,updated_at=? WHERE draft_id=?",
                   (ref, now_iso(), draft_id))
        audit(db, "draft.archive", draft_id,
              detail={"patient_ref": ref, "display_name": display, "measurement_id": mid,
                      "report_id": report.get("report_id"), "report_ok": bool(report.get("ok"))})
    return ok("draft.archive", draft=draft_get({"draft_id": draft_id})["draft"],
              patient_ref=ref, display_name=display, measurement_id=mid,
              report_id=report.get("report_id"), report_status=report.get("status"))


def device_probe(payload):
    cameras = str(payload.get("cameras") or "0,1").replace(",", " ").split()
    cameras = [x for x in cameras if x.isdigit()] or ["0", "1"]
    frames = max(3, min(int(payload.get("frames") or 8), 30))
    out = DATA / "probe_output"
    cmd = [sys.executable, str(RUNTIME / "probe_camera.py"), "--cameras", *cameras,
           "--frames", str(frames), "--out", str(out)]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=110)
    result_file = out / "probe_result.json"
    if not result_file.exists():
        return fail("probe_failed", proc.stderr.strip() or proc.stdout.strip() or "未生成探测结果")
    return ok("device.probe", results=load_json(result_file), result_path=str(result_file),
              note="uint8 不是原始温度；标定有效前禁止生成风险结论。")


def route(action, payload):
    if action == "thermal.analyze": return thermal_analyze(payload)
    if action == "evidence.search": return evidence_search(payload)
    if action == "archive.create_patient": return archive_create_patient(payload)
    if action == "archive.add_measurement": return archive_add_measurement(payload)
    if action == "archive.history": return archive_history(payload)
    if action == "archive.list": return archive_list(payload)
    if action == "report.create_draft": return report_create_draft(payload)
    if action == "report.list": return report_list(payload)
    if action == "draft.create": return draft_create(payload)
    if action == "draft.list": return draft_list(payload)
    if action == "draft.get": return draft_get(payload)
    if action == "draft.update": return draft_update(payload)
    if action == "draft.archive": return draft_archive(payload)
    if action == "device.probe": return device_probe(payload)
    return fail("unknown_action", f"不支持的操作：{action}")


def main():
    try:
        action = sys.argv[1]
        payload = json.load(sys.stdin)
        result = route(action, payload)
    except Exception as exc:
        result = fail("worker_exception", str(exc), "检查输入结构；不要补造缺失的医学数据。")
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
