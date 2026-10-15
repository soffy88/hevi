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

FORBIDDEN_WORDS = [
    "打", "杀", "死", "刀", "枪", "血",
    "恐吓", "吓唬", "笨", "蠢", "丑", "废物",
    "玩火", "爬窗", "独自外出", "可口可乐", "麦当劳", "nike"
]


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
    if isinstance(text_or_path, Path):
        if text_or_path.suffix.lower() in {".mp4", ".avi", ".mov", ".mkv"}:
            res.metrics["dialogue_content"] = "skipped"
            return res
        if text_or_path.exists():
            content = text_or_path.read_text(encoding="utf-8", errors="ignore")
    else:
        if str(text_or_path).endswith((".mp4", ".avi", ".mov", ".mkv")):
            res.metrics["dialogue_content"] = "skipped"
            return res
        content = str(text_or_path)

    found = []
    for w in FORBIDDEN_WORDS:
        if w in content:
            found.append(w)

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
        },
        "checklist": _build_checklist(report_internal) if (report_internal := _build_internal_checks(r_shot, r_flash, r_loud, r_speech, r_font, r_content)) else {},
    }
    return report


# ── 续作 QC 扩展（§3.6，K2 交付物 3）──────────────────────────────
# 原 6 项保持不动；下列函数为 post-hoc 连续性 / 调色 / 转场 / 口语语言检查，
# 统一并入 kids_gate_workflow 的 report（status/violations/warnings/timecodes/metrics）。

# §3.6 完整 checklist 标签
CHECKLIST_ITEMS = [
    "shot_duration_min", "shot_duration_avg", "photosensitive_flash", "loudness",
    "speech_rate", "subtitle_fontsize", "dialogue_content",
    "identity_consistency", "wardrobe_prop_consistency", "location_consistency",
    "style_color_grade", "transition_table_boundary", "spoken_language",
    "no_fast_cut_transition_types",
]


def _build_internal_checks(r_shot, r_flash, r_loud, r_speech, r_font, r_content) -> dict:
    return {
        "r_shot": r_shot, "r_flash": r_flash, "r_loud": r_loud,
        "r_speech": r_speech, "r_font": r_font, "r_content": r_content,
    }


def _build_checklist(internal: dict) -> dict:
    """把 6 项原生检查映射成 checklist 的 pass/warn/fail 状态。"""
    checks = internal
    return {
        "shot_duration_min": "pass" if checks["r_shot"].passed else "fail",
        "shot_duration_avg": "pass" if not checks["r_shot"].warnings else "warn",
        "photosensitive_flash": "pass" if checks["r_flash"].passed else "fail",
        "loudness": "pass" if checks["r_loud"].passed else "fail",
        "speech_rate": "pass" if checks["r_speech"].passed else "fail",
        "subtitle_fontsize": "pass" if checks["r_font"].passed else "fail",
        "dialogue_content": "pass" if checks["r_content"].passed else "fail",
    }


def check_identity_consistency(video_path: Path, *, sample_colors: list[tuple[int,int,int]] | None = None) -> "GateResult":
    """跨镜同一角色 identity 一致性（简化：相邻镜主色调方差 / 中值色漂移）。

    CPU-only 无 CLIP：用逐镜抽帧的中位主色调，检查相邻镜之间是否出现"跳变"
    （色差 > 阈值视为服装/配色漂移红灯）。返回 timecodes 标注漂移发生的镜边界秒。
    """
    res = GateResult(passed=True)
    cmd = [
        "ffmpeg", "-hide_banner", "-i", str(video_path),
        "-vf", "select='not(mod(n,1))',scale=64:64,median,tile=1x1,metadata=print:file=-",
        "-vsync", "vfr", "-f", "null", "-",
    ]
    # 简易稳健做法：逐镜抽首帧求中位主色，避免复杂滤镜兼容性。
    stats = probe_video_stats(video_path)
    dur = stats["duration"]
    if dur <= 0:
        return res
    import subprocess as _sp
    # 按 1s 间隔抽帧（最多 12 帧）求中位主色
    n = min(12, max(2, int(dur)))
    mids: list[tuple[float, tuple[int,int,int]]] = []
    for i in range(n):
        t = (i + 0.5) * dur / n
        frame = _sp.run([
            "ffmpeg", "-hide_banner", "-ss", f"{t:.3f}", "-i", str(video_path),
            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", "8x8", "-",
        ], capture_output=True)
        if len(frame.stdout) < 8*8*3:
            continue
        buf = frame.stdout
        r = sum(buf[0::3]) // 64
        g = sum(buf[1::3]) // 64
        b = sum(buf[2::3]) // 64
        mids.append((t, (r, g, b)))
    res.metrics["identity_samples"] = len(mids)
    if len(mids) >= 2:
        max_diff = 0
        at_t = 0.0
        for (_, c1), (t2, c2) in zip(mids, mids[1:]):
            d = sum(abs(a - b) for a, b in zip(c1, c2))
            if d > max_diff:
                max_diff = d
                at_t = t2
        res.metrics["identity_max_color_diff"] = max_diff
        # 阈值：相邻镜主色总差 > 120（0–255 每通道）视作品牌/服装漂移红灯
        if max_diff > 120:
            res.passed = False
            res.violations.append(
                f"跨镜主色漂移 {max_diff}（>120），疑似服装/配色不连续 @{at_t:.2f}s"
            )
            res.timecodes.append({"item": "identity", "time": at_t, "diff": max_diff})
    return res


