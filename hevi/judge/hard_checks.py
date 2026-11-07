"""Hard-defect checks that do not require a model."""
from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from pathlib import Path

from hevi.judge.types import HardCheckReport, HardFinding


def _run(cmd, timeout=300):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def probe_video(path):
    path = str(path)
    cp = _run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", path])
    try:
        data = json.loads(cp.stdout or "{}")
    except Exception:
        data = {}
    fmt = data.get("format", {}) or {}
    streams = data.get("streams", []) or []
    vstream = next((s for s in streams if s.get("codec_type") == "video"), None)
    astream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(fmt.get("duration") or 0.0)
    if duration <= 0 and vstream:
        duration = float(vstream.get("duration") or 0.0)
    return {
        "path": path,
        "duration": duration,
        "width": int(vstream.get("width", 0)) if vstream else 0,
        "height": int(vstream.get("height", 0)) if vstream else 0,
        "fps": vstream.get("r_frame_rate") if vstream else None,
        "has_video": vstream is not None,
        "has_audio": astream is not None,
        "audio_codec": astream.get("codec_name") if astream else None,
        "video_codec": vstream.get("codec_name") if vstream else None,
    }


def _mean_volume(path):
    cp = _run(["ffmpeg", "-i", str(path), "-af", "volumedetect", "-vn", "-sn", "-dn", "-f", "null", "-"])
    m = re.search(r"mean_volume:\s*(-?[\d.]+)\s*dB", cp.stderr or "")
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def check_duration(path, expected_s=None, tolerance=0.15):
    out = []
    info = probe_video(path)
    dur = info["duration"]
    if dur <= 0:
        out.append(HardFinding("duration", "blocker", "无法读取视频时长", dur))
        return out
    if expected_s is not None and expected_s > 0:
        dev = abs(dur - expected_s) / expected_s
        if dev > tolerance:
            out.append(HardFinding("duration_deviation", "major",
                                    f"时长偏差 {dev:.1%}（{dur:.2f}s vs 预期 {expected_s:.2f}s）", {"duration": dur, "expected": expected_s}))
    if dur < 3.0:
        out.append(HardFinding("duration_too_short", "major", f"视频过短 {dur:.2f}s", dur))
    return out


def check_audio(path):
    out = []
    info = probe_video(path)
    if not info["has_audio"]:
        out.append(HardFinding("no_audio_track", "blocker", "无音轨", None))
        return out
    mv = _mean_volume(path)
    if mv is not None and mv < -50.0:
        out.append(HardFinding("silent_audio", "major", f"音轨近似静音 (mean {mv:.1f} dB)", mv))
    return out


def check_black_frames(path):
    out = []
    info = probe_video(path)
    dur = info["duration"] or 1.0
    cp = _run(["ffmpeg", "-i", str(path), "-vf", "blackdetect=d=0.2:pix_th=0.10", "-an", "-f", "null", "-"])
    text = cp.stderr or ""
    total_black = 0.0
    for m in re.finditer(r"black_start:([\d.]+)\s*black_end:([\d.]+)\s*black_duration:([\d.]+)", text):
        try:
            total_black += float(m.group(3))
        except ValueError:
            pass
    ratio = total_black / dur if dur > 0 else 0.0
    if ratio > 0.15:
        out.append(HardFinding("black_frames", "major", f"黑屏占比 {ratio:.1%}", {"black_duration_s": total_black, "ratio": ratio}))
    return out


def check_frozen_frames(path):
    out = []
    cp = _run(["ffmpeg", "-i", str(path), "-vf", "freezedetect=n=-60dB:d=2", "-an", "-f", "null", "-"])
    text = cp.stderr or ""
    freezes = re.findall(r"freeze_start:([\d.]+)\s*freeze_duration:([\d.]+)\s*freeze_end:([\d.]+)", text)
    long_freezes = [f for f in freezes if float(f[1]) >= 3.0]
    if long_freezes:
        out.append(HardFinding("frozen_frames", "major", f"检测到 {len(long_freezes)} 处冻帧(≥3s)", long_freezes))
    return out


