"""Edit assembly -- ``story.edit_assemble``.

Turns a gated single-episode prompt package plus a list of finished
shot clips into an edit decision list (EDL) and a deterministic ffmpeg
assembly command. This capability never generates media and never calls
any generation API: it only arranges material the caller already has.

Inputs (``build_edl`` params):

* ``prompt_package`` (or ``package``): an ``episode_prompts`` package --
  ``episode_no``, ``title`` and ``shots``. Each shot may carry compiler
  ``blocks`` (authoritative when present) or raw episode fields
  (``scene_id``, ``action``, ``dialogue``, ``duration_sec``).
* ``clips``: one finished clip per prompt shot, ``{shot_id, file,
  duration_sec, in_sec?, out_sec?}``. Every prompt shot MUST have a
  clip; a missing clip, a clip for an unknown shot, a duplicate clip,
  or an out-of-range in/out point raises :class:`CapabilityError`.
  Nothing is silently skipped.
* ``music`` (optional): ``{bpm?, beats?, duration_sec?}``. With no
  music information the beat table is ``pending`` -- beats are never
  invented. With ``bpm`` a beat grid is computed; with explicit
  ``beats`` those timestamps are used verbatim.
* ``sound_cues`` (optional): caller-supplied sound layers, either
  per-shot (``shot.sound_cues``) or top-level with ``shot_id``. Each
  cue names a layer, a trigger action/node and a time window. On top
  of caller cues, a small generic foley keyword rule maps common
  action verbs to layer categories (footsteps, door, object handling,
  cloth, water); rule layers are marked ``source: keyword-rule`` and
  must be verified against the recorded audio at mix time. A caller
  cue for the same layer on the same shot replaces the rule layer.
* ``subtitle_file`` (optional): path to a prepared .srt/.ass file.
  When present, :func:`assemble_ffmpeg` output is included in the
  report; when absent the ffmpeg step is ``pending`` rather than
  faked. ``music_file`` / ``sfx_files`` are only mixed when supplied.

Output (``edit_assemble.json``) mirrors the sibling report shape:
``episode_no``, ``title``, ``total_duration_sec``, ``edit_ready``,
``edl`` (one entry per shot, in order, with in/out points,
transitions, action nodes, sound layers and subtitle lines),
``music_beat_table``, ``sound_layers`` (flat list, same objects as
in the EDL entries), ``subtitle_spec``, ``spatial_continuity`` and
``findings``. ``spatial_continuity`` (scene sequence + scene changes)
and ``edit_ready`` are the fields the ``drama_gates`` edit-ready /
spatial placeholders consume: ``edit_ready`` is false exactly when a
blocker finding exists.

``assemble_ffmpeg`` builds an executable ffmpeg command list (concat
+ mix + subtitle burn). It never executes ffmpeg. Only ``cut``
transitions are covered by the generated command; a dissolve/fade
join raises :class:`CapabilityError` naming the shot, because it
needs a hand-built xfade chain -- the report flags such joins instead
of emitting a wrong command.

Method-level references (own wording, no code or text copied from
any source; the unlicensed source below is method-read-only):

* Blueprint gate: the edit plan (intake summary, materials, shot
  list, contact sheet, beat table, edit plan, QA plan) is produced
  and reviewable before any render step; when approval is required,
  an unapproved blueprint blocks the ffmpeg step.
* Voice-truncation check: a trimmed clip is flagged for a manual
  mid-speech check -- without speech timestamps no automatic
  expansion is invented.
* Audio-video duration check: each used clip length is compared
  against its prompt shot length; drift is a finding, not a silent
  re-time.
* Face-safe subtitles: subtitle/panel areas must not cover faces;
  enforced as a spec constraint plus a QA checklist item, since this
  capability performs no image detection.
* Sound hierarchy: dialogue first, effects never over words, music
  ducked under dialogue.
"""

from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

MISSING = "[缺失]"

ALLOWED_TRANSITIONS = ("cut", "dissolve", "fade")
DEFAULT_TRANSITION_DURATION_SEC = 0.5

# Generic foley keyword rules: (keywords, layer name). A rule fires at
# most once per shot, on the first matching keyword, and only when no
# caller cue claims the same layer for that shot. These are assembly
# suggestions, not measured audio: every rule layer is marked as such.
SOUND_KEYWORD_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("推开", "拉开", "关上", "开门"), "木门声"),
    (("走进", "走出", "跟在"), "脚步声"),
    (("放在", "递给", "推到", "拿起", "放进"), "器物声"),
    (("擦",), "布料摩擦声"),
    (("挂到", "挂上"), "挂置声"),
    (("浸入", "晃动"), "水声"),
    (("翻动", "展开"), "纸张声"),
)

