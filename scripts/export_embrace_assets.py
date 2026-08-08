#!/usr/bin/env python3
"""导出 3O 内化资产 → hevi-web/public/embrace/ JSON(3O 内化 wire ④)。

让前端零 API 改动消费:镜头配方卡(画廊/卡片选择)、判例式审美准则(终检展示)、
失败模式定义(诊断/负向子句说明)。由 CI 或构建前跑;产物为纯静态 JSON。

用法:
    python scripts/export_embrace_assets.py [--out hevi-web/public/embrace]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hevi.motion.recipe_card import build_seed_library, save_library
from hevi.verdict.aesthetic_canon import default_canon
from hevi.verdict.failure_registry import default_registry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("hevi-web/public/embrace"),
        help="输出目录(默认 hevi-web/public/embrace)",
    )
    args = parser.parse_args(argv)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    # 镜头配方卡
    cards = build_seed_library()
    save_library(cards, out / "cards.json")

    # 判例式审美准则
    canon = default_canon()
    (out / "canon.json").write_text(
        json.dumps(canon.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 失败模式定义
    registry = default_registry()
    (out / "failure_modes.json").write_text(
        json.dumps(
            [
                {
                    "code": m.code,
                    "layer": m.layer,
                    "description": m.description,
                    "negative_clause": m.negative_clause,
                    "keywords": list(m.keywords),
                }
                for m in registry.modes.values()
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"embrace assets -> {out}")
    print(f"  cards: {len(cards)}")
    print(f"  canon rules: {len(canon.rules)}")
    print(f"  failure modes: {len(registry.modes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
