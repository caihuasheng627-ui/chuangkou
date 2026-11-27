#!/usr/bin/env python3
"""常驻创口实时采集服务（复用 chuangkou/app 引擎）。
宿主插件通过 /wound-clinic/live/* 反向代理本服务，前端只跟宿主同源通信。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VENDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vendor')
if os.path.isdir(VENDOR) and VENDOR not in sys.path:
    sys.path.insert(0, VENDOR)

from app.engine import Engine  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / 'data'
CFG_PATH = DATA / 'live_config.json'


def load_config():
    base = {'source': 'auto', 'camera': 0, 'fps': 10, 'raw_scale': 0.01,
            'raw_offset': 0.0, 'roi': 'auto', 'scenario': 'strong', 'idle_exit': 120}
    try:
        base.update(json.loads(CFG_PATH.read_text(encoding='utf-8')))
    except Exception:
        pass
    return base


def save_config(cfg):
    DATA.mkdir(parents=True, exist_ok=True)
    CFG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')


class Capture:
    """把 chuangkou Engine 包装成 live_server 原来的采集接口。"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.engine = Engine()
        self.source = 'none'
        self.kind = 'none'
        self.jpg = b''
        self.frame_id = 0
        self.frames_total = 0
        self.fps_real = 0.0
        self.last_error = ''
        self.meta = {}
        self.temps = {}
        self.roi = None
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self._last_seq = 0
        self._thread = None

    def _source_spec(self):
        src = str(self.cfg.get('source') or 'auto')
        cam = int(self.cfg.get('camera', 0))
        if src in ('mock', 'synthetic'):
            return f"synthetic:{self.cfg.get('scenario') or 'strong'}", 'mock'
        if src.startswith('synthetic:'):
            return src, 'mock'
        if src == 'file':
            return 'file', 'file'
        if src == 'window' or src.startswith('window:'):
            return src, 'window'
        if src.startswith('cam:'):
            return src, 'cam'
        return f'cam:{cam}', 'cam'

    def open(self):
        spec, self.kind = self._source_spec()
        self.source = spec
        try:
            self.engine.set_raw_calibration(
                float(self.cfg.get('raw_scale', 0.01)),
                float(self.cfg.get('raw_offset', 0.0)),
            )
        except Exception:
            pass
        self.engine.start(spec)
        return True

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while not self.stop_event.is_set():
            data, seq = self.engine.wait_jpeg(self._last_seq, timeout=0.5)
            self._last_seq = seq
            if not data:
                if self.stop_event.is_set():
                    break
                continue
            st = self.engine.state()
            width = (st.get('matrix') or {}).get('width')
            height = (st.get('matrix') or {}).get('height')
            if not width or not height:
                with self.engine._lock:
                    image = self.engine._last_image
                    if image is not None:
                        height, width = image.shape[:2]
            with self.lock:
                self.jpg = data
                self.frame_id = seq
                self.frames_total = int(st.get('frame_count') or max(0, seq - 1))
                self.fps_real = float(st.get('fps') or 0)
                self.last_error = st.get('error') or ''
                self.meta = {
                    'has_temperature': bool(st.get('has_temperature')),
                    'calibrated': bool(st.get('has_temperature')),
                    'width': width,
                    'height': height,
                    'source_label': st.get('source_label'),
                    'note': st.get('note'),
                    'engine': st,
                }
                self.temps = self._temps(st)
                self.roi = st.get('wound_roi')
                if self.source.startswith('synthetic'):
                    self.kind = 'mock'
                elif st.get('has_temperature'):
                    self.kind = 'y16'
                elif self.source == 'file':
                    self.kind = 'file'
                else:
                    self.kind = 'color'

    @staticmethod
    def _temps(st):
        if not st.get('has_temperature') or st.get('delta') is None:
            return {}
        wound = st.get('wound') or {}
        ref = st.get('ref') or {}
        return {
            't_wound_mean_c': wound.get('mean'),
            't_wound_max_c': wound.get('max'),
            't_ref_far_c': ref.get('mean'),
            't_ref_near_c': ref.get('mean'),
            'delta_t_c': st.get('delta'),
            'area_ratio': st.get('mask_fraction'),
            't_min_c': None,
            't_max_c': st.get('frame_max'),
        }

    def snapshot(self):
        with self.lock:
            return {
                'ok': True, 'source': self.kind, 'source_spec': self.source,
                'has_temperature': bool(self.meta.get('has_temperature')),
                'calibrated': bool(self.meta.get('calibrated')),
                'fps': round(self.fps_real, 2), 'frames': self.frames_total,
                'frame_id': self.frame_id, 'width': self.meta.get('width'),
                'height': self.meta.get('height'), 'temperatures': self.temps,
                'roi': self.roi, 'error': self.last_error,
                'note': self.meta.get('note'),
                'jpeg_bytes': len(self.jpg),
                'engine': self.meta.get('engine'),
            }

    def stop(self):
        self.stop_event.set()
        try:
            self.engine.stop()
        except Exception:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)


