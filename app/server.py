"""本机页面：实时画面、两个框、三级判定、稳态采集与点温查询。"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import app.clinic as clinic_mod
import app.engine as eng_mod
from app.engine import Engine, list_cameras
from app.foreground import available_models
from app.probe_camera import probe_devices, probe_ffmpeg_dshow_options


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
ENGINE = Engine()
MAX_BODY_BYTES = 1_048_576
FAVICON_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    b'<rect width="32" height="32" rx="7" fill="#13171e"/>'
    b'<circle cx="16" cy="16" r="9" fill="none" stroke="#ffb020" stroke-width="2.2"/>'
    b'<circle cx="16" cy="16" r="3.5" fill="#ff6347"/>'
    b'<path d="M16 3v5M16 24v5M3 16h5M24 16h5" stroke="#6bc2ff" stroke-width="2" stroke-linecap="round"/>'
    b"</svg>"
)


class _PayloadTooLarge(ValueError):
    pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        if args and str(args[1]).startswith("2"):
            return
        super().log_message(fmt, *args)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            self._file(STATIC / "index.html", "text/html; charset=utf-8")
        elif path == "/static/app.css":
            self._file(STATIC / "app.css", "text/css; charset=utf-8")
        elif path == "/static/app.js":
            self._file(STATIC / "app.js", "text/javascript; charset=utf-8")
        elif path == "/favicon.ico":
            self._bytes(FAVICON_SVG, "image/svg+xml", cache="public, max-age=3600")
        elif path == "/api/devices":
            self._json({"devices": list_cameras(), "models": available_models()})
        elif path == "/api/probe":
            self._probe()
        elif path == "/api/state":
            self._json(ENGINE.state())
        elif path == "/api/records":
            self._json(ENGINE.list_records())
        elif path == "/api/records.csv":
            self._csv_export()
        elif path == "/api/clinic/summary":
            self._json(clinic_mod.clinic_summary())
        elif path == "/api/clinic/draft":
            qs = parse_qs(parsed.query)
            draft_id = qs.get("draft_id", [""])[0]
            self._json(clinic_mod.draft_get(draft_id))
        elif path == "/api/clinic/evidence":
            qs = parse_qs(parsed.query)
            self._json(clinic_mod.evidence_search(qs.get("q", [""])[0], qs.get("scenario", [""])[0]))
        elif path.startswith("/api/clinic/report/"):
            report_id = path.split("/api/clinic/report/", 1)[1].strip("/")
            content = clinic_mod.read_report_html(report_id)
            if content is None:
                self.send_error(404)
            else:
                self._bytes(content, "text/html; charset=utf-8", cache="no-store")
        elif path == "/api/point":
            qs = parse_qs(parsed.query)
            try:
                x = float(qs.get("x", ["0.5"])[0])
                y = float(qs.get("y", ["0.5"])[0])
            except ValueError:
                self._json({"ok": False, "error": "坐标无效"}, 400)
                return
            self._json(ENGINE.point_temp(x, y))
        elif path == "/stream.mjpg":
            self._stream()
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            body = self._body()
        except _PayloadTooLarge as exc:
            self._json({"ok": False, "error": str(exc)}, 413)
            return
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            self._json({"ok": False, "error": str(exc) if isinstance(exc, ValueError) else "请求不是有效 JSON"}, 400)
            return
        if path == "/api/start":
            source = str(body.get("source", ""))
            ENGINE.start(source)
            self._json({"ok": True, "state": ENGINE.state()})
        elif path == "/api/stop":
            ENGINE.stop()
            self._json({"ok": True, "state": ENGINE.state()})
        elif path == "/api/roi":
            try:
                ENGINE.set_rois(body.get("wound"), body.get("ref"), manual=bool(body.get("manual")))
            except (KeyError, TypeError, ValueError):
                self._json({"ok": False, "error": "ROI 参数格式无效"}, 400)
                return
            self._json({"ok": True, "state": ENGINE.state()})
        elif path == "/api/auto":
            ENGINE.set_auto(bool(body.get("enabled", True)))
            self._json({"ok": True, "state": ENGINE.state()})
        elif path == "/api/region":
            try:
                index = int(body.get("index", 0))
            except (TypeError, ValueError):
                self._json({"ok": False, "error": "区域索引无效"}, 400)
                return
            ENGINE.select_region(index)
            self._json({"ok": True, "state": ENGINE.state()})
        elif path == "/api/measure":
            self._json(ENGINE.start_measure())
        elif path == "/api/unlock":
            self._json(ENGINE.unlock_measure())
        elif path == "/api/weight":
            ENGINE.set_weight(str(body.get("model", "u2netp")))
            self._json({"ok": True, "models": available_models(), "state": ENGINE.state()})
        elif path == "/api/view":
            ENGINE.set_view(str(body.get("mode", "original")))
            self._json({"ok": True, "state": ENGINE.state()})
        elif path == "/api/distance":
            try:
                ENGINE.set_distance(float(body.get("mm", 300)))
            except (TypeError, ValueError):
                self._json({"ok": False, "error": "距离数值无效"}, 400)
                return
            self._json({"ok": True, "state": ENGINE.state()})
        elif path == "/api/emissivity":
            try:
                ENGINE.set_emissivity(float(body.get("value", 0.98)))
            except (TypeError, ValueError):
                self._json({"ok": False, "error": "发射率数值无效"}, 400)
                return
            self._json({"ok": True, "state": ENGINE.state()})
        elif path == "/api/save":
            self._json(
                ENGINE.save_record(
                    group=str(body.get("group", "日常初筛")),
                    ntc_delta=body.get("ntc_delta"),
                )
            )
        elif path == "/api/replay":
            self._json(
                ENGINE.load_capture(
                    str(body.get("npy_path", "")),
                    wound_px=str(body.get("wound_px", "")),
                    ref_px=str(body.get("ref_px", "")),
                )
            )
        elif path == "/api/align_pose":
            self._json(ENGINE.align_rois_to_pose())
        elif path == "/api/raw_calib":
            try:
                ENGINE.set_raw_calibration(float(body.get("scale", 0.01)), float(body.get("offset", 0.0)))
            except (TypeError, ValueError):
                self._json({"ok": False, "error": "标定参数无效"}, 400)
                return
            self._json({"ok": True, "state": ENGINE.state()})
        elif path == "/api/clinic/draft/create":
            measurement = body.get("measurement")
            if measurement is None:
                try:
                    measurement = clinic_mod.measurement_from_engine(ENGINE)
                except RuntimeError as exc:
                    self._json({"ok": False, "error": {"code": "no_frame", "message": str(exc)}}, 409)
                    return
            res = clinic_mod.draft_create(str(body.get("title") or ""), measurement, body.get("details"))
            self._json(res)
        elif path == "/api/clinic/draft/update":
            self._json(clinic_mod.draft_update(body))
        elif path == "/api/clinic/draft/archive":
            self._json(clinic_mod.draft_archive(str(body.get("draft_id") or "")))
        else:
            self.send_error(404)

    def _body(self) -> dict:
        raw_len = self.headers.get("Content-Length", "0").strip()
        try:
            length = int(raw_len)
        except ValueError as exc:
            raise ValueError("Content-Length 无效") from exc
        if length < 0:
            raise ValueError("Content-Length 不能为负")
        if length > MAX_BODY_BYTES:
            raise _PayloadTooLarge("请求体超过 1 MB 限制")
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    def _bytes(self, data: bytes, content_type: str, cache: str = "no-cache", extra_headers: dict | None = None) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _probe(self) -> None:
        st = ENGINE.state()
        if st.get("running") and str(st.get("source") or "").startswith("cam:"):
            # 摄像头正在采集中时不抢占句柄，仅查询 DirectShow 格式列表并返回当前后端状态
            devices = list_cameras()
            dshow_options = [
                {
                    "id": dev["id"],
                    "label": dev["label"],
                    "options": probe_ffmpeg_dshow_options(dev.get("dshow") or dev["label"]),
                }
                for dev in devices
                if dev.get("backend") == "dshow"
            ]
            self._json(
                {
                    "ok": True,
                    "busy": True,
                    "devices": devices,
                    "dshow_options": dshow_options,
                    "opencv_probes": [],
                    "has_16bit_candidate": bool(st.get("has_temperature")),
                    "summary": f"当前正在采集（{st.get('capture_backend') or st.get('source_label')}），已返回 DirectShow 编码列表；如需 OpenCV 16bit 位深探测请先点“停止”。",
                }
            )
            return
        self._json(probe_devices(frames=4))

    def _csv_export(self) -> None:
        v2 = eng_mod.RECORD_PATH.with_name("records_v2.csv")
        target = v2 if v2.exists() else eng_mod.RECORD_PATH
        if target.exists():
            data = target.read_bytes()
        else:
            data = ("\ufeff" + ",".join(eng_mod.RECORD_HEADERS) + "\r\n").encode("utf-8")
        self._bytes(
            data,
            "text/csv; charset=utf-8",
            cache="no-store",
            extra_headers={"Content-Disposition": 'attachment; filename="chuangkou_records.csv"'},
        )

    def _file(self, path: Path, content_type: str) -> None:
        self._bytes(path.read_bytes(), content_type, cache="no-cache")

    def _json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        last = -1
        try:
            while True:
                jpeg, seq = ENGINE.wait_jpeg(last, 0.5)
                if seq == last or not jpeg:
                    continue
                last = seq
                header = (
                    b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                    + str(len(jpeg)).encode("ascii")
                    + b"\r\n\r\n"
                )
                self.wfile.write(header)
                self.wfile.write(jpeg)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            return


def main() -> None:
    _configure_stdio()
    devices = list_cameras()
    thermal = next(
        (item["id"] for item in devices if any(k in item["label"].upper() for k in ("UVC", "HIK", "THERMAL"))),
        None,
    )
    if thermal:
        ENGINE.start(thermal)
    port = int(os.environ.get("CHUANGKOU_PORT", "8765"))
    server = _Server(("127.0.0.1", port), Handler)
    print(f"创口温差初筛  http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        ENGINE.stop()
        server.shutdown()


if __name__ == "__main__":
    main()
