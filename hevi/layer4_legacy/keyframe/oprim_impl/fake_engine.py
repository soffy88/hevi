"""Fake keyframe engine for deterministic unit testing.

E2E path strictly forbids this engine.
"""

from __future__ import annotations

import hashlib
import resource
import time
from pathlib import Path

from PIL import Image, ImageDraw

from hevi.layer4_legacy.keyframe.oprim_impl.contracts import KeyframeEngine, KeyframeResult


class FakeKeyframeEngine(KeyframeEngine):
    """Deterministic, lightweight fake engine producing synthetic test images."""

    @property
    def name(self) -> str:
        return "fake"

    def available(self) -> bool:
        return True

    @property
    def max_resident_mb(self) -> float:
        return 10.0

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
        t0 = time.time()
        effective_seed = seed if seed is not None else 42

        # Create a deterministic color from seed & prompt
        digest = hashlib.md5(f"{effective_seed}:{prompt_en}".encode("utf-8")).hexdigest()
        r = int(digest[0:2], 16)
        g = int(digest[2:4], 16)
        b = int(digest[4:6], 16)

        img = Image.new("RGB", (width, height), color=(r, g, b))
        draw = ImageDraw.Draw(img)

        # Draw diagonal line and text box to ensure non-solid variance
        draw.line([(0, 0), (width, height)], fill=(255 - r, 255 - g, 255 - b), width=4)
        draw.line([(0, height), (width, 0)], fill=(200, 200, 200), width=2)
        text = f"FAKE [{effective_seed}]: {prompt_en[:30]}"
        draw.text((20, 20), text, fill=(255, 255, 255))

        if output_path is None:
            cache_dir = Path("/tmp/hevi_fake_keyframes")
            cache_dir.mkdir(parents=True, exist_ok=True)
            output_path = cache_dir / f"fake_{effective_seed}_{digest[:8]}.png"
        else:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

        img.save(output_path)
        sec = max(0.001, time.time() - t0)
        rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0

        return KeyframeResult(
            path=output_path,
            seed=effective_seed,
            engine="fake",
            model="synthetic-v1",
            sec=sec,
            rss_mb=rss_mb,
            width=width,
            height=height,
            steps=steps,
        )