def restart_capture(cfg):
    """相机索引/标定参数变化后，停止旧采集并按新配置重新打开。"""
    old = Handler.capture
    new = Capture(cfg)
    new.open()
    new.start()
    Handler.capture = new
    if old is not None:
        old.stop()


def measurement_from(capture):
    snap = capture.snapshot()
    with capture.lock:
        jpeg = capture.jpg
        cfg = dict(capture.cfg)
    if not jpeg:
        raise RuntimeError('尚未取得画面帧，无法记录当前帧')
    eng = snap.get('engine') or {}
    temps = snap.get('temperatures') or {}
    has_temp = bool(snap.get('has_temperature'))
    mock = snap['source'] == 'mock'
    mode = 'mock_y16' if mock else ('y16_raw' if has_temp else 'pseudo')
    warnings = []
    if mock:
        warnings.append('mock 模式仅用于联调，不构成临床数据')
    if not has_temp:
        warnings.append(eng.get('grade_text') or '当前仅取得可见光/伪彩画面，未获得可用温度矩阵；本帧只能保存图像，不能给出真实温差')
    if eng.get('unstable'):
        warnings.append(eng.get('message') or '当前温度波动较大，请保持静止后再采集')
    mid = 'MEAS-LIVE-' + hashlib.sha1(jpeg + str(time.time()).encode()).hexdigest()[:16]
    roi_valid = bool(eng.get('wound_roi'))
    ref_valid = bool(eng.get('ref'))
    return {
        'schema_version': '1.0',
        'measurement_id': mid,
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'patient_ref': None,
        'device': {
            'model': snap.get('source_spec') or 'chuangkou-engine',
            'capture_mode': mode,
            'emissivity': eng.get('emissivity', 0.98),
            'distance_m': round((eng.get('distance_mm') or 300) / 1000, 3),
            'ambient_c': None,
            'calibration': {
                'status': 'valid' if has_temp else 'invalid',
                'method': 'chuangkou_temperature_matrix' if has_temp else 'no_temperature_matrix',
                'raw_scale': cfg.get('raw_scale'),
                'raw_offset': cfg.get('raw_offset'),
            },
        },
        'quality': {
            'frames_used': snap['frames'],
            'temporal_median_frames': 10,
            'roi_valid': roi_valid,
            'reference_valid': ref_valid,
            'temperature_in_range': has_temp and not eng.get('unstable', False),
            'warnings': warnings,
        },
        'metrics': {
            't_wound_mean_c': temps.get('t_wound_mean_c'),
            't_wound_max_c': temps.get('t_wound_max_c'),
            't_ref_far_c': temps.get('t_ref_far_c'),
            't_ref_near_c': temps.get('t_ref_near_c'),
            'delta_t_c': temps.get('delta_t_c'),
            'area_ratio': temps.get('area_ratio'),
            't_min_c': temps.get('t_min_c'),
            't_max_c': temps.get('t_max_c'),
            'temperature_unit': 'degC',
        },
        'thresholds': {'version': 'wound-delta-v1', 'normal_max_c': 0.6,
                       'warning_max_c': 2.2, 'infection_min_c': 2.55},
        'frame_image': {
            'mime': 'image/jpeg',
            'base64': base64.b64encode(jpeg).decode('ascii'),
            'width': snap.get('width'), 'height': snap.get('height'),
        },
        'note': '自动热点 ROI 仅用于记录当前帧；ΔT = 创口均温 − 参考皮温，不能用于确诊感染。',
        'engine': eng,
    }