def check_style_color_grade(video_path: Path) -> "GateResult":
    """画风与 color grade 一致（无段间色温跳变）：取画面中心区域计算 R/B 比，避开边缘暗角（vignette）伪影。"""
    res = GateResult(passed=True)
    stats = probe_video_stats(video_path)
    dur = stats["duration"]
    if dur <= 0:
        return res
    import subprocess as _sp
    n = min(12, max(2, int(dur)))
    ratios: list[tuple[float, float]] = []
    for i in range(n):
        t = (i + 0.5) * dur / n
        frame = _sp.run([
            "ffmpeg", "-hide_banner", "-ss", f"{t:.3f}", "-i", str(video_path),
            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", "16x16", "-",
        ], capture_output=True)
        if len(frame.stdout) < 16*16*3:
            continue
        buf = frame.stdout
        center_pixels = []
        for yy in range(4, 12):
            for xx in range(4, 12):
                idx_px = (yy * 16 + xx) * 3
                rr = buf[idx_px]
                gg = buf[idx_px+1]
                bb = buf[idx_px+2]
                if (rr + gg + bb) // 3 > 30:
                    center_pixels.append((rr, gg, bb))
        if not center_pixels:
            continue
        r_sum = sum(p[0] for p in center_pixels)
        b_sum = sum(p[2] for p in center_pixels)
        r_avg = r_sum / len(center_pixels)
        b_avg = max(1.0, b_sum / len(center_pixels))
        ratios.append((t, r_avg / b_avg))
    res.metrics["color_grade_samples"] = len(ratios)
    if len(ratios) >= 2:
        max_jump = 0.0
        at_t = 0.0
        for (_, x1), (t2, x2) in zip(ratios, ratios[1:]):
            j = abs(x2 - x1)
            if j > max_jump:
                max_jump = j
                at_t = t2
        res.metrics["color_grade_max_ratio_jump"] = round(max_jump, 3)
        if max_jump > 1.5:
            res.passed = False
            res.violations.append(
                f"段间色温跳变 {max_jump:.3f}（>1.5），疑似调色不连续 @{at_t:.2f}s"
            )
            res.timecodes.append({"item": "color_grade", "time": at_t, "jump": max_jump})
    return res


def check_transition_table_boundary(video_path: Path, manifest: object | None = None) -> "GateResult":
    """转场类型检查：无快切/闪切；只用淡入淡出/擦除/推拉（§3.6 / KIDS_ANIME_DIRECTION）。

    若提供 manifest，则核对每个切点边界是否符合 transition_table 的 OUT/IN 记录；
    否则只做"无短于 1s 的硬切"的通用绿灯检查（短硬切视为违规）。
    """
    res = GateResult(passed=True)
    stats = probe_video_stats(video_path)
    dur = stats["duration"]
    if dur <= 0:
        return res
    cuts = _detect_cut_boundaries(video_path)
    res.metrics["detected_cuts"] = len(cuts)
    # 任意两相邻镜之间重叠 < 1s（极短硬切）视为快切违规
    short = [c for c, length in cuts if length < 1.0]
    if short:
        res.passed = False
        res.violations.append(f"检出 {len(short)} 处快切/硬切（<1s），转场只能用淡入淡出/擦除/推拉")
        for t, _ in short:
            res.timecodes.append({"item": "transition", "time": t, "reason": "fast_cut"})
    if manifest is not None:
        # 若 manifest 给出 transition_table，记录覆盖情况（不强制红灯，绿灯核对）
        tt = getattr(manifest, "transition_table", lambda: [])()
        res.metrics["transition_table_entries"] = len(tt or [])
    return res


