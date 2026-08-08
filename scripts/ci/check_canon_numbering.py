#!/usr/bin/env python3
"""CI: 判例库编号只增不重排 + 每族齐全(3O 内化 Phase B)。

检查 hevi/verdict/aesthetic_canon.py 的种子判例库:
  1. 编号格式(族+序号)合法,族 ∈ {R,Q,S,C,P}
  2. 同一族内序号严格递增(只增不重排)
  3. 每族至少一条(规则 + self_check 非空)

Exit 0 = 通过;非 0 = 列出问题。
"""
from __future__ import annotations

import sys

from hevi.verdict.aesthetic_canon import (
    CANON_FAMILIES,
    default_canon,
    validate_canon,
)


def main() -> int:
    canon = default_canon()
    issues = validate_canon(canon)
    seen: dict[str, int] = {}
    for rule in canon.rules:
        family = rule.code[0]
        number = int(rule.code[1:])
        if family in seen and number <= seen[family]:
            issues.append(
                f"{rule.code}: numbering must only append "
                f"(family max {family}{seen[family]})"
            )
        seen[family] = max(seen.get(family, 0), number)
        if not rule.self_check.strip():
            issues.append(f"{rule.code}: self_check must not be empty")
    if issues:
        for issue in issues:
            print(f"CANON: {issue}")
        return 1
    print(f"CANON: {sum(len(canon.by_family(f)) for f in CANON_FAMILIES)} rules OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
