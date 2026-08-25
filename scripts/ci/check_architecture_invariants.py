# ruff: noqa: PERF401
"""Fail CI when production code reintroduces architecture-contract violations.

The RFC in docs/Hevi_10分完整架构升级方案_v1.0 lists the invariants that keep
Hevi a single production runtime rather than a pile of workflows. This checker
is deliberately syntactic: it catches regressions at review time instead of
waiting for a multi-instance incident.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEVI = ROOT / "hevi"
ROUTERS = HEVI / "api" / "routers"

FORBIDDEN_STATE_NAMES = {"_WORKS", "_RUNS", "_TASKS", "_SESSIONS"}
ALLOWED_LOCAL_PROJECTIONS = {"_LOCAL_WORK_PROJECTIONS"}
FORBIDDEN_ROUTER_MODULES = {
    "fal_client",
    "openai",
    "anthropic",
    "dashscope",
    "google.generativeai",
}
BILLABLE_ADD_TASK = {"run_task", "run_task_background", "orchestrate_longvideo"}
HARDCODED_BALANCE = re.compile(r"唯一有余额|本机当前唯一有余额|唯一有钱")
REVISION_MUTATION = re.compile(
    r"UPDATE\s+production_revisions[\s\S]{0,200}snapshot_json\s*=",
    re.IGNORECASE,
)


def _module_assigns(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.append(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.append(node.target.id)
    return names


def _imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
            modules.add(node.module)
    return modules


def _add_task_callees(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "add_task" and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Name):
                names.append(arg.id)
            elif isinstance(arg, ast.Attribute):
                names.append(arg.attr)
    return names


def main() -> int:
    violations: list[str] = []

    for path in ROUTERS.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, str(path))
        rel = path.relative_to(ROOT)
        for name in _module_assigns(tree):
            if name in FORBIDDEN_STATE_NAMES:
                violations.append(f"{rel}: process-level durable state {name}")
            if name.endswith("_WORKS") and name not in ALLOWED_LOCAL_PROJECTIONS:
                violations.append(f"{rel}: process-level work map {name}")
        imported = _imported_modules(tree)
        for module in sorted(FORBIDDEN_ROUTER_MODULES & imported):
            violations.append(f"{rel}: router imports provider SDK {module}")
        for callee in _add_task_callees(tree):
            if callee in BILLABLE_ADD_TASK:
                violations.append(
                    f"{rel}: BackgroundTasks schedules billable {callee}"
                )

    for path in HEVI.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        if path.parent == HEVI / "provider_policy" and HARDCODED_BALANCE.search(text):
            violations.append(f"{rel}: hardcoded account-balance policy")
        if REVISION_MUTATION.search(text):
            violations.append(f"{rel}: locked revision mutated in place")

    compiler = (HEVI / "constraints" / "compiler.py").read_text(encoding="utf-8")
    if "silent_drops" not in compiler:
        violations.append("hevi/constraints/compiler.py: required silent_drops tracking missing")

    if violations:
        print("architecture invariant violations:")
        for item in violations:
            print(f"  - {item}")
        return 1
    print("check_architecture_invariants: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
