"""Deterministic keyframe engine backed by the library-aware handdraw illustrator.

Why it exists: the SD-Turbo CPU engine needs ~5.5 GB resident and is the
default production path; on memory-constrained hosts the comic line can still
produce real, style-locked panels with this CPU-only engine.  It is explicit
(engine name ``handraw_cpu``), seed-deterministic, and uses the same library
style/theme ids as the rest of S27.  It is not a fake: the output is a rendered
illustration, not a placeholder.
"""

from __future__ import annotations

import contextlib
import hashlib
import resource
import time
from pathlib import Path

from PIL import Image

from hevi.layer4_legacy.handdraw.illustrator import (
    ILLUSTRATION_BUILDERS,
    build_scene_illustration,
)
from hevi.layer4_legacy.handdraw.styles import get_style_config
from hevi.layer4_legacy.keyframe.oprim_impl.contracts import KeyframeEngine, KeyframeResult

_SCENE_KEYS = sorted(ILLUSTRATION_BUILDERS)


class HandrawLibraryEngine(KeyframeEngine):
    _instance: HandrawLibraryEngine | None = None

    def __init__(self) -> None:
        self.style_id = "17"
        self.theme_color_id = "C-27"

    @classmethod
    def get_instance(cls) -> HandrawLibraryEngine:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def name(self) -> str:
        return "handraw_cpu"

    def available(self) -> bool:
        return True

    @property
    def max_resident_mb(self) -> float:
        return 600.0

    def configure(self, *, style_id: str | None = None, theme_color_id: str | None = None) -> None:
        if style_id:
            self.style_id = style_id
        if theme_color_id:
            self.theme_color_id = theme_color_id

    def _scene_for(self, prompt: str) -> str:
        text = prompt.lower()
        routes = [
            (("money", "coin", "price", "cost", "invest"), "coin_pyramid"),
            (("growth", "data", "trend", "curve", "increase"), "growth_curves"),
            (("choice", "balance", "fair", "trade-off", "decision"), "balance_scale"),
            (("fear", "courage", "brave", "anxious"), "cat_courage"),
            (("nature", "space", "science", "star", "universe"), "stars_nature"),
            (("emotion", "feeling", "anger", "sad", "mood"), "feelings"),
            (("plan", "judge", "calm", "think"), "calm_decision"),
            (("snowball", "accumulate", "compound"), "snowball_effect"),
        ]
        for words, key in routes:
            if any(w in text for w in words):
                return key
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        return _SCENE_KEYS[int(digest[:8], 16) % len(_SCENE_KEYS)]

    def generate(
        self,
        prompt_en: str,
        *,
        negative: str | None = None,
        width: int = 512,
        height: int = 512,
        steps: int = 2,
        seed: int | None = None,
        ref_image: Path | None = None,
        output_path: Path | None = None,
    ) -> KeyframeResult:
        started = time.time()
        effective_seed = int(seed if seed is not None else 1234)
        scene = self._scene_for(prompt_en)
        cfg = get_style_config(self.style_id, theme_color_id=self.theme_color_id)
        tmp = (output_path or Path("output/keyframes/handraw_tmp.png")).with_suffix(".illu.png")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        build_scene_illustration(
            scene,
            tmp,
            style_id=self.style_id,
            size=(width, height),
            seed=effective_seed,
            theme_color_id=self.theme_color_id,
        )
        paper = Image.new("RGB", (width, height), cfg.paper_color)
        illu = Image.open(tmp).convert("RGBA")
        paper.paste(illu, (0, 0), illu)
        out = Path(output_path) if output_path else Path("output/keyframes") / (
            f"handraw_{effective_seed}_{hashlib.md5(prompt_en.encode()).hexdigest()[:8]}.png"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        paper.save(out)
        with contextlib.suppress(OSError):
            tmp.unlink()
        rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
        return KeyframeResult(
            path=out,
            seed=effective_seed,
            engine=self.name,
            model="handraw-library",
            sec=time.time() - started,
            rss_mb=rss_mb,
            width=width,
            height=height,
            steps=max(1, int(steps)),
        )


def register() -> None:
    from hevi.layer4_legacy.keyframe.oprim_impl.registry import register_engine

    register_engine("handraw_cpu", engine=HandrawLibraryEngine)


__all__ = ["HandrawLibraryEngine", "register"]
