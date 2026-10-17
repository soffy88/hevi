"""Register WebKit/webrender capabilities into the Hevi unified registry."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import Capability, CapabilityResult, register


def _render_satori_title(
    params: dict[str, Any],
    out_dir: Path | str,
    *,
    duration: float = 0.0,
    aspect: str = "16:9",
    seed: int = 42,
) -> CapabilityResult:
    from hevi.webrender.satori_resvg import SatoriResvgCardRenderer

    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)
    renderer = SatoriResvgCardRenderer()
    title = params.get("title", "Hevi Video")
    subtitle = params.get("subtitle", "Automated Production")
    out_path = out_dir_path / f"satori_title_{seed}.png"
    renderer.render_card_png(title, subtitle, str(out_path), aspect=aspect)

    sha = hashlib.sha256(out_path.read_bytes()).hexdigest()
    return CapabilityResult(
        png=str(out_path), duration_s=duration, sha256=sha, qa={"status": "ok"}
    )


def register_webrender_capabilities() -> None:
    register(
        Capability(
            name="satori.title_card",
            kind="title",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "subtitle": {"type": "string"},
                },
            },
            cpu_cost_hint=0.1,
            render=_render_satori_title,
            line="webrender",
            description="Satori + resvg CPU 静态卡片/标题卡渲染",
        )
    )


register_webrender_capabilities()
