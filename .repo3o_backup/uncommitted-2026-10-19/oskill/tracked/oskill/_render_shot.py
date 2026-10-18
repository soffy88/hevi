"""K-render_shot: unified shot rendering dispatcher (generative / code_render)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from oprim._render_html_to_mp4 import RenderHtmlError, render_html_to_mp4
from oprim._shot_types import ShotResult
from oprim._video_generate import VideoGenError, video_generate


async def render_shot(
    *,
    shot_type: Literal["generative", "code_render"],
    shot_spec: dict,
    output_path: Path,
    llm=None,
    validate: bool = True,
) -> ShotResult:
    """Unified shot renderer. Routes by shot_type and returns ShotResult.

    generative:   calls video_generate (oprim) via the registered provider.
                  shot_spec: {provider, prompt, duration_s, width?, height?, fps?}
    code_render:  calls render_html_to_mp4 (oprim) for HTML/CSS/GSAP clips.
                  shot_spec: {html, duration_s, width?, height?, fps?}

    validate=True (default): run validate_html for code_render shots.
    llm: optional LLM caller for generative shots that use prompt refinement.
    """
    duration_s: float = float(shot_spec.get("duration_s", 5.0))

    if shot_type == "code_render":
        html: str = shot_spec.get("html", "")
        violations: list[str] = []
        try:
            await render_html_to_mp4(
                html=html,
                output_path=output_path,
                duration_s=duration_s,
                width=int(shot_spec.get("width", 1920)),
                height=int(shot_spec.get("height", 1080)),
                fps=int(shot_spec.get("fps", 30)),
                validate=validate,
            )
            is_valid = True
        except RenderHtmlError as exc:
            is_valid = False
            violations = [str(exc)]
            output_path.write_bytes(b"")  # placeholder so callers don't crash

        return ShotResult(
            output_path=output_path,
            shot_type="code_render",
            duration_s=duration_s,
            metadata={
                "width": shot_spec.get("width", 1920),
                "height": shot_spec.get("height", 1080),
            },
            is_valid=is_valid,
            validation_violations=violations,
        )

    elif shot_type == "generative":
        provider: str = shot_spec.get("provider", "wan_local")
        prompt: str = shot_spec.get("prompt", "")
        try:
            await video_generate(
                provider=provider,
                prompt=prompt,
                duration_s=duration_s,
                width=int(shot_spec.get("width", 1080)),
                height=int(shot_spec.get("height", 1920)),
                output_path=output_path,
                timeout_s=float(shot_spec.get("timeout_s", 600.0)),
            )
            is_valid = True
            violations = []
        except (VideoGenError, Exception) as exc:
            is_valid = False
            violations = [str(exc)]
            output_path.write_bytes(b"")

        return ShotResult(
            output_path=output_path,
            shot_type="generative",
            duration_s=duration_s,
            metadata={"provider": provider, "prompt_preview": prompt[:100]},
            is_valid=is_valid,
            validation_violations=violations,
        )

    else:
        raise ValueError(
            f"Unknown shot_type: {shot_type!r}. Must be 'generative' or 'code_render'."
        )
