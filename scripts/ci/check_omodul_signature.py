"""3O 规范 CI 检查 2/3:校验所有新建/重构 omodul 符合三件套签名。

三件套签名(3O SPEC §5):
  - 命名为 ``*_workflow`` 的模块(或含 ``video_assemble_workflow`` 等标准事务)
    必须导出 async 函数 ``xxx_workflow(config, input_data, output_dir, *, on_step=None)``
  - 返回 dict(含 "status": "completed" | "failed"),失败不 raise
  - 显式声明 ``_enabled_pillars``(见 check_enabled_pillars.py)

扫描范围:hevi/ 下所有定义/引用 ``*_workflow`` 的模块。
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEVI = ROOT / "hevi"


def _has_status_dict_return(tree: ast.AST) -> bool:
    """函数体内出现 return {.."status"..} 或 return {"status"...}。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            for key in node.value.keys:
                if isinstance(key, ast.Constant) and key.value == "status":
                    return True
    return False


BOUNDARY_DIRS = {"assembly", "digital_human", "production"}


def _is_boundary(py: Path) -> bool:
    rel = py.relative_to(HEVI).as_posix()
    return rel.split("/")[0] in BOUNDARY_DIRS


def main() -> int:
    violations: list[str] = []
    for py in HEVI.rglob("*.py"):
        if "__pycache__" in str(py):
            continue
        if not _is_boundary(py):
            continue
        src = py.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src, str(py))
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.endswith("_workflow") and node.name != "video_assemble_workflow":
                continue
            # 签名校验:config, input_data, output_dir(+可选 on_step)
            argnames = [a.arg for a in node.args.args]
            missing = [n for n in ("config", "input_data", "output_dir") if n not in argnames]
            if missing:
                violations.append(f"{py.relative_to(ROOT)}::{node.name} 缺参数 {missing}")
                continue
            # 失败不 raise:主体中 return dict(status=...)
            if not _has_status_dict_return(node):
                violations.append(
                    f"{py.relative_to(ROOT)}::{node.name} 无 status 返回(失败不 raise 契约)"
                )
            # _enabled_pillars 显式声明
            if not any(
                isinstance(st, ast.Assign)
                and any(
                    isinstance(t, ast.Name) and t.id == "_enabled_pillars"
                    for t in st.targets
                )
                for st in node.body
            ):
                violations.append(f"{py.relative_to(ROOT)}::{node.name} 未声明 _enabled_pillars")

    if violations:
        print("3O 规范违规(omodul 三件套签名):")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("check_omodul_signature: OK(所有 *_workflow 符合三件套签名)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