SUBTITLE_SPEC: dict[str, Any] = {
    # All sizes are relative to frame dimensions, never absolute pixels:
    # a spec that only works at one resolution is a spec that breaks.
    "safe_area": {
        "width_pct": 90,
        "horizontal_margin_pct": 5,
        "bottom_margin_pct": 8,
        "top_margin_pct": 5,
        "note": "字幕带位于画面底部安全区内，避开顶部人脸区与左右边缘。",
    },
    "font_size_rel": 0.042,
    "font_size_note": "字幕字高 = 0.042 * 画面高度（相对值，随分辨率缩放）。",
    "max_chars_per_line": 20,
    "max_lines": 2,
    "min_line_sec": 0.8,
    "max_line_sec": 6.0,
    "timing_note": (
        "本能力输出的字幕行时间轴为按对白行数均分本镜时长的估算值，"
        "标记为 estimated-even-split；烧录前须以实录音频/ASR 对齐替换，"
        "不得直接用估算轴出片。"
    ),
    # Face-safe rule (method-level reference, own wording): subtitle
    # and panel areas must never cover a speaker's face. This
    # capability does no image detection, so the rule is enforced as
    # a spec constraint plus a QA checklist item, not as a measured
    # pass/fail on pixels.
    "face_safe": {
        "rule": "字幕与面板不压人物面部。",
        "band": "字幕只进底部安全带，不进画面上部人脸区。",
        "check": (
            "逐镜核对字幕带与人物面部框无重叠；本能力不做图像检测，"
            "该项须由剪辑时人工或面部检测核对，核对前不得宣称通过。"
        ),
    },
}

def _as_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _nonempty(value: Any) -> str | None:
    text = _as_str(value).strip()
    return text if text else None


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _finding(
    check: str,
    severity: str,
    issue: str,
    suggestion: str,
    shot_id: str | None = None,
    scene_id: str | None = None,
) -> dict[str, Any]:
    return {
        "check": check,
        "severity": severity,
        "shot_id": shot_id,
        "scene_id": scene_id,
        "issue": issue,
        "suggestion": suggestion,
    }


def _normalize_shot(raw: dict[str, Any], idx: int) -> dict[str, Any]:
    """Normalize one package shot to edit-checkable fields.

    Compiler ``blocks`` win when present; otherwise the raw episode
    fields are used. Dialogue ``None`` (key absent) stays ``None`` to
    mirror the gates' distinction from an explicit empty list, which
    means a pure-visual shot.
    """
    shot_id = _nonempty(raw.get("shot_id")) or f"shot_{idx + 1:02d}"
    blocks = raw.get("blocks") if isinstance(raw.get("blocks"), dict) else {}
    if blocks:
        dialogue = blocks.get("dialogue")
        return {
            "shot_id": shot_id,
            "shot_id_missing": raw.get("shot_id") is None,
            "scene_id": _nonempty(blocks.get("scene_id")),
            "scene_name": _nonempty(blocks.get("scene_name")),
            "scene": _nonempty(blocks.get("scene")),
            "action": _nonempty(blocks.get("action")),
            "dialogue": dialogue,
            "duration_sec": _num(blocks.get("duration_sec")),
            "first_frame": _nonempty(blocks.get("first_frame")),
            "transition": _nonempty(raw.get("transition")) or "cut",
            "action_nodes": raw.get("action_nodes"),
            "sound_cues": raw.get("sound_cues"),
        }
    dialogue = raw.get("dialogue", None)
    return {
        "shot_id": shot_id,
        "shot_id_missing": raw.get("shot_id") is None,
        "scene_id": _nonempty(raw.get("scene_id")),
        "scene_name": _nonempty(raw.get("scene_name")),
        "scene": _nonempty(raw.get("scene")),
        "action": _nonempty(raw.get("action")),
        "dialogue": dialogue,
        "duration_sec": _num(raw.get("duration_sec")),
        "first_frame": _nonempty(raw.get("first_frame")),
        "transition": _nonempty(raw.get("transition")) or "cut",
        "action_nodes": raw.get("action_nodes"),
        "sound_cues": raw.get("sound_cues"),
    }


def _normalize_action_nodes(
    shot: dict[str, Any], used_sec: float
) -> list[dict[str, Any]]:
    """Caller nodes verbatim, or one node spanning the whole shot."""
    raw_nodes = shot.get("action_nodes")
    action_text = shot.get("action") or ""
    if not isinstance(raw_nodes, list) or not raw_nodes:
        return [
            {
                "node_id": f"{shot['shot_id']}-A1",
                "action": action_text,
                "start_offset_sec": 0.0,
                "end_offset_sec": used_sec,
            }
        ]
    nodes: list[dict[str, Any]] = []
    for i, raw in enumerate(raw_nodes):
        if not isinstance(raw, dict):
            raise CapabilityError(
                f"story.edit_assemble: action node {i} of shot "
                f"{shot['shot_id']} must be an object"
            )
        start = _num(raw.get("start_offset_sec"))
        end = _num(raw.get("end_offset_sec"))
        start = 0.0 if start is None else start
        end = used_sec if end is None else end
        if start < 0 or end <= start or end > used_sec:
            raise CapabilityError(
                f"story.edit_assemble: action node of shot {shot['shot_id']} "
                f"has out-of-range window [{start:g}, {end:g}] for a "
                f"{used_sec:g}s shot"
            )
        nodes.append(
            {
                "node_id": _nonempty(raw.get("node_id"))
                or f"{shot['shot_id']}-A{i + 1}",
                "action": _nonempty(raw.get("action")) or action_text,
                "start_offset_sec": start,
                "end_offset_sec": end,
            }
        )
    return nodes


