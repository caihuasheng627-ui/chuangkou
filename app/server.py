"""本机页面：实时画面、两个框、三级判定、稳态采集与点温查询。"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.engine import Engine, list_cameras
from app.foreground import available_models

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
ENGINE = Engine()


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
        elif path == "/api/devices":
            self._json({"devices": list_cameras(), "models": available_models()})
        elif path == "/api/state":
            self._json(ENGINE.state())
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
        except json.JSONDecodeError:
            self._json({"ok": False, "error": "请求不是 JSON"}, 400)
            return
        if path == "/api/start":
            source = str(body.get("source", ""))
            ENGINE.start(source)
            self._json({"ok": True, "state": ENGINE.state()})
        elif path == "/api/stop":
            ENGINE.stop()
            self._json({"ok": True})
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
            self._json(ENGINE.save_record())
        else:
            self.send_error(404)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _file(self, path: Path, content_type: str) -> None:
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

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
    devices = list_cameras()
    thermal = next((item["id"] for item in devices if "UVC" in item["label"].upper()), None)
    if thermal:
        ENGINE.start(thermal)
    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    print("创口温差初筛  http://127.0.0.1:8765", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        ENGINE.stop()
        server.shutdown()


if __name__ == "__main__":
    main()
