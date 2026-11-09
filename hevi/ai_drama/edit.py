"""Edit list, subtitles, FCPXML / 剪映 plan and ffmpeg assembly."""

from __future__ import annotations

import contextlib
import functools
import html
import json
import operator
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .schema import estimate_seconds, iter_dialogue, iter_shots
from .voice import make_silence

FFMPEG = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/usr/bin/ffprobe"
CJK_FONT = Path("/home/soffy/.fonts/simhei.ttf")

SUBTITLE_STYLES = {
    "said": {"color": "#FFFFFF", "outline": "#000000", "italic": False},
    "inner": {"color": "#FFD166", "outline": "#1A1A1A", "italic": True},
    "vo": {"color": "#8FD3FF", "outline": "#10202B", "italic": False},
}


def _fmt_srt(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = round((t - int(t)) * 1000)
    if ms == 1000:
        s += 1
        ms = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ass_time(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    cs = round((t - int(t)) * 100)
    if cs == 100:
        s += 1
        cs = 0
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _voice_lookup(voice_plan: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
    lookup: dict[tuple[str, str, str], dict[str, Any]] = {}
    for line in (voice_plan.get("lines") or {}).values():
        key = (str(line.get("speaker")), str(line.get("text")), str(line.get("kind") or "said"))
        lookup[key] = line
    return lookup


def fit_storyboard_to_audio(storyboard: dict[str, Any], voice_plan: dict[str, Any]) -> None:
    """Grow shot/segment durations so every dialogue line fits its shot."""
    lookup = _voice_lookup(voice_plan)
    for seg in storyboard.get("segments") or []:
        for shot in seg.get("shots") or []:
            need = 0.0
            for line in shot.get("dialogue") or []:
                key = (str(line.get("speaker")), str(line.get("text")), str(line.get("kind") or "said"))
                info = lookup.get(key)
                if info:
                    need += float(info.get("duration_s") or 0)
                else:
                    need += estimate_seconds(str(line.get("text") or ""))
            need += 0.5 if need else 0.0
            shot["duration_s"] = round(min(8.0, max(float(shot.get("duration_s") or 0), need, 2.0)), 2)
        seg["duration_s"] = round(sum(float(s.get("duration_s") or 0) for s in seg.get("shots") or []), 2)


def build_edit(
    storyboard: dict[str, Any],
    script: dict[str, Any],
    voice_plan: dict[str, Any],
    out_dir: Path,
    *,
    clip_paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    lookup = _voice_lookup(voice_plan)
    items: list[dict[str, Any]] = []
    subtitles: list[dict[str, Any]] = []
    overlays: list[dict[str, Any]] = []
    cursor = 0.0
    shot_list = list(iter_shots(storyboard))
    for idx, shot in enumerate(shot_list):
        dur = float(shot.get("duration_s") or 0)
        item = {
            "shot_id": shot.get("shot_id"),
            "scene_id": shot.get("scene_id"),
            "start_s": round(cursor, 3),
            "end_s": round(cursor + dur, 3),
            "duration_s": round(dur, 3),
            "clip": (clip_paths or {}).get(str(shot.get("shot_id"))) or shot.get("image") or "",
            "dialogue": [dict(line) for line in shot.get("dialogue") or []],
            "mode": shot.get("mode", "talking"),
            "sfx": str(shot.get("sfx") or ""),
        }
        items.append(item)
        line_cursor = cursor + 0.15
        for line in shot.get("dialogue") or []:
            key = (str(line.get("speaker")), str(line.get("text")), str(line.get("kind") or "said"))
            info = lookup.get(key) or {}
            line_dur = float(info.get("duration_s") or estimate_seconds(str(line.get("text") or "")))
            start = line_cursor
            end = min(cursor + dur - 0.1, line_cursor + line_dur)
            subtitles.append({
                "shot_id": shot.get("shot_id"),
                "speaker": str(line.get("speaker")),
                "text": str(line.get("text") or ""),
                "kind": str(line.get("kind") or "said"),
                "start_s": round(start, 3),
                "end_s": round(max(start + 0.5, end), 3),
                "audio": info.get("path", ""),
            })
            if line_dur > 5.0:
                reaction = next(
                    (s for s in shot_list[idx + 1: idx + 3]
                     if str(s.get("mode")) in ("reaction", "insert") and not s.get("dialogue")),
                    None,
                )
                if reaction is not None:
                    overlays.append({
                        "during_shot": shot.get("shot_id"),
                        "reaction_shot": reaction.get("shot_id"),
                        "start_s": round(start + max(1.0, line_dur - 1.8), 3),
                        "duration_s": 1.5,
                    })
            line_cursor += line_dur + 0.08
        cursor += dur

    total = round(cursor, 3)
    script_lines = [(str(line.get("speaker")), str(line.get("text") or "")) for _, _, line in iter_dialogue(script)]
    sub_lines = [(row["speaker"], row["text"]) for row in subtitles]
    if script_lines != sub_lines:
        raise ValueError("剪辑字幕与剧本不一致（逐字对齐检查失败）")

    sfx_cues = [
        {"t": round(float(item.get("start_s") or 0), 3), "name": str(item.get("sfx")), "gain": 0.8}
        for item in items if str(item.get("sfx") or "").strip()
    ]
    edit = {
        "episode_no": storyboard.get("episode_no", 1),
        "title": storyboard.get("title", script.get("title", "")),
        "aspect": "9:16",
        "duration_s": total,
        "items": items,
        "subtitles": subtitles,
        "subtitle_styles": SUBTITLE_STYLES,
        "reaction_overlays": overlays,
        "layers": ["dialogue", "sfx", "music"],
        "loudness": {"target_lufs": -14.0, "true_peak": -1.5, "lra": 11},
        "sfx_cues": sfx_cues,
        "bgm": script.get("bgm"),
        "bgm_allowed": bool(script.get("bgm_allowed", bool(script.get("bgm")))),
        "ending_suspense": str(
            script.get("ending_suspense")
            or (script.get("scenes") or [{}])[-1].get("beats", [{}])[-1].get("event", "")
            or "停在未回答的问题上"
        ),
        "ai_label": True,
        "ai_label_text": "AI 生成",
        "ui_overlays": (script.get("game_pov") or {}).get("ui_overlays") or [],
        "dialogue_box": (script.get("game_pov") or {}).get("dialogue_box"),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "edit_list.json").write_text(json.dumps(edit, ensure_ascii=False, indent=2), encoding="utf-8")
    return edit


def write_ass(edit: dict[str, Any], out_path: Path, *, width: int = 1080, height: int = 1920) -> Path:
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Said,Noto Sans CJK SC,58,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,4,2,2,60,60,150,1",
        "Style: Inner,Noto Sans CJK SC,54,&H0066D1FF,&H0066D1FF,&H00101010,&H80000000,0,1,0,0,100,100,0,0,1,4,2,2,60,60,150,1",
        "Style: VO,Noto Sans CJK SC,54,&H00FFD38F,&H00FFD38F,&H0010202B,&H80000000,0,0,0,0,100,100,0,0,1,4,2,2,60,60,150,1",
        "Style: AI,Noto Sans CJK SC,30,&H00E0E0E0,&H00E0E0E0,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,0,3,0,0,40,1",
        "Style: Secondary,Noto Sans CJK SC,42,&H00EAF4FF,&H00EAF4FF,&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,60,60,150,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    style_for = {"said": "Said", "inner": "Inner", "vo": "VO"}
    for row in edit.get("subtitles") or []:
        text = str(row.get("text") or "").replace("\n", r"\N")
        secondary = str(row.get("secondary") or "").replace("\n", r"\N")
        if secondary:
            text = f"{text}\\N{{\\rSecondary}}{secondary}"
        lines.append(
            f"Dialogue: 0,{_ass_time(float(row['start_s']))},{_ass_time(float(row['end_s']))},"
            f"{style_for.get(str(row.get('kind')), 'Said')},,0,0,0,,{text}"
        )
    if edit.get("ai_label"):
        lines.append(f"Dialogue: 1,{_ass_time(0)},{_ass_time(float(edit.get('duration_s') or 0))},AI,,0,0,0,,"
                     f"{edit.get('ai_label_text') or 'AI 生成'}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def export_fcpxml(edit: dict[str, Any], out_path: Path) -> Path:
    clips = edit.get("items") or []
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!DOCTYPE fcpxml>",
        '<fcpxml version="1.11">',
        "<resources>",
    ]
    for i, item in enumerate(clips):
        out.append(f'  <asset id="a{i}" name="{html.escape(str(item.get("shot_id")))}" '
                   f'src="file://{html.escape(str(item.get("clip") or ""))}" duration="{float(item.get("duration_s") or 0):.3f}s" />')
    out += ["</resources>", "<library><event name=\"hevi-ai-drama\"><project name=\"ai_drama\">",
            "<sequence format=\"r1\">"]
    for i, item in enumerate(clips):
        out.append(f'  <clip name="{html.escape(str(item.get("shot_id")))}" offset="{float(item.get("start_s") or 0):.3f}s" '
                   f'duration="{float(item.get("duration_s") or 0):.3f}s" ref="a{i}" />')
    out += ["</sequence></project></event></library>", "</fcpxml>"]
    out_path.write_text("\n".join(out), encoding="utf-8")
    return out_path


def export_jianying_plan(edit: dict[str, Any], out_path: Path) -> Path:
    """pyJianYingDraft-shaped plan; no draft file is fabricated."""
    plan = {
        "title": edit.get("title", ""),
        "aspect": "9:16",
        "duration_s": edit.get("duration_s"),
        "tracks": [
            {
                "type": "video",
                "clips": [
                    {"shot_id": i["shot_id"], "start_s": i["start_s"], "end_s": i["end_s"], "source": i.get("clip")}
                    for i in edit.get("items") or []
                ],
            },
            {
                "type": "audio",
                "clips": [
                    {"text": s["text"], "start_s": s["start_s"], "end_s": s["end_s"], "kind": s["kind"],
                     "source": s.get("audio")}
                    for s in edit.get("subtitles") or []
                ],
            },
            {
                "type": "subtitle",
                "clips": [
                    {"text": s["text"], "start_s": s["start_s"], "end_s": s["end_s"], "style": s["kind"]}
                    for s in edit.get("subtitles") or []
                ],
            },
        ],
        "draft_file": None,
        "note": "plan only; pyJianYingDraft is not installed and no draft file is fabricated",
    }
    out_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def _concat_video(items: list[dict[str, Any]], out_path: Path, work: Path) -> Path:
    work.mkdir(parents=True, exist_ok=True)
    normalized: list[Path] = []
    for i, item in enumerate(items):
        clip = Path(str(item.get("clip") or ""))
        if not clip.is_file():
            raise RuntimeError(f"剪辑缺片段: {item.get('shot_id')} -> {clip}")
        dst = work / f"n{i:03d}.mp4"
        subprocess.run(
            [FFMPEG, "-y", "-v", "error", "-i", str(clip), "-vf",
             "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,format=yuv420p",
             "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(dst)],
            check=True,
        )
        normalized.append(dst)
    lst = work / "concat.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in normalized), encoding="utf-8")
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(out_path)],
        check=True,
    )
    return out_path


def _build_dialogue_track(edit: dict[str, Any], out_path: Path, work: Path) -> tuple[Path, list[dict[str, Any]]]:
    total = float(edit.get("duration_s") or 0)
    silence = work / "silence.wav"
    make_silence(total, silence)
    inputs = [silence]
    filters = []
    labels = ["[0:a]"]
    used = 0
    for i, row in enumerate(edit.get("subtitles") or []):
        audio = row.get("audio")
        if not audio or not Path(str(audio)).is_file():
            continue
        used += 1
        inputs.append(Path(str(audio)))
        delay = round(float(row.get("start_s") or 0) * 1000)
        filters.append(f"[{len(inputs) - 1}:a]adelay={delay}|{delay},volume=1.0[a{i}]")
        labels.append(f"[a{i}]")
    if used == 0:
        return silence, []
    mix = "".join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=longest[out]"
    filt = ";".join([*filters, mix])
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", *functools.reduce(operator.iadd, [["-i", str(p)] for p in inputs], []),
         "-filter_complex", filt, "-map", "[out]", "-t", f"{total:.3f}", "-ar", "48000", "-ac", "2", str(out_path)],
        check=True,
    )
    return out_path, [{"inputs": len(inputs) - 1}]


def _loudnorm(src: Path, dst: Path, *, target: float = -14.0, tp: float = -1.5) -> dict[str, Any]:
    proc = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", str(src), "-af", f"loudnorm=I={target}:TP={tp}:LRA=11:print_format=json",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    data: dict[str, Any] = {}
    text = proc.stderr
    start = text.rfind("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            data = {}
    if data:
        af = (
            f"loudnorm=I={target}:TP={tp}:LRA=11:"
            f"measured_I={data.get('input_i')}:measured_TP={data.get('input_tp')}:"
            f"measured_LRA={data.get('input_lra')}:measured_thresh={data.get('input_thresh')}:"
            f"offset={data.get('target_offset', 0)}:linear=true:print_format=summary"
        )
    else:
        af = f"loudnorm=I={target}:TP={tp}:LRA=11"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-i", str(src), "-af", af, "-ar", "48000", str(dst)], check=True)
    probe = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", str(dst), "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    measured_i = None
    for line in probe.stderr.splitlines():
        if "I:" in line and "LUFS" in line:
            with contextlib.suppress(ValueError, IndexError):
                measured_i = float(line.split("I:")[1].split("LUFS")[0].strip())
    if measured_i is not None and abs(measured_i - target) > 0.15:
        delta = target - measured_i
        corrected = dst.with_name(dst.stem + "_corr.wav")
        subprocess.run(
            [FFMPEG, "-y", "-v", "error", "-i", str(dst), "-af",
             f"volume={delta:.2f}dB,alimiter=limit={10 ** (tp / 20):.4f}", "-ar", "48000", str(corrected)],
            check=True,
        )
        corrected.replace(dst)
    return {"mode": "two-pass" if data else "single-pass", "measured": data,
            "corrected_i": measured_i, "after_log_tail": probe.stderr[-600:]}


def _make_ding(work: Path) -> Path:
    out = work / "sfx_ding.wav"
    if not out.is_file():
        subprocess.run(
            [FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i",
             "sine=frequency=1320:duration=0.26,afade=t=out:st=0.02:d=0.24,volume=0.7",
             "-ar", "48000", "-ac", "2", str(out)],
            check=True,
        )
    return out


def _build_sfx_track(edit: dict[str, Any], total: float, work: Path) -> Path | None:
    cues = [c for c in edit.get("sfx_cues") or [] if 0 <= float(c.get("t") or 0) < total]
    if not cues:
        return None
    ding = _make_ding(work)
    labels = ["[0:a]"]
    filters = []
    for i, cue in enumerate(cues):
        delay = round(float(cue.get("t") or 0) * 1000)
        gain = float(cue.get("gain") or 0.8)
        filters.append(f"[0:a]adelay={delay}|{delay},volume={gain:.2f}[sfx{i}]")
        labels.append(f"[sfx{i}]")
    filt = ";".join([*filters, "".join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=longest[out]"])
    out = work / "sfx.wav"
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-i", str(ding), "-filter_complex", filt, "-map", "[out]",
         "-t", f"{total:.3f}", "-ar", "48000", "-ac", "2", str(out)],
        check=True,
    )
    return out


def _build_bgm_track(edit: dict[str, Any], total: float, work: Path) -> Path | None:
    bgm = edit.get("bgm") or {}
    path = str(bgm.get("path") or "")
    if not path or not Path(path).is_file():
        return None
    climax = float(bgm.get("climax_s") or 0.0)
    target = float(bgm.get("target_s") or max(0.0, total * 0.35))
    offset = max(0.0, climax - target)
    delay_ms = max(0, round((target - climax) * 1000))
    volume = float(bgm.get("volume") or 0.18)
    out = work / "bgm.wav"
    filters = [f"atrim=start={offset:.3f},asetpts=PTS-STARTPTS", "volume=" + f"{volume:.3f}",
               "afade=t=in:st=0:d=0.6"]
    if delay_ms:
        filters.append(f"adelay={delay_ms}|{delay_ms}")
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-stream_loop", "-1", "-i", str(path), "-af", ",".join(filters),
         "-t", f"{total:.3f}", "-ar", "48000", "-ac", "2", str(out)],
        check=True,
    )
    return out