class Handler(BaseHTTPRequestHandler):
    capture = None
    last_client = time.time()

    def log_message(self, fmt, *args):
        pass

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        Handler.last_client = time.time()
        if self.path.startswith('/status'):
            self._json(self.capture.snapshot())
        elif self.path.startswith('/measurement'):
            try:
                self._json({'ok': True, 'measurement': measurement_from(self.capture)})
            except Exception as exc:
                self._json({'ok': False, 'error': str(exc)}, 409)
        elif self.path.startswith('/frame.jpg'):
            data = self.capture.jpg
            if not data:
                self._json({'ok': False, 'error': 'no frame'}, 404)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self._cors()
            self.end_headers()
            self.wfile.write(data)
        elif self.path.startswith('/stream'):
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
            self.send_header('Cache-Control', 'no-store')
            self._cors()
            self.end_headers()
            last = 0
            try:
                while not self.capture.stop_event.is_set():
                    Handler.last_client = time.time()
                    data, seq = self.capture.engine.wait_jpeg(last, timeout=1.0)
                    last = seq
                    if not data:
                        continue
                    self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ' +
                                     str(len(data)).encode() + b'\r\n\r\n' + data + b'\r\n')
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
        else:
            self._json({'ok': False, 'error': 'not found'}, 404)

    def do_POST(self):
        Handler.last_client = time.time()
        if self.path.startswith('/stop'):
            self._json({'ok': True})
            threading.Thread(target=self._shutdown, daemon=True).start()
        elif self.path.startswith('/engine'):
            try:
                n = int(self.headers.get('Content-Length', '0'))
                patch = json.loads(self.rfile.read(n) or b'{}')
                if patch.get('weight'):
                    self.capture.engine.set_weight(str(patch['weight']))
                if patch.get('view'):
                    self.capture.engine.set_view(str(patch['view']))
                if 'auto' in patch:
                    self.capture.engine.set_auto(bool(patch['auto']))
                self._json({'ok': True, 'status': self.capture.snapshot()})
            except Exception as exc:
                self._json({'ok': False, 'error': str(exc)}, 400)
        elif self.path.startswith('/config'):
            try:
                n = int(self.headers.get('Content-Length', '0'))
                patch = json.loads(self.rfile.read(n) or b'{}')
                if 'scale' in patch and 'raw_scale' not in patch:
                    patch['raw_scale'] = patch['scale']
                if 'offset' in patch and 'raw_offset' not in patch:
                    patch['raw_offset'] = patch['offset']
                cfg = load_config()
                for k in ('source', 'camera', 'fps', 'raw_scale', 'raw_offset', 'roi', 'scenario'):
                    if k in patch:
                        cfg[k] = patch[k]
                save_config(cfg)
                restart_capture(cfg)
                self._json({'ok': True, 'config': cfg, 'restart_required': False, 'status': self.capture.snapshot()})
            except Exception as exc:
                self._json({'ok': False, 'error': str(exc)}, 400)
        else:
            self._json({'ok': False, 'error': 'not found'}, 404)

    def _shutdown(self):
        self.capture.stop()
        threading.Thread(target=self.server.shutdown, daemon=True).start()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', default=None)
    ap.add_argument('--source', default=None)
    ap.add_argument('--camera', type=int, default=None)
    ap.add_argument('--fps', type=int, default=None)
    ap.add_argument('--scale', type=float, default=None)
    ap.add_argument('--offset', type=float, default=None)
    ap.add_argument('--roi', default=None)
    ap.add_argument('--scenario', default=None)
    ap.add_argument('--idle-exit', type=int, default=None)
    ap.add_argument('--config', default=None)
    args = ap.parse_args()
    cfg = load_config()
    if args.config:
        try:
            cfg.update(json.loads(Path(args.config).read_text(encoding='utf-8')))
        except Exception:
            pass
    for key, val in (('source', args.source), ('camera', args.camera), ('fps', args.fps),
                     ('raw_scale', args.scale), ('raw_offset', args.offset), ('roi', args.roi),
                     ('scenario', args.scenario), ('idle_exit', args.idle_exit)):
        if val is not None:
            cfg[key] = val
    cap = Capture(cfg)
    Handler.capture = cap
    try:
        cap.open()
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}), flush=True)
        sys.exit(2)
    cap.start()
    srv = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    srv.daemon_threads = True
    print(json.dumps({'event': 'ready', 'ok': True, 'port': srv.server_address[1],
                      'pid': os.getpid(), 'source': cap.source}), flush=True)
    idle = int(cfg.get('idle_exit', 120) or 0)

    def watch_idle():
        if idle <= 0:
            return
        while not cap.stop_event.is_set():
            time.sleep(5)
            if time.time() - Handler.last_client > idle:
                cap.stop()
                threading.Thread(target=srv.shutdown, daemon=True).start()
                return

    threading.Thread(target=watch_idle, daemon=True).start()
    try:
        srv.serve_forever()
    finally:
        cap.stop()
        srv.server_close()


if __name__ == '__main__':
    main()
