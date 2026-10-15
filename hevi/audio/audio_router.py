"""🚨 v9.0: 多模型音频路由中枢 —— 双音色情绪播报 + TTS 无缝拼接。

遍历 cues，根据 `audio_style`（formal / conversational）分别调用：
- formal  → CosyVoice（权威播音风格）
- conversational → ChatTTS 或 Voicebox（松弛口语化，支持 [laugh]、[uv_break] 等控制符）

生成的多个音频片段通过 pydub / FFmpeg 顺序拼接为唯一的 Master Audio。

使用方式：
    from hevi.audio.audio_router import route_and_stitch_master_audio

        master_path = await route_and_stitch_master_audio(
            cues=[...],       # list of ExplainerCue with text/audio_style fields
            output_dir=Path("output/audio"),
            voice="cosyvoice_default",
        )

    Provider identity (P1-D): route_single_cue returns explicit
    requested/actual/substituted provenance — no silent provider substitution.
    """

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Literal

from oprim import probe_duration

logger = logging.getLogger(__name__)

AudioStyle = Literal["formal", "conversational"]


class AudioRoutingError(RuntimeError):
    """音频路由/拼接失败。"""


def _identity_envelope(
    path: Path,
    *,
    requested_provider: str,
    actual_provider: str,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "path": path,
        "requested_provider": requested_provider,
        "actual_provider": actual_provider,
        "substituted": requested_provider != actual_provider,
    }
    if fallback_reason is not None:
        envelope["fallback_reason"] = fallback_reason
    return envelope


def _formal_requested_provider() -> str:
    return os.getenv("HEVI_TTS_FORMAL_PROVIDER", "lux_tts").strip().lower()


def _conversational_requested_provider() -> str:
    return os.getenv("HEVI_TTS_CONVERSATIONAL_PROVIDER", "lux_tts").strip().lower()


def _infer_audio_style(text: str) -> AudioStyle:
    """Heuristic to infer audio_style from text content.

    Used as a fallback when the cue does not explicitly set audio_style.
    - Text containing colloquial markers like 「啦」「呢」「嘛」「哈哈」「好吧」
      → conversational
    - Otherwise → formal (default).
    """
    conversational_markers = [
        "啦",
        "呢",
        "嘛",
        "哈",
        "嘿",
        "哇",
        "哦",
        "嗯",
        "好吧",
        "嘿嘿",
        "哈哈哈",
        "哎呀",
        "其实",
        "说白了",
        "要知道",
    ]
    for marker in conversational_markers:
        if marker in text:
            return "conversational"
    return "formal"


async def route_single_cue(
    *,
    cue_text: str,
    cue_style: AudioStyle | None,
    output_path: Path,
    voice: str,
    instruct: str | None = None,
    **tts_kwargs: Any,
) -> dict[str, Any]:
    """Route one cue to the correct TTS backend based on audio_style.

    Returns an envelope with the audio path and explicit provider identity:
    requested/actual provider + style, substituted flag, optional fallback_reason.
    """
    style = cue_style or _infer_audio_style(cue_text)
    requested_style = style
    if style == "conversational":
        requested_provider = _conversational_requested_provider()
    else:
        requested_provider = _formal_requested_provider()

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if style == "conversational":
            synth = await _synthesize_conversational(
                text=cue_text,
                output_path=output_path,
                instruct=instruct,
                **tts_kwargs,
            )
        else:
            synth = await _synthesize_formal(
                text=cue_text,
                output_path=output_path,
                voice=voice,
                instruct=instruct,
                **tts_kwargs,
            )

        result_path = Path(synth["path"])
        if not result_path.exists() or result_path.stat().st_size < 100:
            raise AudioRoutingError(f"Synthesis produced empty file: {result_path}")

        actual_provider = str(synth["actual_provider"])
        identity = dict(synth)
        identity.update(
            {
                "path": result_path,
                "requested_provider": str(synth.get("requested_provider", requested_provider)),
                "actual_provider": actual_provider,
                "requested_style": requested_style,
                "actual_style": style,
                "substituted": bool(synth.get("substituted"))
                or requested_provider != actual_provider
                or requested_style != style,
            }
        )
        return identity

    except Exception as exc:
        logger.warning("TTS routing failed for cue style=%s: %s", style, exc)
        fallback = await _synthesize_formal(
            text=cue_text,
            output_path=output_path,
            voice=voice,
            instruct=instruct,
            **tts_kwargs,
        )
        fallback_path = Path(fallback["path"])
        if fallback_path.exists():
            return {
                **fallback,
                "path": fallback_path,
                "requested_provider": requested_provider,
                "actual_provider": str(fallback["actual_provider"]),
                "requested_style": requested_style,
                "actual_style": "formal",
                "substituted": True,
                "fallback_reason": f"style_fallback:{exc}",
            }
        raise AudioRoutingError(f"All TTS backends failed: {exc}") from exc


