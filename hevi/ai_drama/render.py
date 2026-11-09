"""Render storyboard shots to video segments through the provider abstraction."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .assets import shot_prompt
from .compliance import assert_generated_assets
from .credits import CreditLedger
from .providers import VideoRequest, select_provider
from .providers.offline import _silence
from .schema import iter_shots
from .voice import concat_audio, pad_to
from .voice import duration as audio_duration


def _lookup(voice_plan: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
    out = {}
    for line in (voice_plan.get("lines") or {}).values():
        out[(str(line.get("speaker")), str(line.get("text")), str(line.get("kind") or "said"))] = line
    return out


def shot_audio(shot: dict[str, Any], voice_plan: dict[str, Any], out_dir: Path) -> Path | None:
    lookup = _lookup(voice_plan)
    parts = []
    for line in shot.get("dialogue") or []:
        key = (str(line.get("speaker")), str(line.get("text")), str(line.get("kind") or "said"))
        info = lookup.get(key)
        if info and Path(str(info.get("path"))).is_file():
            parts.append(Path(str(info["path"])))
    if not parts:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    merged = out_dir / f"{shot.get('shot_id')}_dialogue.wav"
    concat_audio(parts, merged)
    return merged


def _pick_image(shot: dict[str, Any], asset_paths: dict[str, str], assets: dict[str, Any]) -> str:
    if shot.get("image"):
        return str(shot["image"])
    kinds = {str(img.get("ref")): str(img.get("kind")) for img in assets.get("images") or []}
    refs = [str(r) for r in shot.get("refs") or [] if str(r) in asset_paths]
    if not refs:
        raise RuntimeError(f"镜头 {shot.get('shot_id')} 没有可用图片")
    if str(shot.get("mode")) in ("talking", "reaction") or shot.get("dialogue"):
        for ref in refs:
            if kinds.get(ref) == "character_portrait":
                return asset_paths[ref]
    for ref in refs:
        if kinds.get(ref) == "scene":
            return asset_paths[ref]
    return asset_paths[refs[0]]


def render_shots(
    storyboard: dict[str, Any],
    script: dict[str, Any],
    assets: dict[str, Any],
    asset_paths: dict[str, str],
    voice_plan: dict[str, Any],
    out_dir: Path,
    *,
    ledger: CreditLedger | None = None,
    prefer_provider: str | None = None,
    lipsync: bool | None = None,
    seed: int = 42,
    episode_id: str = "",
) -> dict[str, Any]:
    assert_generated_assets(assets)
    provider, status = select_provider(ledger, prefer=prefer_provider)
    clips_dir = out_dir / "clips"
    audio_dir = out_dir / "shot_audio"
    clips_dir.mkdir(parents=True, exist_ok=True)
    if lipsync is None:
        lipsync = os.environ.get("AI_DRAMA_LIPSYNC", "1").strip() not in ("0", "false", "off")
    profiles = {str(c.get("id")): c.get("voice") or {} for c in script.get("characters") or []}
    results: dict[str, Any] = {"provider": provider.name, "providers": status, "clips": {}, "meta": {}}
    for shot in iter_shots(storyboard):
        sid = str(shot.get("shot_id"))
        image = _pick_image(shot, asset_paths, assets)
        audio = shot_audio(shot, voice_plan, audio_dir)
        if audio is None:
            audio = _silence(float(shot.get("duration_s") or 2.0), audio_dir / f"{sid}_silence.wav")
        elif audio_duration(audio) < float(shot.get("duration_s") or 0) - 0.05:
            audio = pad_to(audio, float(shot.get("duration_s") or 0), audio_dir / f"{sid}_padded.wav")
        out = clips_dir / f"{sid}.mp4"
        character_id = str(shot.get("character_id") or (shot.get("characters") or [None])[0] or "")
        profile = profiles.get(character_id, {})
        ref_audio = (profile.get("reference") or {}).get("path") if isinstance(profile.get("reference"), dict) else None
        ref_images = [asset_paths[r] for r in shot.get("refs") or [] if r in asset_paths]
        mode = str(shot.get("mode") or "talking")
        req = VideoRequest(
            prompt=shot_prompt(shot, str(storyboard.get("style") or "live_action"),
                               game_pov=str(storyboard.get("style")) == "game_pov"),
            output_path=out,
            duration_s=float(shot.get("duration_s") or 2.0),
            aspect="9:16",
            mode="reference" if mode != "digital_human" else "digital_human",
            seed=seed + len(results["clips"]) * 13,
            reference_images=ref_images,
            reference_audio=[ref_audio] if ref_audio else [],
            first_frame=shot.get("first_frame"),
            last_frame=shot.get("last_frame"),
            image=image,
            audio=str(audio),
            lipsync_portrait=image if mode in ("talking", "reaction") else None,
            lipsync=bool(lipsync and mode in ("talking", "reaction")),
            sound_description=str(shot.get("sound") or ""),
            shot_id=sid,
            episode_id=episode_id,
        )
        offline_charge = None
        if ledger is not None and provider.name == "offline":
            offline_charge = ledger.reserve("offline", float(shot.get("duration_s") or 0), ref=sid)
        try:
            result = provider.render(req)
            if ledger is not None and offline_charge is not None:
                ledger.settle("offline", float(shot.get("duration_s") or 0), ref=sid, success=True)
            results["clips"][sid] = str(result.path)
            results["meta"][sid] = {"provider": result.provider, **result.meta}
        except Exception as exc:
            if provider.name != "offline":
                # Paid path failed; retry this shot offline rather than re-buy it.
                from .providers.offline import OfflineProvider
                req.lipsync = False
                result = OfflineProvider().render(req)
                results["clips"][sid] = str(result.path)
                results["meta"][sid] = {"provider": "offline_fallback", "error": str(exc)[:400], **result.meta}
            else:
                if ledger is not None and offline_charge is not None:
                    ledger.settle("offline", float(shot.get("duration_s") or 0), ref=sid, success=False)
                results["meta"][sid] = {"provider": provider.name, "error": str(exc)[:400]}
                raise
    (out_dir / "segments_manifest.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return results


def render_segments(
    storyboard: dict[str, Any], clips: dict[str, str], out_dir: Path
) -> dict[str, Any]:
    """Concatenate shot clips into segment clips (2-4 shots each)."""
    from .edit import FFMPEG

    seg_dir = out_dir / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, str] = {}
    for seg in storyboard.get("segments") or []:
        sid = str(seg.get("segment_id"))
        paths = [Path(clips[str(s.get("shot_id"))]) for s in seg.get("shots") or []]
        if any(not p.is_file() for p in paths):
            raise RuntimeError(f"段 {sid} 缺镜头片段")
        lst = seg_dir / f"{sid}.txt"
        lst.write_text("".join(f"file '{p.resolve()}'\n" for p in paths), encoding="utf-8")
        target = seg_dir / f"{sid}.mp4"
        import subprocess
        subprocess.run(
            [FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "160k", str(target)],
            check=True,
        )
        out[sid] = str(target)
    return out
