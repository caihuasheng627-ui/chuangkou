import subprocess
import sys
from pathlib import Path

import numpy as np

OUT = Path(r"C:\Users\蔡华升\Desktop\chuangkou\data")


def grab(args, timeout=10):
    print("CMD", " ".join(args), flush=True)
    log_path = OUT / "probe.log"
    log = open(log_path, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=log)
    try:
        data, _ = proc.communicate(timeout=timeout)
        err = log_path.read_text(encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        proc.kill()
        data, _ = proc.communicate()
        log.flush()
        err = log_path.read_text(encoding="utf-8", errors="replace")
        print("TIMEOUT", len(data))
    log.close()
    for line in err.splitlines():
        if any(key in line for key in ("Video:", "Stream #", "Error", "error", "size=")):
            print(line[:200])
    print("exit", proc.returncode, "stdout", len(data))
    return data


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "yuyv"
    if mode == "yuyv":
        data = grab(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "info",
                "-f", "dshow", "-pixel_format", "yuyv422",
                "-video_size", "120x160", "-framerate", "25",
                "-i", "video=UVC Camera", "-frames:v", "2",
                "-f", "rawvideo", "-pix_fmt", "yuyv422", "pipe:1",
            ]
        )
        frame_bytes = 120 * 160 * 2
        print("frames", len(data) / frame_bytes if frame_bytes else 0)
        if len(data) < frame_bytes:
            return
        raw = np.frombuffer(data[:frame_bytes], dtype="<u2")
        print("u16", int(raw.min()), int(raw.max()), float(raw.mean()))
        for scale in (1, 10, 16, 32, 64, 100):
            c = raw.astype(np.float32) / scale - 273.15
            print(f"scale {scale} med {np.median(c):.2f} p95 {np.percentile(c, 95):.2f}")
        (OUT / "yuyv.raw").write_bytes(data[:frame_bytes])
    elif mode == "wide":
        grab(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "info",
                "-f", "dshow", "-video_size", "640x360", "-framerate", "30",
                "-i", "video=UVC Camera", "-frames:v", "1", "-update", "1",
                str(OUT / "wide.jpg"),
            ]
        )


if __name__ == "__main__":
    main()