async def _synthesize_conversational(
    *, text: str, output_path: Path, instruct: str | None, **_kw: Any
) -> dict[str, Any]:
    """Conversational synthesis — supports ChatTTS-style control tokens.

    Voicebox handles emotion tags like [laugh], [uv_break], [breath] natively.
    For raw ChatTTS, this delegates to the oprim.chattts_call entry point.
    """
    requested = _conversational_requested_provider()

    if requested in {"lux", "lux_tts", "luxtts"}:
        return await _synthesize_luxtts_with_fallback(
            text=text,
            output_path=output_path,
            voice="auto",
            instruct=instruct,
            requested_provider=requested,
            **_kw,
        )

    if requested == "chattts":
        try:
            from oprim import chattts_call as _chattts_api

            result = _chattts_api(text=text, output_path=str(output_path))
            path = Path(result) if isinstance(result, str) else output_path
            return _identity_envelope(
                path, requested_provider="chattts", actual_provider="chattts"
            )
        except ImportError:
            logger.debug("ChatTTS oprim not installed; falling back to voicebox")
            from hevi.explainer.voicebox_client import synthesize as vb_synthesize

            await vb_synthesize(text, output_path, instruct=instruct or "casual, conversational")
            return _identity_envelope(
                output_path,
                requested_provider="chattts",
                actual_provider="voicebox",
                fallback_reason="chattts_unavailable",
            )

    from hevi.explainer.voicebox_client import synthesize as vb_synthesize

    await vb_synthesize(text, output_path, instruct=instruct or "casual, conversational")
    if requested == "voicebox":
        return _identity_envelope(
            output_path, requested_provider="voicebox", actual_provider="voicebox"
        )
    return _identity_envelope(
        output_path,
        requested_provider=requested,
        actual_provider="voicebox",
        fallback_reason=f"unsupported_conversational_provider:{requested}",
    )


