"""Executable AI-Shorts runtime owned by HEVI.

The OpenShorts surface describes a website/description -> script -> voice ->
talking-head -> composite transaction.  This module is the concrete boundary
for that transaction.  It deliberately accepts provider callables instead of
installing a particular actor/video SDK.  A provider must return a real local
artifact; otherwise the transaction is blocked and never reports success.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlparse

import httpx

from hevi.openshorts.oprim import generate_script_from_description, plan_ai_short_actor
from hevi.openshorts.schemas import AICostMode
from hevi.production.artifacts import Artifact, ArtifactManifest
from hevi.voicepro.oskill import synthesize_native_voice


class _VisibleTextParser(HTMLParser):
    """Small dependency-free HTML to visible text extractor."""

    _skip: ClassVar[set[str]] = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self._skip:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._skip and self._depth:
            self._depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._depth:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)


def _fingerprint(config: dict[str, Any], data: dict[str, Any]) -> str:
    shape = {
        "config": {
            key: value
            for key, value in config.items()
            if key not in {"api_key", "token", "secret", "provider", "providers"}
            and not callable(value)
        },
        "input_keys": sorted(data),
        "has_url": bool(data.get("url") or data.get("product_url")),
        "has_description": bool(data.get("description") or data.get("product_description")),
    }
    return hashlib.sha256(json.dumps(shape, sort_keys=True, default=str).encode()).hexdigest()[:24]


async def _notify(callback: Any, stage: str, progress_pct: float, **meta: Any) -> None:
    if callback is None:
        return
    value = callback({"stage": stage, "progress_pct": progress_pct, **meta})
    if inspect.isawaitable(value):
        await value


def _endpoint_provider(endpoint: str, *, token: str = "") -> Any:
    async def call(payload: dict[str, Any]) -> Any:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
        if not isinstance(body, dict):
            raise ValueError("AI Shorts provider response must be a JSON object")
        return body

    return call


def _provider(data: dict[str, Any], config: dict[str, Any], name: str) -> Any:
    providers = data.get("providers") or config.get("providers") or {}
    if isinstance(providers, dict) and providers.get(name) is not None:
        value = providers[name]
        if callable(value):
            return value
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return _endpoint_provider(value, token=str(config.get("provider_token") or os.getenv("HEVI_AI_SHORT_PROVIDER_TOKEN", "")))
        return None
    value = data.get(f"{name}_provider") or config.get(f"{name}_provider")
    if callable(value):
        return value
    endpoint = str(data.get(f"{name}_endpoint") or config.get(f"{name}_endpoint") or os.getenv(f"HEVI_AI_SHORT_{name.upper()}_ENDPOINT", "")).strip()
    if endpoint.startswith(("http://", "https://")):
        return _endpoint_provider(endpoint, token=str(config.get("provider_token") or os.getenv("HEVI_AI_SHORT_PROVIDER_TOKEN", "")))
    return None


async def _call_provider(provider: Any, payload: dict[str, Any]) -> Any:
    if not callable(provider):
        return None
    try:
        result = provider(payload)
    except TypeError:
        # A few existing HEVI adapters use keyword payloads.
        result = provider(**payload)
    return await result if inspect.isawaitable(result) else result


def _artifact_path(value: Any, *, label: str) -> Path:
    if isinstance(value, dict):
        value = value.get("path") or value.get("output_path") or value.get("artifact")
    path = Path(str(value or "")).expanduser()
    if not path.is_file() or path.stat().st_size <= 0:
        raise FileNotFoundError(f"{label} provider did not return a non-empty local artifact: {path}")
    return path


async def fetch_product_description(url: str, *, timeout_s: float = 20.0) -> str:
    """Fetch a bounded visible-text snapshot for a product URL.

    This is intentionally a source snapshot, not an SEO/LLM claim.  If the
    page cannot be retrieved, callers receive an explicit error and can ask
    for a manual description.
    """

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("product URL must be an absolute http(s) URL")
    async with httpx.AsyncClient(
        timeout=timeout_s,
        follow_redirects=True,
        headers={"User-Agent": "HEVI/1.0 product research"},
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
    parser = _VisibleTextParser()
    parser.feed(response.text[:1_000_000])
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    if not text:
        raise ValueError("product page returned no visible text")
    return text[:12_000]


def _script_narration(script: Any) -> str:
    return " ".join(
        str(getattr(script, field, "") or "").strip()
        for field in ("hook", "problem", "solution", "cta")
        if str(getattr(script, field, "") or "").strip()
    )


def _run_ffmpeg(args: list[str], *, output: Path) -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("FFmpeg 未安装，无法合成 AI Shorts 成片")
    process = subprocess.run(args, capture_output=True, text=True, check=False, timeout=180)
    if process.returncode != 0 or not output.is_file() or output.stat().st_size <= 0:
        detail = (process.stderr or process.stdout or "unknown ffmpeg error").strip()[-800:]
        raise RuntimeError(f"AI Shorts FFmpeg 合成失败: {detail}")


def _compose(
    talking_head: Path,
    output: Path,
    *,
    voiceover: Path | None = None,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    if voiceover is not None:
        args = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(talking_head), "-i", str(voiceover),
            "-map", "0:v:0", "-map", "1:a:0", "-shortest",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-movflags", "+faststart", str(output),
        ]
    else:
        args = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(talking_head), "-map", "0:v:0", "-an",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(output),
        ]
    _run_ffmpeg(args, output=output)
    return output


def _report_error(
    output_dir: Path,
    *,
    status: str,
    operation: str,
    fingerprint: str,
    trail: list[dict[str, Any]],
    error: Exception,
) -> dict[str, Any]:
    report_path = output_dir / "ai_shorts_report.json"
    payload = {
        "status": status,
        "operation": operation,
        "fingerprint": fingerprint,
        "decision_trail": trail,
        "error": {"type": type(error).__name__, "message": str(error)[:800]},
        "artifacts": [],
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": status,
        "error": payload["error"],
        "fingerprint": fingerprint,
        "decision_trail": trail,
        "report_path": str(report_path),
        "artifacts": [],
        "findings": {},
    }


async def ai_shorts_generation_workflow(
    config: Any,
    input_data: Any,
    output_dir: str | Path,
    *,
    on_step: Any = None,
) -> dict[str, Any]:
    """Run the AI Shorts transaction with verified local artifacts.

    Required for a completed run: a talking-head provider or an existing
    local talking-head video.  Voice is similarly either a real local file,
    an injected provider, or HEVI's native local renderer.  Actor/video APIs
    are intentionally injected at this boundary so HEVI does not install or
    silently substitute third-party model SDKs.
    """

    cfg = dict(config.model_dump() if hasattr(config, "model_dump") else config or {})
    data = dict(input_data.model_dump() if hasattr(input_data, "model_dump") else input_data or {})
    output = Path(output_dir).expanduser()
    output.mkdir(parents=True, exist_ok=True)
    fingerprint = _fingerprint(cfg, data)
    trail: list[dict[str, Any]] = []
    try:
        description = str(data.get("description") or data.get("product_description") or "").strip()
        url = str(data.get("url") or data.get("product_url") or "").strip()
        if not description and url:
            await _notify(on_step, "analyze", 10.0)
            description = await fetch_product_description(url, timeout_s=float(cfg.get("url_timeout_s") or 20.0))
            trail.append({"stage": "analyze", "source": "url_snapshot", "chars": len(description)})
        if not description:
            raise ValueError("AI Shorts requires description or a readable product URL")

        mode_value = str(data.get("cost_mode") or cfg.get("cost_mode") or "low_cost")
        mode = AICostMode(mode_value)
        await _notify(on_step, "script", 25.0)
        script_provider = _provider(data, cfg, "script")
        script = await _call_provider(script_provider, {"description": description, "cost_mode": mode.value})
        if script is None:
            script = generate_script_from_description(description, mode)
        if isinstance(script, dict):
            from hevi.openshorts.schemas import AIScript

            script = AIScript.model_validate(script)
        if not _script_narration(script):
            raise ValueError("script stage returned empty narration")
        trail.append({"stage": "script", "provider": "injected" if script_provider else "hevi-native"})

        actor = plan_ai_short_actor(description, mode)
        actor_provider = _provider(data, cfg, "actor")
        actor_result = await _call_provider(actor_provider, {"description": description, "actor": actor.model_dump(mode="json")})
        portrait = None
        if actor_result is not None:
            portrait = _artifact_path(actor_result, label="actor")
            actor.portrait_path = str(portrait)
        elif data.get("actor_image") or data.get("portrait_path"):
            portrait = _artifact_path(data.get("actor_image") or data.get("portrait_path"), label="actor")
            actor.portrait_path = str(portrait)
        trail.append({"stage": "actor", "provider": "injected" if actor_provider else ("local_asset" if portrait else "not_required")})

        talking_provider = _provider(data, cfg, "talking_head") or _provider(data, cfg, "video")
        talking_asset = data.get("talking_head_path") or cfg.get("talking_head_path")
        if talking_provider is None and not talking_asset:
            raise RuntimeError("AI Shorts 缺少 talking_head_path；请注入 talking_head/video provider")

        voiceover: Path | None = None
        if bool(data.get("with_voiceover", cfg.get("with_voiceover", True))):
            await _notify(on_step, "voice", 40.0)
            supplied_voice = data.get("voiceover_path") or cfg.get("voiceover_path")
            voice_provider = _provider(data, cfg, "voice")
            voice_result = await _call_provider(
                voice_provider,
                {"text": _script_narration(script), "script": script.model_dump(mode="json")},
            )
            if voice_result is not None:
                voiceover = _artifact_path(voice_result, label="voice")
                voice_source = "injected"
            elif supplied_voice:
                voiceover = _artifact_path(supplied_voice, label="voiceover")
                voice_source = "local_asset"
            else:
                voiceover = output / "voiceover.wav"
                language = str(data.get("language") or cfg.get("language") or ("zh" if re.search(r"[\u4e00-\u9fff]", _script_narration(script)) else "en"))
                voice_engine = str(
                    data.get("voice_engine")
                    or cfg.get("voice_engine")
                    or os.getenv("HEVI_AI_SHORT_TTS_PROVIDER", "native")
                ).strip().lower()
                voice_kwargs: dict[str, Any] = {
                    "language": language,
                    "reference_audio": data.get("reference_audio") or cfg.get("reference_audio"),
                    "voice_design": str(data.get("voice_design") or cfg.get("voice_design") or ""),
                    "speed": float(data.get("voice_speed") or cfg.get("voice_speed") or 1.0),
                }
                if voice_engine in {"pocket", "pocket-tts", "pocket_tts"}:
                    from hevi.audio.pocket_tts_service import synth_with_pocket_tts

                    await synth_with_pocket_tts(
                        _script_narration(script),
                        output_path=voiceover,
                        voice=str(data.get("voice") or cfg.get("voice") or "alba"),
                        config=str(data.get("model_config") or cfg.get("model_config") or "") or None,
                        **voice_kwargs,
                    )
                    voice_engine = "pocket_tts"
                elif voice_engine == "voxcpm":
                    from hevi.audio.voxcpm_service import synth_with_voxcpm

                    await synth_with_voxcpm(
                        _script_narration(script),
                        voiceover,
                        **voice_kwargs,
                    )
                elif voice_engine in {"native", "hevi", "hevi-native"}:
                    await synthesize_native_voice(
                        _script_narration(script),
                        voiceover,
                        voice=str(data.get("voice") or cfg.get("voice") or ""),
                        **voice_kwargs,
                    )
                    voice_engine = "hevi-native"
                else:
                    raise ValueError(f"unsupported AI Shorts voice_engine: {voice_engine}")
                voiceover = _artifact_path(voiceover, label="native voice")
                voice_source = voice_engine
            trail.append({"stage": "voice", "provider": voice_source, "path": str(voiceover)})

        await _notify(on_step, "video", 60.0)
        talking_result = await _call_provider(
            talking_provider,
            {
                "script": script.model_dump(mode="json"),
                "description": description,
                "actor": actor.model_dump(mode="json"),
                "voiceover_path": str(voiceover) if voiceover else None,
                "output_dir": str(output),
            },
        )
        talking_path = talking_result or data.get("talking_head_path") or cfg.get("talking_head_path")
        if not talking_path:
            raise RuntimeError("AI Shorts 缺少 talking_head_path；请注入 talking_head/video provider")
        talking_head = _artifact_path(talking_path, label="talking-head")
        trail.append({"stage": "video", "provider": "injected" if talking_provider else "local_asset", "path": str(talking_head)})

        b_roll: list[Path] = []
        broll_provider = _provider(data, cfg, "b_roll") or _provider(data, cfg, "broll")
        broll_result = await _call_provider(
            broll_provider,
            {"description": description, "script": script.model_dump(mode="json"), "output_dir": str(output)},
        )
        raw_broll = broll_result if broll_result is not None else data.get("b_roll_paths") or cfg.get("b_roll_paths") or []
        if isinstance(raw_broll, (str, Path)):
            raw_broll = [raw_broll]
        b_roll = [_artifact_path(item, label="b-roll") for item in raw_broll]
        trail.append({"stage": "broll", "provider": "injected" if broll_provider else ("local_asset" if b_roll else "none"), "count": len(b_roll)})

        await _notify(on_step, "composite", 82.0)
        composite = _compose(talking_head, output / "composite.mp4", voiceover=voiceover)
        artifacts = [
            Artifact.from_path(composite, kind="video", media_type="video/mp4", primary=True, logical_role="ai_short_composite"),
            Artifact.from_path(talking_head, kind="video", media_type="video/mp4", logical_role="talking_head"),
        ]
        if voiceover:
            artifacts.append(Artifact.from_path(voiceover, kind="audio", media_type="audio/wav", logical_role="voiceover"))
        artifacts.extend(Artifact.from_path(path, kind="image" if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} else "video", logical_role="b_roll") for path in b_roll)
        manifest = ArtifactManifest(artifacts=artifacts)
        trail.append({"stage": "composite", "path": str(composite), "verified": True})

        publish_results: list[dict[str, Any]] = []
        for platform in data.get("publish_to") or data.get("publish_platforms") or []:
            from hevi.publishers import publish_to_platform

            result = await publish_to_platform(str(platform), composite, title=script.hook, description=_script_narration(script))
            publish_results.append(result.to_dict())
        report = {
            "status": "succeeded",
            "operation": "ai_shorts_generation_workflow",
            "fingerprint": fingerprint,
            "decision_trail": trail,
            "cost_usd": float(data.get("actual_cost_usd") or cfg.get("actual_cost_usd") or 0.0),
            "artifact_manifest": manifest.model_dump(mode="json"),
            "publish_results": publish_results,
        }
        report_path = output / "ai_shorts_report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        await _notify(on_step, "completed", 100.0)
        return {
            "status": "succeeded",
            "error": None,
            "fingerprint": fingerprint,
            "decision_trail": trail,
            "report_path": str(report_path),
            "cost_usd": report["cost_usd"],
            "artifacts": manifest.model_dump(mode="json")["artifacts"],
            "findings": {
                "description": description,
                "script": script.model_dump(mode="json"),
                "actor": actor.model_dump(mode="json"),
                "voiceover_path": str(voiceover) if voiceover else "",
                "talking_head_path": str(talking_head),
                "b_roll_paths": [str(path) for path in b_roll],
                "composite_path": str(composite),
                "publish_results": publish_results,
            },
        }
    except (FileNotFoundError, ValueError, RuntimeError, httpx.HTTPError) as exc:
        status = "blocked" if isinstance(exc, (FileNotFoundError, ValueError)) and "provider" in str(exc).lower() else "failed"
        return _report_error(output, status=status, operation="ai_shorts_generation_workflow", fingerprint=fingerprint, trail=trail, error=exc)
    except Exception as exc:  # provider SDKs must not leak an unrecorded failure
        return _report_error(output, status="failed", operation="ai_shorts_generation_workflow", fingerprint=fingerprint, trail=trail, error=exc)


__all__ = ["ai_shorts_generation_workflow", "fetch_product_description"]
