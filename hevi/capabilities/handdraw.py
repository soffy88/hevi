"""Handdraw line capabilities registered into the unified Hevi registry.

Four render capabilities expose the CPU hand-drawn "口播" line so that any
product line (ShotSpec, zero, talkcraft, artmotion, explainer, …) can invoke them
by name, e.g. ``hevi.capabilities.get("handdraw.narration").render(...)``.

The render functions wrap the vendored HANDDRAW pipeline.  They fail closed: any
missing input, failed render, or unreadable output raises ``CapabilityError``
rather than returning a fabricated success.  Outputs are deterministic for a
given ``seed`` because the pipeline takes no external randomness (CPU-only,
no paid APIs, fixed scene/style/hand presets).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from hevi.capabilities.registry import (
    Capability,
    CapabilityError,
    CapabilityResult,
    register,
)

logger = logging.getLogger(__name__)

SUPPORTED_STYLES = ("1", "8", "10", "17")
SUPPORTED_HANDS = ("navy", "pen-only")
ASPECTS = ("16:9", "9:16")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _render_handdraw(
    *,
    topic: str,
    style_id: str,
    hand_preset: str,
    canvas_size: tuple[int, int],
    output_dir: Path,
    seed: int,
    prefer_cosy: bool,
    duration: float = 0.0,
    stroke_style: str = "legacy",
    rough_roughness: float = 2.0,
    rough_bowing: float = 2.0,
) -> CapabilityResult:
    """Render a topic-grounded preschool video or an exact-duration preview."""
    from hevi.layer4_legacy.handdraw.kids_storyboards import select_kids_storyboard
    from hevi.layer4_legacy.handdraw.pipeline import render_handdraw_pipeline

    # ``seed`` is accepted for interface parity (deterministic CPU render) but the
    # pipeline is already seed-deterministic; we surface it in the QA report.
    if style_id not in SUPPORTED_STYLES:
        raise CapabilityError(f"unsupported style_id: {style_id}")
    if hand_preset not in SUPPORTED_HANDS:
        raise CapabilityError(f"unsupported hand_preset: {hand_preset}")
    if stroke_style not in ("legacy", "rough"):
        raise CapabilityError(f"unsupported stroke_style: {stroke_style}")

    spec = select_kids_storyboard(topic)
    if not 0 <= float(duration) <= 3:
        raise CapabilityError("duration must be 0 for a full delivery or between 0 and 3 seconds for preview")
    # The unified capability contract interprets a positive duration as a partial
    # video render of exactly that many seconds; zero requests a full deliverable.
    result = render_handdraw_pipeline(
        job_id=f"cap_handdraw_{seed}",
        title=spec["title"],
        pages_spec=spec["pages"][:1] if duration > 0 else spec["pages"],
        output_dir=output_dir,
        canvas_size=canvas_size,
        style_id=style_id,
        hand_preset=hand_preset,
        prefer_cosy=prefer_cosy,
        seed=seed,
        preview_duration=float(duration) if duration > 0 else None,
        stroke_style=stroke_style,
        rough_roughness=rough_roughness,
        rough_bowing=rough_bowing,
    )

    mp4 = Path(result["video_path"])
    png = Path(result["cover_path"])
    srt = Path(result["srt_path"])
    if not mp4.is_file() or not png.is_file() or not srt.is_file():
        raise CapabilityError(f"handdraw render incomplete: {result}")
    return CapabilityResult(
        mp4=mp4,
        png=png,
        wav=Path(output_dir / "inputs" / "narration" / "master.wav"),
        duration_s=float(result["duration"]),
        sha256=result["sha256"],
        qa={
            "lufs": result["lufs"],
            "canvas": result["canvas"],
            "style_id": result["style_id"],
            "hand_preset": result["hand_preset"],
            "seed": seed,
            "stroke_style": stroke_style,
            "srt": str(srt),
            "verification": result["verification_path"],
            "kids_safety_report": result.get("kids_safety_path"),
            "preview": bool(duration > 0),
        },
    )


def _render_canvas(
    topic: str,
    style_id: str,
    hand_preset: str,
    canvas_size: tuple[int, int],
    out_dir: Path,
    *,
    seed: int,
    prefer_cosy: bool = True,
    duration: float = 0.0,
    stroke_style: str = "legacy",
    rough_roughness: float = 2.0,
    rough_bowing: float = 2.0,
) -> CapabilityResult:
    if not topic or not str(topic).strip():
        raise CapabilityError("handdraw capability requires a non-empty 'topic'")
    from hevi.layer4_legacy.handdraw.kids_storyboards import UnsupportedKidsTopicError
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        return _render_handdraw(
            topic=topic,
            style_id=style_id,
            hand_preset=hand_preset,
            canvas_size=canvas_size,
            output_dir=out_dir,
            seed=seed,
            prefer_cosy=prefer_cosy,
            duration=duration,
            stroke_style=stroke_style,
            rough_roughness=rough_roughness,
            rough_bowing=rough_bowing,
        )
    except UnsupportedKidsTopicError as exc:
        raise CapabilityError(str(exc)) from exc
    except Exception as exc:
        if isinstance(exc, CapabilityError):
            raise
        raise CapabilityError(f"handdraw render failed: {type(exc).__name__}: {exc}") from exc


_PARAMS = {
    "type": "object",
    "additionalProperties": False,
    "required": ["topic", "aspect"],
    "properties": {
        "topic": {"type": "string", "minLength": 2},
        "aspect": {"type": "string", "enum": list(ASPECTS)},
        "style_id": {"type": "string", "enum": list(SUPPORTED_STYLES)},
        "hand_preset": {"type": "string", "enum": list(SUPPORTED_HANDS)},
        "stroke_style": {"type": "string", "enum": ["legacy", "rough"]},
        "rough_roughness": {"type": "number", "minimum": 0, "maximum": 25},
        "rough_bowing": {"type": "number", "minimum": 0, "maximum": 25},
    },
}


def _register() -> None:
    register(
        Capability(
            name="handdraw.full",
            kind="line",
            aspects=ASPECTS,
            params_schema=dict(_PARAMS, required=["topic", "aspect"]),
            cpu_cost_hint=120.0,
            render=lambda params, out_dir, *, duration=0.0, aspect="16:9", seed=0: _render_canvas(
                topic=str((params or {}).get("topic") or ""),
                style_id=str((params or {}).get("style_id") or "8"),
                hand_preset=str((params or {}).get("hand_preset") or "navy"),
                canvas_size=(1920, 1080) if aspect == "16:9" else (1080, 1920),
                out_dir=out_dir,
                seed=int(seed),
                duration=float(duration),
                stroke_style=str((params or {}).get("stroke_style") or "legacy"),
                rough_roughness=float((params or {}).get("rough_roughness") if (params or {}).get("rough_roughness") is not None else 2.0),
                rough_bowing=float((params or {}).get("rough_bowing") if (params or {}).get("rough_bowing") is not None else 2.0),
            ),
            description="幼儿向手绘动画；正 duration 为精确时长预览，0 为完整交付。可选 stroke_style='rough' 启用 rough 式手绘描边（双描+抖动，默认 legacy 不变）。",
        )
    )
    register(
        Capability(
            name="handdraw.storyboard",
            kind="line",
            aspects=ASPECTS,
            params_schema=dict(_PARAMS, required=["topic"]),
            cpu_cost_hint=4.0,
            render=lambda params, out_dir, *, duration=0.0, aspect="16:9", seed=0: _render_storyboard(
                topic=str(params["topic"]),
                style_id=str(params.get("style_id") or "8"),
                out_dir=out_dir,
                seed=int(seed),
                stroke_style=str(params.get("stroke_style") or "legacy"),
                rough_roughness=float(params.get("rough_roughness") if params.get("rough_roughness") is not None else 2.0),
                rough_bowing=float(params.get("rough_bowing") if params.get("rough_bowing") is not None else 2.0),
            ),
            description="仅生成分镜插画+口播稿（CPU 矢量插画），不渲染视频。可选 stroke_style='rough' 启用 rough 式手绘描边（默认 legacy 不变）。",
        )
    )
    register(
        Capability(
            name="handdraw.narration",
            kind="audio",
            aspects=ASPECTS,
            params_schema=dict(_PARAMS, required=["topic"]),
            cpu_cost_hint=30.0,
            render=lambda params, out_dir, *, duration=0.0, aspect="16:9", seed=0: _render_narration(
                topic=str(params["topic"]),
                out_dir=out_dir,
                seed=int(seed),
            ),
            description="整篇 CosyVoice/piper 旁白母带 + 时间戳对齐 JSON，不渲染画面。",
        )
    )
    register(
        Capability(
            name="handdraw.illustration",
            kind="shot",
            aspects=ASPECTS,
            params_schema=dict(_PARAMS, required=["topic", "style_id"]),
            cpu_cost_hint=2.0,
            render=lambda params, out_dir, *, duration=0.0, aspect="16:9", seed=0: _render_illustration(
                topic=str(params["topic"]),
                style_id=str(params.get("style_id") or "8"),
                out_dir=out_dir,
                seed=int(seed),
                stroke_style=str(params.get("stroke_style") or "legacy"),
                rough_roughness=float(params.get("rough_roughness") if params.get("rough_roughness") is not None else 2.0),
                rough_bowing=float(params.get("rough_bowing") if params.get("rough_bowing") is not None else 2.0),
            ),
            description="单张 CPU 矢量风格插画 PNG（指定手绘风格）。可选 stroke_style='rough' 启用 rough 式手绘描边（双描+抖动，默认 legacy 不变）。",
        )
    )
    logger.info("registered 4 handdraw capabilities")


def _render_storyboard(
    topic: str, style_id: str, out_dir: Path, *, seed: int,
    stroke_style: str = "legacy", rough_roughness: float = 2.0, rough_bowing: float = 2.0,
) -> CapabilityResult:
    from hevi.layer4_legacy.handdraw.illustrator import build_scene_illustration
    from hevi.layer4_legacy.handdraw.kids_storyboards import select_kids_storyboard

    if style_id not in SUPPORTED_STYLES:
        raise CapabilityError(f"unsupported style_id: {style_id}")
    if stroke_style not in ("legacy", "rough"):
        raise CapabilityError(f"unsupported stroke_style: {stroke_style}")
    spec = select_kids_storyboard(topic)

    out_dir = Path(out_dir).resolve()
    illu_dir = out_dir / "illustrations"
    illu_dir.mkdir(parents=True, exist_ok=True)
    pngs = []
    for p_idx, page in enumerate(spec["pages"]):
        scene_key = page["scene_key"]
        path = illu_dir / f"scene_{p_idx + 1}_{scene_key}.png"
        build_scene_illustration(
            scene_key=scene_key, output_path=path, style_id=style_id, size=(800, 800), seed=seed,
            stroke_style=stroke_style, rough_roughness=rough_roughness, rough_bowing=rough_bowing,
        )
        if not path.is_file():
            raise CapabilityError(f"illustration not produced: {path}")
        pngs.append(path)
    script_path = out_dir / "script.txt"
    script_path.write_text(
        "\n".join(beat["text"] for page in spec["pages"] for beat in page["beats"]),
        encoding="utf-8",
    )
    return CapabilityResult(
        png=pngs[0],
        duration_s=0.0,
        sha256=_sha256_file(pngs[0]),
        qa={
            "scenes": [str(p) for p in pngs],
            "script": str(script_path),
            "style_id": style_id,
            "seed": seed,
            "stroke_style": stroke_style,
            "pages": len(spec["pages"]),
        },
    )


def _render_narration(topic: str, out_dir: Path, *, seed: int) -> CapabilityResult:
    from hevi.layer4_legacy.handdraw.kids_storyboards import select_kids_storyboard
    from hevi.layer4_legacy.handdraw.tts import build_narration_master

    spec = select_kids_storyboard(topic)

    out_dir = Path(out_dir).resolve()
    audio_dir = out_dir / "narration"
    audio_dir.mkdir(parents=True, exist_ok=True)
    beats = []
    for p_idx, page in enumerate(spec["pages"]):
        for b_idx, beat in enumerate(page["beats"]):
            beats.append({"id": f"p{p_idx:02d}_b{b_idx:02d}", "text": beat["text"]})
    master, alignment, dur = build_narration_master(beats, audio_dir, prefer_cosy=True)
    if not master.is_file():
        raise CapabilityError("narration master not produced")
    return CapabilityResult(
        wav=master,
        duration_s=float(dur),
        sha256=_sha256_file(master),
        qa={
            "alignment": str(alignment),
            "beats": len(beats),
            "seed": seed,
        },
    )


def _render_illustration(
    topic: str, style_id: str, out_dir: Path, *, seed: int,
    stroke_style: str = "legacy", rough_roughness: float = 2.0, rough_bowing: float = 2.0,
) -> CapabilityResult:
    from hevi.layer4_legacy.handdraw.illustrator import build_scene_illustration
    from hevi.layer4_legacy.handdraw.kids_storyboards import select_kids_storyboard

    if style_id not in SUPPORTED_STYLES:
        raise CapabilityError(f"unsupported style_id: {style_id}")
    if stroke_style not in ("legacy", "rough"):
        raise CapabilityError(f"unsupported stroke_style: {stroke_style}")
    spec = select_kids_storyboard(topic)

    out_dir = Path(out_dir).resolve()
    illu_dir = out_dir / "illustrations"
    illu_dir.mkdir(parents=True, exist_ok=True)
    # Use the first scene of the matched storyboard.
    page = spec["pages"][0]
    scene_key = page["scene_key"]
    path = illu_dir / f"scene_1_{scene_key}.png"
    meta = build_scene_illustration(
        scene_key=scene_key, output_path=path, style_id=style_id, size=(800, 800), seed=seed,
        stroke_style=stroke_style, rough_roughness=rough_roughness, rough_bowing=rough_bowing,
    )
    if not path.is_file():
        raise CapabilityError(f"illustration not produced: {path}")
    return CapabilityResult(
        png=path,
        duration_s=0.0,
        sha256=_sha256_file(path),
        qa={
            "scene_key": scene_key,
            "style_id": style_id,
            "seed": seed,
            "stroke_style": stroke_style,
            "parts": [p["id"] for p in meta["parts"]],
        },
    )


# Auto-register on import.
_register()