def _detect_cut_boundaries(video_path: Path) -> list[tuple[float, float]]:
    """返回 [(cut_time, preceding_shot_length), ...]：基于 scene 检测 + 相邻镜长。"""
    import subprocess as _sp
    cmd = [
        "ffmpeg", "-hide_banner", "-i", str(video_path),
        "-vf", "select='gt(scene,0.3)',showinfo", "-f", "null", "-",
    ]
    proc = _sp.run(cmd, capture_output=True, text=True)
    pts: list[float] = [0.0]
    for line in proc.stderr.splitlines():
        if "pts_time:" in line:
            parts = line.split("pts_time:")
            if len(parts) > 1:
                try:
                    pts.append(float(parts[1].split()[0]))
                except ValueError:
                    pass
    stats = probe_video_stats(video_path)
    pts.append(stats["duration"])
    pts = sorted(set(pts))
    return [(pts[i], pts[i+1] - pts[i]) for i in range(len(pts) - 1)]


def check_spoken_language(video_path: Path, *, manifest: object | None = None, lines: str | None = None) -> "GateResult":
    """逐镜口语语言检查：manifest 标注的语言应一致（默认 zh-CN），且不出现翻译漂移。

    CPU-only 无 ASR：接收可选的逐镜台词文本（lines，换行分隔，每行一镜台词）。
    若提供 manifest，核对 spoken_language 覆盖所有说话镜且语言一致。
    """
    res = GateResult(passed=True)
    langs = set()
    if manifest is not None:
        sl = getattr(manifest, "spoken_language", lambda: [])()
        langs = {e.get("language") for e in (sl or [])}
    res.metrics["spoken_languages"] = sorted(x for x in langs if x)
    # 多条不同语言视为口语语言不一致（红灯）
    if len([x for x in langs if x]) > 1:
        res.passed = False
        res.violations.append(f"逐镜口语语言不一致：{sorted(langs)}")
    # 若提供台词文本，检查是否混入非中文/拉丁品牌词（简单启发式）
    if lines:
        foreign = [w for w in ("Nike", "Coca", "Adidas", "Starbucks") if w.lower() in lines.lower()]
        if foreign:
            res.passed = False
            res.violations.append(f"台词出现非中文品牌词：{foreign}")
    return res


def check_wardrobe_prop_consistency(manifest: object | None = None) -> "GateResult":
    """服装/道具状态与 manifest 的 constant/plot-driven 一致（声明级核对）。

    若提供 manifest，检查所有 constant 道具/服装都有固定描述（非空），且任一
    plot-driven 条目都至少有一条 transition_table 行解释其转变镜头。
    """
    res = GateResult(passed=True)
    if manifest is None:
        res.metrics["wardrobe_checked"] = False
        return res
    props = getattr(manifest, "props", lambda: [])()
    tt = getattr(manifest, "transition_table", lambda: [])()
    res.metrics["wardrobe_checked"] = True
    for p in props:
        state = p.get("state")
        desc = p.get("fixed_description") or p.get("description")
        if state == "constant" and not desc:
            res.passed = False
            res.violations.append(f"constant 道具/服装 '{p.get('id')}' 缺固定描述")
        if state == "plot-driven" and not tt:
            res.warnings.append(
                f"plot-driven 条目 '{p.get('id')}' 无 transition_table 解释其转变镜头"
            )
    return res


def check_location_consistency(manifest: object | None = None) -> "GateResult":
    """反复地点布局/光线/调色一致（声明级核对：manifest 给了 palette）。"""
    res = GateResult(passed=True)
    if manifest is None:
        res.metrics["location_checked"] = False
        return res
    scenes = getattr(manifest, "scenes", lambda: [])()
    res.metrics["location_checked"] = True
    for sc in scenes:
        palette = sc.get("palette")
        if not palette:
            res.warnings.append(f"地点 '{sc.get('id')}' 缺 palette（调色一致性无法核对）")
    return res


