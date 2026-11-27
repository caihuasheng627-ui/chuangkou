# -*- coding: utf-8 -*-
"""实时采集服务回归测试：起一个 chuangkou 合成温度源，走 HTTP 读状态、帧、测量。"""
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "live_server.py")


def get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=15) as resp:
        return resp.status, resp.headers.get("content-type"), resp.read()


def main():
    proc = subprocess.Popen([sys.executable, SERVER, "--source", "synthetic:strong",
                             "--idle-exit", "0"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env={**os.environ, "PYTHONUTF8": "1"})
    port = None
    deadline = time.time() + 40
    try:
        while time.time() < deadline:
            line = proc.stdout.readline().decode("utf-8", "ignore").strip()
            if not line:
                continue
            payload = json.loads(line)
            if payload.get("ok") is True and payload.get("port"):
                port = payload["port"]
                assert payload.get("source") == "synthetic:strong", payload
                break
            if payload.get("ok") is False:
                raise RuntimeError(payload.get("error"))
        if not port:
            raise RuntimeError("没有等到 ready 行")

        time.sleep(1.5)
        status, ctype, raw = get(port, "/status")
        assert status == 200 and "application/json" in ctype, ctype
        st = json.loads(raw)
        assert st["ok"] is True and st["source"] == "mock", st
        assert st["has_temperature"] is True, st
        assert st["temperatures"]["delta_t_c"] is not None, st
        assert st["engine"]["grade"] == 2, st["engine"]

        status, ctype, raw = get(port, "/frame.jpg")
        assert status == 200 and ctype == "image/jpeg", (status, ctype)
        assert raw[:2] == b"\xff\xd8" and raw[-2:] == b"\xff\xd9", "不是完整 JPEG"
        assert len(raw) > 4000, len(raw)

        status, ctype, raw = get(port, "/measurement")
        m = json.loads(raw)["measurement"]
        assert m["schema_version"] == "1.0"
        assert m["device"]["capture_mode"] == "mock_y16", m["device"]
        assert m["device"]["calibration"]["status"] == "valid"
        assert m["quality"]["roi_valid"] is True and m["quality"]["reference_valid"] is True
        assert abs(m["metrics"]["delta_t_c"] - (m["metrics"]["t_wound_mean_c"] - m["metrics"]["t_ref_far_c"])) < 0.02
        assert m["measurement_id"].startswith("MEAS-LIVE-"), m["measurement_id"]
        assert any("mock" in w for w in m["quality"]["warnings"]), m["quality"]["warnings"]

        req = urllib.request.Request(f"http://127.0.0.1:{port}/engine",
                                     data=json.dumps({"view": "compare", "weight": "thermal"}).encode(),
                                     method="POST", headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            engine_reply = json.loads(resp.read())
        assert engine_reply["ok"] is True and engine_reply["status"]["engine"]["view"] == "compare"

        req = urllib.request.Request(f"http://127.0.0.1:{port}/stop", data=b"{}", method="POST",
                                     headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert json.loads(resp.read())["ok"] is True

        proc.wait(timeout=15)
        print("LIVE_TESTS_OK chuangkou-synthetic-stream-measurement")
    finally:
        if proc.poll() is None:
            proc.kill()
        err = proc.stderr.read().decode("utf-8", "ignore").strip()
        if err and proc.returncode not in (0, None):
            print("STDERR:", err[-1200:])


if __name__ == "__main__":
    main()