def _mix_tracks(dialogue: Path, sfx: Path | None, bgm: Path | None, total: float, work: Path) -> Path:
    inputs = [dialogue]
    labels = ["[0:a]"]
    filters = []
    if sfx is not None:
        inputs.append(sfx)
        labels.append(f"[{len(inputs) - 1}:a]")
    if bgm is not None:
        inputs.append(bgm)
        # Duck the music under the dialogue rather than raising it.
        filters.append(f"[{len(inputs) - 1}:a]volume=1.0[bgmduck]")
        labels.append("[bgmduck]")
    filt = ";".join([*filters, "".join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=longest[out]"])
    out = work / "mix.wav"
    cmd = [FFMPEG, "-y", "-v", "error"]
    for path in inputs:
        cmd += ["-i", str(path)]
    cmd += ["-filter_complex", filt, "-map", "[out]", "-t", f"{total:.3f}", "-ar", "48000", "-ac", "2", str(out)]
    subprocess.run(cmd, check=True)
    return out


def trim_silent_edges(edit: dict[str, Any]) -> dict[str, Any]:
    """Drop leading/trailing shots with no dialogue; shift the remaining timeline."""
    items = list(edit.get("items") or [])
    if len(items) <= 1:
        return edit
    head = 0
    while head < len(items) - 1 and not items[head].get("dialogue") and str(items[head].get("mode")) in (
        "action", "establishing", "insert"
    ):
        head += 1
    tail = len(items)
    while tail - 1 > head and not items[tail - 1].get("dialogue") and str(items[tail - 1].get("mode")) in (
        "action", "establishing", "insert"
    ):
        tail -= 1
    if head == 0 and tail == len(items):
        return edit
    removed_head = float(items[head].get("start_s") or 0)
    removed_tail = float(items[-1].get("end_s") or 0) - float(items[tail - 1].get("end_s") or 0)
    kept = items[head:tail]
    shift = removed_head
    for item in kept:
        item["start_s"] = round(max(0.0, float(item.get("start_s") or 0) - shift), 3)
        item["end_s"] = round(max(0.0, float(item.get("end_s") or 0) - shift), 3)
    kept_ids = {str(item.get("shot_id")) for item in kept}
    edit["items"] = kept
    edit["subtitles"] = [
        {**row, "start_s": round(max(0.0, float(row.get("start_s") or 0) - shift), 3),
         "end_s": round(max(0.0, float(row.get("end_s") or 0) - shift), 3)}
        for row in edit.get("subtitles") or [] if str(row.get("shot_id")) in kept_ids
    ]
    edit["duration_s"] = round(sum(float(item.get("duration_s") or 0) for item in kept), 3)
    edit["trim"] = {"removed_head_s": round(removed_head, 3), "removed_tail_s": round(removed_tail, 3),
                    "kept_shots": len(kept)}
    return edit


def assemble(edit: dict[str, Any], out_dir: Path, *, burn_subtitles: bool = True) -> dict[str, Any]:
    work = out_dir / "assemble"
    work.mkdir(parents=True, exist_ok=True)
    video = _concat_video(edit.get("items") or [], work / "video.mp4", work)
    audio_raw, _ = _build_dialogue_track(edit, work / "dialogue_raw.wav", work)
    total = float(edit.get("duration_s") or 0)
    sfx = _build_sfx_track(edit, total, work)
    bgm = _build_bgm_track(edit, total, work)
    mixed = _mix_tracks(audio_raw, sfx, bgm, total, work) if (sfx or bgm) else audio_raw
    audio_path = work / "dialogue.wav"
    audio_info = _loudnorm(mixed, audio_path,
                           target=float((edit.get("loudness") or {}).get("target_lufs", -14)),
                           tp=float((edit.get("loudness") or {}).get("true_peak", -1.5)))
    ass = write_ass(edit, work / "final.ass")
    final = out_dir / "final.mp4"
    cmd = [FFMPEG, "-y", "-v", "error", "-i", str(video), "-i", str(audio_path)]
    if burn_subtitles:
        cmd += ["-vf", f"ass={ass}"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(final)]
    subprocess.run(cmd, check=True)
    srt = out_dir / "final.srt"
    srt.write_text(
        "\n".join(
            f"{i}\n{_fmt_srt(float(r['start_s']))} --> {_fmt_srt(float(r['end_s']))}\n{r['text']}\n"
            for i, r in enumerate(edit.get("subtitles") or [], start=1)
        ),
        encoding="utf-8",
    )
    probe: dict[str, Any] = {}
    try:
        import json as _json

        out = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=avg_frame_rate,width,height,color_transfer",
             "-of", "json", str(final)],
            capture_output=True, text=True, check=False,
        )
        stream = ((_json.loads(out.stdout or "{}").get("streams") or [{}])[0])
        rate = str(stream.get("avg_frame_rate") or "0/1")
        num, _, den = rate.partition("/")
        fps = round(float(num) / float(den or 1), 3) if float(den or 1) else 0
        probe = {
            "fps": fps,
            "width": stream.get("width"),
            "height": stream.get("height"),
            "color_transfer": stream.get("color_transfer") or "unspecified",
        }
    except Exception:
        probe = {}
    return {
        "final": str(final),
        "audio": str(audio_path),
        "subtitles": str(srt),
        "ass": str(ass),
        "video": str(video),
        "loudness": audio_info,
        "duration_s": float(edit.get("duration_s") or 0),
        "probe": probe,
    }
