"""Kids Gate: 幼儿动漫安全与节奏质检闸门 (Hevi quality gate for kids anime).

Checks:
1. Shot duration: single shot <2.5s -> fail, average <3.5s -> warn.
2. Photosensitive flashing: WCAG 2.3.1 / Harding rules, >3 flashes/s -> fail.
3. Loudness: integrated -16±1 LUFS, true peak <= -1.5 dBTP, adjacent 400ms short-term jump >10 LU -> fail.
4. Speech rate: >3.5 chars/sec -> fail.
5. Subtitle font size: portrait <56px -> fail.
6. Dialogue content: forbidden words list (violence, intimidation, disparagement, dangerous behavior, brand names).
7. Visual safety: CLIP zero-shot (optional/warn).
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

def load_safety_rules() -> dict[str, Any]:
    try:
        path = Path(__file__).parent.parent / "kids" / "data" / "kids_safety_rules.json"
        if not path.exists():
            path = Path("hevi/kids/data/kids_safety_rules.json")
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"whitelist": [], "categories": {}, "negative_modifiers": ["不", "没", "别", "不要", "不能"]}


def _load_forbidden_words_flat() -> list[str]:
    rules = load_safety_rules()
    words = []
    for cat, plist in rules.get("categories", {}).items():
        words.extend(plist)
    if not words:
        words = ["杀", "死", "毒药", "炸弹"]
    return words


FORBIDDEN_WORDS = _load_forbidden_words_flat()


# Characters that separate clauses. A negation marker separated from a
# candidate violation by any of these does NOT excuse it (R4/H3).
_CLAUSE_BREAKS = frozenset("，。！？；、,.!?;…\n\r\t “”‘’（）()【】\u3000")

# Max number of characters allowed between a negation marker and the word it
# negates. "不可以下毒" / "不打人" -> 0; "不吃药，…毒药" -> too far (R4/H3).
_NEG_GAP = 2


def _is_negated(text: str, phrase_start: int, neg_mods: list[str]) -> bool:
    """True only if a negation marker immediately precedes the violation.

    R4/H3: negation must directly modify the forbidden word. A negation that is
    far away or in a previous clause must not excuse the violation.
    """
    for neg in neg_mods:
        if not neg:
            continue
        start = 0
        while True:
            p = text.find(neg, start)
            if p == -1:
                break
            end = p + len(neg)
            gap = phrase_start - end
            if 0 <= gap <= _NEG_GAP:
                between = text[end:phrase_start]
                if not any(c in _CLAUSE_BREAKS for c in between):
                    return True
            start = p + 1
    return False


def check_content_safety_text(text: str) -> list[str]:
    rules = load_safety_rules()
    whitelist = rules.get("whitelist", [])
    categories = rules.get("categories", {})
    neg_mods = rules.get("negative_modifiers", ["不", "没", "别", "不要", "不能"])

    # R4/H1: mask whitelisted compounds (longest first) so a benign word such
    # as "一刀切菜" / "浇浇水" cannot trip a bare single-character rule.
    masked = text
    for w in sorted(whitelist, key=len, reverse=True):
        if w and w in masked:
            masked = masked.replace(w, "\u3000" * len(w))

    found_violations = []

    for _cat_name, phrases in categories.items():
        for phrase in phrases:
            if not phrase:
                continue
            if phrase in whitelist:
                continue

            idx = masked.find(phrase)
            while idx != -1:
                if not _is_negated(masked, idx, neg_mods):
                    found_violations.append(phrase)
                    break
                idx = masked.find(phrase, idx + 1)

    return sorted(set(found_violations))



@dataclass
class GateResult:
    passed: bool
    score: float = 1.0
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    timecodes: list[dict[str, Any]] = field(default_factory=list)


def probe_video_stats(path: Path) -> dict[str, Any]:
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(res.stdout)
    video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    fmt = data.get("format", {})
    return {
        "duration": float(fmt.get("duration", 0.0)),
        "width": int(video_stream.get("width", 0)),
        "height": int(video_stream.get("height", 0)),
        "has_audio": audio_stream is not None,
    }


def check_shot_duration(video_path: Path) -> GateResult:
    """Detect shot cuts via ffmpeg scdet or select filter."""
    res = GateResult(passed=True)
    stats = probe_video_stats(video_path)
    dur = stats["duration"]
    if dur <= 0:
        return res

    # Run ffmpeg select scene detection to find cut timestamps
    cmd = [
        "ffmpeg", "-hide_banner", "-i", str(video_path),
        "-vf", "select='gt(scene,0.3)',showinfo", "-f", "null", "-"
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    cuts = [0.0]
    for line in proc.stderr.splitlines():
        if "pts_time:" in line:
            parts = line.split("pts_time:")
            if len(parts) > 1:
                try:
                    t = float(parts[1].split()[0])
                    cuts.append(t)
                except ValueError:
                    pass
    cuts.append(dur)
    cuts = sorted(list(set(cuts)))

    shot_lengths = []
    for i in range(len(cuts) - 1):
        l = cuts[i+1] - cuts[i]
        shot_lengths.append(l)

    if not shot_lengths:
        shot_lengths = [dur]

    min_shot = min(shot_lengths)
    avg_shot = sum(shot_lengths) / len(shot_lengths)
    res.metrics["min_shot_duration"] = min_shot
    res.metrics["avg_shot_duration"] = avg_shot
    res.metrics["shot_count"] = len(shot_lengths)

    if min_shot < 2.5:
        res.passed = False
        res.violations.append(f"单镜头最短时长 {min_shot:.2f}s < 2.5s 违规")
        res.timecodes.append({"item": "shot_duration", "time": min_shot, "reason": "shot < 2.5s"})

    if avg_shot < 3.5:
        res.warnings.append(f"平均镜头时长 {avg_shot:.2f}s < 3.5s 警告")

    return res


def check_photosensitive_flash(video_path: Path) -> GateResult:
    """Check flashing using ffmpeg signalstats YAVG per frame."""
    res = GateResult(passed=True)
    cmd = [
        "ffmpeg", "-hide_banner", "-i", str(video_path),
        "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YAVG",
        "-f", "null", "-"
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    lumas = []
    for line in proc.stderr.splitlines():
        if "lavfi.signalstats.YAVG=" in line:
            try:
                val = float(line.split("lavfi.signalstats.YAVG=")[1].split()[0])
                lumas.append(val / 255.0)
            except ValueError:
                pass

    if len(lumas) < 5:
        return res

    # Count relative luminance swings >= 0.1
    transitions = 0
    flashes = 0
    direction = 0 # 1 up, -1 down
    last_val = lumas[0]
    for i, v in enumerate(lumas[1:], 1):
        diff = v - last_val
        if abs(diff) >= 0.1:
            new_dir = 1 if diff > 0 else -1
            if direction != 0 and new_dir != direction:
                flashes += 1
            direction = new_dir
            last_val = v

    stats = probe_video_stats(video_path)
    dur = stats["duration"] or 1.0
    flashes_per_sec = flashes / dur
    res.metrics["flashes_per_second"] = flashes_per_sec

    if flashes_per_sec > 3.0:
        res.passed = False
        res.violations.append(f"光敏闪烁频率 {flashes_per_sec:.2f} 次/秒 > 3次/秒 违规")
        res.timecodes.append({"item": "flash", "rate": flashes_per_sec})

    return res


def check_loudness(video_path: Path) -> GateResult:
    """Check loudness using ffmpeg ebur128."""
    res = GateResult(passed=True)
    stats = probe_video_stats(video_path)
    if not stats["has_audio"]:
        res.metrics["has_audio"] = False
        return res

    cmd = [
        "ffmpeg", "-nostats", "-hide_banner", "-i", str(video_path),
        "-af", "ebur128=peak=true", "-f", "null", "-"
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    stderr = proc.stderr or ""

    # Parse integrated loudness I
    i_lufs = -16.0
    m_i = re.search(r"Integrated loudness:\s*\n\s*I:\s*(-?[\d.]+) LUFS", stderr, re.IGNORECASE)
    if m_i:
        i_lufs = float(m_i.group(1))

    # Parse true peak
    true_peak = -1.5
    m_p = re.search(r"Peak:\s*(-?[\d.]+) dBFS", stderr)
    if m_p:
        true_peak = float(m_p.group(1))

    res.metrics["integrated_lufs"] = i_lufs
    res.metrics["true_peak_dbtp"] = true_peak

    if not (-17.0 <= i_lufs <= -15.0):
        res.passed = False
        res.violations.append(f"整体响度 {i_lufs:.1f} LUFS 超出 -16±1 LUFS 范围")

    if true_peak > -1.5:
        res.passed = False
        res.violations.append(f"真峰值 {true_peak:.1f} dBTP 超过 -1.5 dBTP 限制")

    # Check short term jumps (scare sound / sudden +10 LU jump)
    short_terms = []
    for line in stderr.splitlines():
        if "M:" in line or "S:" in line:
            # parse numeric LU
            match = re.search(r"([-\d.]+)\s*LU", line)
            if match:
                try:
                    short_terms.append(float(match.group(1)))
                except ValueError:
                    pass

    for a, b in zip(short_terms, short_terms[1:]):
        if abs(b - a) > 10.0:
            res.passed = False
            res.violations.append(f"相邻短时响度跳变 {abs(b-a):.1f} LU > 10 LU (惊吓音)")
            break

    return res


def check_speech_rate(srt_path: Path | None) -> GateResult:
    res = GateResult(passed=True)
    if not srt_path or not srt_path.exists():
        return res

    text = srt_path.read_text(encoding="utf-8", errors="ignore")
    def _ts(s: str) -> float:
        h, m, rest = s.split(":")
        sec, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000

    total_chars = 0
    total_duration = 0.0
    for line in text.splitlines():
        if "-->" not in line:
            continue
        a, b = (p.strip() for p in line.split("-->"))
        try:
            start = _ts(a)
            end = _ts(b.split()[0])
            dur = max(0.1, end - start)
            # Find the text in subsequent lines
            # For simplicity, we scan all non-timestamp lines
            total_duration += dur
        except Exception:
            pass

    # Count all non-whitespace chars in text
    clean_text = "".join(c for c in text if c not in "0123456789:,-->\n\r ")
    total_chars = len(clean_text)

    if total_duration > 0:
        rate = total_chars / total_duration
        res.metrics["speech_rate_chars_per_sec"] = rate
        if rate > 3.5:
            res.passed = False
            res.violations.append(f"语速 {rate:.2f} 字/秒 > 3.5 字/秒 违规")

    return res


def check_subtitle_fontsize(metadata_path: Path | None, video_path: Path) -> GateResult:
    res = GateResult(passed=True)
    stats = probe_video_stats(video_path)
    is_portrait = stats["height"] > stats["width"]

    font_px = 64
    if metadata_path and metadata_path.exists():
        try:
            meta = json.loads(metadata_path.read_text(encoding="utf-8"))
            font_px = int(meta.get("subtitle_font_px", 64))
        except Exception:
            pass

    res.metrics["subtitle_font_px"] = font_px
    res.metrics["is_portrait"] = is_portrait

    if is_portrait and font_px < 56:
        res.passed = False
        res.violations.append(f"竖屏字幕字号 {font_px}px < 56px 违规")

    return res


def check_dialogue_content(text_or_path: Path | str) -> GateResult:
    res = GateResult(passed=True)
    content = ""
    if isinstance(text_or_path, Path) and text_or_path.exists():
        content = text_or_path.read_text(encoding="utf-8", errors="ignore")
    else:
        content = str(text_or_path)

    found = check_content_safety_text(content)
    res.metrics["forbidden_words_found"] = found
    if found:
        res.passed = False
        res.violations.append(f"台词包含禁用词: {found}")

    return res


def kids_gate_workflow(
    video_path: Path,
    *,
    srt_path: Path | None = None,
    metadata_path: Path | None = None,
    profile: str = "kids",
) -> dict[str, Any]:
    """Execute all kids gate checks and return complete report dict."""
    vp = Path(video_path)
    sp = Path(srt_path) if srt_path else None
    mp = Path(metadata_path) if metadata_path else None

    r_shot = check_shot_duration(vp)
    r_flash = check_photosensitive_flash(vp)
    r_loud = check_loudness(vp)
    r_speech = check_speech_rate(sp)
    r_font = check_subtitle_fontsize(mp, vp)
    r_content = check_dialogue_content(sp if sp else vp)

    all_passed = all([
        r_shot.passed, r_flash.passed, r_loud.passed,
        r_speech.passed, r_font.passed, r_content.passed
    ])

    violations = (
        r_shot.violations + r_flash.violations + r_loud.violations +
        r_speech.violations + r_font.violations + r_content.violations
    )
    warnings = (
        r_shot.warnings + r_flash.warnings + r_loud.warnings +
        r_speech.warnings + r_font.warnings + r_content.warnings
    )
    timecodes = (
        r_shot.timecodes + r_flash.timecodes + r_loud.timecodes
    )

    verdict = "ok" if all_passed else "red"
    if not all_passed and warnings and not violations:
        verdict = "warn"

    report = {
        "status": verdict,
        "verdict": verdict,
        "passed": all_passed,
        "profile": profile,
        "path": str(vp),
        "violations": violations,
        "warnings": warnings,
        "timecodes": timecodes,
        "metrics": {
            **r_shot.metrics,
            **r_flash.metrics,
            **r_loud.metrics,
            **r_speech.metrics,
            **r_font.metrics,
            **r_content.metrics,
        }
    }
    return report
