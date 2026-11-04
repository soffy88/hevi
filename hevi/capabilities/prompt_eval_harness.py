"""Prompt eval harness (``qa.prompt_eval_harness``).

Judges prompt *text* and offline artifacts only: fixed frozen
samples, measured coverage/repetition/frame-consistency numbers,
and a structured pass/fail report. It never generates anything.

The frozen sample set (``SAMPLE_VERSION``) reuses the audit's bad
samples as regression cases: a prompt that was bad before the
2026-10-31 compiler fixes must fail here, and the repaired good
samples must pass. Changing a sample requires bumping
``SAMPLE_VERSION`` -- samples are frozen, not edited in place.

Generation consistency (does the generated clip match the prompt?)
is measured here ONLY from offline artifacts a caller supplies:
a full-film ASR transcript and/or forced-alignment word timings
(the ``audio.forced_align`` output shape), frame records extracted
from the generated clip (per-frame anchor agreement, frame
difference, movement direction and banned-content detections),
and the prompt's expected lines, ban list and declared camera
movement. :func:`measure_generation_consistency` implements the
four measurements on that contract and nothing else: with no
usable artifact for a measurement it reports
``planned_not_measured`` for that measurement, with ``value``
``None`` -- never a score. It never generates anything, never
calls a transcription or alignment service, and never reads a
video file: a bare video path is provenance only, not evidence.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from hevi.capabilities.asr_normalization import normalized_text_only
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)
from hevi.capabilities.pure_helpers import (
    _containment_coverage,
)
from hevi.capabilities.pure_helpers import (
    _PUNCT,
    _normalise_text,
)

_Registered = False

SAMPLE_VERSION = "3"  # v3: three-layer clip samples added (7-step workflow graft); v2 samples untouched.

# Generation-consistency measurements: interface only. Each entry
# names the measurement, the offline artifact it needs, and the
# comparison it performs. No implementation here produces a score.
CONSISTENCY_MEASUREMENTS: tuple[dict[str, str], ...] = (
    {
        "name": "character_consistency",
        "needs": "generated clip frames + anchor reference files",
        "comparison": "per-shot face/appearance agreement with the confirmed anchor",
    },
    {
        "name": "dialogue_asr",
        "needs": "generated clip audio + verbatim lines from the prompt",
        "comparison": "ASR transcript of the clip against the prompt lines, with timestamps",
    },
    {
        "name": "motion_frame_diff",
        "needs": "generated clip frames + declared camera movement",
        "comparison": "frame-difference / optical-flow direction against the declared movement",
    },
    {
        "name": "ban_violation",
        "needs": "generated clip frames + the prompt's ban list",
        "comparison": "presence of banned content (on-screen text, extra people, watermark)",
    },
)


# Offline-artifact contract for generation-consistency measurement.
# Every measurement needs its own evidence; a missing piece leaves
# exactly that measurement ``planned_not_measured``. Frame records
# are MEASURED values extracted from a generated clip by the
# caller (an extractor, a human review, or ``qa.final_qc_gate``'s
# sampling) -- this module never invents them from a video path.
GENERATION_CONSISTENCY_CONTRACT: dict[str, Any] = {
    "prompt": {
        "expected_lines": "verbatim dialogue/VO lines from the prompt (list of strings)",
        "bans": "the prompt's ban list (list of strings); an empty list means no bans declared",
        "declared_camera_movement": "one of dolly_in/dolly_out/pan_left/pan_right/tilt_up/tilt_down/static",
    },
    "asr_text": "full-film ASR transcript text (string)",
    "word_timings": "forced-alignment word timings: [{text, start_ms, end_ms}] or [{text, start_sec, end_sec}]",
    "frames": "frame records: [{anchor_agreement (0..1), frame_diff (>=0), "
              "movement_direction, banned (list of detected banned items)}]",
    "video_path": "provenance only; a path alone measures nothing",
}

DIALOGUE_COVERAGE_FLOOR = 0.8
CHARACTER_AGREEMENT_FLOOR = 0.8
MOTION_DIRECTION_FLOOR = 0.6

_MOVEMENT_DIRECTIONS: dict[str, str] = {
    "dolly_in": "zoom_in", "zoom_in": "zoom_in",
    "dolly_out": "zoom_out", "zoom_out": "zoom_out",
    "pan_left": "pan_left", "pan_right": "pan_right",
    "tilt_up": "tilt_up", "tilt_down": "tilt_down",
    "static": "static", "fixed": "static",
}







def _prompt_section(artifacts: dict[str, Any]) -> dict[str, Any]:
    prompt = artifacts.get("prompt")
    return prompt if isinstance(prompt, dict) else {}


def _expected_lines(artifacts: dict[str, Any]) -> list[str] | None:
    prompt = _prompt_section(artifacts)
    lines = prompt.get("expected_lines", prompt.get("lines", artifacts.get("expected_lines")))
    if lines is None:
        return None
    if isinstance(lines, str):
        lines = [lines]
    if not isinstance(lines, list) or any(not isinstance(line, str) for line in lines):
        raise CapabilityError(
            "qa.prompt_eval_harness: expected_lines must be a list of strings")
    return [line for line in lines if line.strip()]


def _timing_text(word_timings: Any) -> str | None:
    if not isinstance(word_timings, list) or not word_timings:
        return None
    texts: list[str] = []
    for entry in word_timings:
        if not isinstance(entry, dict):
            return None
        text = entry.get("text")
        if not isinstance(text, str):
            return None
        texts.append(text)
    return " ".join(texts)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and value == value and value not in (float("inf"), float("-inf"))


def _unmeasured(spec: dict[str, str], reason: str) -> dict[str, Any]:
    return {**spec, "status": "planned_not_measured", "value": None,
            "verdict": "planned_not_measured", "detail": reason}


def _measure_dialogue_asr(artifacts: dict[str, Any]) -> dict[str, Any]:
    spec = next(s for s in CONSISTENCY_MEASUREMENTS if s["name"] == "dialogue_asr")
    lines = _expected_lines(artifacts)
    if not lines:
        return _unmeasured(spec, "no expected lines in the prompt section")
    asr_text = artifacts.get("asr_text")
    timing_text = _timing_text(artifacts.get("word_timings"))
    if not isinstance(asr_text, str) or not asr_text.strip():
        if timing_text is None:
            return _unmeasured(spec, "no ASR transcript and no forced-alignment word timings")
        observed = timing_text
        source = "forced-alignment word timings"
    else:
        observed = asr_text
        source = "ASR transcript"
    coverages = [_containment_coverage(line, observed) for line in lines]
    value = sum(coverages) / len(coverages)
    timing_coverage: float | None = None
    if timing_text is not None and observed is not timing_text:
        timing_coverages = [_containment_coverage(line, timing_text) for line in lines]
        timing_coverage = sum(timing_coverages) / len(timing_coverages)
    result: dict[str, Any] = {
        **spec, "status": "measured", "value": round(value, 4),
        "verdict": "pass" if value >= DIALOGUE_COVERAGE_FLOOR else "fail",
        "detail": (f"mean line coverage {value:.3f} over {len(lines)} expected "
                   f"line(s) from the {source} (floor {DIALOGUE_COVERAGE_FLOOR})"),
        "per_line_coverage": [round(c, 4) for c in coverages],
    }
    if timing_coverage is not None:
        result["timing_coverage"] = round(timing_coverage, 4)
    return result


def _frame_records(artifacts: dict[str, Any]) -> list[dict[str, Any]] | None:
    frames = artifacts.get("frames")
    if frames is None:
        return None
    if not isinstance(frames, list) or not frames \
            or any(not isinstance(frame, dict) for frame in frames):
        raise CapabilityError(
            "qa.prompt_eval_harness: frames must be a non-empty list of frame records")
    return frames


def _measure_character_consistency(artifacts: dict[str, Any]) -> dict[str, Any]:
    spec = next(s for s in CONSISTENCY_MEASUREMENTS if s["name"] == "character_consistency")
    frames = _frame_records(artifacts)
    if frames is None:
        return _unmeasured(spec, "no frame records supplied")
    scores: list[float] = []
    for frame in frames:
        score = frame.get("anchor_agreement")
        if not _is_number(score) or not 0.0 <= float(score) <= 1.0:
            return _unmeasured(
                spec, "a frame record carries no measured anchor_agreement in [0, 1]; "
                      "agreement is never estimated from a video path")
        scores.append(float(score))
    value = sum(scores) / len(scores)
    return {**spec, "status": "measured", "value": round(value, 4),
            "verdict": "pass" if value >= CHARACTER_AGREEMENT_FLOOR else "fail",
            "detail": (f"mean anchor agreement {value:.3f} over {len(scores)} frame "
                       f"record(s), min {min(scores):.3f} "
                       f"(floor {CHARACTER_AGREEMENT_FLOOR})"),
            "min_agreement": round(min(scores), 4)}


def _measure_motion_frame_diff(artifacts: dict[str, Any]) -> dict[str, Any]:
    spec = next(s for s in CONSISTENCY_MEASUREMENTS if s["name"] == "motion_frame_diff")
    frames = _frame_records(artifacts)
    if frames is None:
        return _unmeasured(spec, "no frame records supplied")
    declared = _prompt_section(artifacts).get(
        "declared_camera_movement", artifacts.get("declared_camera_movement"))
    if not isinstance(declared, str) or declared.strip() not in _MOVEMENT_DIRECTIONS:
        return _unmeasured(
            spec, "no recognised declared_camera_movement in the prompt section")
    want = _MOVEMENT_DIRECTIONS[declared.strip()]
    agreements = 0
    checked = 0
    diffs: list[float] = []
    for frame in frames[1:]:
        diff = frame.get("frame_diff")
        direction = frame.get("movement_direction", frame.get("flow_direction"))
        if not _is_number(diff) or float(diff) < 0 or not isinstance(direction, str):
            return _unmeasured(
                spec, "a frame record carries no measured frame_diff / "
                      "movement_direction; motion is never inferred from a video path")
        diffs.append(float(diff))
        checked += 1
        if direction.strip() == want or (want == "static" and float(diff) < 2.0):
            agreements += 1
    if not checked:
        return _unmeasured(spec, "fewer than two frame records; no interval to measure")
    agreement = agreements / checked
    mean_diff = sum(diffs) / len(diffs)
    return {**spec, "status": "measured", "value": round(agreement, 4),
            "verdict": "pass" if agreement >= MOTION_DIRECTION_FLOOR else "fail",
            "detail": (f"movement-direction agreement {agreement:.3f} "
                       f"({agreements}/{checked} intervals, declared {declared.strip()} "
                       f"-> {want}, mean frame diff {mean_diff:.2f}, "
                       f"floor {MOTION_DIRECTION_FLOOR})"),
            "mean_frame_diff": round(mean_diff, 4)}


def _measure_ban_violation(artifacts: dict[str, Any]) -> dict[str, Any]:
    spec = next(s for s in CONSISTENCY_MEASUREMENTS if s["name"] == "ban_violation")
    prompt = _prompt_section(artifacts)
    bans = prompt.get("bans", artifacts.get("bans"))
    if bans is None:
        return _unmeasured(spec, "no ban list in the prompt section")
    if isinstance(bans, str):
        bans = [bans]
    if not isinstance(bans, list) or any(not isinstance(ban, str) for ban in bans):
        raise CapabilityError("qa.prompt_eval_harness: bans must be a list of strings")
    banned_terms = {ban.strip().lower() for ban in bans if ban.strip()}
    frames = _frame_records(artifacts)
    if frames is None:
        return _unmeasured(spec, "no frame records supplied")
    violating: list[int] = []
    hits: list[str] = []
    for index, frame in enumerate(frames):
        detected = frame.get("banned")
        if detected is None:
            return _unmeasured(
                spec, f"frame record {index} carries no banned detection list; "
                      "a missing detection is not a clean frame")
        if not isinstance(detected, list) or any(not isinstance(item, str) for item in detected):
            raise CapabilityError(
                "qa.prompt_eval_harness: frame banned must be a list of strings")
        found = [item for item in detected if item.strip().lower() in banned_terms]
        if found:
            violating.append(index)
            hits.extend(found)
    value = len(violating) / len(frames)
    return {**spec, "status": "measured", "value": round(value, 4),
            "verdict": "pass" if not violating else "fail",
            "detail": (f"{len(violating)}/{len(frames)} frame records violate the ban "
                       f"list ({sorted(set(hits)) or 'none'})" if violating else
                       f"0/{len(frames)} frame records violate the ban list"),
            "violating_frames": violating}


def measure_generation_consistency(artifacts: Any) -> dict[str, Any]:
    """Measure generation consistency from offline artifacts only.

    ``artifacts`` follows :data:`GENERATION_CONSISTENCY_CONTRACT`.
    Each of the four measurements is computed only from the
    evidence it names; a measurement without its evidence reports
    ``planned_not_measured`` with ``value`` ``None``. A score
    without a generated artifact would be invented, so none is
    ever produced here.
    """
    if not isinstance(artifacts, dict):
        raise CapabilityError(
            "qa.prompt_eval_harness: generation artifacts must be a JSON object")
    measurements = [
        _measure_character_consistency(artifacts),
        _measure_dialogue_asr(artifacts),
        _measure_motion_frame_diff(artifacts),
        _measure_ban_violation(artifacts),
    ]
    measured = [m for m in measurements if m["status"] == "measured"]
    if len(measured) == len(measurements):
        status = "measured"
    elif measured:
        status = "partially_measured"
    else:
        status = "planned_not_measured"
    if status == "measured":
        verdict = "pass" if all(m["verdict"] == "pass" for m in measurements) else "fail"
    elif status == "partially_measured":
        verdict = "fail" if any(m["verdict"] == "fail" for m in measurements) \
            else "planned_not_measured"
    else:
        verdict = "planned_not_measured"
    return {
        "status": status,
        "verdict": verdict,
        "measured_count": len(measured),
        "measurements": measurements,
        "required_artifacts": [spec["needs"] for spec in CONSISTENCY_MEASUREMENTS],
        "contract": GENERATION_CONSISTENCY_CONTRACT,
        "note": (
            "Scores come only from the supplied offline artifacts. "
            "A measurement without its artifact stays "
            "planned_not_measured; no executor, transcription or "
            "alignment service is called here."
        ),
    }


def build_generation_consistency_fixture() -> dict[str, Any]:
    """Fixed offline sample for the consistency measurements.

    Synthetic MEASURED records (not a real generation): an ASR
    transcript and forced-alignment timings that contain the
    prompt's lines, and frame records with anchor agreement,
    frame differences, movement directions and ban detections.
    It proves the measurement code runs; it proves nothing about
    any real generated clip.
    """
    return {
        "video_path": "fixture://generation-consistency-sample.mp4",
        "prompt": {
            "expected_lines": ["玉兰开了", "春天来了"],
            "bans": ["on-screen text", "watermark"],
            "declared_camera_movement": "dolly_in",
        },
        "asr_text": "玉兰开了，春天来了，花瓣飘落。",
        "word_timings": [
            {"text": "玉兰开了", "start_ms": 0, "end_ms": 900},
            {"text": "春天来了", "start_ms": 1000, "end_ms": 1900},
        ],
        "frames": [
            {"anchor_agreement": 0.92, "frame_diff": 0.0,
             "movement_direction": "static", "banned": []},
            {"anchor_agreement": 0.90, "frame_diff": 5.5,
             "movement_direction": "zoom_in", "banned": []},
            {"anchor_agreement": 0.88, "frame_diff": 6.1,
             "movement_direction": "zoom_in", "banned": []},
            {"anchor_agreement": 0.91, "frame_diff": 5.8,
             "movement_direction": "zoom_in", "banned": []},
        ],
    }


def _picture_file(work_dir: Path, picture: int, content: bytes) -> dict[str, Any]:
    path = work_dir / f"picture_{picture}.png"
    path.write_bytes(content)
    return {"file": str(path), "sha256": hashlib.sha256(content).hexdigest()}


def _anchor_sheet(file: str, sha256: str, *, confirmed: bool) -> dict[str, Any]:
    return {
        "character_id": "alan",
        "name": "阿兰",
        "anchor": {
            "file": file,
            "sha256": sha256,
            "look_snapshot": "二十多岁女子，象牙白缎面抹胸长裙，金色花朵发簪",
            "description_fingerprint": hashlib.sha256(
                "二十多岁女子，象牙白缎面抹胸长裙，金色花朵发簪".encode("utf-8")
            ).hexdigest(),
            "confirmed": confirmed,
        },
        "views": [],
        "anchor_changes": 0,
    }


def _state() -> dict[str, Any]:
    return {
        "人物": {"脸": "与参考图一致", "发簪": "金色花朵发簪在位"},
        "服装": {"裙": "象牙白缎面抹胸长裙"},
        "道具": {"左手": "轻轻搭在月洞门石边沿"},
    }


def _good_episode() -> dict[str, Any]:
    return {
        "episode_no": "HARNESS",
        "title": "玉兰开了",
        "target_duration_s": 10.0,
        "aspect": "9:16",
        "style": "小红书新中式写真风格，奶白色调，低饱和，柔焦",
        "shots": [
            {
                "shot_no": "H01",
                "scene": "苏州园林风格中式古典园林，白墙圆形月洞门",
                "time_of_day": "春日午后",
                "duration_s": 10.0,
                "camera": {
                    "shot_size": "中景",
                    "shot_size_end": "中近景",
                    "angle": "平视",
                    "movement": "dolly_in",
                    "easing": "ease_in_out",
                    "start_frame": {
                        "state_kind": "trigger_in_progress",
                        "description": "人物站在月洞门边，微风未起",
                    },
                    "end_frame": {"description": "人物微笑看着镜头，花瓣飘落"},
                },
                "characters": ["阿兰"],
                "props": ["金色花朵发簪"],
                "continuity": {"entry_state": _state(), "exit_state": _state()},
                "negative_prompts": ["换脸", "发簪消失", "手指畸形"],
                "fallbacks": [
                    {"trigger": "接花瓣失败", "replacement": "删掉递花瓣动作，改为低头看掌心花瓣"},
                ],
                "beats": [
                    {"beat_no": 1, "t_start_s": 0.0, "t_end_s": 2.5,
                     "action": "微风吹过，玉兰枝摇动，花瓣飘落，人物看着镜头",
                     "sound": "风声、树叶沙沙声"},
                    {"beat_no": 2, "t_start_s": 2.5, "t_end_s": 4.5,
                     "action": "人物把头轻轻转向画面左侧看向池水，再慢慢转回来看向镜头",
                     "sound": "风声、鸟叫", "camera_move": "dolly_in"},
                    {"beat_no": 3, "t_start_s": 4.5, "t_end_s": 5.5,
                     "action": "一片玉兰花瓣飘到身前，抬起画面右侧那只手掌心向上接住花瓣",
                     "sound": "风声"},
                    {"beat_no": 4, "t_start_s": 5.5, "t_end_s": 8.3,
                     "action": "看着镜头轻声说话，说到一起来看时把掌心花瓣轻轻往镜头方向递了一下",
                     "sound": "古筝加竹笛，说话时音乐压低",
                     "line": "玉兰开了", "speaker": "阿兰", "line_mode": "dialogue"},
                    {"beat_no": 5, "t_start_s": 8.3, "t_end_s": 10.0,
                     "action": "轻轻歪头温柔地笑，微风又吹落几片花瓣，保持微笑定格",
                     "sound": "古筝加竹笛、风声"},
                ],
                "clips": [{"clip_id": "H01c1", "beats": [1, 2, 3, 4, 5]}],
            }
        ],
    }


def _good_scene_plan() -> dict[str, Any]:
    return {
        "scene": {"description": "A quiet tea room.", "framing": "Fixed camera, wide shot."},
        "characters": [
            {"name": "守仁", "description": "A twelve-year-old student in a grey-green robe.",
             "anchor": {
                 "file": "", "sha256": "",
                 "look_snapshot": "十二岁少年，灰绿长袍，蓝色头巾",
                 "confirmed": True,
             }},
        ],
        "angles": [{"description": "The same room from the doorway."}],
        "shots": [{"description": "守仁走进私塾。",
                   "dialogue": "守仁说：\"我想做圣贤。\""}],
        "soundscape": "Rain against the window, faint steam.",
        "voices": ["守仁"],
        # Execution fields (fix 6): a strict build without
        # duration_s fails; the frame count is written into the
        # prompt text from canonical_frame_count (route h3).
        "duration_s": 10.0,
        "camera_movement": "Fixed camera.",
        "shot_size": "wide shot",
        "lighting": "soft window light",
        "style": "quiet tea room, natural light",
        "negative_prompts": ["on-screen text"],
        "aspect_ratio": "16:9",
    }


def build_frozen_samples(work_dir: Path) -> list[dict[str, Any]]:
    """Build the frozen sample set, creating its picture files in ``work_dir``.

    Picture files are deterministic harness-owned bytes whose hashes
    are recorded in the bindings: the files exist, the hashes match,
    and nothing is downloaded or generated.
    Composes (3O SPEC 1.2): build_three_layer_fixtures.
    """
    import copy

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    scene_pic = _picture_file(work_dir, 1, b"prompt-eval-harness picture 1: garden gate\n")
    alan_pic = _picture_file(work_dir, 2, b"prompt-eval-harness picture 2: alan anchor\n")
    shouren_pic = _picture_file(work_dir, 3, b"prompt-eval-harness picture 3: shouren anchor\n")
    angle_pic = _picture_file(work_dir, 4, b"prompt-eval-harness picture 4: doorway angle\n")
    bindings = {1: scene_pic, 2: alan_pic}
    anchors = {"阿兰": _anchor_sheet(alan_pic["file"], alan_pic["sha256"], confirmed=True)}

    samples: list[dict[str, Any]] = []

    def beat_sample(name: str, expect: str, **overrides: Any) -> dict[str, Any]:
        sample: dict[str, Any] = {
            "name": name, "kind": "beat_episode", "expect": expect,
            "episode": copy.deepcopy(_good_episode()),
            "provider": "fasth3_local",
            "anchors": copy.deepcopy(anchors),
            "reference_bindings": copy.deepcopy(bindings),
        }
        sample.update(overrides)
        return sample

    samples.append(beat_sample("good_beat_episode", "pass"))

    no_anchor = beat_sample("no_anchor_fails", "fail")
    no_anchor["anchors"] = {}
    samples.append(no_anchor)

    unconfirmed = beat_sample("unconfirmed_anchor_fails", "fail")
    unconfirmed["anchors"] = {
        "阿兰": _anchor_sheet(alan_pic["file"], alan_pic["sha256"], confirmed=False)}
    samples.append(unconfirmed)

    no_binding = beat_sample("missing_picture_1_binding_fails", "fail")
    no_binding["reference_bindings"] = {2: alan_pic}
    samples.append(no_binding)

    no_provider = beat_sample("no_provider_fails", "fail")
    no_provider["provider"] = ""
    samples.append(no_provider)

    over_cap = beat_sample("over_provider_cap_fails", "fail")
    episode = over_cap["episode"]
    episode["target_duration_s"] = 35.0
    shot = episode["shots"][0]
    shot["duration_s"] = 35.0
    spans = [(0.0, 5.0), (5.0, 12.0), (12.0, 18.0), (18.0, 28.0), (28.0, 35.0)]
    for beat, (start, end) in zip(shot["beats"], spans):
        beat["t_start_s"], beat["t_end_s"] = start, end
    samples.append(over_cap)

    repeated = beat_sample("repeated_beats_fail", "fail")
    episode = repeated["episode"]
    shot = episode["shots"][0]
    shot["beats"] = [
        {"beat_no": i + 1, "t_start_s": i * 2.5, "t_end_s": (i + 1) * 2.5,
         "action": "人物站在月洞门边一动不动", "sound": "风声"}
        for i in range(4)
    ]
    shot["clips"] = [{"clip_id": "H01c1", "beats": [1, 2, 3, 4]}]
    shot.pop("negative_prompts", None)
    samples.append(repeated)

    scene_bindings = {1: scene_pic, 2: angle_pic, 3: shouren_pic}
    scene_plan = _good_scene_plan()
    scene_plan["characters"][0]["anchor"]["file"] = shouren_pic["file"]
    scene_plan["characters"][0]["anchor"]["sha256"] = shouren_pic["sha256"]
    scene_plan["angles"][0]["file"] = angle_pic["file"]
    scene_plan["angles"][0]["sha256"] = angle_pic["sha256"]
    samples.append({
        "name": "good_scene_reference", "kind": "scene_reference", "expect": "pass",
        "plan": scene_plan, "reference_files": scene_bindings,
    })

    unbound_dialogue = copy.deepcopy(scene_plan)
    unbound_dialogue["voices"] = []
    samples.append({
        "name": "chinese_dialogue_without_voice_fails", "kind": "scene_reference",
        "expect": "fail", "plan": unbound_dialogue,
        "reference_files": scene_bindings,
    })

    no_duration = copy.deepcopy(scene_plan)
    no_duration.pop("duration_s")
    samples.append({
        "name": "scene_reference_without_duration_fails", "kind": "scene_reference",
        "expect": "fail", "plan": no_duration,
        "reference_files": scene_bindings,
    })

    # v3: three-layer clip samples (7-step workflow graft). The
    # fixtures live in qa.three_layer_clip and are versioned there;
    # the harness only pins two of them (one pass, one fail).
    from hevi.capabilities.three_layer_clip import (
        build_three_layer_fixtures,
    )

    for fixture in build_three_layer_fixtures():
        if fixture["name"] in ("good_three_layer_clip",
                               "two_actions_in_one_segment_fails"):
            samples.append({
                "name": fixture["name"], "kind": "three_layer_clip",
                "expect": fixture["expect"], "clip": fixture["clip"],
            })
    return samples


def _measure_beat_prompts(result: dict[str, Any]) -> dict[str, Any]:
    prompts = result.get("prompts", [])
    clip_prompts = result.get("clip_prompts", {})
    shots = result.get("shot_count", 0)
    measurements: dict[str, Any] = {
        "anchor_coverage": (
            len(result.get("readiness", {}).get("anchors", [])) / max(shots, 1)
            if prompts else 0.0
        ),
        "picture_bindings": len(result.get("readiness", {}).get("picture_bindings", [])),
        "negative_coverage": (
            sum(1 for p in prompts if p.get("negative_prompts")) / max(len(prompts), 1)),
        "camera_coverage": (
            sum(1 for p in prompts if p.get("easing") or p.get("shot_size_end"))
            / max(len(prompts), 1)),
        "frames_in_prompt": all("帧" in p["prompt"] for p in prompts) if prompts else False,
        "anchor_in_prompt": all("锚点已确认" in p["prompt"] for p in prompts) if prompts else False,
        "clip_prompts": len(clip_prompts),
        "clip_camera_state_constraints": (
            all("Camera:" in t and "State:" in t and "Constraints:" in t
                for t in clip_prompts.values())
            if clip_prompts else False
        ),
    }
    return measurements


def evaluate_sample(sample: dict[str, Any]) -> dict[str, Any]:
    """Run one frozen sample. Returns a report with verdict + measurements. Composes (3O SPEC 1.2): check_three_layer_clip, compile_generation_ready_episode."""
    kind = sample.get("kind")
    expect = sample.get("expect")
    report: dict[str, Any] = {
        "name": sample.get("name"), "kind": kind, "expect": expect,
        "sample_version": SAMPLE_VERSION,
    }
    try:
        if kind == "beat_episode":
            from hevi.capabilities.prompt_compiler import (
                compile_generation_ready_episode,
            )

            result = compile_generation_ready_episode(
                sample["episode"],
                provider=sample["provider"],
                anchors=sample["anchors"],
                reference_bindings=sample["reference_bindings"],
            )
            report["verdict"] = "pass"
            report["measurements"] = _measure_beat_prompts(result)
            report["issues"] = []
        elif kind == "scene_reference":
            from hevi.capabilities.scene_reference import (
                build_h3_prompt,
                check_h3_prompt,
            )

            built = build_h3_prompt(
                sample["plan"], strict=True,
                reference_files=sample["reference_files"])
            check = check_h3_prompt(built)
            if check["verdict"] != "pass":
                raise CapabilityError(
                    f"pipeline.scene_reference: check verdict {check['verdict']}: "
                    f"{[i['code'] for i in check['issues']]}")
            report["verdict"] = "pass"
            report["measurements"] = {
                "dialogue_speakers": built["dialogue_speakers"],
                "speaker_tagged": "(S1)" in built["text"],
                "picture_files": built.get("picture_files", {}),
                "frames": built.get("frames"),
                "execution_in_text": "243 frames" in built["text"],
                "execution": built.get("execution", {}),
            }
            report["issues"] = []
        elif kind == "three_layer_clip":
            from hevi.capabilities.three_layer_clip import (
                check_three_layer_clip,
            )

            check = check_three_layer_clip(sample["clip"])
            if check["verdict"] != "pass":
                raise CapabilityError(
                    "qa.three_layer_clip: check verdict "
                    f"{check['verdict']}: "
                    f"{[i['code'] for i in check['issues']]}")
            report["verdict"] = "pass"
            report["measurements"] = {
                "segments": len(check["segments"]),
                "still_instant_once": check["rendered"].count("[静图瞬间]") == 1
                if check["rendered"] else False,
            }
            report["issues"] = []
        else:
            raise CapabilityError(f"qa.prompt_eval_harness: unknown sample kind {kind!r}")
    except Exception as exc:  # noqa: BLE001 - harness reports, never raises
        report["verdict"] = "fail"
        report["measurements"] = {}
        report["issues"] = [{"code": type(exc).__name__, "message": str(exc)}]
    report["matched_expectation"] = report["verdict"] == expect
    return report


def run_frozen_samples(work_dir: Path) -> dict[str, Any]:
    """Run the whole frozen set. Returns the structured harness report."""
    samples = build_frozen_samples(Path(work_dir))
    reports = [evaluate_sample(sample) for sample in samples]
    return {
        "sample_version": SAMPLE_VERSION,
        "samples": reports,
        "matched": sum(1 for r in reports if r["matched_expectation"]),
        "total": len(reports),
        "verdict": "pass" if all(r["matched_expectation"] for r in reports) else "fail",
        "generation_consistency": measure_generation_consistency({}),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    report = run_frozen_samples(Path(out_dir) / "prompt_eval_assets")
    report_path = Path(out_dir) / "prompt_eval_harness.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"],
            "matched": report["matched"], "total": report["total"]},
    )


def register_prompt_eval_harness_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="qa.prompt_eval_harness",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        cpu_cost_hint=0.0,
        render=_render,
        has_media_output=False,
        description=(
            "Prompt eval harness (offline, no generation): frozen prompt "
            "samples with measured anchor/binding/field coverage, "
            "repetition and frame consistency. Generation-consistency "
            "measurements run only on supplied offline artifacts "
            "(ASR / forced-alignment timings / frame records) and "
            "stay planned_not_measured without them."
        ),
        line="qa",
    ))
    return ["qa.prompt_eval_harness"]


register_prompt_eval_harness_capabilities_once()