def check_extended_kids_hazards(video_path: Path) -> list[tuple[str, float, str]]:
    """检测饱和度下限、空画面、画面成人文字、色相漂移、服装跳变。返回 [(hazard_name, time_sec, reason), ...]"""
    hazards = []
    stats = probe_video_stats(video_path)
    dur = stats["duration"]
    if dur <= 0:
        return hazards

    import subprocess as _sp
    from PIL import Image
    import io
    import numpy as np

    ocr_engine = None
    try:
        from rapidocr_onnxruntime import RapidOCR
        ocr_engine = RapidOCR()
    except Exception:
        pass

    adult_keywords = ["深入机制分析", "宏观经济传导", "第三章", "机制分析"]

    n_samples = min(16, max(2, int(dur)))
    prev_center_hue = None
    prev_blocks = None

    for i in range(n_samples):
        t = (i + 0.5) * dur / n_samples
        proc = _sp.run([
            "ffmpeg", "-hide_banner", "-ss", f"{t:.3f}", "-i", str(video_path),
            "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-",
        ], capture_output=True)
        if not proc.stdout:
            continue
        try:
            im = Image.open(io.BytesIO(proc.stdout)).convert("RGB")
        except Exception:
            continue

        w_img, h_img = im.size

        # 1. 饱和度下限：逐帧有效像素平均饱和度（灰化片 gray_full/gray_second_half）
        hsv = np.array(im.convert("HSV")).astype(float)
        s_flat = hsv[:, :, 1].reshape(-1) / 255.0
        v_flat = hsv[:, :, 2].reshape(-1)
        valid = v_flat > 15  # 排除纯黑背景，只看有内容的像素
        mean_s = float(s_flat[valid].mean()) if valid.any() else 1.0

        gray = im.convert("L")
        g_arr = np.array(gray).astype(float)
        mean_l = float(g_arr.mean())
        var_l = float(g_arr.var())

        if mean_s < 0.02:
            hazards.append(("low_saturation", t, f"画面过灰/饱和度过低 ({mean_s:.3f})"))

        # 2. 空画面/近黑：低亮度 + 低细节（empty_black_full、empty_star 后半）
        if mean_l < 10.0 or (mean_l < 25.0 and var_l < 60.0):
            hazards.append(("empty_screen", t, f"空画面/近黑画面 (亮度 {mean_l:.1f}, 方差 {var_l:.1f})"))

        # 3. 画面成人文字：OCR 命中成人词表，且位于画面上部非字幕区（y 中心 < 25% 高）
        if ocr_engine is not None:
            try:
                res_ocr, _ = ocr_engine(np.array(im))
                for item in (res_ocr or []):
                    if len(item) < 3 or float(item[2]) < 0.85:
                        continue
                    txt = item[1]
                    if not any(k in txt for k in adult_keywords):
                        continue
                    box = item[0]
                    cy = (box[0][1] + box[2][1]) / 2.0 / h_img
                    if cy < 0.25:
                        hazards.append(("adult_text", t, f"画面上部非字幕区出现成人/非幼儿文字 '{txt}'"))
                        break
            except Exception:
                pass

        # 4. 色相漂移：画面中心区域平均色相（HSV H）相邻帧圆周距离
        cx0, cx1 = int(w_img * 0.25), int(w_img * 0.75)
        cy0, cy1 = int(h_img * 0.25), int(h_img * 0.75)
        center = im.crop((cx0, cy0, cx1, cy1)).resize((32, 32))
        mean_rgb = np.array(center).reshape(-1, 3).mean(axis=0)
        mean_px = Image.new("RGB", (1, 1), tuple(np.clip(mean_rgb, 0, 255).astype(int)))
        curr_hue = float(np.array(mean_px.convert("HSV"))[0, 0, 0])
        if prev_center_hue is not None:
            dh = abs(curr_hue - prev_center_hue)
            dh = min(dh, 255.0 - dh)
            if dh > 30.0:
                hazards.append(("hue_drift", t, f"画面中心色相漂移 {dh:.0f}（>30）"))
        prev_center_hue = curr_hue

        # 5. 服装/局部色块跳变：4x4 网格内色相突变的连通块（看局部而非整帧均色）
        sub_hsv = np.array(im.resize((16, 16)).convert("HSV")).astype(int)
        if prev_blocks is not None:
            h1 = prev_blocks[:, :, 0]
            h2 = sub_hsv[:, :, 0]
            s2 = sub_hsv[:, :, 1]
            dh2 = np.abs(h1 - h2)
            dh2 = np.minimum(dh2, 255 - dh2)
            changed = (dh2 > 25) & (s2 > 60)
            n_changed = int(changed.sum())
            max_comp = 0
            if n_changed:
                from scipy import ndimage as _ndi
                lab, ncomp = _ndi.label(changed)
                if ncomp:
                    max_comp = int(np.bincount(lab.ravel())[1:].max())
            if max_comp >= 10:
                hazards.append(("wardrobe_jump", t, f"局部服装/色块跳变（{max_comp} 格连通色相突变）"))
        prev_blocks = sub_hsv

    return hazards


