# -*- coding: utf-8 -*-
"""Windows 相机窗口抓帧兜底模块（零额外依赖，纯 Win32 ctypes + numpy）。

仅在极少数受安全软件或系统策略拦截、桌面进程无法直连 UVC 时作为可选输入源使用；
通过 PrintWindow(..., PW_RENDERFULLCONTENT) 抓取已打开的 Windows“相机”窗口并自动裁去黑边。
"""
from __future__ import annotations

import ctypes
import platform
from ctypes import wintypes
from typing import Optional

import numpy as np

PW_RENDERFULLCONTENT = 2
DIB_RGB_COLORS = 0
BI_RGB = 0

CAMERA_WINDOW_HINTS = ("相机", "Camera", "Windows Camera")


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", _BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


def _setup_win32():
    if platform.system() != "Windows":
        return None, None
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    return user32, gdi32


def list_camera_windows(keyword: str = "") -> list[dict]:
    """列出当前可见的匹配窗口（默认优先匹配 Windows 相机应用）。"""
    user32, _ = _setup_win32()
    if user32 is None:
        return []

    results: list[dict] = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    kw = keyword.strip().casefold()

    def _cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        if not title:
            return True
        cls_buf = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(hwnd, cls_buf, 128)
        cls_name = cls_buf.value.strip()

        matched = False
        if kw:
            matched = kw in title.casefold()
        else:
            t_cf = title.casefold()
            matched = any(h.casefold() == t_cf or h.casefold() in t_cf for h in CAMERA_WINDOW_HINTS)
            # 排除浏览器标签页误匹配
            if matched and any(b in t_cf for b in ("edge", "chrome", "firefox", "创口温差")):
                matched = False

        if matched:
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w >= 120 and h >= 120:
                results.append({"hwnd": int(hwnd), "title": title, "class": cls_name, "width": w, "height": h})
        return True

    user32.EnumWindows(WNDENUMPROC(_cb), 0)
    # 优先 UWP ApplicationFrameWindow
    results.sort(key=lambda item: (0 if item["class"] == "ApplicationFrameWindow" else 1, -item["width"] * item["height"]))
    return results


def crop_thermal_content(bgr: np.ndarray) -> np.ndarray:
    """裁掉 Windows 相机窗口四周的标题栏、纯黑信箱边与底部工具栏。"""
    if bgr is None or bgr.ndim != 3:
        return bgr
    h, w = bgr.shape[:2]
    if h < 120 or w < 120:
        return bgr

    # 优先寻找海康机芯自带的亮绿预览边框
    b = bgr[:, :, 0].astype(np.int16)
    g = bgr[:, :, 1].astype(np.int16)
    r = bgr[:, :, 2].astype(np.int16)
    green_frame = (g > 150) & (g > r + 60) & (g > b + 60)
    ys, xs = np.where(green_frame)
    if xs.size >= 120:
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        if (x1 - x0) >= 120 and (y1 - y0) >= 120:
            return np.ascontiguousarray(bgr[y0:y1, x0:x1])

    # 否则按亮度裁去纯黑边（跳过顶部 40px 标题栏）
    top = min(40, h // 8)
    sub = bgr[top:, :]
    gray = sub.max(axis=2)
    row_active = np.where(gray.mean(axis=1) > 10.0)[0]
    col_active = np.where(gray.mean(axis=0) > 10.0)[0]
    if row_active.size >= 80 and col_active.size >= 80:
        y0 = top + int(row_active[0])
        y1 = top + int(row_active[-1]) + 1
        x0 = int(col_active[0])
        x1 = int(col_active[-1]) + 1
        if (x1 - x0) >= 120 and (y1 - y0) >= 120:
            return np.ascontiguousarray(bgr[y0:y1, x0:x1])
    return bgr


def grab_window_bgr(hwnd: int, crop: bool = True) -> Optional[np.ndarray]:
    """抓取指定 HWND 的 BGR 帧；窗口最小化或抓取失败时返回 None。"""
    user32, gdi32 = _setup_win32()
    if user32 is None or gdi32 is None or not hwnd:
        return None
    if not user32.IsWindow(hwnd) or not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
        return None

    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if width < 64 or height < 64 or width > 4096 or height > 4096:
        return None

    hdc_window = user32.GetWindowDC(hwnd)
    if not hdc_window:
        return None
    hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
    hbitmap = gdi32.CreateCompatibleBitmap(hdc_window, width, height)
    old_obj = gdi32.SelectObject(hdc_mem, hbitmap)
    try:
        ok = user32.PrintWindow(hwnd, hdc_mem, PW_RENDERFULLCONTENT)
        if not ok:
            ok = user32.PrintWindow(hwnd, hdc_mem, 0)
        if not ok:
            return None

        bmi = _BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height  # top-down DIB
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB

        buf_size = width * height * 4
        raw = ctypes.create_string_buffer(buf_size)
        lines = gdi32.GetDIBits(hdc_mem, hbitmap, 0, height, raw, ctypes.byref(bmi), DIB_RGB_COLORS)
        if lines <= 0:
            return None
        bgra = np.frombuffer(raw.raw, dtype=np.uint8).reshape(height, width, 4)
        bgr = np.ascontiguousarray(bgra[:, :, :3])
        if float(bgr.max()) < 2.0:
            return None
        return crop_thermal_content(bgr) if crop else bgr
    finally:
        gdi32.SelectObject(hdc_mem, old_obj)
        gdi32.DeleteObject(hbitmap)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd, hdc_window)
