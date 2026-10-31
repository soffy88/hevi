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
is deliberately NOT measured here: there is no executor in this
module. :func:`measure_generation_consistency` only declares the
measurement interface and its offline-artifact contract, and
always reports ``planned_not_measured``. Any score for character
consistency, dialogue ASR, motion frame difference or ban
violation without a real generated artifact would be fabricated.
"""

from __future__ import annotations

import hashlib
import json
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

SAMPLE_VERSION = "1"

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


def measure_generation_consistency(artifacts: Any) -> dict[str, Any]:
    """Declare the generation-consistency interface. Always unmeasured.

    ``artifacts`` is accepted and validated for shape only; no
    score is ever computed from it here. Callers with real
    generated artifacts must run the (not yet built) measurement
    implementations and record their own results elsewhere.
    """
    if not isinstance(artifacts, dict):
        raise CapabilityError(
            "qa.prompt_eval_harness: generation artifacts must be a JSON object")
    return {
        "status": "planned_not_measured",
        "measurements": [
            {**spec, "status": "planned_not_measured", "value": None}
            for spec in CONSISTENCY_MEASUREMENTS
        ],
        "required_artifacts": [spec["needs"] for spec in CONSISTENCY_MEASUREMENTS],
        "note": (
            "No executor is wired into this harness. A consistency "
            "score without a generated artifact would be invented."
        ),
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
    }


def build_frozen_samples(work_dir: Path) -> list[dict[str, Any]]:
    """Build the frozen sample set, creating its picture files in ``work_dir``.

    Picture files are deterministic harness-owned bytes whose hashes
    are recorded in the bindings: the files exist, the hashes match,
    and nothing is downloaded or generated.
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
    """Run one frozen sample. Returns a report with verdict + measurements."""
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
            "measurements are declared as planned_not_measured only."
        ),
        line="qa",
    ))
    return ["qa.prompt_eval_harness"]


register_prompt_eval_harness_capabilities_once()