async def _synthesize_luxtts_with_fallback(
    *,
    text: str,
    output_path: Path,
    voice: str,
    instruct: str | None,
    requested_provider: str = "lux_tts",
    **kwargs: Any,
) -> dict[str, Any]:
    """Use the LuxTTS HTTP service first, then explicitly fall back to Cozy/Piper."""
    from hevi.audio.lux_tts_service import lux_tts_available, synth_with_luxtts

    lux_error: Exception | None = None
    cosy_error: Exception | None = None
    try:
        if not lux_tts_available():
            raise RuntimeError("LuxTTS HTTP /health is not ready")
        remote_voice = str(kwargs.get("remote_voice") or os.getenv("HEVI_LUXTTS_VOICE", "auto")).strip().lower()
        if remote_voice not in {"auto", "soffy", "en_male"}:
            logger.warning("Ignoring unsupported HEVI_LUXTTS_VOICE=%r; using auto", remote_voice)
            remote_voice = "auto"
        await synth_with_luxtts(
            text=text,
            output_path=output_path,
            voice=remote_voice,
            speed=float(kwargs.get("speed") or 1.0),
            steps=int(kwargs.get("steps") or 4),
        )
        return _identity_envelope(
            output_path, requested_provider=requested_provider, actual_provider="lux_tts"
        )
    except Exception as exc:
        lux_error = exc
        logger.warning(
            "LuxTTS HTTP unavailable/failed; falling back to CosyVoice then Piper: %s",
            lux_error,
        )

    try:
        from types import SimpleNamespace

        from hevi.audio.cosyvoice_service import cosyvoice_synthesize

        mode = os.getenv("HEVI_COSY_INFERENCE_MODE", "").strip() or None
        celeb = (kwargs.get("celeb") or os.getenv("COSY_CELEB") or "").strip()
        await cosyvoice_synthesize(
            config={"strict_voice": bool(celeb)},
            script=[SimpleNamespace(
                text=text,
                inference_mode=mode,
                instruct_text=instruct,
                voice_ref=str(kwargs.get("reference_audio") or "") or None,
                ref_text=str(kwargs.get("reference_text") or "") or None,
                voice_id=celeb or voice,
            )],
            output_path=output_path,
        )
        logger.warning("LuxTTS fallback selected CosyVoice after the HTTP service failed")
        return _identity_envelope(
            output_path,
            requested_provider=requested_provider,
            actual_provider="cosyvoice",
            fallback_reason=f"luxtts_http_unavailable:{lux_error}",
        )
    except Exception as exc:
        cosy_error = exc
        logger.warning("CosyVoice fallback failed; attempting Piper: %s", cosy_error)

    temp_root = Path(__file__).resolve().parents[2] / ".tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    piper_output = temp_root / f"piper_fallback_{uuid.uuid4().hex}.wav"
    try:
        from hevi.layer4_legacy.talkcraft.omodul_impl._media import piper_tts

        language = "zh" if any("\u4e00" <= ch <= "\u9fff" for ch in text) else "en"
        await asyncio.to_thread(
            piper_tts,
            text=text,
            out_wav=piper_output,
            lang=language,
            length_scale=float(kwargs.get("length_scale") or 1.0),
        )
        if not piper_output.is_file() or piper_output.stat().st_size < 100:
            raise RuntimeError("Piper did not produce a valid WAV")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(piper_output, output_path)
        logger.warning("LuxTTS and CosyVoice failed; Piper supplied fallback narration")
        return _identity_envelope(
            output_path,
            requested_provider=requested_provider,
            actual_provider="piper",
            fallback_reason=f"luxtts_http_unavailable:{lux_error};cosyvoice_unavailable:{cosy_error}",
        )
    except Exception as piper_error:
        raise AudioRoutingError(
            "LuxTTS HTTP, CosyVoice and Piper all failed: "
            f"luxtts={lux_error}; cosyvoice={cosy_error}; piper={piper_error}"
        ) from piper_error