def _subtitle_lines(
    shot: dict[str, Any], timeline_start: float, used_sec: float
) -> list[dict[str, Any]]:
    """Dialogue lines split per the subtitle spec, timing estimated.

    Long lines are chunked at ``max_chars_per_line``; every chunk gets
    an even share of the shot duration. Timing is explicitly marked
    estimated -- see SUBTITLE_SPEC['timing_note'].
    """
    dialogue = shot.get("dialogue")
    if not isinstance(dialogue, list) or not dialogue:
        return []
    chunks: list[dict[str, Any]] = []
    max_chars = int(SUBTITLE_SPEC["max_chars_per_line"])
    for line in dialogue:
        if isinstance(line, dict):
            speaker = _as_str(line.get("speaker", ""))
            text = _as_str(line.get("text", ""))
        else:
            speaker, text = "", _as_str(line)
        text = text.strip()
        if not text:
            continue
        for start in range(0, len(text), max_chars):
            chunks.append({"speaker": speaker, "text": text[start : start + max_chars]})
    if not chunks:
        return []
    share = used_sec / len(chunks)
    out: list[dict[str, Any]] = []
    for i, chunk in enumerate(chunks):
        out.append(
            {
                "shot_id": shot["shot_id"],
                "speaker": chunk["speaker"],
                "text": chunk["text"],
                "start_sec": round(timeline_start + i * share, 3),
                "end_sec": round(timeline_start + (i + 1) * share, 3),
                "timing": "estimated-even-split",
            }
        )
    return out


