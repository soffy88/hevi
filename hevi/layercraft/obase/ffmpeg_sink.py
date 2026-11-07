"""obase: stream Pillow frames into ffmpeg (libx264, yuv420p)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class FFmpegSink:
    def __init__(self, path: str | Path, size: tuple[int, int], fps: int = 24, crf: int = 23):
        exe = shutil.which("ffmpeg")
        if not exe:
            raise RuntimeError("ffmpeg not found on PATH")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        w, h = size
        if w % 2 or h % 2:
            raise ValueError("size must be even for yuv420p")
        self.size = size
        self.frames = 0
        self._p = subprocess.Popen(
            [exe, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
             "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(self.path)],
            stdin=subprocess.PIPE)

    def write(self, img) -> None:
        if img.size != self.size:
            raise ValueError(f"frame size {img.size} != {self.size}")
        self._p.stdin.write(img.convert("RGB").tobytes())
        self.frames += 1

    def close(self) -> Path:
        self._p.stdin.close()
        if self._p.wait() != 0:
            raise RuntimeError(f"ffmpeg failed writing {self.path}")
        return self.path

    def __enter__(self):
        return self

    def __exit__(self, et, ev, tb):
        if et is None:
            self.close()
        else:
            self._p.kill()
