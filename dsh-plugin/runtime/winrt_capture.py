# -*- coding: utf-8 -*-
"""WinRT MediaCapture 取流（可选兜底后端）。

整合自 dsh-wound-clinic v0.7.2，并修复原版仅用 SharedReadOnly 导致独占流未启动时
读不到帧的问题：默认优先尝试 ExclusiveControl + CPU 内存，失败后再回退 SharedReadOnly。
缺少 winrt-* 依赖时抛出 ImportError，由上层引擎自动回退到 FFmpeg / OpenCV。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _attr(obj, *names):
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    raise AttributeError(f"{type(obj).__name__} 没有属性 {names}")


def _call(obj, *names, args=()):
    return _attr(obj, *names)(*args)


def _load():
    try:
        import winrt.windows.devices.enumeration as enumeration
        import winrt.windows.graphics.imaging as imaging
        import winrt.windows.media.capture as capture
        import winrt.windows.media.capture.frames as framekit
        import winrt.windows.storage.streams as streams
    except ImportError as exc:
        raise ImportError("未安装 winrt-* 依赖，跳过 WinRT 采集后端。") from exc
    return {"e": enumeration, "i": imaging, "c": capture, "f": framekit, "s": streams}


def _enum(kind, *names):
    for name in names:
        if hasattr(kind, name):
            return getattr(kind, name)
    raise AttributeError(f"{kind} 没有成员 {names}")


async def _find_cameras():
    m = _load()
    infos = await _call(
        m["e"].DeviceInformation,
        "find_all_async",
        "FindAllAsync",
        args=(_enum(m["e"].DeviceClass, "VIDEO_CAPTURE", "VideoCapture"),),
    )
    return [(str(info.name), str(info.id)) for info in infos]


def list_cameras() -> list[tuple[str, str]]:
    """返回 [(设备名, 设备ID)]，顺序与系统相机一致。"""
    return asyncio.run(_find_cameras())


def _ibuffer_bytes(m, buf) -> bytes:
    for getter in (lambda: bytes(memoryview(buf)), lambda: bytes(buf)):
        try:
            return getter()
        except Exception:
            continue
    length = int(_attr(buf, "length", "Length"))
    reader = _call(m["s"].DataReader, "from_buffer", "FromBuffer", args=(buf,))
    return bytes(_call(reader, "read_bytes", "ReadBytes", args=(length,)))


def _pick_source(m, cap, prefer_size=None):
    sources = _attr(cap, "frame_sources", "FrameSources")
    color = _enum(m["f"].MediaFrameSourceKind, "COLOR", "Color")
    preview = _enum(m["c"].MediaStreamType, "VIDEO_PREVIEW", "VideoPreview")
    fallback = []
    for source in sources.values():
        info = _attr(source, "info", "Info")
        if _attr(info, "source_kind", "SourceKind") != color:
            continue
        fallback.append(source)
        if prefer_size is not None:
            fmt = _attr(source, "current_format", "CurrentFormat")
            video = _attr(fmt, "video_format", "VideoFormat")
            if (int(_attr(video, "width", "Width")), int(_attr(video, "height", "Height"))) == tuple(prefer_size):
                return source
        if _attr(info, "media_stream_type", "MediaStreamType") == preview:
            return source
    return fallback[0] if fallback else None


def _to_bgr(m, frame):
    try:
        video = _attr(frame, "video_media_frame", "VideoMediaFrame")
        bitmap = _attr(video, "software_bitmap", "SoftwareBitmap")
        if bitmap is None:
            return None
        bgra8 = _enum(m["i"].BitmapPixelFormat, "BGRA8", "Bgra8")
        if _attr(bitmap, "bitmap_pixel_format", "BitmapPixelFormat") != bgra8:
            bitmap = _call(m["i"].SoftwareBitmap, "convert", "Convert", args=(bitmap, bgra8))
        width = int(_attr(bitmap, "pixel_width", "PixelWidth"))
        height = int(_attr(bitmap, "pixel_height", "PixelHeight"))
        buf = m["s"].Buffer(width * height * 4)
        _call(bitmap, "copy_to_buffer", "CopyToBuffer", args=(buf,))
        raw = _ibuffer_bytes(m, buf)
        expected = width * height * 4
        if len(raw) < expected:
            return None
        bgra = np.frombuffer(raw, np.uint8, expected).reshape(height, width, 4)
        return np.ascontiguousarray(bgra[:, :, :3])
    except Exception:
        return None


class WinRTFrameStream:
    """在独立线程中持续拉帧，主线程通过 latest() 获取最新 BGR 帧。"""

    def __init__(
        self,
        device_name: str,
        prefer_size=None,
        start_timeout: float = 12.0,
        sharing_mode: str = "auto",
    ):
        self.device_name = device_name
        self.prefer_size = prefer_size
        self.start_timeout = start_timeout
        self.sharing_mode = sharing_mode  # auto | exclusive | shared
        self.error: str | None = None
        self.running = False
        self.count = 0
        self.width = 0
        self.height = 0
        self.subtype = ""
        self.active_mode = ""
        self._frame = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._entry, name="winrt-capture", daemon=True)
        self._thread.start()
        self._ready.wait(self.start_timeout)
        if self.error:
            raise RuntimeError(self.error)
        return self

    def _entry(self):
        try:
            asyncio.run(self._main())
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            self.running = False
            self._ready.set()

    async def _init_capture(self, m, device_id: str, exclusive: bool):
        cap = m["c"].MediaCapture()
        settings = m["c"].MediaCaptureInitializationSettings()
        setattr(settings, "video_device_id", device_id)
        setattr(settings, "streaming_capture_mode", _enum(m["c"].StreamingCaptureMode, "VIDEO", "Video"))
        try:
            setattr(
                settings,
                "memory_preference",
                _enum(m["c"].MediaCaptureMemoryPreference, "CPU", "Cpu"),
            )
        except Exception:
            pass
        if exclusive:
            mode = _enum(m["c"].MediaCaptureSharingMode, "EXCLUSIVE_CONTROL", "ExclusiveControl")
        else:
            mode = _enum(m["c"].MediaCaptureSharingMode, "SHARED_READ_ONLY", "SharedReadOnly")
        setattr(settings, "sharing_mode", mode)
        await _call(cap, "initialize_async", "InitializeAsync", args=(settings,))
        return cap

    async def _main(self):
        m = _load()
        device_id = await self._resolve_device_id()
        if self.sharing_mode == "exclusive":
            modes = [("exclusive", True)]
        elif self.sharing_mode == "shared":
            modes = [("shared", False)]
        else:
            modes = [("exclusive", True), ("shared", False)]

        cap = None
        last_exc = None
        for mode_label, is_exclusive in modes:
            try:
                cap = await self._init_capture(m, device_id, is_exclusive)
                self.active_mode = mode_label
                break
            except Exception as exc:
                last_exc = exc
                continue
        if cap is None:
            raise RuntimeError(f"WinRT MediaCapture 初始化失败: {last_exc}")

        source = _pick_source(m, cap, self.prefer_size)
        if source is None:
            try:
                _call(cap, "close", "Close")
            except Exception:
                pass
            raise RuntimeError("设备没有可用的彩色帧源")

        fmt = _attr(source, "current_format", "CurrentFormat")
        video = _attr(fmt, "video_format", "VideoFormat")
        self.width = int(_attr(video, "width", "Width"))
        self.height = int(_attr(video, "height", "Height"))
        self.subtype = str(_attr(video, "subtype", "Subtype"))

        reader = await _call(cap, "create_frame_reader_async", "CreateFrameReaderAsync", args=(source,))
        await _call(reader, "start_async", "StartAsync")
        self.running = True
        self._ready.set()
        try:
            while not self._stop.is_set():
                frame = _call(reader, "try_acquire_latest_frame", "TryAcquireLatestFrame")
                if frame is None:
                    await asyncio.sleep(0.006)
                    continue
                try:
                    bgr = _to_bgr(m, frame)
                finally:
                    try:
                        _call(frame, "close", "Close")
                    except Exception:
                        pass
                if bgr is not None:
                    with self._lock:
                        self._frame = (bgr, time.time())
                        self.count += 1
                await asyncio.sleep(0)
        finally:
            self.running = False
            try:
                await _call(reader, "stop_async", "StopAsync")
            except Exception:
                pass
            try:
                _call(cap, "close", "Close")
            except Exception:
                pass

    async def _resolve_device_id(self) -> str:
        wanted = self.device_name.strip()
        if wanted.startswith("\\\\?\\"):
            return wanted
        cameras = await _find_cameras()
        for name, device_id in cameras:
            if name.casefold() == wanted.casefold():
                return device_id
        for name, device_id in cameras:
            if wanted.casefold() in name.casefold():
                return device_id
        listing = "、".join(name for name, _ in cameras) or "（未枚举到任何相机）"
        raise RuntimeError(f"没有名为“{self.device_name}”的相机。当前可见：{listing}")

    def latest(self, max_age: float | None = None):
        with self._lock:
            item = self._frame
        if item is None:
            return None
        if max_age is not None and time.time() - item[1] > max_age:
            return None
        return item

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)


def main(argv=None) -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="WinRT 取流自测")
    parser.add_argument("--name", default="UVC Camera", help="设备名")
    parser.add_argument("--seconds", type=float, default=4.0, help="取流秒数")
    parser.add_argument("--mode", choices=["auto", "exclusive", "shared"], default="auto")
    parser.add_argument("--save", default="", help="保存首尾两帧的目录")
    parser.add_argument("--list", action="store_true", help="只列设备")
    args = parser.parse_args(argv)

    if args.list:
        for name, device_id in list_cameras():
            print(f"{name} | {device_id}")
        return 0

    t0 = time.time()
    stream = WinRTFrameStream(args.name, sharing_mode=args.mode).start()
    print(f"初始化 {time.time() - t0:.1f}s  {stream.width}x{stream.height}  {stream.subtype}  mode={stream.active_mode}")
    time.sleep(args.seconds)
    first = stream.latest()
    count = stream.count
    last = stream.latest()
    stream.stop()
    elapsed = time.time() - t0
    print(f"帧数 {count}  约 {count / max(elapsed, 0.001):.1f} 帧/秒  运行中={stream.running}  错误={stream.error!r}")
    if first is not None:
        frame = first[0]
        print(f"尺寸 {frame.shape}  均值 {float(frame.mean()):.2f}  标准差 {float(frame.astype(np.float32).std()):.2f}")
        if args.save:
            import cv2

            out_dir = Path(args.save)
            out_dir.mkdir(parents=True, exist_ok=True)
            ok1, buf1 = cv2.imencode(".png", frame)
            if ok1:
                (out_dir / "winrt_first.png").write_bytes(buf1.tobytes())
            if last is not None:
                ok2, buf2 = cv2.imencode(".png", last[0])
                if ok2:
                    (out_dir / "winrt_last.png").write_bytes(buf2.tobytes())
            print(f"已保存到 {out_dir}")
        return 0
    print("没有取到任何帧")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
