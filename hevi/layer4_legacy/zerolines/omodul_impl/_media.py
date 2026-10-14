"""Side-effecting media helpers for zero-cost lines (omodul layer): ffmpeg /
ffprobe, Piper TTS, Pexels free-licence stock, faster-whisper, frame encoding,
measured QA, contact sheets.  CPU only.  Every failure raises ``ZeroMediaError``;
nothing here substitutes a placeholder for a missing input."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import urllib.parse
import urllib.request
import wave
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np

from hevi.layer4_legacy.talkcraft.omodul_impl._media import FFMPEG, FFPROBE, PIPER, VOICE_DIR, VOICES
from hevi.layer4_legacy.zerolines.oskill_impl.audio_math import rms_from_pcm, synth_bgm
from hevi.layer4_legacy.zerolines.oskill_impl.qa import frame_stats, judge
from hevi.layer4_legacy.zerolines.oskill_impl.shots import camera_filter, source_offset, xfade_graph

FONTS_DIR = os.environ.get("HEVI_ZERO_FONTS_DIR", "/usr/share/fonts/opentype/noto")
CACHE = Path(os.environ.get("HEVI_ZERO_CACHE", str(Path.home() / ".cache/hevi/zerolines")))
WHISPER_MODEL = os.environ.get("HEVI_WHISPER_MODEL", "/home/soffy/models/faster-whisper-large-v3-turbo")


class ZeroMediaError(RuntimeError):
    pass


def sh(cmd: list[str]) -> None:
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if r.returncode:
        raise ZeroMediaError(f"{Path(cmd[0]).name} failed ({r.returncode}): {' '.join(cmd)[:300]}\n{r.stderr[-1500:]}")


def dur(path: str | Path) -> float:
    out = subprocess.check_output(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], text=True
    )
    return float(out.strip())


def sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ---------------------------------------------------------------- TTS (Piper)
def tts(text: str, out: Path, *, lang: str = "zh", speed: float = 1.0) -> float:
    if not Path(PIPER).is_file():
        raise ZeroMediaError(f"piper binary missing: {PIPER} (set HEVI_TALKCRAFT_PIPER)")
    voice = Path(VOICE_DIR) / VOICES[lang]
    if not voice.is_file():
        raise ZeroMediaError(f"piper voice missing: {voice} (set HEVI_TALKCRAFT_VOICES)")
    raw = out.with_suffix(".raw.wav")
    r = subprocess.run(
        [PIPER, "-m", str(voice), "-f", str(raw), "--length_scale", f"{1 / speed:.4f}", "--sentence_silence", "0.25"],
        input=text, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    if r.returncode or not raw.is_file():
        raise ZeroMediaError(f"piper failed: {r.stderr[-800:]}")
    sh([FFMPEG, "-y", "-v", "error", "-i", str(raw), "-af", "highpass=f=70,loudnorm=I=-16:TP=-1.5",
        "-ar", "44100", "-ac", "2", str(out)])
    raw.unlink(missing_ok=True)
    d = dur(out)
    if d < 0.3:
        raise ZeroMediaError(f"piper produced {d:.2f}s of audio for {text!r}")
    return d


def tts_lines(lines: list[str], outdir: Path, *, lang: str = "zh", gap: float = 0.35, speed: float = 1.0):
    """Synthesise each line; return (concat wav, [(start, end, text)])."""
    outdir.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    cues: list[tuple[float, float, str]] = []
    t = 0.0
    sil = outdir / "sil.wav"
    sh([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", str(gap), str(sil)])
    for i, line in enumerate(lines):
        p = outdir / f"vo_{i:02d}.wav"
        d = tts(line, p, lang=lang, speed=speed)
        cues.append((t, t + d, line))
        parts += [p, sil]
        t += d + gap
    lst = outdir / "vo.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    out = outdir / "vo.wav"
    sh([FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)])
    return out, cues


# ---------------------------------------------------------------- music / mix
def write_bgm(out: Path, seconds: float, mood: str = "warm", sr: int = 44100) -> Path:
    st = synth_bgm(seconds, mood=mood, sr=sr)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(st.tobytes())
    return out


def mix(vo: Path | None, music: Path | None, out: Path, total: float, music_db: float = -20) -> Path:
    """VO over music with sidechain ducking, padded/trimmed to ``total``."""
    if vo and music:
        fc = (f"[1:a]volume={music_db}dB,atrim=0:{total}[m];[0:a]apad,atrim=0:{total},asplit[v][sc];"
              f"[m][sc]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[d];"
              f"[v][d]amix=inputs=2:duration=longest:normalize=0,atrim=0:{total}[a]")
        sh([FFMPEG, "-y", "-v", "error", "-i", str(vo), "-i", str(music), "-filter_complex", fc,
            "-map", "[a]", "-ar", "44100", str(out)])
    else:
        src = vo or music
        if src is None:
            raise ZeroMediaError("mix needs voice or music")
        sh([FFMPEG, "-y", "-v", "error", "-i", str(src), "-af", f"apad,atrim=0:{total}", "-ar", "44100", str(out)])
    return out


# ---------------------------------------------------------------- Pexels
def _pexels_key() -> str:
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not key:
        raise ZeroMediaError("PEXELS_API_KEY is not configured (b-roll lines need the free Pexels API)")
    return key


def pexels(query: str, *, orientation: str = "landscape", min_d: float = 4, exclude: set[int] | None = None) -> dict[str, Any]:
    """Download one Pexels clip (free licence); returns provenance incl. local path.
    ``exclude`` = clip ids already used in this film (no shot is repeated)."""
    q = urllib.parse.quote(query)
    req = urllib.request.Request(
        f"https://api.pexels.com/videos/search?query={q}&per_page=15&orientation={orientation}",
        headers={"Authorization": _pexels_key(), "User-Agent": "hevi-zerolines"},
    )
    try:
        data = json.load(urllib.request.urlopen(req, timeout=20))
    except Exception as exc:  # network / auth: surface, never substitute
        raise ZeroMediaError(f"pexels search failed for {query!r}: {exc}") from exc
    vids = [v for v in data.get("videos", []) if v.get("duration", 0) >= min_d and v["id"] not in (exclude or set())]
    if not vids:
        raise ZeroMediaError(f"pexels: no usable clip for {query!r}")
    v = vids[0]
    key = "width" if orientation == "landscape" else "height"
    files = [f for f in v["video_files"] if f.get(key) and 1000 <= f[key] <= 2000 and f.get("file_type") == "video/mp4"]
    files = files or sorted(v["video_files"], key=lambda f: -(f.get(key) or 0))
    f = files[0]
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"pexels_{v['id']}_{f.get('width')}x{f.get('height')}.mp4"
    if not path.exists():
        part = path.with_suffix(".part")
        try:
            dreq = urllib.request.Request(f["link"], headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(dreq, timeout=180) as r, open(part, "wb") as o:
                o.write(r.read())
        except Exception as exc:
            part.unlink(missing_ok=True)
            raise ZeroMediaError(f"pexels download failed for {query!r}: {exc}") from exc
        part.rename(path)
    if exclude is not None:
        exclude.add(v["id"])
    return {"source": "pexels", "query": query, "pexels_id": v["id"], "page": v.get("url"),
            "author": (v.get("user") or {}).get("name"), "licence": "Pexels License (free)",
            "path": str(path), "duration": v.get("duration")}


# ---------------------------------------------------------------- shots / assembly
def shot(src: str | Path, out: Path, d: float, W: int, H: int, *, ss: float | None = None, move: str = "push",
         grade: str = "", fps: int = 30) -> Path:
    sd = dur(src)
    start = source_offset(source_dur=sd, d=d, ss=ss)
    vf = camera_filter(move=move, d=d, width=W, height=H, fps=fps, grade=grade)
    loop = ["-stream_loop", "-1"] if sd < d + start else []
    sh([FFMPEG, "-y", "-v", "error", *loop, "-ss", f"{start:.2f}", "-t", f"{d:.3f}", "-i", str(src), "-vf", vf,
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(fps), str(out)])
    return out


def xfade_concat(shots: list[Path], out: Path, xd: float = 0.5, trans: str = "fade") -> Path:
    if len(shots) == 1:
        sh([FFMPEG, "-y", "-v", "error", "-i", str(shots[0]), "-c", "copy", str(out)])
        return out
    graph, label = xfade_graph(durations=[dur(p) for p in shots], xd=xd, transition=trans)
    ins: list[str] = []
    for p in shots:
        ins += ["-i", str(p)]
    sh([FFMPEG, "-y", "-v", "error", *ins, "-filter_complex", graph, "-map", label, "-c:v", "libx264",
        "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(out)])
    return out


def subtitles_filter(ass: Path) -> str:
    return f"subtitles='{ass}':fontsdir={FONTS_DIR}"


def finish(video: Path, audio: Path | None, out: Path, ass: Path | None = None, extra_vf: str = "") -> Path:
    vf = [x for x in (extra_vf, subtitles_filter(ass) if ass else "") if x]
    args = [FFMPEG, "-y", "-v", "error", "-i", str(video)]
    if audio:
        args += ["-i", str(audio)]
    args += ["-vf", ",".join(vf) or "null", "-map", "0:v"]
    if audio:
        args += ["-map", "1:a", "-c:a", "aac", "-b:a", "160k", "-shortest"]
    args += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    sh(args)
    return out


def frames_to_video(frames: Iterable[np.ndarray], out: Path, W: int, H: int, fps: int = 24) -> Path:
    p = subprocess.Popen(
        [FFMPEG, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps),
         "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(out)],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert p.stdin is not None
    n = 0
    try:
        for fr in frames:
            p.stdin.write(np.ascontiguousarray(fr, dtype=np.uint8).tobytes())
            n += 1
    finally:
        p.stdin.close()
        err = p.stderr.read().decode("utf-8", "replace") if p.stderr else ""
        p.wait()
    if p.returncode or n == 0:
        raise ZeroMediaError(f"frame encode failed ({n} frames): {err[-800:]}")
    return out


def rms_envelope(wav: Path, fps: int) -> np.ndarray:
    raw = subprocess.check_output([FFMPEG, "-v", "error", "-i", str(wav), "-ac", "1", "-ar", "16000", "-f", "s16le", "-"])
    return rms_from_pcm(np.frombuffer(raw, np.int16).astype(np.float32) / 32768, fps=fps, sr=16000)


def whisper_segments(src: str | Path, lang: str) -> list[dict[str, Any]]:
    if not Path(WHISPER_MODEL).exists():
        raise ZeroMediaError(f"whisper model missing: {WHISPER_MODEL} (set HEVI_WHISPER_MODEL)")
    from faster_whisper import WhisperModel

    m = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8", cpu_threads=int(os.environ.get("HEVI_ZERO_WHISPER_THREADS", "4")))
    segs, _ = m.transcribe(str(src), language=lang, word_timestamps=True, vad_filter=True)
    out = [{"start": s.start, "end": s.end, "text": s.text.strip(),
            "words": [(w.start, w.end, w.word) for w in (s.words or [])]} for s in segs]
    if not out:
        raise ZeroMediaError(f"whisper found no speech in {src}")
    return out


# ---------------------------------------------------------------- measured QA
def probe(path: Path) -> dict[str, Any]:
    return json.loads(subprocess.check_output(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
         "-of", "json", str(path)], text=True))


def measure(path: Path, *, expect_size: tuple[int, int], thresholds: Any) -> dict[str, Any]:
    info = probe(path)
    streams = info.get("streams", [])
    d = float(info["format"]["duration"])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    raw = subprocess.check_output([FFMPEG, "-v", "error", "-i", str(path), "-vf", "fps=4,scale=96:54,format=gray",
                                   "-f", "rawvideo", "-"])
    stats = frame_stats(np.frombuffer(raw, np.uint8).reshape(-1, 54, 96))
    vol = None
    if a is not None:
        err = subprocess.run([FFMPEG, "-i", str(path), "-af", "volumedetect", "-vn", "-f", "null", "-"],
                             stderr=subprocess.PIPE, text=True).stderr
        for line in err.splitlines():
            if "mean_volume" in line:
                vol = float(line.split(":")[1].split()[0])
    verdict = judge(
        stats=stats, duration_s=d, has_video=v is not None, has_audio=a is not None, mean_volume_db=vol,
        width=int(v["width"]) if v else 0, height=int(v["height"]) if v else 0, expect_size=expect_size,
        min_motion=thresholds.min_motion, max_static_ratio=thresholds.max_static_ratio,
        max_black_ratio=thresholds.max_black_ratio, max_dark_ratio=thresholds.max_dark_ratio,
        min_volume_db=thresholds.min_volume_db, expect_audio=thresholds.expect_audio,
        min_duration_s=thresholds.min_duration_s,
    )
    return {
        "path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "duration": round(d, 3),
        "resolution": f"{v['width']}x{v['height']}" if v else None,
        "video_codec": v.get("codec_name") if v else None, "fps": v.get("r_frame_rate") if v else None,
        "audio_codec": a.get("codec_name") if a else None, "audio_channels": a.get("channels") if a else None,
        "mean_volume_db": vol, **{k: round(val, 3) for k, val in stats.items()},
        **verdict,
        **({"not_applicable_reason": thresholds.not_applicable_reason} if verdict["checks_not_applicable"] else {}),
    }


def contact_sheet(path: Path, out: Path, n: int = 6) -> Path:
    d = dur(path)
    tmp = out.parent / f".{out.stem}_frames"
    tmp.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        sh([FFMPEG, "-y", "-v", "error", "-ss", f"{d * (i + 0.5) / n:.2f}", "-i", str(path), "-frames:v", "1", "-vf",
            "scale=480:270:force_original_aspect_ratio=decrease,pad=480:270:(ow-iw)/2:(oh-ih)/2", str(tmp / f"{i}.jpg")])
    sh([FFMPEG, "-y", "-v", "error", "-i", str(tmp / "%d.jpg"), "-vf", "tile=3x2", "-frames:v", "1", str(out)])
    for f in tmp.iterdir():
        f.unlink()
    tmp.rmdir()
    return out