def _sample_frame_brightness(path, t):
    cp = _run(["ffmpeg", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1", "-vf", "signalstats", "-f", "null", "-"])
    text = cp.stderr or ""
    m = re.search(r"YAVG:([\d.]+)", text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def check_first_last_frames(path):
    out = []
    info = probe_video(path)
    dur = info["duration"]
    if dur <= 0:
        return out
    first = _sample_frame_brightness(str(path), 0.05)
    last = _sample_frame_brightness(str(path), max(0.0, dur - 0.1))
    if first is not None and first < 8:
        out.append(HardFinding("first_frame_black", "major", f"首帧近黑 (YAVG={first:.1f})", first))
    if last is not None and last < 8:
        out.append(HardFinding("last_frame_black", "minor", f"尾帧近黑 (YAVG={last:.1f})", last))
    return out


def check_repetition(path, threshold=0.85):
    out = []
    info = probe_video(path)
    dur = info["duration"]
    if dur <= 0:
        return out
    import hashlib
    n = 8
    hashes = []
    for i in range(n):
        t = dur * (i + 0.5) / n
        cp = subprocess.run(["ffmpeg", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "-"], capture_output=True)
        if cp.returncode == 0 and cp.stdout:
            hashes.append(hashlib.md5(cp.stdout).hexdigest())
    if hashes:
        c = Counter(hashes)
        dup = sum(v - 1 for v in c.values() if v > 1)
        ratio = dup / len(hashes) if hashes else 0.0
        if ratio > (1 - threshold):
            out.append(HardFinding("frame_repetition", "minor", f"抽样帧重复率 {ratio:.1%}", {"duplicate_frames": dup, "sampled": len(hashes)}))
    return out


def _parse_srt(text):
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.strip().splitlines()
        if len(lines) < 2:
            continue
        time_line = None
        for ln in lines:
            if "-->" in ln:
                time_line = ln
                break
        if not time_line:
            continue
        m = re.search(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})", time_line)
        if not m:
            continue
        def to_s(h, mm, s, ms):
            return int(h) * 3600 + int(mm) * 60 + int(s) + int(ms) / 1000.0
        start = to_s(m.group(1), m.group(2), m.group(3), m.group(4))
        end = to_s(m.group(5), m.group(6), m.group(7), m.group(8))
        content = "\n".join(l for l in lines if l != time_line and not l.strip().isdigit())
        cues.append((start, end, content))
    return cues


def check_subtitles(path, subtitle_path=None, duration=None):
    out = []
    if not subtitle_path:
        return out
    sp = Path(subtitle_path)
    if not sp.is_file():
        return out
    text = sp.read_text(encoding="utf-8", errors="ignore")
    if duration is None:
        duration = probe_video(path)["duration"]
    cues = _parse_srt(text)
    oob = [c for c in cues if c[1] > duration + 0.5 or c[0] < 0]
    if oob:
        out.append(HardFinding("subtitle_out_of_bounds", "major", f"{len(oob)} 条字幕越界", {"count": len(oob)}))
    mixed = 0
    for _, _, content in cues:
        has_cjk = bool(re.search(r"[\u4e00-\u9fff]", content))
        has_latin = bool(re.search(r"[A-Za-z]{3,}", content))
        if has_cjk and has_latin:
            mixed += 1
    if mixed:
        out.append(HardFinding("subtitle_mixed_script", "minor", f"{mixed} 条字幕中英混杂", {"count": mixed}))
    return out


MODEL_HARD_CHECK_PROMPT = """You are a video quality judge. Inspect the attached contact sheet (frames every 2s) and the metrics. Identify model-level hard defects: off-topic content, fabricated text/UI (fake subtitles, fake interface), audio-visual mismatch if cues exist, severe visual artifacts. Return ONLY JSON: {"findings": [{"name": "...", "severity": "blocker|major|minor", "detail": "..."}], "passed": true|false}. Empty findings if none."""


def run_model_hard_checks(backend, video_path):
    out = []
    try:
        res = backend.run(str(video_path), MODEL_HARD_CHECK_PROMPT)
        data = res.raw if isinstance(res.raw, dict) else extract_json(res.text) if False else None
    except Exception:
        return out
    from hevi.judge.backend import extract_json
    data = res.raw if isinstance(res.raw, dict) else extract_json(res.text)
    if not isinstance(data, dict):
        return out
    for f in (data.get("findings") or []):
        if not isinstance(f, dict):
            continue
        name = str(f.get("name") or "model_defect")
        sev = str(f.get("severity") or "minor")
        if sev not in ("blocker", "major", "minor"):
            sev = "minor"
        detail = str(f.get("detail") or "")
        out.append(HardFinding(name, sev, detail, None))
    return out


def run_hard_checks(video_path, *, expected_duration_s=None, subtitle_path=None, target_duration_s=None, backend=None):
    vp = str(video_path)
    findings = []
    metrics = {}
    info = probe_video(vp)
    metrics["probe"] = info
    if not info["has_video"]:
        findings.append(HardFinding("no_video_stream", "blocker", "无视频流", None))
    findings += check_duration(vp, expected_s=(expected_duration_s if expected_duration_s is not None else target_duration_s))
    findings += check_audio(vp)
    findings += check_black_frames(vp)
    findings += check_frozen_frames(vp)
    findings += check_first_last_frames(vp)
    findings += check_repetition(vp)
    findings += check_subtitles(vp, subtitle_path=subtitle_path, duration=info["duration"])
    if backend is not None:
        findings += run_model_hard_checks(backend, vp)
    passed = not any(f.severity in ("blocker", "major") for f in findings)
    return HardCheckReport(video_path=vp, passed=passed, findings=findings, metrics=metrics)


def _black_ratio(path):
    cp = _run(["ffmpeg", "-i", str(path), "-vf", "blackdetect=d=0.2:pix_th=0.10", "-an", "-f", "null", "-"])
    text = cp.stderr or ""
    total_black = 0.0
    for m in re.finditer(r"black_start:([\d.]+)\s*black_end:([\d.]+)\s*black_duration:([\d.]+)", text):
        try:
            total_black += float(m.group(3))
        except ValueError:
            pass
    dur = probe_video(path)["duration"] or 1.0
    return total_black / dur if dur > 0 else 0.0


def _freeze_count(path):
    cp = _run(["ffmpeg", "-i", str(path), "-vf", "freezedetect=n=-60dB:d=2", "-an", "-f", "null", "-"])
    text = cp.stderr or ""
    freezes = re.findall(r"freeze_start:([\d.]+)\s*freeze_duration:([\d.]+)\s*freeze_end:([\d.]+)", text)
    return sum(1 for f in freezes if float(f[1]) >= 2.0)


def _repetition_ratio(path):
    info = probe_video(path)
    dur = info["duration"]
    if dur <= 0:
        return 0.0
    import hashlib
    from collections import Counter
    n = 8
    hashes = []
    for i in range(n):
        t = dur * (i + 0.5) / n
        cp = subprocess.run(["ffmpeg", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "-"], capture_output=True)
        if cp.returncode == 0 and cp.stdout:
            hashes.append(hashlib.md5(cp.stdout).hexdigest())
    if not hashes:
        return 0.0
    c = Counter(hashes)
    dup = sum(v - 1 for v in c.values() if v > 1)
    return dup / len(hashes)


def _first_last_brightness(path):
    info = probe_video(path)
    dur = info["duration"]
    if dur <= 0:
        return None, None
    first = _sample_frame_brightness(str(path), 0.05)
    last = _sample_frame_brightness(str(path), max(0.0, dur - 0.1))
    return first, last


def local_quality_score(video_path, expected_duration_s=None):
    vp = str(video_path)
    rep = run_hard_checks(vp, expected_duration_s=expected_duration_s)
    info = rep.metrics.get("probe", {}) or probe_video(vp)
    score = 0.0
    for f in rep.findings:
        score += 100.0 if f.severity == "blocker" else 10.0 if f.severity == "major" else 1.0
    br = _black_ratio(vp)
    score += br * 50.0
    fc = _freeze_count(vp)
    score += fc * 5.0
    rr = _repetition_ratio(vp)
    score += rr * 20.0
    mv = _mean_volume(vp)
    if mv is not None:
        if mv < -45:
            score += (-45 - mv) * 2.0
        if mv > -3:
            score += (mv + 3) * 2.0
    first, last = _first_last_brightness(vp)
    for b in (first, last):
        if b is not None and b < 10:
            score += (10 - b)
    if expected_duration_s and expected_duration_s > 0 and info.get("duration", 0) > 0:
        score += abs(info["duration"] - expected_duration_s) / expected_duration_s * 10.0
    # duration floor preference: very short videos slightly penalized
    if info.get("duration", 0) < 5:
        score += 5.0
    return score, rep, info
