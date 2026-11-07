"""ffmpeg 适配：探测、silencedetect 解析、按保留区间渲染。"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

_FALLBACK_DIRS = ("/home/soffy/.local/bin", "/usr/local/bin", "/usr/bin")


def _find(name: str) -> str:
    env = os.environ.get(f"HEVI_{name.upper()}")
    if env:
        return env
    p = shutil.which(name)
    if p:
        return p
    for d in _FALLBACK_DIRS:
        c = Path(d) / name
        if c.exists():
            return str(c)
    raise FileNotFoundError(f"{name} not found")


def ffmpeg_bin() -> str:
    return _find("ffmpeg")


def ffprobe_bin() -> str:
    return _find("ffprobe")


def probe_duration(path: str | Path) -> float:
    out = subprocess.run(
        [
            ffprobe_bin(),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return float(out)


def has_video(path: str | Path) -> bool:
    out = subprocess.run(
        [
            ffprobe_bin(),
            "-v",
            "error",
            "-select_streams",
            "v",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
    ).stdout
    return "video" in out


_S = re.compile(r"silence_start:\s*(-?[\d.]+)")
_E = re.compile(r"silence_end:\s*(-?[\d.]+)")


def parse_silencedetect(stderr: str, duration: float) -> list[tuple[float, float]]:
    """把 ffmpeg silencedetect 输出解析成 [(start, end)]，末尾未闭合的静音补到 duration。"""
    out: list[tuple[float, float]] = []
    cur: float | None = None
    for line in stderr.splitlines():
        m = _S.search(line)
        if m:
            cur = max(0.0, float(m.group(1)))
            continue
        m = _E.search(line)
        if m and cur is not None:
            out.append((cur, min(duration, float(m.group(1)))))
            cur = None
    if cur is not None and cur < duration:
        out.append((cur, duration))
    return out


def run_silencedetect(
    path: str | Path, noise_db: float = -35.0, min_silence: float = 0.4
) -> list[tuple[float, float]]:
    dur = probe_duration(path)
    p = subprocess.run(
        [
            ffmpeg_bin(),
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-vn",
            "-af",
            f"silencedetect=n={noise_db}dB:d={min_silence}",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    return parse_silencedetect(p.stderr, dur)


def _between(ranges: list[tuple[float, float]]) -> str:
    return "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in ranges)


def render_keep_ranges(src: str | Path, ranges: list[tuple[float, float]], dst: str | Path) -> Path:
    """只保留 ranges 区间并无缝拼接（trim/atrim + concat；ffmpeg 7/8 均可）。"""
    if not ranges:
        raise ValueError("no ranges to keep")
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    script = dst.with_suffix(dst.suffix + ".filter.txt")
    vid = has_video(src) and dst.suffix.lower() not in (".wav", ".mp3", ".m4a", ".aac", ".flac")
    # 用 trim/atrim + concat 而非 select/aselect：ffmpeg 8.0.1(Ubuntu) 的 aselect 不丢帧（aselect=0 也全放行）
    parts, labels = [], ""
    for i, (a, b) in enumerate(ranges):
        if vid:
            parts.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{i}]")
        labels += (f"[v{i}]" if vid else "") + f"[a{i}]"
    parts.append(f"{labels}concat=n={len(ranges)}:v={1 if vid else 0}:a=1" + ("[v][a]" if vid else "[a]"))
    script.write_text(";".join(parts))
    cmd = [
        ffmpeg_bin(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        "-filter_complex_script",
        str(script),
    ]
    if vid:
        cmd += ["-map", "[v]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
    cmd += ["-map", "[a]"]
    if dst.suffix.lower() in (".mp4", ".mov", ".m4a"):
        cmd += ["-c:a", "aac", "-b:a", "160k"]
    cmd.append(str(dst))
    subprocess.run(cmd, check=True)
    script.unlink(missing_ok=True)
    return dst


# ---------------------------------------------------------------- P1：字幕烧录/软挂
def _filter_path(p: str | Path) -> str:
    """ffmpeg 滤镜参数里的路径转义（: ' \\ , [ ]）。"""
    s = str(Path(p).resolve())
    for ch in ("\\", ":", "'", ",", "[", "]"):
        s = s.replace(ch, "\\" + ch)
    return s


