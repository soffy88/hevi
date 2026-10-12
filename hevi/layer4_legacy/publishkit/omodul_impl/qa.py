"""成片交付 QA 与封面 QA（omodul 层：真实媒体测量，无 mock）。

上游 ``delivery-qa.md`` 的机器检查（ffprobe / 解码 / 黑帧 / 静音）全部真跑；
响度用 EBU R128（ebur128）实测；A/V 结束对齐按流时长实测；字幕越界按字幕轨
或渲染时的安全区配置检查。文稿没有字幕轨时如实标 ``unavailable``，不假装通过。
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

FFMPEG = "/home/soffy/.local/bin/ffmpeg"
FFPROBE = "/home/soffy/.local/bin/ffprobe"


class MediaError(RuntimeError):
    pass


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def probe(path: Path) -> dict[str, Any]:
    """ffprobe 实测：分辨率、fps、时长、音轨、帧数。"""

    raw = subprocess.check_output(
        [FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    )
    data = json.loads(raw)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if video is None:
        raise MediaError(f"NO_VIDEO_STREAM: {path}")
    fps = 0.0
    if video.get("r_frame_rate") and "/" in video["r_frame_rate"]:
        num, den = video["r_frame_rate"].split("/")
        fps = float(num) / float(den) if float(den) else 0.0
    fmt = data.get("format", {})
    return {
        "width": int(video.get("width", 0)),
        "height": int(video.get("height", 0)),
        "video_codec": video.get("codec_name", ""),
        "fps": round(fps, 3),
        "video_duration_s": round(float(video.get("duration", 0.0)), 3),
        "nb_frames": int(video.get("nb_frames", 0) or 0),
        "audio_codec": audio.get("codec_name", "") if audio else "",
        "sample_rate": int(audio.get("sample_rate", 0)) if audio else 0,
        "channels": int(audio.get("channels", 0)) if audio else 0,
        "audio_duration_s": round(float(audio.get("duration", 0.0)), 3) if audio else 0.0,
        "duration_s": round(float(fmt.get("duration", 0.0)), 3),
        "size_bytes": int(fmt.get("size", 0)),
    }


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def detect_black_and_silence(path: Path, *, black_d: float = 0.3, silence_d: float = 1.5) -> dict[str, Any]:
    r = _run([
        FFMPEG, "-nostdin", "-v", "info", "-i", str(path),
        "-vf", f"blackdetect=d={black_d}:pix_th=0.06",
        "-af", f"silencedetect=n=-45dB:d={silence_d}",
        "-f", "null", "-",
    ])
    black = [ln.split("] ")[-1] for ln in r.stderr.splitlines() if "black_start" in ln]
    silence = [ln.split("] ")[-1] for ln in r.stderr.splitlines() if "silence_start" in ln]
    decode_errors = [ln for ln in r.stderr.splitlines() if "error" in ln.lower() and "blackdetect" not in ln][:8]
    return {"black_segments": black, "silence_segments": silence, "decode_errors": decode_errors}


def _silence_start_s(entry: str) -> float | None:
    m = re.search(r"silence_start:\s*(-?[\d.]+)", entry)
    return float(m.group(1)) if m else None


def split_silence(segments: list[str], *, narration_end_s: float | None,
                  boundary_tolerance_s: float = 0.5) -> tuple[list[str], list[str]]:
    """区分"口播中间的静音"（要修）和"口播结束后的尾静默"（片尾卡，设计如此）。

    边界取最后一条字幕 cue 的结束时间；容差用于覆盖字幕尾留白
    （渲染配置 ``captions.tailSeconds``，本产线为 0.25s），避免把字幕尾巴
    误判成口播断句。口播结束点未知时，全部算作需要关注——不默认放行。
    """

    if narration_end_s is None:
        return segments, []
    cutoff = narration_end_s - boundary_tolerance_s
    in_body: list[str] = []
    trailing: list[str] = []
    for entry in segments:
        start = _silence_start_s(entry)
        if start is not None and start >= cutoff:
            trailing.append(entry)
        else:
            in_body.append(entry)
    return in_body, trailing


def measure_loudness(path: Path) -> dict[str, Any]:
    """EBU R128 响度实测（ebur128 summary）。"""

    r = _run([FFMPEG, "-nostdin", "-v", "info", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"])
    integrated = None
    true_peak = None
    lra = None
    for ln in r.stderr.splitlines():
        s = ln.strip()
        with suppress(ValueError):
            if s.startswith("I:"):
                integrated = float(s.split("I:")[1].split("LUFS")[0])
            elif s.startswith("LRA:"):
                lra = float(s.split("LRA:")[1].split("LU")[0])
            elif s.startswith("Peak:"):
                true_peak = float(s.split("Peak:")[1].split("dBFS")[0])
    if integrated is None:
        return {"integrated_lufs": None, "lra_lu": None, "true_peak_dbfs": None, "measured": False}
    return {
        "integrated_lufs": round(integrated, 2),
        "lra_lu": round(lra, 2) if lra is not None else None,
        "true_peak_dbfs": round(true_peak, 2) if true_peak is not None else None,
        "measured": True,
    }


def check_av_alignment(probe_data: dict[str, Any]) -> dict[str, Any]:
    """A/V 结束对齐：允许一帧量化误差。"""

    v = probe_data.get("video_duration_s") or 0.0
    a = probe_data.get("audio_duration_s") or 0.0
    fps = probe_data.get("fps") or 25.0
    frame = 1.0 / fps if fps else 0.04
    diff = abs(v - a)
    return {
        "video_duration_s": v,
        "audio_duration_s": a,
        "diff_s": round(diff, 3),
        "frame_budget_s": round(frame, 4),
        "within_one_frame": bool(diff <= frame + 1e-6),
    }


def decode_check(path: Path) -> dict[str, Any]:
    r = _run([FFMPEG, "-nostdin", "-v", "error", "-i", str(path), "-f", "null", "-"])
    lines = [ln for ln in r.stderr.splitlines() if ln.strip()]
    return {"ok": r.returncode == 0 and not lines, "messages": lines[:8]}


def parse_srt(path: Path) -> list[dict[str, Any]]:
    """读 SRT 字幕（真产物），返回按时间排好的 cue 列表。"""

    text = Path(path).read_text(encoding="utf-8")
    cues: list[dict[str, Any]] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        stamp = next((ln for ln in lines if "-->" in ln), None)
        if stamp is None:
            continue
        start, _, end = stamp.partition("-->")
        cues.append({
            "index": len(cues) + 1,
            "start_s": _srt_time(start),
            "end_s": _srt_time(end),
            "text": "".join(ln.strip() for ln in lines[lines.index(stamp) + 1:]),
        })
    return cues


def _srt_time(stamp: str) -> float:
    stamp = stamp.strip().replace(",", ".")
    parts = stamp.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        return int(parts[0]) * 60 + float(parts[1])
    except ValueError:
        return 0.0


def validate_caption_cues(cues: list[dict[str, Any]], duration_s: float) -> dict[str, Any]:
    """字幕区间：有序、不重叠、不越出片长（上游 delivery-qa.md 的机器检查项）。"""

    if not cues:
        return {"status": "unavailable", "reason": "没有字幕 cue 可校验", "passed": False}
    unordered: list[int] = []
    overlaps: list[dict[str, Any]] = []
    negative: list[int] = []
    for i, cue in enumerate(cues):
        if cue["start_s"] < 0 or cue["end_s"] <= cue["start_s"]:
            negative.append(cue["index"])
        if i > 0 and cue["start_s"] < cues[i - 1]["start_s"] - 1e-6:
            unordered.append(cue["index"])
        if i > 0 and cue["start_s"] < cues[i - 1]["end_s"] - 1e-6:
            overlaps.append({"a": cues[i - 1]["index"], "b": cue["index"]})
    last_end = max(c["end_s"] for c in cues)
    beyond = [c["index"] for c in cues if c["end_s"] > duration_s + 0.5]
    passed = not (unordered or overlaps or negative or beyond)
    return {
        "status": "measured_cues",
        "cue_count": len(cues),
        "ordered": not unordered,
        "non_overlapping": not overlaps,
        "all_positive_duration": not negative,
        "within_video_duration": not beyond,
        "last_cue_end_s": round(last_end, 3),
        "video_duration_s": duration_s,
        "violations": {"unordered": unordered, "overlaps": overlaps,
                       "non_positive": negative, "beyond_duration": beyond},
        "passed": passed,
    }


def measure_burned_caption_bounds(path: Path, *, samples: int = 8,
                                  baseline_y: int | None = None,
                                  workdir: Path | None = None) -> dict[str, Any]:
    """烧录字幕的像素实测：画面下缘"有内容"的最低行到底边的留白。

    只有在**知道字幕基线**时这个数才有意义——否则画面底部任何深色内容
    （卡片、遮罩、logo）都会被误判成字幕。所以：
    * 给了 ``baseline_y`` → 判定越界的 gate；
    * 没给 → 只记录，不参与判定（在报告里标明 informational）。
    """

    from PIL import Image

    info = probe(path)
    height = info["height"]
    width = info["width"]
    if not (width and height):
        return {"status": "unavailable", "reason": "视频流尺寸缺失"}

    scan_from = max(int(baseline_y or 0), int(height * 0.70))
    tmp = workdir or Path(tempfile.mkdtemp(prefix="capbounds-"))
    tmp.mkdir(parents=True, exist_ok=True)
    frames: list[dict[str, Any]] = []
    try:
        for i in range(samples):
            at_s = info["duration_s"] * (i + 0.5) / samples
            dest = tmp / f"cap_{i:02d}.png"
            _run([FFMPEG, "-y", "-v", "error", "-ss", f"{at_s:.3f}", "-i", str(path),
                  "-frames:v", "1", str(dest)])
            if not dest.is_file():
                continue
            with Image.open(dest) as im:
                gray = im.convert("L")
                crop = gray.crop((0, scan_from, width, height))
                px = crop.load()
                lowest = -1
                for y in range(crop.size[1]):
                    dark = 0
                    for x in range(0, crop.size[0], 3):
                        if px[x, y] < 90:
                            dark += 1
                    if dark >= (crop.size[0] // 3) * 0.12:
                        lowest = scan_from + y
            frames.append({"at_s": round(at_s, 2),
                           "lowest_content_row": lowest,
                           "bottom_gap_px": height - 1 - lowest})
            dest.unlink(missing_ok=True)
    finally:
        if workdir is None:
            shutil.rmtree(tmp, ignore_errors=True)

    if not frames:
        return {"status": "unavailable", "reason": "抽帧失败，无法实测字幕行位置"}

    min_gap = min(f["bottom_gap_px"] for f in frames)
    max_gap = max(f["bottom_gap_px"] for f in frames)
    min_required = max(2, round(height * 0.012))
    return {
        "status": "measured_pixels",
        "method": "burned_in_caption_row_scan",
        "informational": baseline_y is None,
        "frame_size": f"{width}x{height}",
        "scan_from_row": scan_from,
        "baseline_y": baseline_y,
        "samples": frames,
        "min_bottom_gap_px": min_gap,
        "max_bottom_gap_px": max_gap,
        "required_min_gap_px": min_required,
        "passed": bool(min_gap >= min_required),
        "reason": "字幕带最低行到画面底边的像素留白" + ("（无基线，仅记录）" if baseline_y is None else ""),
    }


def subtitle_overflow_check(
    path: Path,
    *,
    caption_box: dict[str, Any] | None,
    caption_cues: list[dict[str, Any]] | None,
    caption_source: str,
) -> dict[str, Any]:
    """字幕越界：cue 区间校验（主）+ 布局/像素（辅），三者都如实标注来源。"""

    raw = subprocess.check_output(
        [FFPROBE, "-v", "error", "-print_format", "json", "-show_streams", str(path)]
    )
    streams = json.loads(raw).get("streams", [])
    subs = [s for s in streams if s.get("codec_type") == "subtitle"]
    duration = probe(path)["duration_s"]

    cues_result = (
        validate_caption_cues(caption_cues, duration)
        if caption_cues else
        {"status": "unavailable", "reason": "未提供字幕 cue/字幕文件", "passed": False}
    )

    baseline = (caption_box or {}).get("baselineY")
    pixel = measure_burned_caption_bounds(path, baseline_y=baseline)
    layout: dict[str, Any] | None = None
    if caption_box:
        font_size = caption_box.get("fontSize", 0)
        height = caption_box.get("frame_height", 0)
        if height and baseline and font_size:
            bottom_margin = height - baseline
            layout = {
                "baselineY": baseline, "fontSize": font_size,
                "bottom_margin_px": bottom_margin,
                "passed": bool(bottom_margin >= font_size * 0.6),
            }

    gated = [cues_result]
    if layout is not None:
        gated.append({"passed": layout["passed"]})
    if baseline is not None:
        gated.append({"passed": pixel.get("passed")})

    return {
        "caption_source": caption_source,
        "subtitle_streams": len(subs),
        "cue_validation": cues_result,
        "pixel_measurement": pixel,
        "layout_check": layout,
        "passed": all(g.get("passed") for g in gated),
        "status": "measured" if cues_result["status"] == "measured_cues" else cues_result["status"],
    }


def run_delivery_qa(
    path: Path,
    *,
    caption_box: dict[str, Any] | None = None,
    caption_cues: list[dict[str, Any]] | None = None,
    caption_source: str = "none",
    narration_end_s: float | None = None,
    silent_tail_s: float = 0.0,
) -> dict[str, Any]:
    """成片交付机器验收（全部实测）。"""

    path = Path(path)
    probe_data = probe(path)
    anomalies = detect_black_and_silence(path)
    loudness = measure_loudness(path)
    av = check_av_alignment(probe_data)
    decode = decode_check(path)
    subtitle = subtitle_overflow_check(
        path, caption_box=caption_box, caption_cues=caption_cues, caption_source=caption_source
    )
    body_silence, trailing_silence = split_silence(
        anomalies["silence_segments"], narration_end_s=narration_end_s
    )
    trailing_len = 0.0
    if trailing_silence and narration_end_s is not None:
        starts = [s for s in (_silence_start_s(e) for e in trailing_silence) if s is not None]
        if starts:
            trailing_len = round(probe_data["duration_s"] - min(starts), 3)
    # 设计尾静默超出配置时长（例如片尾卡 5.5s + hold 1.5s）要如实报出来
    trailing_within_design = (silent_tail_s <= 0.0) or (trailing_len <= silent_tail_s + 0.75)

    if probe_data["width"] == 0 or probe_data["height"] == 0:
        raise MediaError(f"BAD_RESOLUTION: {path}")

    checks = [
        {"name": "resolution_written", "passed": probe_data["width"] > 0 and probe_data["height"] > 0,
         "value": f"{probe_data['width']}x{probe_data['height']}", "threshold": ">0"},
        {"name": "fps", "passed": probe_data["fps"] > 0, "value": probe_data["fps"], "threshold": ">0"},
        {"name": "audio_stream", "passed": bool(probe_data["audio_codec"]) and probe_data["sample_rate"] > 0,
         "value": f"{probe_data['audio_codec']}@{probe_data['sample_rate']}Hz", "threshold": "aac@>0Hz"},
        {"name": "no_silence_in_narration", "passed": not body_silence,
         "value": len(body_silence), "threshold": "0 段长静音(>1.5s)落在口播区间内"},
        {"name": "trailing_silence_within_design", "passed": trailing_within_design,
         "value": f"{trailing_len}s tail vs {silent_tail_s}s design",
         "threshold": "口播后尾静默 ≤ 设计尾长(+0.75s 容差)"},
        {"name": "no_black_frames", "passed": not anomalies["black_segments"],
         "value": len(anomalies["black_segments"]), "threshold": "0 段黑帧(>0.3s)"},
        {"name": "decode_clean", "passed": decode["ok"], "value": decode["messages"], "threshold": "无解码错误"},
        {"name": "av_end_aligned", "passed": av["within_one_frame"],
         "value": f"{av['diff_s']}s", "threshold": f"≤{av['frame_budget_s']}s(一帧)"},
        {"name": "loudness_measured", "passed": loudness["measured"],
         "value": loudness.get("integrated_lufs"), "threshold": "EBU R128 实测"},
        {"name": "subtitle_overflow", "passed": bool(subtitle.get("passed")),
         "value": subtitle.get("status"), "threshold": "字幕像素实测无越界"},
    ]

    return {
        "video": str(path),
        "sha256": sha256_file(path),
        "probe": probe_data,
        "loudness": loudness,
        "av_alignment": av,
        "decode": decode,
        "subtitle_overflow": subtitle,
        "anomalies": anomalies,
        "silence_in_narration": body_silence,
        "trailing_silence": {
            "segments": trailing_silence,
            "trailing_length_s": trailing_len,
            "narration_end_s": narration_end_s,
            "designed_tail_s": silent_tail_s,
            "within_design": trailing_within_design,
            "note": "口播结束后的尾静默（片尾卡/留白），按设计放行但如实记录",
        },
        "checks": checks,
        "passed": all(c["passed"] for c in checks),
    }