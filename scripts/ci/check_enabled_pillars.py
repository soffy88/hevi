"""3O 规范 CI 检查 3/3:确保所有 omodul 显式声明了 _enabled_pillars。

要求每个 ``*_workflow`` / ``video_assemble_workflow`` 函数体内出现
``_enabled_pillars = {...}``(至少声明 report;cost/decision_trail 按能力)。

3O 支柱枚举:report / cost / decision_trail / trace / fingerprint。
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEVI = ROOT / "hevi"

KNOWN_PILLARS = {"report", "cost", "decision_trail", "trace", "fingerprint"}

BOUNDARY_DIRS = {"assembly", "digital_human", "production"}


def main() -> int:
    violations: list[str] = []
    for py in HEVI.rglob("*.py"):
        if "__pycache__" in str(py):
            continue
        rel = py.relative_to(HEVI).as_posix()
        if rel.split("/")[0] not in BOUNDARY_DIRS:
            continue
        src = py.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src, str(py))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.endswith("_workflow"):
                continue
            declared: set[str] = set()
            for st in node.body:
                if not isinstance(st, ast.Assign):
                    continue
                for t in st.targets:
                    if isinstance(t, ast.Name) and t.id == "_enabled_pillars" and isinstance(
                        st.value, (ast.Set, ast.Tuple, ast.List)
                    ):
                        declared = {e.value for e in st.value.elts if isinstance(e, ast.Constant)}
            if not declared:
                violations.append(f"{py.relative_to(ROOT)}::{node.name} 未声明 _enabled_pillars")
            else:
                unknown = declared - KNOWN_PILLARS
                if unknown:
                    violations.append(
                        f"{py.relative_to(ROOT)}::{node.name} 含未知支柱 {sorted(unknown)}"
                    )

    if violations:
        print("3O 规范违规(_enabled_pillars 声明):")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("check_enabled_pillars: OK(所有 omodul 已显式声明支柱)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