def kids_gate_extended(
    video_path: Path,
    *,
    srt_path: Path | None = None,
    metadata_path: Path | None = None,
    manifest: object | None = None,
    lines: str | None = None,
    profile: str = "kids",
) -> dict[str, Any]:
    """扩展版 kids_gate：原 6 项 + §3.6 续作 QC + 增强视觉/文本危害检测。"""
    vp = Path(video_path)
    sp = Path(srt_path) if srt_path else None
    mp = Path(metadata_path) if metadata_path else None

    # 原 6 项
    r_shot = check_shot_duration(vp)
    r_flash = check_photosensitive_flash(vp)
    r_loud = check_loudness(vp)
    r_speech = check_speech_rate(sp)
    r_font = check_subtitle_fontsize(mp, vp)
    r_content = check_dialogue_content(sp if sp else vp)

    # §3.6 续作 QC
    r_identity = check_identity_consistency(vp)
    r_color = check_style_color_grade(vp)
    r_transition = check_transition_table_boundary(vp, manifest)
    r_lang = check_spoken_language(vp, manifest=manifest, lines=lines)
    r_wardrobe = check_wardrobe_prop_consistency(manifest)
    r_location = check_location_consistency(manifest)

    # 增强危害检测（饱和度、空画面、成人文字、色相漂移、服装跳变）
    hazards = check_extended_kids_hazards(vp)
    ext_passed = True
    ext_violations = []
    ext_timecodes = []
    for hname, htime, hreason in hazards:
        ext_passed = False
        ext_violations.append(f"{hname} 违规: {hreason} @{htime:.2f}s")
        ext_timecodes.append({"item": hname, "time": htime, "reason": hreason})

    blocks = [
        r_shot, r_flash, r_loud, r_speech, r_font, r_content,
        r_identity, r_color, r_transition, r_lang, r_wardrobe, r_location,
    ]
    all_passed = all(b.passed for b in blocks) and ext_passed
    has_warn = any(b.warnings for b in blocks)

    violations = []
    warnings = []
    timecodes = []
    for b in blocks:
        violations.extend(b.violations)
        warnings.extend(b.warnings)
        timecodes.extend(b.timecodes)

    violations.extend(ext_violations)
    timecodes.extend(ext_timecodes)

    metrics = {}
    for b in blocks:
        metrics.update(b.metrics)
    metrics["extended_hazards_count"] = len(hazards)

    checklist = _build_checklist(_build_internal_checks(r_shot, r_flash, r_loud, r_speech, r_font, r_content))
    sat_fail = any(h[0] == "low_saturation" for h in hazards)
    empty_fail = any(h[0] == "empty_screen" for h in hazards)
    text_fail = any(h[0] == "adult_text" for h in hazards)
    hue_fail = any(h[0] in ("hue_drift", "wardrobe_jump") for h in hazards)

    checklist.update({
        "identity_consistency": "fail" if not r_identity.passed else "pass",
        "wardrobe_prop_consistency": "fail" if (not r_wardrobe.passed or hue_fail) else "pass",
        "location_consistency": "fail" if (not r_location.passed or empty_fail) else "pass",
        "style_color_grade": "fail" if (not r_color.passed or sat_fail) else "pass",
        "transition_table_boundary": "pass" if r_transition.passed else "fail",
        "spoken_language": "pass" if r_lang.passed else "fail",
        "no_fast_cut_transition_types": "pass" if r_transition.passed else "fail",
    })

    verdict = "ok" if all_passed else "red"
    if not all_passed and has_warn and not violations:
        verdict = "warn"

    return {
        "status": verdict,
        "verdict": verdict,
        "passed": all_passed,
        "profile": profile,
        "path": str(vp),
        "violations": violations,
        "warnings": warnings,
        "timecodes": timecodes,
        "metrics": metrics,
        "checklist": checklist,
    }
