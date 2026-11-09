"""Side-effecting media helpers for zero-cost lines (omodul layer): ffmpeg /
ffprobe, Piper TTS, Pexels free-licence stock, faster-whisper, frame encoding,
measured QA, contact sheets.  CPU only.  Every failure raises ``ZeroMediaError``;
nothing here substitutes a placeholder for a missing input."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import time
import urllib.parse
import urllib.request
import wave
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np

from hevi.core.asr_paths import resolve_whisper_model
from hevi.layer4_legacy.talkcraft.omodul_impl._media import (
    FFMPEG,
    FFPROBE,
    PIPER,
    VOICE_DIR,
    VOICES,
)
from hevi.layer4_legacy.zerolines.oskill_impl.audio_math import rms_from_pcm, synth_bgm
from hevi.layer4_legacy.zerolines.oskill_impl.qa import frame_stats, judge
from hevi.layer4_legacy.zerolines.oskill_impl.shots import camera_filter, source_offset, xfade_graph

FONTS_DIR = os.environ.get("HEVI_ZERO_FONTS_DIR", "/usr/share/fonts/opentype/noto")
CACHE = Path(os.environ.get("HEVI_ZERO_CACHE", str(Path.home() / ".cache/hevi/zerolines")))
# Import-time best effort only; ``whisper_segments`` resolves again and raises a
# readable Chinese error when nothing is mounted.
WHISPER_MODEL = resolve_whisper_model(required=False) or ""


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


def _urlopen_with_retry(req, *, timeout=20, attempts=6, backoff=2.0):
    last = None
    for i in range(attempts):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except Exception as exc:  # network / auth: retry with backoff
            last = exc
            if i < attempts - 1:
                time.sleep(backoff * (2 ** i))
    raise last


def pexels(query: str, *, orientation: str = "landscape", min_d: float = 4, exclude: set[int] | None = None) -> dict[str, Any]:
    """Download one Pexels clip (free licence); returns provenance incl. local path.
    ``exclude`` = clip ids already used in this film (no shot is repeated)."""
    import time as _time
    key = _pexels_key()
    # try the query, then a shortened fallback
    search_terms = [query]
    words = query.split()
    if len(words) > 2:
        search_terms.append(" ".join(words[:2]))
    data = None
    last_exc = None
    for term in search_terms:
        cache_key = hashlib.sha256(f"{term}|{orientation}".encode()).hexdigest()[:16]
        cache_path = CACHE / f"pexels_search_{cache_key}.json"
        if cache_path.exists():
            try:
                data = json.loads(cache_path.read_text())
                break
            except Exception:
                data = None
        q = urllib.parse.quote(term)
        req = urllib.request.Request(
            f"https://api.pexels.com/videos/search?query={q}&per_page=15&orientation={orientation}",
            headers={"Authorization": key, "User-Agent": "hevi-zerolines"},
        )
        try:
            with _urlopen_with_retry(req, timeout=20, attempts=6, backoff=2.0) as resp:
                data = json.load(resp)
            CACHE.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(data))
            break
        except Exception as exc:
            last_exc = exc
            data = None
    if data is None:
        raise ZeroMediaError(f"pexels search failed for {query!r}: {last_exc}")
    vids = [v for v in data.get("videos", []) if v.get("duration", 0) >= min_d and v["id"] not in (exclude or set())]
    if not vids:
        raise ZeroMediaError(f"pexels: no usable clip for {query!r}")
    # relevance: prefer videos whose duration is closest to a sane 6-12s
    vids.sort(key=lambda v: abs((v.get("duration") or 0) - 8))
    v = vids[0]
    keydim = "width" if orientation == "landscape" else "height"
    files = [f for f in v["video_files"] if f.get(keydim) and 1000 <= f[keydim] <= 2000 and f.get("file_type") == "video/mp4"]
    files = files or sorted(v["video_files"], key=lambda f: -(f.get(keydim) or 0))
    f = files[0]
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"pexels_{v['id']}_{f.get('width')}x{f.get('height')}.mp4"
    if not path.exists():
        part = path.with_suffix(".part")
        ok = False
        for i in range(3):
            try:
                dreq = urllib.request.Request(f["link"], headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(dreq, timeout=180) as r, open(part, "wb") as o:
                    o.write(r.read())
                part.rename(path)
                ok = True
                break
            except Exception as exc:
                part.unlink(missing_ok=True)
                last_exc = exc
                _time.sleep(1.0 * (2 ** i))
        if not ok:
            raise ZeroMediaError(f"pexels download failed for {query!r}: {last_exc}")
    if exclude is not None:
        exclude.add(v["id"])
    return {"source": "pexels", "query": query, "pexels_id": v["id"], "page": v.get("url"),
            "author": (v.get("user") or {}).get("name"), "licence": "Pexels License (free)",
            "path": str(path), "duration": v.get("duration")}


# ---------------------------------------------------------------- shots / assembly
def pexels_photo(query: str, *, orientation: str = "portrait", min_w: int = 900,
                 exclude: set[str] | None = None) -> dict[str, Any]:
    """One free Pexels photo (same API/key as the video source).

    Photo search has much deeper coverage of historical/art subjects than the
    video library, and the API host is reachable from production containers
    where Wikimedia is not.
    """
    key = _pexels_key()
    cache_key = hashlib.sha256(f"photo|{query}|{orientation}".encode()).hexdigest()[:16]
    search_json = CACHE / f"pexels_photo_{cache_key}.json"
    data = None
    if search_json.exists():
        try:
            data = json.loads(search_json.read_text(encoding="utf-8"))
        except Exception:
            data = None
    if data is None:
        params = {"query": query, "per_page": "20", "orientation": orientation, "size": "large"}
        url = "https://api.pexels.com/v1/search?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"Authorization": key, "User-Agent": "hevi-zerolines"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.load(resp)
        CACHE.mkdir(parents=True, exist_ok=True)
        search_json.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    for photo in data.get("photos", []):
        pid = str(photo.get("id") or "")
        if not pid or pid in (exclude or set()):
            continue
        if int(photo.get("width") or 0) < min_w:
            continue
        src = (photo.get("src") or {})
        link = str(src.get("large2x") or src.get("large") or src.get("original") or "")
        if not link:
            continue
        path = CACHE / f"pexels_photo_{pid}.jpg"
        if not path.exists():
            part = path.with_suffix(".part")
            try:
                blob = _https_get(link, timeout=120, headers={"User-Agent": "Mozilla/5.0"})
                with open(part, "wb") as o:
                    o.write(blob)
                part.rename(path)
            except Exception:
                part.unlink(missing_ok=True)
                continue
        if exclude is not None:
            exclude.add(pid)
        return {"source": "pexels_photo", "query": query, "pexels_id": pid,
                "page": photo.get("url"), "author": photo.get("photographer"),
                "licence": "Pexels License (free)", "path": str(path)}
    raise ZeroMediaError(f"pexels photo: no usable image for {query!r}")


def topic_still(query: str, *, width: int = 1280, exclude: set[str] | None = None) -> dict[str, Any]:
    """Topic-specific still: Pexels photo first (production-reachable), Commons fallback."""
    orientation = "portrait" if width >= 1200 else "landscape"
    try:
        return pexels_photo(query, orientation=orientation, exclude=exclude)
    except Exception:
        return commons_image(query, width=width, exclude=exclude)


def commons_image(query: str, *, width: int = 1280, exclude: set[str] | None = None) -> dict[str, Any]:
    """One free Wikimedia Commons still for a topic (fallback for thin stock).

    Commons has deep coverage of historical/art subjects where Pexels video is
    thin.  License + author are returned so the renderer can log provenance.
    """
    key = hashlib.sha256(f"commons|{query}|{width}".encode()).hexdigest()[:16]
    cache_dir = CACHE / "commons"
    cache_dir.mkdir(parents=True, exist_ok=True)
    search_json = cache_dir / f"search_{key}.json"
    data = None
    if search_json.exists():
        try:
            data = json.loads(search_json.read_text(encoding="utf-8"))
        except Exception:
            data = None
    if data is None:
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": f"{query} filetype:bitmap",
            "gsrnamespace": "6",
            "gsrlimit": "12",
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|mime",
            "iiurlwidth": str(width),
            "format": "json",
        }
        url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
        data = json.loads(_https_get(url, timeout=20, headers={"User-Agent": "hevi-zerolines/1.0 (topic b-roll)"}))
        search_json.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    pages = (data.get("query") or {}).get("pages") or {}
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        mime = str(info.get("mime") or "")
        if mime not in ("image/jpeg", "image/png", "image/webp"):
            continue
        title = str(page.get("title") or "")
        if exclude and title in exclude:
            continue
        link = str(info.get("thumburl") or info.get("url") or "")
        if not link:
            continue
        ext = ".jpg" if mime == "image/jpeg" else (".png" if mime == "image/png" else ".webp")
        fname = "commons_" + hashlib.sha256(link.encode()).hexdigest()[:16] + ext
        path = cache_dir / fname
        if not path.exists():
            part = path.with_suffix(path.suffix + ".part")
            try:
                blob = _https_get(link, timeout=120, headers={"User-Agent": "Mozilla/5.0"})
                with open(part, "wb") as o:
                    o.write(blob)
                part.rename(path)
            except Exception:
                part.unlink(missing_ok=True)
                continue
        meta = info.get("extmetadata") or {}

        def _m(name: str, _meta: dict = meta) -> str:
            import html as _html
            return _html.unescape(str((_meta.get(name) or {}).get("value") or ""))
        if exclude is not None:
            exclude.add(title)
        return {
            "source": "wikimedia_commons", "query": query, "title": title,
            "page": (info.get("descriptionurl") or ""), "author": _m("Artist"),
            "licence": _m("LicenseShortName"), "path": str(path),
        }
    raise ZeroMediaError(f"commons: no usable image for {query!r}")


def still_shot(src: str | Path, out: Path, d: float, W: int, H: int, *, move: str = "push",
               grade: str = "", fps: int = 30) -> Path:
    """Animate a still (Ken Burns) into a fixed-size clip."""
    vf = camera_filter(move=move, d=d, width=W, height=H, fps=fps, grade=grade)
    sh([FFMPEG, "-y", "-v", "error", "-loop", "1", "-i", str(src), "-t", f"{d:.3f}", "-vf", vf,
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(fps), str(out)])
    return out


def _https_get(url: str, *, timeout: float, headers: dict[str, str] | None = None) -> bytes:
    """GET over HTTPS forcing IPv4 (some containers have AAAA records but no IPv6 route)."""
    import http.client
    import ssl

    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or 443
    infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
    sock = socket.create_connection(infos[0][4], timeout=timeout)
    ctx = ssl.create_default_context()
    ssock = ctx.wrap_socket(sock, server_hostname=host)
    conn = http.client.HTTPSConnection(host, port, context=ctx)
    conn.sock = ssock
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    conn.request("GET", path, headers=headers or {})
    resp = conn.getresponse()
    data = resp.read()
    status = resp.status
    conn.close()
    if status >= 400:
        raise ZeroMediaError(f"HTTPS {status} for {host}")
    return data


_LANG_PAIRS = {"zh": "zh-CN", "en": "en-GB"}


def translate_text(text: str, *, source: str = "zh", target: str = "en", timeout: float = 12.0) -> str:
    """Free machine translation (MyMemory, no key) with an on-disk cache.

    Returns "" on any error; callers keep the source line rather than inventing
    text.  Used by the localization line for the dub + bilingual subtitles.
    """
    import html

    text = (text or "").strip()
    if not text:
        return ""
    if source == target:
        return text
    key = hashlib.sha256(f"{source}>{target}:{text}".encode()).hexdigest()[:16]
    cache_dir = CACHE / "translate"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{key}.txt"
    if cached.exists():
        return cached.read_text(encoding="utf-8").strip()
    pair = f"{_LANG_PAIRS.get(source, source)}%7C{_LANG_PAIRS.get(target, target)}"
    try:
        url = (
            "https://api.mymemory.translated.net/get?q="
            + urllib.parse.quote(text)
            + f"&langpair={pair}"
        )
        data = json.loads(_https_get(url, timeout=timeout, headers={"User-Agent": "hevi-zerolines"}))
        out = html.unescape(str((data.get("responseData") or {}).get("translatedText") or "")).strip()
        # MyMemory sometimes echoes the query or returns an all-caps error string.
        if out and out.lower() != text.lower() and not out.isupper():
            cached.write_text(out, encoding="utf-8")
            return out
    except Exception:
        pass
    return ""


def translate_to_english(text: str, *, timeout: float = 6.0) -> str:
    """Free zh->en rendering of a topic for stock queries (no paid API)."""
    text = (text or "").strip()
    if not text:
        return ""
    if all(ord(ch) < 128 for ch in text):
        return text
    return translate_text(text, source="zh", target="en", timeout=timeout)


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
    args += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
             "-metadata", f"comment=run-{time.time():.6f}", "-movflags", "+faststart", str(out)]
    sh(args)
    return out


def frames_to_video(frames: Iterable[np.ndarray], out: Path, W: int, H: int, fps: int = 24) -> Path:
    p = subprocess.Popen(
        [FFMPEG, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps),
         "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
         "-metadata", f"comment=run-{time.time():.6f}", str(out)],
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


_WHISPER_CACHE: dict[str, Any] = {}


def whisper_segments(src: str | Path, lang: str) -> list[dict[str, Any]]:
    try:
        model_ref = resolve_whisper_model(required=True)
    except FileNotFoundError as exc:
        raise ZeroMediaError(str(exc)) from exc
    from faster_whisper import WhisperModel

    cache_key = f"{model_ref}:{os.environ.get('HEVI_ZERO_WHISPER_THREADS','4')}"
    m = _WHISPER_CACHE.get(cache_key)
    if m is None:
        m = WhisperModel(model_ref, device="cpu", compute_type="int8",
                         cpu_threads=int(os.environ.get("HEVI_ZERO_WHISPER_THREADS", "2")))
        _WHISPER_CACHE[cache_key] = m
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
