"""Huobao short-drama capabilities registered into the unified capability registry.

Per CAPABILITY_CONTRACT.md, every product line (ShotSpec, zero, talkcraft,
shortdrama ...) calls these by name.  All capabilities are CPU-only, use the
local SD-Turbo keyframe engine + Piper TTS, and are deterministic per seed —
no cloud video/image or paid APIs, no mock success.
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

from hevi.capabilities.registry import Capability, CapabilityError, CapabilityResult, register
from hevi.huobao.assets import AssetRegistry
from hevi.huobao.keyframes import generate_asset_keyframes
from hevi.huobao.refs import UnknownAssetReferenceError, resolve_references
from hevi.layer4_legacy.keyframe.oprim_impl.registry import resolve_keyframe_engine
from hevi.layer4_legacy.keyframe.oprim_impl.style_presets import get_style_preset

logger = logging.getLogger(__name__)

# Same guofeng_anime CPU preset as the rest of the huobao pipeline.
STYLE_NAME = "guofeng_anime"


# ──────────────────────────────────────────────────────────────────────────
# Capability renderers (each returns a CapabilityResult; never a fake success)
# ──────────────────────────────────────────────────────────────────────────

def _render_character_ref(params: dict, out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    name = params["name"]
    appearance = params.get("appearance", "")
    styling = params.get("styling", "")
    role = params.get("role", "supporting")
    reg = AssetRegistry(base_seed=seed)
    char = reg.register_character(name, appearance=appearance, styling=styling, role=role, episode=1)
    char.seed = seed  # pin fixed seed for reproducibility
    generated = generate_asset_keyframes(reg, out_dir, engine_name="sdturbo_cpu_fp16", steps=2, width=512, height=512)
    img = str(generated[char.id])
    return CapabilityResult(
        png=img,
        sha256=_sha256_file(img),
        qa={"asset_id": char.id, "normalized_name": char.normalized_name, "seed": seed},
    )


def _render_scene_ref(params: dict, out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    location = params["location"]
    time_of_day = params.get("time", "白天")
    prompt = params.get("prompt", "")
    lighting = params.get("lighting", "")
    reg = AssetRegistry(base_seed=seed)
    scene = reg.register_scene(location, time_of_day, prompt=prompt, lighting=lighting, episode=1)
    scene.seed = seed
    generated = generate_asset_keyframes(reg, out_dir, engine_name="sdturbo_cpu_fp16", steps=2, width=512, height=512)
    img = str(generated[scene.id])
    return CapabilityResult(
        png=img,
        sha256=_sha256_file(img),
        qa={"asset_id": scene.id, "normalized_location": scene.normalized_location, "seed": seed},
    )


def _render_shot(params: dict, out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    prompt = params["prompt"]
    registry_payload = params.get("registry", {})
    reg = _registry_from_payload(registry_payload, seed)
    try:
        resolved = resolve_references(prompt, reg, base_seed=seed, shot_index=0, style_name=STYLE_NAME)
    except UnknownAssetReferenceError as e:
        raise CapabilityError(str(e)) from e

    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    img_path = frames_dir / f"shot_{seed}.png"
    width, height = (1920, 1080) if aspect == "16:9" else (1080, 1920)

    engine = resolve_keyframe_engine("sdturbo_cpu_fp16")
    preset = get_style_preset(STYLE_NAME)
    if not img_path.is_file() or img_path.stat().st_size == 0:
        engine.generate(
            prompt_en=resolved.expanded_prompt_en,
            negative=preset.negative_prompt,
            width=512,
            height=512,
            steps=2,
            seed=resolved.effective_seed,
            output_path=img_path,
        )
    # Compose still frame into a duration-length 9:16/16:9 video (Ken Burns) with Piper VO.
    from hevi.layer4_legacy.talkcraft.omodul_impl._media import (
        FFMPEG,
        VOICE_DIR,
        VOICES,
        PIPER,
        piper_tts,
    )

    tts_text = params.get("tts_text", "")
    audio_path = frames_dir / f"shot_{seed}.wav"
    if tts_text.strip():
        if not Path(PIPER).is_file():
            raise CapabilityError(f"piper binary 缺失: {PIPER}")
        piper_tts(text=tts_text, out_wav=audio_path, lang="zh", length_scale=1.0)
    else:
        subprocess.run(
            [FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i",
             f"anullsrc=r=44100:cl=stereo:d={duration:.3f}", "-ar", "44100", str(audio_path)],
            check=True,
        )

    clip_path = frames_dir / f"shot_{seed}.mp4"
    fps = 25
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"zoompan=z='min(zoom+0.0008,1.06)':d={int(duration*fps)}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
    )
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-loop", "1", "-i", str(img_path),
         "-i", str(audio_path), "-t", f"{duration:.3f}", "-vf", vf,
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
         "-c:a", "aac", "-b:a", "160k", "-shortest", str(clip_path)],
        check=True,
    )
    dur = _probe_duration(clip_path)
    return CapabilityResult(
        mp4=str(clip_path),
        png=str(img_path),
        wav=str(audio_path),
        duration_s=dur,
        sha256=_sha256_file(clip_path),
        qa={
            "prompt_en": resolved.expanded_prompt_en,
            "effective_seed": resolved.effective_seed,
            "bound_characters": [c.name for c in resolved.bound_characters],
        },
    )


def _registry_from_payload(payload: dict, seed: int) -> AssetRegistry:
    reg = AssetRegistry(base_seed=seed)
    for c in payload.get("characters", []):
        reg.register_character(
            name=c.get("name", ""),
            aliases=c.get("aliases", []),
            role=c.get("role", "supporting"),
            appearance=c.get("appearance", ""),
            styling=c.get("styling", ""),
            episode=int(c.get("episode", 1)),
        )
    for s in payload.get("scenes", []):
        reg.register_scene(
            location=s.get("location", ""),
            time=s.get("time", "白天"),
            prompt=s.get("prompt", ""),
            lighting=s.get("lighting", ""),
            episode=int(s.get("episode", 1)),
        )
    for p in payload.get("props", []):
        reg.register_prop(
            name=p.get("name", ""),
            prop_type=p.get("type", "信物"),
            description=p.get("description", ""),
            episode=int(p.get("episode", 1)),
        )
    return reg


def _sha256_file(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _probe_duration(path: Path) -> float:
    from hevi.layer4_legacy.talkcraft.omodul_impl._media import FFPROBE

    out = subprocess.check_output(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        text=True,
    )
    return float(out.strip())


# ──────────────────────────────────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────────────────────────────────

_CHAR_SCHEMA = {
    "type": "object",
    "required": ["name"],
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "appearance": {"type": "string"},
        "styling": {"type": "string"},
        "role": {"type": "string", "enum": ["protagonist", "antagonist", "supporting"]},
    },
    "additionalProperties": False,
}

_SCENE_SCHEMA = {
    "type": "object",
    "required": ["location"],
    "properties": {
        "location": {"type": "string", "minLength": 1},
        "time": {"type": "string"},
        "prompt": {"type": "string"},
        "lighting": {"type": "string"},
    },
    "additionalProperties": False,
}

_SHOT_SCHEMA = {
    "type": "object",
    "required": ["prompt"],
    "properties": {
        "prompt": {"type": "string", "minLength": 1},
        "tts_text": {"type": "string"},
        "registry": {"type": "object"},
    },
    "additionalProperties": False,
}

_CAPABILITY_DEFS = [
    Capability(
        name="huobao.character_ref",
        kind="shot",
        aspects=["16:9", "9:16"],
        params_schema=_CHAR_SCHEMA,
        cpu_cost_hint=190.0,
        render=_render_character_ref,
        description="生成国风动漫风格的角色参考关键帧（CPU SD-Turbo，固定 seed 保证跨镜一致）。",
    ),
    Capability(
        name="huobao.scene_ref",
        kind="shot",
        aspects=["16:9", "9:16"],
        params_schema=_SCENE_SCHEMA,
        cpu_cost_hint=190.0,
        render=_render_scene_ref,
        description="生成纯背景无人物场景参考关键帧（CPU SD-Turbo，固定 seed）。",
    ),
    Capability(
        name="huobao.shot",
        kind="shot",
        aspects=["16:9", "9:16"],
        params_schema=_SHOT_SCHEMA,
        cpu_cost_hint=200.0,
        render=_render_shot,
        description="渲染单镜头：解析 @角色/@场景/@道具 引用，生成关键帧并用 Piper 配音合成短视频段（CPU）。",
    ),
]


def register_huobao_capabilities() -> None:
    """Idempotently register all huobao capabilities into the shared registry."""
    from hevi.capabilities.registry import _REGISTRY

    for cap in _CAPABILITY_DEFS:
        if cap.name not in _REGISTRY:
            register(cap)