async def _synthesize_formal(
    *, text: str, output_path: Path, voice: str, instruct: str | None, **_kw: Any
) -> dict[str, Any]:
    """Formal synthesis — CosyVoice authoritative broadcast style."""
    provider = _formal_requested_provider()

    if provider == "cosyvoice":
        from types import SimpleNamespace

        from hevi.audio.cosyvoice_service import cosyvoice_synthesize

        mode = os.getenv("HEVI_COSY_INFERENCE_MODE", "").strip() or None
        celeb = (_kw.get("celeb") or os.getenv("COSY_CELEB") or "").strip()
        # cosy-ref-v1: 参考音由 cosyvoice_service 统一解析(显式 voice_ref →
        # 名人/音色目录 → 内置默认)。显式点名的 celeb 必须解析成功(strict),
        # 不再在目录缺失时静默退成"只传文本"。
        await cosyvoice_synthesize(
            config={"strict_voice": bool(celeb)},
            script=[
                SimpleNamespace(
                    text=text,
                    inference_mode=mode,
                    instruct_text=instruct,
                    voice_ref=str(_kw.get("reference_audio") or "") or None,
                    ref_text=str(_kw.get("reference_text") or "") or None,
                    voice_id=celeb or voice,
                )
            ],
            output_path=output_path,
        )
        return _identity_envelope(
            output_path, requested_provider="cosyvoice", actual_provider="cosyvoice"
        )

    if provider == "f5":
        # F5-TTS 零样本克隆: 用环境配置的固定参考音色做解说。
        ref_audio = os.getenv("F5_TTS_REFERENCE_AUDIO", "").strip()
        ref_text = os.getenv("F5_TTS_REFERENCE_TEXT", "").strip()
        celeb = (_kw.get("celeb") or os.getenv("F5_TTS_CELEB") or "").strip()
        if celeb:
            from hevi.studio.voices import find_voice

            spec = find_voice(celeb)
            if spec and spec.local:
                ref_audio = spec.audio_path
                ref_text = spec.transcript or ref_text
        if not ref_audio or not ref_text:
            raise AudioRoutingError(
                "HEVI_TTS_FORMAL_PROVIDER=f5 需设置 F5_TTS_REFERENCE_AUDIO 与 "
                "F5_TTS_REFERENCE_TEXT(参考音频 + 其转录文本)"
            )
        from hevi.audio.f5_tts_service import f5_tts_synthesize

        await f5_tts_synthesize(
            text=text,
            output_path=output_path,
            reference_audio=ref_audio,
            reference_text=ref_text,
            model_name=os.getenv("F5_TTS_MODEL_NAME", "").strip() or None,
        )
        return _identity_envelope(output_path, requested_provider="f5", actual_provider="f5")

    if provider in {"lux", "lux_tts", "luxtts"}:
        return await _synthesize_luxtts_with_fallback(
            text=text,
            output_path=output_path,
            voice=voice,
            instruct=instruct,
            requested_provider=provider,
            **_kw,
        )

    if provider == "voxcpm":
        from hevi.audio.voxcpm_service import synth_with_voxcpm, voxcpm_available

        if not voxcpm_available():
            raise AudioRoutingError(
                "HEVI_TTS_FORMAL_PROVIDER=voxcpm 但 HEVI native voice runtime 不可用"
                "(需要 espeak-ng/espeak)"
            )
        ref_audio = (
            os.getenv("VOXCPM_REFERENCE_AUDIO", "").strip()
            or os.getenv("F5_TTS_REFERENCE_AUDIO", "").strip()
        )
        design = os.getenv("VOXCPM_VOICE_DESIGN", "").strip()
        await synth_with_voxcpm(
            text=text,
            output_path=output_path,
            language=str(_kw.get("language") or ""),
            reference_audio=ref_audio or None,
            voice_design=design,
            speed=float(_kw.get("speed") or 1.0),
        )
        return _identity_envelope(
            output_path, requested_provider="voxcpm", actual_provider="voxcpm"
        )

    if provider in {"pocket_tts", "pocket-tts", "pocket"}:
        from hevi.audio.pocket_tts_service import pocket_tts_available, synth_with_pocket_tts

        if not pocket_tts_available():
            raise AudioRoutingError(
                "HEVI_TTS_FORMAL_PROVIDER=pocket_tts 但 HEVI native voice runtime 不可用"
                "(需要 espeak-ng/espeak)"
            )
        await synth_with_pocket_tts(
            text,
            output_path=output_path,
            voice=str(_kw.get("voice") or os.getenv("POCKET_TTS_VOICE", "alba")),
            language=str(_kw.get("language") or ""),
            reference_audio=str(_kw.get("reference_audio") or "") or None,
            voice_design=str(_kw.get("voice_design") or os.getenv("POCKET_TTS_VOICE_DESIGN", "")),
            speed=float(_kw.get("speed") or 1.0),
        )
        return _identity_envelope(
            output_path, requested_provider=provider, actual_provider="pocket_tts"
        )

    if provider == "voicebox":
        from hevi.explainer.voicebox_client import synthesize as vb_synthesize

        await vb_synthesize(text, output_path, instruct=instruct or "professional, clear narration")
        return _identity_envelope(
            output_path, requested_provider="voicebox", actual_provider="voicebox"
        )

    try:
        import edge_tts

        comm = edge_tts.Communicate(text, voice)
        await comm.save(str(output_path))
        return _identity_envelope(
            output_path,
            requested_provider=provider,
            actual_provider="edge_tts",
            fallback_reason=f"unmatched_formal_provider:{provider}",
        )
    except ImportError:
        pass

    raise AudioRoutingError(f"No formal TTS backend available for provider={provider}")


