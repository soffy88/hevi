"""digital_human omodul:文本规划/任务编排，供 studio/production 工作流调用。

对应 lanshu SKILL.md 的状态机驱动：
intake → content_locked → audio_locked → visual_plan_locked → presenter_generated → composition_checked → rendered → verified
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from hevi.digital_human.oprim import (
    calibrate_audio_loudness as _calibrate_audio_loudness,
)
from hevi.digital_human.oprim import (
    generate_narration as _generate_narration,
)
from hevi.digital_human.oprim import (
    lock_content as _lock_content,
)
from hevi.digital_human.oskill import (
    caption_plan,
    content_lock,
    delivery,
    generate_presenter,
    preflight_check,
    qa_gate,
    visual_plan,
)
from hevi.digital_human.schemas import (
    AudioMeasurement,
    CaptionPlan,
    JobStatus,
    PresenterJob,
    QAReport,
    TimelinePlan,
    make_default_caption_plan,
    make_default_job,
    make_default_qa_report,
    make_default_timeline,
)

# ─── 作业初始化 ─────────────────────────────────────


def init_job(
    job_dir: str,
    presenter_image: str,
    topic: str = "",
    script_path: str = "",
    voice_sample: str = "",
    supporting_media: list[str] | None = None,
    rights_confirmed: bool = False,
    adult_presenter_confirmed: bool = False,
    remote_upload_approved: bool = False,
    voice_clone_approved: bool = False,
    language: str = "auto",
    audience: str = "general",
    duration_target_s: int = 60,
    aspect: str = "9:16",
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    style: str = "credible contemporary presenter",
    watermark: str = "",
    cta: str = "",
) -> PresenterJob:
    """初始化作业（对应 lanshu init_job.py）。

    创建作业目录结构和 job.json，返回 PresenterJob 实例。
    """
    job = make_default_job()
    job.job_id = Path(job_dir).name
    job.topic = topic
    job.script_path = script_path
    job.presenter_image = presenter_image
    job.voice_sample = voice_sample
    job.supporting_media = supporting_media or []
    job.rights_confirmed = rights_confirmed
    job.adult_presenter_confirmed = adult_presenter_confirmed
    job.remote_upload_approved = remote_upload_approved
    job.voice_clone_approved = voice_clone_approved
    job.language = language
    job.audience = audience
    job.duration_target_s = duration_target_s
    job.aspect = aspect
    job.width = width
    job.height = height
    job.fps = fps
    job.style = style
    job.watermark = watermark
    job.cta = cta

    # 创建目录结构
    dirs = [
        "docs",
        "assets/source",
        "assets/audio/reference",
        "assets/audio/raw",
        "assets/audio/final",
        "assets/video/candidates",
        "assets/video/selected",
        "assets/video/render",
        "assets/captions",
        "qa/requests",
        "qa/asr",
        "qa/contacts",
        "qa/reports",
        "renders",
        "outputs",
    ]
    for d in dirs:
        (Path(job_dir) / d).mkdir(parents=True, exist_ok=True)

    # 保存 job.json
    job_path = Path(job_dir) / "job.json"
    job_path.write_text(job.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8")

    return job


# ─── 阶段计划构建 ────────────────────────────────────


def plan_generation(job: PresenterJob) -> dict[str, Any]:
    """构建生成阶段计划 (intake → audio_locked)。

    对应 lanshu generation.md 的完整流程
    """
    # 预检
    preflight = preflight_check(job)

    plan = {
        "phase": "generation",
        "job_id": job.job_id,
        "current_status": job.status.value,
        "target_status": JobStatus.AUDIO_LOCKED.value,
        "preflight": preflight.model_dump(),
        "steps": [
            {
                "step": "lock_content",
                "fn": "content_lock",
                "args": {"voice_id": job.voice_id, "rate": job.rate},
                "required": True,
            },
            {
                "step": "generate_narration",
                "fn": "generate_narration",
                "args": {},
                "required": True,
            },
            {
                "step": "calibrate_loudness",
                "fn": "calibrate_audio_loudness",
                "args": {"target_lufs": job.program_lufs},
                "required": True,
            },
        ],
        "gate": {
            "type": "qa_gate",
            "checks": [
                "rights_confirmed",
                "adult_presenter_confirmed",
                "remote_upload_approved",
                "voice_clone_approved",
                "script_not_empty",
                "final_audio_exists",
            ],
        },
    }

    return plan


def plan_visual(job: PresenterJob, narration_duration_s: float) -> dict[str, Any]:
    """构建视觉规划阶段计划 (audio_locked → visual_plan_locked)。

    对应 lanshu editing.md 的视觉路线选择 + 时间轴构建
    """
    plan = {
        "phase": "visual_plan",
        "job_id": job.job_id,
        "current_status": job.status.value,
        "target_status": JobStatus.VISUAL_PLAN_LOCKED.value,
        "steps": [
            {
                "step": "visual_plan",
                "fn": "visual_plan",
                "args": {
                    "narration_duration_s": narration_duration_s,
                    "opening_target_s": 4.0,
                    "closing_target_s": 5.0,
                },
                "required": True,
            },
            {
                "step": "caption_plan",
                "fn": "caption_plan",
                "args": {
                    "audio_duration_s": narration_duration_s,
                    "keyword_anchors": None,
                },
                "required": True,
            },
        ],
        "gate": {
            "type": "qa_gate",
            "checks": [
                "timeline_valid",
                "caption_plan_valid",
            ],
        },
    }

    return plan


def plan_presenter_generation(job: PresenterJob) -> dict[str, Any]:
    """构建人物生成阶段计划 (visual_plan_locked → presenter_generated)。

    对应 lanshu generation.md 第 2 节：试片 → 全片
    """
    plan = {
        "phase": "presenter_generation",
        "job_id": job.job_id,
        "current_status": job.status.value,
        "target_status": JobStatus.PRESENTER_GENERATED.value,
        "steps": [
            {
                "step": "pilot_generation",
                "fn": "generate_presenter",
                "args": {"mode": "pilot", "pilot_duration_s": 5.0},
                "required": True,
            },
            {
                "step": "pilot_qa",
                "fn": "qa_gate",
                "args": {
                    "identity_coherent": True,
                    "mouth_sync": True,
                    "no_black_frames": True,
                    "captions_readable": True,
                    "safe_zones_ok": True,
                },
                "required": True,
            },
            {
                "step": "full_generation",
                "fn": "generate_presenter",
                "args": {"mode": "full"},
                "required": True,
            },
        ],
        "gate": {
            "type": "qa_gate",
            "checks": [
                "pilot_accepted",
                "identity_stable",
                "mouth_timing_ok",
            ],
        },
    }

    return plan


def plan_composition(job: PresenterJob) -> dict[str, Any]:
    """构建合成/剪辑阶段计划 (presenter_generated → composition_checked)。

    对应 lanshu editing.md 第 3-4 节：时间轴合成 + 字幕/动效烧录
    """
    plan = {
        "phase": "composition",
        "job_id": job.job_id,
        "current_status": job.status.value,
        "target_status": JobStatus.COMPOSITION_CHECKED.value,
        "steps": [
            {
                "step": "compose_timeline",
                "fn": "compose_timeline",
                "args": {},
                "required": True,
            },
            {
                "step": "burn_captions",
                "fn": "burn_captions",
                "args": {},
                "required": True,
            },
            {
                "step": "add_keyword_effects",
                "fn": "add_keyword_effects",
                "args": {},
                "required": True,
            },
            {
                "step": "composition_qa",
                "fn": "qa_gate",
                "args": {
                    "identity_coherent": True,
                    "mouth_sync": True,
                    "no_black_frames": True,
                    "no_overlay": True,
                    "captions_readable": True,
                    "safe_zones_ok": True,
                },
                "required": True,
            },
        ],
        "gate": {
            "type": "qa_gate",
            "checks": [
                "no_flash",
                "no_duplicate_presenter",
                "no_source_time_reset",
                "no_missing_overlay",
                "no_face_obstruction",
                "no_caption_collision",
                "ui_readable",
            ],
        },
    }

    return plan


def plan_delivery(job: PresenterJob, render_path: str, output_dir: str, stem: str = "presenter-video") -> dict[str, Any]:
    """构建交付阶段计划 (composition_checked → verified)。

    对应 lanshu finalize_delivery.sh
    """
    plan = {
        "phase": "delivery",
        "job_id": job.job_id,
        "current_status": job.status.value,
        "target_status": JobStatus.VERIFIED.value,
        "steps": [
            {
                "step": "render_master",
                "fn": "delivery",
                "args": {
                    "render_path": render_path,
                    "output_dir": output_dir,
                    "stem": stem,
                },
                "required": True,
            },
            {
                "step": "final_qa",
                "fn": "qa_gate",
                "args": {
                    "identity_coherent": True,
                    "mouth_sync": True,
                    "no_black_frames": True,
                    "captions_readable": True,
                    "safe_zones_ok": True,
                },
                "required": True,
            },
        ],
        "gate": {
            "type": "qa_gate",
            "checks": [
                "master_decode_ok",
                "share_decode_ok",
                "loudness_in_spec",
                "contact_sheet_complete",
                "visual_review_passed",
            ],
        },
    }

    return plan


# ─── 完整作业计划 ────────────────────────────────────


def build_full_job_plan(
    job: PresenterJob,
    narration_duration_s: float,
    render_path: str,
    output_dir: str,
    stem: str = "presenter-video",
) -> dict[str, Any]:
    """构建完整的端到端作业计划。

    供 production workflow 调用，一次性生成全阶段计划。
    """
    return {
        "job_id": job.job_id,
        "created_at": datetime.utcnow().isoformat(),
        "phases": [
            plan_generation(job),
            plan_visual(job, narration_duration_s),
            plan_presenter_generation(job),
            plan_composition(job),
            plan_delivery(job, render_path, output_dir, stem),
        ],
        "state_machine": [
            "intake",
            "content_locked",
            "audio_locked",
            "visual_plan_locked",
            "presenter_generated",
            "composition_checked",
            "rendered",
            "verified",
        ],
        "current_state": job.status.value,
    }


# ─── 执行器 ─────────────────────────────────────────


async def execute_plan(job: PresenterJob, plan: dict[str, Any]) -> dict[str, Any]:
    """执行计划的各个阶段（由 workflow 调用）。"""
    results: dict[str, Any] = {"job_id": job.job_id, "phases": []}

    for phase_plan in plan.get("phases", []):
        phase_result = await _execute_phase(job, phase_plan)
        results["phases"].append(phase_result)

        # 更新作业状态
        job.status = JobStatus(phase_plan["target_status"])

    return results


async def _execute_phase(job: PresenterJob, phase_plan: dict[str, Any]) -> dict[str, Any]:
    """Execute only registered stage adapters; never report fake success."""
    phase_name = phase_plan.get("phase", "unknown")
    results = {"phase": phase_name, "steps": []}

    adapters: dict[str, Any] = {
        "lock_content": _lock_content,
        "generate_narration": _generate_narration,
        "calibrate_loudness": _calibrate_loudness,
        "pilot_generation": generate_presenter,
        "visual_plan": visual_plan,
        "caption_plan": caption_plan,
        "compose_timeline": _compose_timeline,
        "burn_captions": _burn_captions,
        "add_keyword_effects": _add_keyword_effects,
        "pilot_qa": qa_gate,
        "composition_qa": qa_gate,
        "full_generation": generate_presenter,
        "render_master": delivery,
        "final_qa": qa_gate,
    }
    for step in phase_plan.get("steps", []):
        step_name = step["step"]
        adapter = adapters.get(step_name)
        if adapter is None:
            raise NotImplementedError(
                f"digital_human phase '{phase_name}' step '{step_name}' has no "
                "registered production adapter"
            )
        args = dict(step.get("args") or {})
        if step_name == "lock_content":
            value = adapter(job)
        elif step_name == "generate_narration":
            value = adapter(job, **{k: v for k, v in args.items() if k in {"voice_id", "rate"}})
        elif step_name in {
            "calibrate_loudness",
            "visual_plan",
            "caption_plan",
            "compose_timeline",
            "burn_captions",
            "add_keyword_effects",
            "pilot_qa",
            "composition_qa",
            "final_qa",
            "pilot_generation",
            "full_generation",
            "render_master",
        }:
            value = adapter(job, **args)
        else:  # pragma: no cover - guarded by adapter lookup above
            raise NotImplementedError(step_name)
        step_result = {"step": step_name, "ok": True, "result": _json_safe(value)}
        results["steps"].append(step_result)

    return results


def _composition_root(job: PresenterJob) -> Path:
    root = Path(os.getenv("HEVI_DIGITAL_HUMAN_OUTPUT_DIR", "data/digital_human")).expanduser()
    destination = root / job.job_id / "composition"
    destination.mkdir(parents=True, exist_ok=True)
    return destination


def _probe_composition_video(path: str | Path, label: str) -> dict[str, Any]:
    """Require a real decodable video with an audio clock for composition."""

    candidate = Path(path)
    if not candidate.is_file() or candidate.stat().st_size == 0:
        raise RuntimeError(f"{label} artifact is missing or empty: {candidate}")
    from hevi.digital_human.oprim.qa import _ffprobe

    probe = _ffprobe(candidate)
    streams = probe.get("streams", [])
    if not any(stream.get("codec_type") == "video" for stream in streams):
        raise RuntimeError(f"{label} has no decodable video stream: {candidate}")
    if not any(stream.get("codec_type") == "audio" for stream in streams):
        raise RuntimeError(f"{label} has no audio stream: {candidate}")
    return probe


def _run_composition_ffmpeg(
    source: Path,
    destination: Path,
    operation: str,
    video_filter: str | None = None,
    fps: int = 30,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.{operation}.mp4")
    temporary.unlink(missing_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
    ]
    filters = [
        "scale=trunc(iw/2)*2:trunc(ih/2)*2:flags=lanczos",
        "setsar=1",
        f"fps={max(1, fps)}",
    ]
    if video_filter:
        filters.append(video_filter)
    command.extend(
        [
            "-vf",
            ",".join(filters),
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-preset",
            "medium",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(temporary),
        ]
    )
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=900)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout)[-1800:]
        raise RuntimeError(f"{operation} ffmpeg failed: {detail}")
    if not temporary.is_file() or temporary.stat().st_size == 0:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"{operation} produced no video artifact")
    temporary.replace(destination)
    _probe_composition_video(destination, operation)


def _compose_timeline(job: PresenterJob) -> dict[str, Any]:
    """Materialize the presenter/timeline input into a deterministic base MP4."""

    source = Path(job.rendered)
    source_probe = _probe_composition_video(source, "presenter")
    if job.timeline:
        try:
            TimelinePlan.model_validate_json(job.timeline)
        except Exception as exc:
            raise RuntimeError(f"timeline plan is invalid: {exc}") from exc
    destination = _composition_root(job) / "timeline.mp4"
    _run_composition_ffmpeg(source, destination, "timeline", fps=job.fps)
    job.rendered = str(destination)
    job.updated_at = datetime.utcnow()
    return {"path": str(destination), "source": str(source), "probe": source_probe}


def _load_caption_plan(job: PresenterJob) -> CaptionPlan:
    if not job.caption_json:
        raise RuntimeError("caption plan is missing; run caption_plan before composition")
    candidate = Path(job.caption_json)
    payload = candidate.read_text(encoding="utf-8") if candidate.is_file() else job.caption_json
    try:
        plan = CaptionPlan.model_validate_json(payload)
    except Exception as exc:
        raise RuntimeError(f"caption plan is invalid: {exc}") from exc
    if not plan.is_available():
        raise RuntimeError("caption plan contains no readable phrases")
    return plan


def _ass_time(seconds: float) -> str:
    total_cs = max(0, round(float(seconds) * 100))
    hours, remainder = divmod(total_cs, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"


def _ass_text(text: str) -> str:
    return str(text).replace("{", "\\{" ).replace("}", "\\}").replace("\n", r"\N")


def _write_caption_ass(job: PresenterJob, plan: CaptionPlan) -> Path:
    path = _composition_root(job) / "captions.ass"
    width = max(320, int(job.width or 1080))
    height = max(320, int(job.height or 1920))
    font_size = max(34, round(min(width, height) * 0.055))
    margin_v = max(60, round(height * 0.075))
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,Arial,{font_size},&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,60,60,{margin_v},1",
        f"Style: radial_burst,Arial,{font_size},&H0000D7FF,&H0000D7FF,&H00101010,&H80000000,1,0,0,0,100,100,0,0,1,3,1,2,60,60,{margin_v},1",
        f"Style: tilted_ribbon,Arial,{font_size},&H0000A5FF,&H0000A5FF,&H00101010,&H80000000,1,0,0,0,100,100,0,0,1,3,1,2,60,60,{margin_v},1",
        f"Style: hand_drawn_circle,Arial,{font_size},&H0055FF55,&H0055FF55,&H00101010,&H80000000,1,0,0,0,100,100,0,0,1,3,1,2,60,60,{margin_v},1",
        f"Style: type_contrast,Arial,{font_size},&H00FFFF55,&H00FFFF55,&H00101010,&H80000000,1,0,0,0,100,100,0,0,1,3,1,2,60,60,{margin_v},1",
        f"Style: word_chip_cluster,Arial,{font_size},&H00FF55FF,&H00FF55FF,&H00101010,&H80000000,1,0,0,0,100,100,0,0,1,3,1,2,60,60,{margin_v},1",
        f"Style: outline_lockup,Arial,{font_size},&H0055AAFF,&H0055AAFF,&H00101010,&H80000000,1,0,0,0,100,100,0,0,1,3,1,2,60,60,{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for phrase in plan.phrases:
        start = max(0.0, phrase.start_s)
        end = max(start + 0.05, phrase.start_s + phrase.duration_s)
        style = phrase.style if phrase.style in set(plan.keyword_presets) else "Default"
        lines.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},{style},,0,0,0,,{_ass_text(phrase.text)}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _filter_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")


def _burn_captions(job: PresenterJob) -> dict[str, Any]:
    source = Path(job.rendered)
    _probe_composition_video(source, "timeline")
    plan = _load_caption_plan(job)
    ass_path = _write_caption_ass(job, plan)
    destination = _composition_root(job) / "captions.mp4"
    _run_composition_ffmpeg(
        source,
        destination,
        "captions",
        video_filter=f"subtitles={_filter_path(ass_path)}",
        fps=job.fps,
    )
    job.rendered = str(destination)
    job.updated_at = datetime.utcnow()
    return {"path": str(destination), "caption_file": str(ass_path), "phrase_count": len(plan.phrases)}


def _add_keyword_effects(job: PresenterJob) -> dict[str, Any]:
    """Add timed keyword accent bars after captions have been burned."""

    source = Path(job.rendered)
    _probe_composition_video(source, "captioned composition")
    plan = _load_caption_plan(job)
    accent_y = max(0, int((job.height or 1920) * 0.855))
    accent_w = max(160, int((job.width or 1080) * 0.72))
    accent_x = max(0, int(((job.width or 1080) - accent_w) / 2))
    colors = ("0x38BDF8", "0xF59E0B", "0xA78BFA", "0x34D399")
    filters: list[str] = []
    for index, phrase in enumerate(plan.phrases[:120]):
        if phrase.style == "default":
            continue
        start = max(0.0, phrase.start_s)
        end = max(start + 0.05, phrase.start_s + phrase.duration_s)
        color = colors[index % len(colors)]
        filters.append(
            f"drawbox=x={accent_x}:y={accent_y}:w={accent_w}:h=8:"
            f"color={color}@0.85:t=fill:enable='between(t,{start:.3f},{end:.3f})'"
        )
    if not filters:
        raise RuntimeError("caption plan contains no keyword effect phrases")
    destination = _composition_root(job) / "final-composition.mp4"
    _run_composition_ffmpeg(source, destination, "keyword_effects", ",".join(filters), job.fps)
    job.rendered = str(destination)
    report_path = _composition_root(job) / "composition-report.json"
    report_path.write_text(
        json.dumps(
            {
                "status": "verified",
                "rendered": str(destination),
                "caption_file": str(_composition_root(job) / "captions.ass"),
                "keyword_effect_count": len(filters),
                "probe": _probe_composition_video(destination, "final composition"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    job.qa_composition = str(report_path)
    job.updated_at = datetime.utcnow()
    return {"path": str(destination), "report": str(report_path), "keyword_effect_count": len(filters)}


def _calibrate_loudness(job: PresenterJob, target_lufs: float = -16) -> AudioMeasurement:
    if not job.final_audio:
        raise RuntimeError("cannot calibrate loudness before narration is generated")
    return _calibrate_audio_loudness(job.final_audio, target_lufs=target_lufs)


def _json_safe(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


# ─── 导出 ───────────────────────────────────────────

__all__ = [
    "build_full_job_plan",
    "execute_plan",
    "init_job",
    "plan_composition",
    "plan_delivery",
    "plan_generation",
    "plan_presenter_generation",
    "plan_visual",
]
