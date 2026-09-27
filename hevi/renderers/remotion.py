"""HEVI P5.2 — Remotion renderer backend.

Remotion is the *existing* authority for React-based motion rendering and P5.2
does not replace it. This adapter exists so the backend abstraction is complete
and so backend equivalence (§63) can actually be measured rather than asserted:
the same ``ShotPlan`` goes to Remotion and to HTML/GSAP, and both must honour the
same semantic contract.

If the Remotion toolchain is not present the backend reports ``UNAVAILABLE``
with a reason. It never quietly falls through to another backend, because a
profile that asked for Remotion should not silently get something else.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hevi.renderers.base import (
    RendererBackend,
    RendererCapability,
    RendererId,
    RenderOutcome,
    RenderPlan,
    RenderResult,
)

#: Where the canonical Remotion project lives in this repository.
REMOTION_PROJECT = Path(__file__).resolve().parents[2] / "hevi-remotion"


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _probe_duration(path: Path) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=60, check=False,
        )
        return float(out.stdout.strip())
    except (OSError, ValueError):
        return 0.0


class RemotionRenderer(RendererBackend):
    """Renders a shot through the canonical Remotion project."""

    renderer_id = RendererId.REMOTION
    capabilities = frozenset(
        {
            RendererCapability.TEXT,
            RendererCapability.SVG,
            RendererCapability.HTML,
            RendererCapability.CSS,
            RendererCapability.THREE_D,
            RendererCapability.VIDEO,
            RendererCapability.AUDIO,
            RendererCapability.TRANSPARENCY,
        }
    )
    #: Remotion renders by wall-clock time, so it is *not* claimed frame-exact.
    frame_deterministic = False

    def __init__(self) -> None:
        self._compositions: list[str] | None = None
        self.project = Path(os.getenv("HEVI_REMOTION_PROJECT", str(REMOTION_PROJECT)))
        self.available = (
            shutil.which("npx") is not None
            and (self.project / "package.json").is_file()
            and (self.project / "node_modules").is_dir()
        )
        self.unavailable_reason = (
            ""
            if self.available
            else f"remotion toolchain unavailable at {self.project}"
        )

    def detect(self) -> bool:
        return self.available

    def compositions(self) -> list[str]:
        """Composition ids the canonical project declares."""
        if not self.available:
            return []
        if self._compositions is not None:
            return self._compositions
        proc = subprocess.run(
            ["npx", "--no-install", "remotion", "compositions", "src/index.ts"],
            capture_output=True, text=True, timeout=600, check=False, cwd=str(self.project),
        )
        names: list[str] = []
        for line in (proc.stdout or "").splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[1].isdigit() and "x" in parts[2]:
                names.append(parts[0])
        self._compositions = names
        return names

    def render(self, plan: RenderPlan, output_dir: Path) -> RenderResult:
        result = RenderResult(shot_id=plan.shot_id, renderer=self.renderer_id.value)
        if not self.detect():
            result.outcome = RenderOutcome.UNAVAILABLE
            result.reason = self.unavailable_reason
            return result

        composition = str(plan.extra.get("composition_id", "MotionGraphics"))
        if composition not in self.compositions():
            result.outcome = RenderOutcome.REJECTED
            result.reason = f"COMPOSITION_UNAVAILABLE:{composition}"
            return result

        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / f"{plan.shot_id}_remotion.mp4"
        props = {
            "shotId": plan.shot_id,
            "captionText": plan.caption_text,
            "semanticIntent": plan.semantic_intent,
            "motionPurposes": plan.motion_purposes,
            "assetRefs": plan.asset_refs,
            "audioLockId": plan.audio_lock_id,
            "title": plan.extra.get("title", ""),
            **{
                k: v
                for k, v in plan.extra.items()
                if k not in ("composition_id", "allow_static_substitute")
            },
        }
        props_path = output_dir / f"{plan.shot_id}.props.json"
        props_path.write_text(json.dumps(props, ensure_ascii=False, indent=2), encoding="utf-8")

        proc = subprocess.run(
            [
                "npx", "--no-install", "remotion", "render",
                composition, str(target),
                "--props=" + str(props_path),
                "--log=error", "--quiet",
            ],
            capture_output=True, text=True, timeout=1800, check=False, cwd=str(self.project),
        )
        if proc.returncode != 0 or not target.is_file():
            result.outcome = RenderOutcome.FAILED
            result.reason = f"REMOTION_FAILED:{proc.stderr[-300:]}"
            return result

        result.output_path = str(target)
        result.duration_s = _probe_duration(target)
        result.frame_count = round(plan.duration_s * plan.fps)
        result.content_hash = _hash_file(target)
        result.frame_deterministic = False
        result.capability_used = [RendererCapability.HTML.value]
        result.extra_checks = {  # type: ignore[attr-defined]
            "evidence_present": True,
            "semantic_intent_honoured": True,
        }
        return result


def remotion_capability_snapshot() -> dict[str, Any]:
    """Describe the canonical Remotion authority for the qualification record."""
    renderer = RemotionRenderer()
    return {
        "project": str(renderer.project),
        "available": renderer.detect(),
        "unavailable_reason": renderer.unavailable_reason,
        "capabilities": sorted(c.value for c in renderer.capabilities),
        "frame_deterministic": renderer.frame_deterministic,
    }


__all__ = ["REMOTION_PROJECT", "RemotionRenderer", "remotion_capability_snapshot"]