def _sound_layers(
    shot: dict[str, Any],
    nodes: list[dict[str, Any]],
    timeline_start: float,
    caller_cues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Caller cues first, then generic keyword rules (dedupe by layer)."""
    layers: list[dict[str, Any]] = []
    claimed: set[str] = set()
    action_text = shot.get("action") or ""
    for cue in caller_cues:
        if not isinstance(cue, dict):
            continue
        layer = _nonempty(cue.get("layer"))
        if layer is None:
            continue
        start = _num(cue.get("start_offset_sec"))
        end = _num(cue.get("end_offset_sec"))
        # Window defaults to the triggering node's window, else the shot.
        node = nodes[0] if nodes else None
        trigger_node = _nonempty(cue.get("trigger_node_id"))
        if trigger_node:
            for cand in nodes:
                if cand["node_id"] == trigger_node:
                    node = cand
                    break
        node_start = node["start_offset_sec"] if node else 0.0
        node_end = node["end_offset_sec"] if node else 0.0
        start = node_start if start is None else start
        end = node_end if end is None else end
        layers.append(
            {
                "shot_id": shot["shot_id"],
                "layer": layer,
                "trigger_action": _nonempty(cue.get("trigger_action")) or action_text,
                "trigger_node_id": node["node_id"] if node else None,
                "start_sec": round(timeline_start + start, 3),
                "end_sec": round(timeline_start + end, 3),
                "source": "caller-cue",
                "file": _nonempty(cue.get("file")),
            }
        )
        claimed.add(layer)
    for keywords, layer in SOUND_KEYWORD_RULES:
        if layer in claimed:
            continue
        if any(kw in action_text for kw in keywords):
            layers.append(
                {
                    "shot_id": shot["shot_id"],
                    "layer": layer,
                    "trigger_action": action_text,
                    "trigger_node_id": nodes[0]["node_id"] if nodes else None,
                    "start_sec": round(timeline_start, 3),
                    "end_sec": round(
                        timeline_start + (nodes[0]["end_offset_sec"] if nodes else 0.0), 3
                    ),
                    "source": "keyword-rule",
                    "file": None,
                }
            )
            claimed.add(layer)
    return layers


def _music_beat_table(
    music: Any, total_sec: float, boundaries: list[float]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Beat-cut table, or an honest pending table when music is absent."""
    findings: list[dict[str, Any]] = []
    if music is None:
        return {
            "status": "pending",
            "reason": "未提供音乐信息（bpm 或节拍点），节拍剪切表为空，不编造节拍。",
            "cuts": [],
        }, findings
    if not isinstance(music, dict):
        raise CapabilityError("story.edit_assemble: 'music' must be an object")
    beats: list[float] = []
    beats_raw = music.get("beats")
    if isinstance(beats_raw, list) and beats_raw:
        for value in beats_raw:
            num = _num(value)
            if num is None or num <= 0:
                raise CapabilityError(
                    "story.edit_assemble: music beats must be positive numbers"
                )
            beats.append(num)
        dropped = [b for b in beats if b >= total_sec]
        beats = [b for b in beats if b < total_sec]
        if dropped:
            findings.append(
                _finding(
                    "music",
                    "minor",
                    f"音乐节拍点 {dropped} 落在本集片长之外，已忽略。",
                    "只保留片长内的节拍点；确认音乐总时长与成片时长是否一致。",
                )
            )
    else:
        bpm = _num(music.get("bpm"))
        if bpm is None or bpm <= 0:
            return {
                "status": "pending",
                "reason": "音乐已给但无可用 bpm 或节拍点，无法生成节拍剪切表。",
                "cuts": [],
            }, [
                _finding(
                    "music",
                    "major",
                    "音乐信息缺少 bpm 与节拍点，节拍剪切表为空。",
                    "补音乐 bpm 或显式节拍点列表后重跑。",
                )
            ]
        step = 60.0 / bpm
        beat = step
        while beat < total_sec:
            beats.append(round(beat, 3))
            beat += step
    cuts: list[dict[str, Any]] = []
    for boundary in boundaries:
        if not beats:
            break
        nearest = min(beats, key=lambda b: abs(b - boundary))
        offset = round(abs(nearest - boundary), 3)
        cuts.append(
            {
                "boundary_sec": round(boundary, 3),
                "nearest_beat_sec": nearest,
                "offset_sec": offset,
                "on_beat": offset <= 0.15,
            }
        )
    status = "ready"
    music_dur = _num(music.get("duration_sec"))
    if music_dur is not None and music_dur < total_sec:
        status = "partial"
        findings.append(
            _finding(
                "music",
                "major",
                f"音乐时长 {music_dur:g}s 短于成片 {total_sec:g}s，尾段无音乐覆盖。",
                "换更长的音乐，或循环/延展音乐后重跑。",
            )
        )
    return {"status": status, "cuts": cuts}, findings


def assemble_ffmpeg(
    edl: list[dict[str, Any]],
    subtitle_file: str,
    *,
    output_file: str = "episode_assembled.mp4",
    music_file: str | None = None,
    music_volume: float = 0.25,
    sfx_files: list[dict[str, Any]] | None = None,
    require_blueprint_approval: bool = False,
    blueprint_approved: bool = False,
) -> dict[str, Any]:
    """Build (never run) the ffmpeg assembly command for an EDL.

    Cut-only: clips are concatenated, dialogue audio is mixed with
    optional music / sfx, and subtitles are burned from
    ``subtitle_file``. Any dissolve/fade join raises CapabilityError:
    it needs a hand-built xfade chain, and emitting a concat command
    for it would be a wrong command, not a simplification.

    Blueprint gate (method-level reference, own wording): the edit
    plan is a blueprint first and the render step second. When
    ``require_blueprint_approval`` is true, an unapproved blueprint
    raises here instead of producing a command -- approval is an
    explicit caller flag, never assumed from silence.
    """
    if require_blueprint_approval and not blueprint_approved:
        raise CapabilityError(
            "story.edit_assemble: blueprint not approved -- the edit "
            "plan must be approved before any assembly command is built"
        )
    if not isinstance(edl, list) or not edl:
        raise CapabilityError("story.edit_assemble: edl must be a non-empty list")
    if not _nonempty(subtitle_file):
        raise CapabilityError(
            "story.edit_assemble: subtitle_file is required to build the "
            "assembly command (subtitles are burned, not skipped)"
        )
    if not _nonempty(output_file):
        raise CapabilityError("story.edit_assemble: output_file must be non-empty")
    for entry in edl:
        if not isinstance(entry, dict):
            raise CapabilityError("story.edit_assemble: edl entries must be objects")
        if not _nonempty(entry.get("source_file")):
            raise CapabilityError(
                f"story.edit_assemble: edl entry {entry.get('shot_id')} "
                "is missing source_file"
            )
        transition = entry.get("transition", "cut")
        if transition not in ("cut",):
            raise CapabilityError(
                f"story.edit_assemble: shot {entry.get('shot_id')} uses "
                f"transition {transition!r}; the generated command covers "
                "cuts only -- build an xfade chain by hand for this join"
            )
    sfx: list[dict[str, Any]] = []
    for item in sfx_files or []:
        if not isinstance(item, dict) or not _nonempty(item.get("file")):
            raise CapabilityError(
                "story.edit_assemble: every sfx entry needs a non-empty file"
            )
        delay = _num(item.get("delay_sec"))
        delay = 0.0 if delay is None else delay
        if delay < 0:
            raise CapabilityError("story.edit_assemble: sfx delay_sec must be >= 0")
        sfx.append({"file": _as_str(item["file"]), "delay_sec": delay})

    cmd: list[str] = ["ffmpeg"]
    for entry in edl:
        cmd += ["-i", _as_str(entry["source_file"])]
    n_clips = len(edl)
    concat_inputs = "".join(f"[{i}:v][{i}:a]" for i in range(n_clips))
    filters = [f"{concat_inputs}concat=n={n_clips}:v=1:a=1[vout][aout]"]
    audio_label = "aout"
    next_input = n_clips
    mix_inputs: list[str] = []
    if _nonempty(music_file):
        cmd += ["-i", _as_str(music_file)]
        filters.append(f"[{next_input}:a]volume={music_volume:g}[mus]")
        mix_inputs.append("mus")
        next_input += 1
    sfx_labels: list[str] = []
    for i, item in enumerate(sfx):
        cmd += ["-i", item["file"]]
        delay_ms = int(round(item["delay_sec"] * 1000))
        filters.append(f"[{next_input}:a]adelay={delay_ms}:all=1[sfx{i}]")
        sfx_labels.append(f"sfx{i}")
        next_input += 1
    if mix_inputs or sfx_labels:
        all_mix = "[aout]" + "".join(f"[{label}]" for label in mix_inputs + sfx_labels)
        total = 1 + len(mix_inputs) + len(sfx_labels)
        filters.append(
            f"{all_mix}amix=inputs={total}:duration=first:dropout_transition=0[aud]"
        )
        audio_label = "aud"
    filters.append(f"[vout]subtitles={shlex.quote(_as_str(subtitle_file))}[vsub]")
    cmd += [
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[vsub]",
        "-map",
        f"[{audio_label}]",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        _as_str(output_file),
    ]
    unmixed = [
        layer
        for entry in edl
        for layer in (entry.get("sound_layers") or [])
        if not layer.get("file")
    ]
    notes = [
        "本命令只拼出、不执行；执行前请确认所有输入文件路径存在。",
        "字幕样式（相对字号与安全区）以 subtitle_spec 与字幕文件本身为准，"
        "ffmpeg subtitles 滤镜只做烧录，不重算样式。",
    ]
    if unmixed:
        notes.append(
            f"{len(unmixed)} 个声层无音频文件，未混入本命令，"
            "见 unmixed_sound_layers，混音前须补录或指定文件。"
        )
    return {
        "command": cmd,
        "command_str": " ".join(shlex.quote(part) for part in cmd),
        "output_file": _as_str(output_file),
        "unmixed_sound_layers": unmixed,
        "notes": notes,
    }


def build_edl(params: dict[str, Any]) -> dict[str, Any]:
    """Pure build step (no file I/O): params -> edit assembly payload."""
    package = params.get("prompt_package", params.get("package"))
    if not isinstance(package, dict):
        raise CapabilityError(
            "story.edit_assemble: 'prompt_package' must be an object"
        )
    shots_raw = package.get("shots", []) or []
    if not isinstance(shots_raw, list) or not shots_raw:
        raise CapabilityError(
            "story.edit_assemble: 'prompt_package.shots' must be a non-empty list"
        )
    clips_raw = params.get("clips")
    if not isinstance(clips_raw, list):
        raise CapabilityError("story.edit_assemble: 'clips' must be a list")
    clips: dict[str, dict[str, Any]] = {}
    for clip in clips_raw:
        if not isinstance(clip, dict):
            raise CapabilityError("story.edit_assemble: every clip must be an object")
        shot_id = _nonempty(clip.get("shot_id"))
        if shot_id is None:
            raise CapabilityError("story.edit_assemble: every clip needs a shot_id")
        if shot_id in clips:
            raise CapabilityError(
                f"story.edit_assemble: duplicate clip for shot {shot_id}"
            )
        clips[shot_id] = clip
    top_cues: dict[str, list[dict[str, Any]]] = {}
    for cue in params.get("sound_cues", []) or []:
        if isinstance(cue, dict) and _nonempty(cue.get("shot_id")):
            top_cues.setdefault(_as_str(cue["shot_id"]), []).append(cue)

    findings: list[dict[str, Any]] = []
    edl: list[dict[str, Any]] = []
    flat_layers: list[dict[str, Any]] = []
    scene_sequence: list[str | None] = []
    scene_changes: list[dict[str, Any]] = []
    duration_mismatches: list[dict[str, Any]] = []
    trimmed_shots: list[dict[str, Any]] = []
    prev_scene: str | None = None
    timeline = 0.0
    boundaries: list[float] = []
    for idx, raw in enumerate(shots_raw):
        if not isinstance(raw, dict):
            raise CapabilityError(
                f"story.edit_assemble: shot {idx} must be an object"
            )
        shot = _normalize_shot(raw, idx)
        shot_id = shot["shot_id"]
        if shot["shot_id_missing"]:
            findings.append(
                _finding(
                    "edit_ready",
                    "minor",
                    f"镜 {shot_id} 缺 shot_id，已用序号占位标识（不补写内容）。",
                    "给本镜补正式 shot_id 后重跑。",
                    shot_id,
                    shot["scene_id"],
                )
            )
        clip = clips.get(shot_id)
        if clip is None:
            raise CapabilityError(
                f"story.edit_assemble: no finished clip for shot {shot_id} "
                "-- refusing to assemble with a missing shot"
            )
        source_file = _nonempty(clip.get("file"))
        if source_file is None:
            raise CapabilityError(
                f"story.edit_assemble: clip for shot {shot_id} is missing file"
            )
        clip_dur = _num(clip.get("duration_sec"))
        if clip_dur is None or clip_dur <= 0:
            raise CapabilityError(
                f"story.edit_assemble: clip for shot {shot_id} needs a "
                "positive duration_sec"
            )
        in_sec = _num(clip.get("in_sec"))
        in_sec = 0.0 if in_sec is None else in_sec
        out_sec = _num(clip.get("out_sec"))
        out_sec = clip_dur if out_sec is None else out_sec
        if in_sec < 0 or out_sec <= in_sec or out_sec > clip_dur:
            raise CapabilityError(
                f"story.edit_assemble: clip for shot {shot_id} has "
                f"out-of-range in/out [{in_sec:g}, {out_sec:g}] for a "
                f"{clip_dur:g}s clip"
            )
        used_sec = out_sec - in_sec
        # Voice-truncation check (method-level reference, own wording):
        # a trimmed clip may cut mid-speech. Without speech timestamps
        # this capability cannot auto-expand the cut, so a trimmed
        # clip is flagged for a manual check instead of being quietly
        # accepted -- and never silently "fixed" by inventing bounds.
        if in_sec > 0 or out_sec < clip_dur:
            trimmed_shots.append(
                {
                    "shot_id": shot_id,
                    "in_sec": in_sec,
                    "out_sec": out_sec,
                    "clip_duration_sec": clip_dur,
                }
            )
            findings.append(
                _finding(
                    "voice_cut",
                    "minor",
                    f"镜 {shot_id} 成片经裁剪（用 [{in_sec:g}, {out_sec:g}]，"
                    f"原片 {clip_dur:g}s），须核对起止未切在语音中间。",
                    "核对语音时间戳；若切在语音中间，外扩起止到最近停顿处。",
                    shot_id,
                    shot["scene_id"],
                )
            )
        # Audio-video duration check (method-level reference, own
        # wording): the used clip length must match the prompt shot
        # length; a gap means picture and plan have drifted apart.
        prompt_dur = shot["duration_sec"]
        if prompt_dur is not None and abs(used_sec - prompt_dur) > 0.01:
            duration_mismatches.append(
                {
                    "shot_id": shot_id,
                    "prompt_duration_sec": prompt_dur,
                    "used_duration_sec": round(used_sec, 3),
                    "diff_sec": round(used_sec - prompt_dur, 3),
                }
            )
            findings.append(
                _finding(
                    "av_duration",
                    "major",
                    f"镜 {shot_id} 成片用长 {used_sec:g}s 与 prompt 镜时长 "
                    f"{prompt_dur:g}s 不一致（差 {used_sec - prompt_dur:+g}s）。",
                    "核对成片与 prompt：补齐或重裁该镜，勿让音画时长差带入成片。",
                    shot_id,
                    shot["scene_id"],
                )
            )
        transition = shot["transition"]
        if transition not in ALLOWED_TRANSITIONS:
            raise CapabilityError(
                f"story.edit_assemble: shot {shot_id} has unknown "
                f"transition {transition!r} (allowed: {ALLOWED_TRANSITIONS})"
            )
        nodes = _normalize_action_nodes(shot, used_sec)
        timeline_start = timeline
        timeline_end = timeline + used_sec
        cues = list(shot.get("sound_cues") or []) + top_cues.get(shot_id, [])
        layers = _sound_layers(shot, nodes, timeline_start, cues)
        sub_lines = _subtitle_lines(shot, timeline_start, used_sec)
        if shot["scene_id"] is None and shot["scene"] is None:
            findings.append(
                _finding(
                    "edit_ready",
                    "blocker",
                    f"镜 {shot_id} 缺场景：无法确认空间连续性。",
                    "给本镜指定一个 bible 中的场景后重跑。",
                    shot_id,
                    None,
                )
            )
        if shot["dialogue"] is None:
            findings.append(
                _finding(
                    "edit_ready",
                    "blocker",
                    f"镜 {shot_id} 缺对白字段（不是纯视觉镜），字幕行无法生成。",
                    "补写本镜对白，或明确把对白置为空列表声明为纯视觉镜。",
                    shot_id,
                    shot["scene_id"],
                )
            )
        # Note: estimated subtitle timing can exceed max_line_sec on
        # long shots with few lines; that is expected for an estimate
        # and is already covered by SUBTITLE_SPEC['timing_note'] (the
        # axis must be replaced with ASR alignment before burning), so
        # no per-shot finding is emitted for it here.
        scene_sequence.append(shot["scene_id"])
        if prev_scene is not None and shot["scene_id"] != prev_scene:
            scene_changes.append(
                {
                    "seq": len(edl) + 1,
                    "shot_id": shot_id,
                    "from_scene": prev_scene,
                    "to_scene": shot["scene_id"],
                    "at_sec": round(timeline_start, 3),
                }
            )
        prev_scene = shot["scene_id"]
        entry = {
            "seq": len(edl) + 1,
            "shot_id": shot_id,
            "scene_id": shot["scene_id"],
            "scene_name": shot["scene_name"],
            "first_frame": shot["first_frame"],
            "source_file": source_file,
            "in_sec": in_sec,
            "out_sec": out_sec,
            "clip_duration_sec": clip_dur,
            "timeline_start_sec": round(timeline_start, 3),
            "timeline_end_sec": round(timeline_end, 3),
            "duration_sec": round(used_sec, 3),
            "transition": transition,
            "transition_duration_sec": (
                0.0 if transition == "cut" else DEFAULT_TRANSITION_DURATION_SEC
            ),
            "action_nodes": nodes,
            "sound_layers": layers,
            "subtitle_lines": sub_lines,
        }
        edl.append(entry)
        flat_layers.extend(layers)
        timeline = timeline_end
        if idx < len(shots_raw) - 1:
            boundaries.append(timeline_end)
    unknown_clips = sorted(set(clips) - {e["shot_id"] for e in edl})
    if unknown_clips:
        raise CapabilityError(
            "story.edit_assemble: clips for unknown shots: "
            + ", ".join(unknown_clips)
        )
    total_sec = round(timeline, 3)
    beat_table, music_findings = _music_beat_table(
        params.get("music"), total_sec, boundaries
    )
    findings.extend(music_findings)
    counts = {"blocker": 0, "major": 0, "minor": 0}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    subtitle_file = _nonempty(params.get("subtitle_file"))
    music_file = _nonempty(params.get("music_file"))
    require_approval = bool(params.get("require_blueprint_approval", False))
    blueprint_approved = bool(params.get("blueprint_approved", False))
    missing_inputs: list[str] = []
    if params.get("music") is None:
        missing_inputs.append("音乐信息（bpm 或节拍点）")
    if subtitle_file is None:
        missing_inputs.append("字幕文件")
    transition_counts: dict[str, int] = {}
    for entry in edl:
        transition_counts[entry["transition"]] = (
            transition_counts.get(entry["transition"], 0) + 1
        )
    # Blueprint gate (method-level reference, own wording): the edit
    # plan is written and reviewable BEFORE any render step. The
    # blueprint itself never claims a render happened; approval is a
    # separate explicit flag, and an unapproved blueprint blocks the
    # ffmpeg step when approval is required.
    blueprint = {
        "phase": "blueprint",
        "intake_summary": {
            "episode_no": package.get("episode_no"),
            "title": package.get("title", ""),
            "shot_count": len(edl),
            "total_duration_sec": total_sec,
            "music_status": beat_table["status"],
            "missing_inputs": missing_inputs,
        },
        "materials": {
            "clips": [entry["source_file"] for entry in edl],
            "subtitle_file": subtitle_file,
            "music_file": music_file,
            "sfx_files": (
                [item.get("file") for item in params.get("sfx_files", [])]
                if isinstance(params.get("sfx_files"), list)
                else []
            ),
        },
        "shot_list": [
            {
                "seq": entry["seq"],
                "shot_id": entry["shot_id"],
                "scene_id": entry["scene_id"],
                "timeline_start_sec": entry["timeline_start_sec"],
                "timeline_end_sec": entry["timeline_end_sec"],
            }
            for entry in edl
        ],
        "contact_sheet": [
            {"shot_id": entry["shot_id"], "first_frame": entry["first_frame"]}
            for entry in edl
        ],
        "beat_table_status": beat_table["status"],
        "edit_plan": {
            "transition_counts": transition_counts,
            "sound_layer_count": len(flat_layers),
            "subtitle_line_count": sum(
                len(entry["subtitle_lines"]) for entry in edl
            ),
        },
        "qa_plan": [
            "时长核对：成片总时长与 prompt 总时长一致。",
            "入出点核对：每镜入出点在成片时长内。",
            "音画时长差：逐镜成片用长与 prompt 镜时长一致（见 qa_checks）。",
            "语音截断：经裁剪的镜核对起止未切在语音中间（见 qa_checks）。",
            "字幕面部审计：逐镜核对字幕带与人物面部框无重叠。",
            "字幕可读性：字号相对值与安全区按 subtitle_spec 落实。",
            "尾帧检查：最后 0.5 秒无黑闪、无循环点跳变。",
            "黑帧与重复镜：人工核对成片无黑帧、无重复镜。",
            "版本化：输出文件不覆盖旧成片，改版存新文件。",
        ],
        "qa_checks": {
            "duration_mismatches": duration_mismatches,
            "trimmed_shots": trimmed_shots,
        },
    }
    payload: dict[str, Any] = {
        "episode_no": package.get("episode_no"),
        "title": package.get("title", ""),
        "total_duration_sec": total_sec,
        "edit_ready": counts["blocker"] == 0,
        "counts": counts,
        "findings": findings,
        "edl": edl,
        "music_beat_table": beat_table,
        "sound_layers": flat_layers,
        "subtitle_spec": SUBTITLE_SPEC,
        "spatial_continuity": {
            "scene_sequence": scene_sequence,
            "scene_changes": scene_changes,
            "shots_missing_scene": [
                e["shot_id"] for e in edl if e["scene_id"] is None
            ],
        },
        "blueprint": blueprint,
        "blueprint_gate": {
            "required": require_approval,
            "approved": blueprint_approved,
            "blocked": require_approval and not blueprint_approved,
        },
        # Sound hierarchy (method-level reference, own wording):
        # dialogue first, effects never over words, music ducked
        # under dialogue. This is mix policy, not measured audio.
        "mix_policy": {
            "dialogue": "人声优先定基准，音效与音乐不得压词。",
            "music": "音乐在对白下压低（默认音量 0.25）；空镜为主时可抬高。",
            "sfx": "音效不压词，同一声层不在一集内无故重复。",
        },
    }
    if subtitle_file is not None and not (
        require_approval and not blueprint_approved
    ):
        sfx = params.get("sfx_files")
        payload["ffmpeg"] = assemble_ffmpeg(
            edl,
            subtitle_file,
            output_file=_nonempty(params.get("output_file"))
            or "episode_assembled.mp4",
            music_file=music_file,
            music_volume=_num(params.get("music_volume")) or 0.25,
            sfx_files=sfx if isinstance(sfx, list) else None,
            require_blueprint_approval=require_approval,
            blueprint_approved=blueprint_approved,
        )
    elif subtitle_file is None:
        payload["ffmpeg"] = {
            "status": "pending",
            "reason": "未提供 subtitle_file，ffmpeg 组装命令未生成（不跳过字幕烧录）。",
        }
    else:
        payload["ffmpeg"] = {
            "status": "blocked",
            "reason": "蓝图未批准，ffmpeg 组装命令未生成（蓝图门要求先批准）。",
        }
    return payload


_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "prompt_package": {"type": "object"},
        "package": {"type": "object"},
        "clips": {"type": "array"},
        "music": {"type": "object"},
        "sound_cues": {"type": "array"},
        "subtitle_file": {"type": "string"},
        "music_file": {"type": "string"},
        "music_volume": {"type": "number"},
        "sfx_files": {"type": "array"},
        "output_file": {"type": "string"},
        "require_blueprint_approval": {"type": "boolean"},
        "blueprint_approved": {"type": "boolean"},
    },
    "required": ["clips"],
    "additionalProperties": False,
}