def burn_subtitles(
    src: str | Path,
    subs: str | Path,
    dst: str | Path,
    *,
    fonts_dir: str | Path | None = None,
    force_style: str = "",
    crf: int = 20,
) -> Path:
    """硬字幕：.ass 走 ass 滤镜（保留样式），其余走 subtitles 滤镜（可 force_style）。音频直拷。"""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    subs = Path(subs)
    fd = fonts_dir or next(
        (d for d in ("/usr/share/fonts/opentype/noto", "/usr/share/fonts") if Path(d).exists()), None
    )
    if subs.suffix.lower() == ".ass":
        vf = f"ass={_filter_path(subs)}"
    else:
        vf = f"subtitles={_filter_path(subs)}"
        if force_style:
            vf += f":force_style='{force_style}'"
    if fd:
        vf += f":fontsdir={_filter_path(fd)}"
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-vf", vf,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-c:a", "copy", str(dst)]
    subprocess.run(cmd, check=True)
    return dst


def mux_soft_subs(
    src: str | Path, tracks: list[dict], dst: str | Path
) -> Path:
    """软字幕：tracks=[{"path","lang"(ISO639-2 如 eng/chi),"title"?,"default"?}]，音视频直拷。

    mp4/mov → mov_text（ASS 样式会丢）；mkv → 保留 srt/ass 原格式。
    """
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    mkv = dst.suffix.lower() == ".mkv"
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src)]
    for t in tracks:
        cmd += ["-i", str(t["path"])]
    cmd += ["-map", "0:v?", "-map", "0:a?"]
    for i in range(len(tracks)):
        cmd += ["-map", str(i + 1)]
    cmd += ["-c:v", "copy", "-c:a", "copy", "-c:s", "copy" if mkv else "mov_text"]
    for i, t in enumerate(tracks):
        cmd += [f"-metadata:s:s:{i}", f"language={t.get('lang', 'und')}"]
        if t.get("title"):
            cmd += [f"-metadata:s:s:{i}", f"title={t['title']}"]
        cmd += [f"-disposition:s:{i}", "default" if t.get("default", i == 0) else "0"]
    cmd.append(str(dst))
    subprocess.run(cmd, check=True)
    return dst


def list_streams(path: str | Path) -> list[dict]:
    import json as _json

    out = subprocess.run(
        [ffprobe_bin(), "-v", "error", "-show_entries", "stream=index,codec_type,codec_name:stream_tags=language",
         "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    return _json.loads(out).get("streams", [])


# ---------------------------------------------------------------- P1：画面信号（黑场/静止/场景切换）
_BLACK = re.compile(r"black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)")
_FS = re.compile(r"freeze_start:\s*([\d.]+)")
_FE = re.compile(r"freeze_end:\s*([\d.]+)")
_SCD = re.compile(r"lavfi\.scd\.score:\s*([\d.]+),\s*lavfi\.scd\.time:\s*([\d.]+)")


def parse_visual_detect(stderr: str, duration: float) -> dict:
    """解析 blackdetect/freezedetect/scdet 日志 → {"black":[(s,e)],"freeze":[(s,e)],"scene":[(t,score)]}。"""
    black, freeze, scene = [], [], []
    cur = None
    for line in stderr.splitlines():
        m = _BLACK.search(line)
        if m:
            black.append((float(m.group(1)), min(duration, float(m.group(2)))))
            continue
        m = _FS.search(line)
        if m:
            cur = float(m.group(1))
            continue
        m = _FE.search(line)
        if m and cur is not None:
            freeze.append((cur, min(duration, float(m.group(1)))))
            cur = None
            continue
        m = _SCD.search(line)
        if m:
            scene.append((float(m.group(2)), float(m.group(1))))
    if cur is not None and cur < duration:
        freeze.append((cur, duration))
    return {"black": black, "freeze": freeze, "scene": scene}


def run_visual_detect(
    path: str | Path,
    *,
    black_min: float = 0.3,
    black_pix_th: float = 0.10,
    freeze_noise_db: float = -60.0,
    freeze_min: float = 1.5,
    scene_th: float = 10.0,
    scale_w: int = 320,
) -> dict:
    """一次解码同时跑 blackdetect + freezedetect + scdet（先缩到 scale_w 宽以省 CPU）。"""
    dur = probe_duration(path)
    vf = (f"scale={scale_w}:-2,blackdetect=d={black_min}:pix_th={black_pix_th},"
          f"freezedetect=n={freeze_noise_db}dB:d={freeze_min},scdet=t={scene_th}")
    p = subprocess.run(
        [ffmpeg_bin(), "-hide_banner", "-nostats", "-loglevel", "info", "-i", str(path), "-an",
         "-vf", vf, "-f", "null", "-"], capture_output=True, text=True)
    return parse_visual_detect(p.stderr, dur)
