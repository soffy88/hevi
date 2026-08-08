#!/usr/bin/env python3
"""CI: 配方卡 schema 校验(3O 内化 Phase B/C)。

检查 hevi 内建的镜头配方卡库:
  1. 卡名 kebab-case 且唯一(dict key == card.name)
  2. category 在 CARD_CATEGORIES 枚举内
  3. energy 合法;suggested_duration_s > 0;purpose 非空
  4. known_pitfalls 非空(配方卡的命门标注是硬要求 —— 来源 shotcraft)

Exit 0 = 通过;非 0 = 列出问题。
"""
from __future__ import annotations

import sys

from hevi.motion.recipe_card import build_seed_library, validate_library


def main() -> int:
    library = build_seed_library()
    issues = validate_library(library)
    # 硬要求:已知坑必须标注
    for name, card in library.items():
        if not card.known_pitfalls:
            issues.append(f"card {name}: known_pitfalls must not be empty")
    if issues:
        for issue in issues:
            print(f"RECIPE-CARD: {issue}")
        return 1
    print(f"RECIPE-CARD: {len(library)} cards OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