def _write_report(out_dir: Path, payload: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "edit_assemble.json"
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    payload = build_edl(params)
    report = _write_report(Path(out_dir), payload)
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), **payload},
    )


def register_edit_assemble_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="story.edit_assemble",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema=_PARAMS_SCHEMA,
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "剪辑组装：已过门禁的单集 prompt 包＋镜头成片清单 → 蓝图"
                "（先出可审的剪辑方案，批了再渲染）＋ EDL（顺序、入出点、"
                "转场）、音乐节拍剪切表（缺音乐信息即 pending，不编造）、"
                "按动作节点挂接的环境声层清单、字幕排版规格（face-safe"
                " 区、相对字号、单行时长上限、人脸安全规则）；另含语音"
                "截断校验与音画时长差校验；assemble_ffmpeg 拼出可执行的"
                " ffmpeg 命令（拼接＋混音＋字幕烧录），输入缺失即报错、"
                "绝不静默跳过，函数本身不执行 ffmpeg、不调任何生成"
                " API。离线 deterministic。"
            ),
            line="edit_assemble",
        )
    )
    return ["story.edit_assemble"]


register_edit_assemble_capabilities_once()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run story.edit_assemble on a params JSON file")
    parser.add_argument("--input", required=True, help="params JSON file")
    parser.add_argument("--out", required=True, help="output directory")
    args = parser.parse_args(argv)
    params = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = _render(params, Path(args.out), duration=0.0, aspect="16:9", seed=42)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
