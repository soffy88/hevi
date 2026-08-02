"""3O 规范 CI 检查 1/3:确保 oprim 与 omodul 无"裸调同级"现象。

规则(hevi 项目层):
  - omodul 编排层模块(位于 hevi/assembly、hevi/digital_human 等 3O 边界目录)
    不得在同一模块顶层同时 import oprim 原语与 omodul workflow —— 这会让编排层
    裸调同级原语,绕过 Layer 0-3 分层。
  - Layer 4 编排发起点(hevi/pipeline/longvideo_orchestrator.py 等)允许同时
    引用 oprim/omodul(它是唯一合法的跨层边界),列入 allowlist。

退出码:0 = 通过;1 = 违规(打印违规清单)。
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # repo root
HEVI = ROOT / "hevi"

# Layer 4 编排发起点(合法跨层边界):文件相对路径(相对 hevi/)。
ALLOWLIST = {
    "pipeline/longvideo_orchestrator.py",
    "tasks/task_service.py",
    "api/main.py",
    "providers/registry.py",
}

# 3O 边界目录(omodul 编排层落点) —— 此处禁止模块级同时裸调 oprim+omodul。
BOUNDARY_DIRS = {"assembly", "digital_human", "production"}


def main() -> int:
    violations: list[str] = []
    for py in HEVI.rglob("*.py"):
        if "__pycache__" in str(py):
            continue
        rel = py.relative_to(HEVI).as_posix()
        top = rel.split("/")[0]
        if top not in BOUNDARY_DIRS:
            continue
        if rel in ALLOWLIST:
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"), str(py))
        except SyntaxError:
            continue
        uses_oprim = uses_omodul = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod.startswith("oprim"):
                    uses_oprim = True
                if mod.startswith("omodul"):
                    uses_omodul = True
        if uses_oprim and uses_omodul:
            violations.append(rel)

    if violations:
        print("3O 规范违规:以下 3O 边界模块同时裸调 oprim 与 omodul(应经 obase/编排层):")
        for v in violations:
            print(f"  - hevi/{v}")
        return 1
    print("check_no_sibling_call: OK(3O 边界无裸调同级)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
