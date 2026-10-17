"""HEVI brandfilm — CPU 15s brand film line (line=brandfilm).

Internalizes code-brand-film (MIT, nutllwhy) into Hevi as a production line:
brief -> shot-list -> copy -> HTML/GSAP -> frame render -> beat-aligned algorithmic
score -> three quality gates.
"""

from __future__ import annotations

from .generator import generate_brandfilm_project
from .pipeline import BrandfilmBrief, run_brandfilm_pipeline
from .score import compose_brandfilm_score, mux_audio_video

__all__ = [
    "BrandfilmBrief",
    "compose_brandfilm_score",
    "generate_brandfilm_project",
    "mux_audio_video",
    "run_brandfilm_pipeline",
]
