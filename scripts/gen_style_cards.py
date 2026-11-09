"""Generate the eight built-in ai_drama style cards with local SD-Turbo.

Each card gets a cover (a small scene) and a flat-light makeup reference (a
front / head-and-shoulders portrait on a plain background).  Everything runs on
CPU through the same engine the ai_drama keyframes use; nothing is downloaded.

Usage:
    python scripts/gen_style_cards.py [--force]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _bootstrap_env() -> None:
    if os.environ.get("JWT_SECRET"):
        return
    env_file = Path(os.environ.get("HEVI_ENV_FILE", "/data/soffy/projects/hevi-release/.env"))
    if env_file.is_file():
        try:
            from dotenv import dotenv_values

            for key, value in dotenv_values(env_file).items():
                if value is not None:
                    os.environ.setdefault(key, value)
        except Exception:
            pass
    os.environ.setdefault("APP_ENV", "development")


_bootstrap_env()

from PIL import Image  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets" / "style_cards"

# Keep prompts short; SD-Turbo responds better to a compact clause list.
COVER_SUBJECT = (
    "a young adult character standing in a simple room, three-quarter body, "
    "calm expression, plain background"
)
MAKEUP_SUBJECT = (
    "same character, head and shoulders portrait, front facing, neutral expression, "
    "flat even lighting, plain light grey seamless background, no shadow, no filter, "
    "character reference photo"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    from hevi.ai_drama.style_cards import STYLE_CARDS
    from hevi.layer4_legacy.keyframe.oprim_impl.registry import resolve_keyframe_engine

    ASSETS.mkdir(parents=True, exist_ok=True)
    engine = resolve_keyframe_engine("sdturbo_cpu")
    made = 0
    for index, card in enumerate(STYLE_CARDS):
        for kind, subject, suffix in (
            ("cover", COVER_SUBJECT, "cover"),
            ("makeup", MAKEUP_SUBJECT, "makeup"),
        ):
            target = ASSETS / str(card[suffix])
            if target.is_file() and target.stat().st_size > 0 and not args.force:
                continue
            prompt = f"{card['style_prompt']}, {subject}"
            raw = ASSETS / f".{card['id']}_{kind}.png"
            engine.generate(
                prompt_en=prompt,
                negative=card["negative_prompt"],
                width=512,
                height=768,
                steps=2,
                seed=101 + index * 13 + (0 if kind == "cover" else 7),
                output_path=raw,
            )
            with Image.open(raw) as img:
                img.convert("RGB").save(target, "JPEG", quality=88, optimize=True)
            raw.unlink(missing_ok=True)
            print(f"{card['id']}: {kind} -> {target.name} ({target.stat().st_size} bytes)")
            made += 1
    print(f"generated {made} image(s) into {ASSETS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