async def route_and_stitch_master_audio(
    cues: list[Any],
    output_dir: Path,
    *,
    voice: str = "Dylan",
    aspect_ratio: str = "9:16",
    stitch_format: str = "wav",
) -> dict[str, Any]:
    """🚨 Core orchestrator: Route each cue → TTS, then stitch into one master.

    Returns:
        {
            "master_path": Path,           # Stitched master WAV/MP3
            "segment_paths": [Path, ...],  # Individual cue audio files
            "total_duration_s": float,     # Combined duration
            "manifest": list[dict],        # Per-segment metadata + provider identity
        }
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    segment_paths: list[Path] = []
    manifest_segments: list[dict[str, Any]] = []
    cursor_sec = 0.0

    for idx, cue in enumerate(cues):
        cue_text = getattr(cue, "text", "") or ""
        cue_style = getattr(cue, "audio_style", None)
        cue_id = getattr(cue, "id", f"cue-{idx + 1}")
        getattr(cue, "start_sec", cursor_sec)
        cue_captions = getattr(cue, "captions", [])

        suffix = stitch_format or ("mp3" if "edge_tts" in voice else "wav")
        seg_path = output_dir / f"{cue_id}.{suffix}"

        try:
            routed = await route_single_cue(
                cue_text=cue_text,
                cue_style=cue_style,
                output_path=seg_path,
                voice=voice,
            )
            routed_path = Path(routed["path"])
            segment_paths.append(routed_path)
            dur = probe_duration(routed_path)
        except Exception as e:
            logger.error("Failed to route cue %s: %s", cue_id, e)
            continue

        manifest_segments.append(
            {
                "id": cue_id,
                "text": cue_text,
                "audio_file": str(routed_path),
                "duration_sec": round(dur, 3),
                "start_sec": round(cursor_sec, 3),
                "captions": cue_captions if isinstance(cue_captions, list) else [],
                "visual_type": getattr(cue, "visual_type", "voiceover"),
                "visual_config": getattr(cue, "visual_config", {}),
                "layout_mode": getattr(cue, "layout_mode", "fullscreen"),
                "keywords": getattr(cue, "keywords", []),
                "requested_provider": routed.get("requested_provider"),
                "actual_provider": routed.get("actual_provider"),
                "substituted": bool(routed.get("substituted")),
                "requested_style": routed.get("requested_style"),
                "actual_style": routed.get("actual_style"),
                "fallback_reason": routed.get("fallback_reason"),
            }
        )
        cursor_sec += dur

    # Stitch all segments into master audio
    master_path = output_dir / f"master_audio.{stitch_format}"
    master_dur = cursor_sec

    if len(segment_paths) > 1:
        temp_root = Path(__file__).resolve().parents[2] / ".tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        concat_list = temp_root / f"audio_concat_{uuid.uuid4().hex}.txt"
        lines = [f"file '{sp.resolve()}'" for sp in segment_paths]
        concat_list.write_text("\n".join(lines))

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c:a",
            "pcm_s16le" if stitch_format == "wav" else "aac",
            "-b:a",
            "192k" if stitch_format != "wav" else "0",
            "-ar",
            "48000",
            "-ac",
            "1",
            str(master_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise AudioRoutingError(
                f"ffmpeg failed to stitch master audio: {stderr.decode(errors='replace')[-1000:]}"
            )

    if not master_path.exists() and segment_paths:
        # Copy the single segment as master
        import shutil

        shutil.copy2(segment_paths[0], master_path)

    return {
        "master_path": master_path,
        "segment_paths": segment_paths,
        "total_duration_s": round(master_dur, 3),
        "manifest": manifest_segments,
    }


# Import at bottom to avoid circular deps
