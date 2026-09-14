"""Shared, source-based helpers for the 3O v3 architecture gates.

These helpers intentionally do not consume an audit manifest.  The gates resolve
the installed pinned packages and inspect Python source directly.
"""

from __future__ import annotations

import ast
import importlib.util
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEVI = ROOT / "hevi"
CANONICAL = ("obase", "oprim", "oskill", "omodul", "oservi")
PILLARS = {"fingerprint", "decision_trail", "report", "cost"}
PROJECT_PREFIXES = ("hevi_", "inkos_", "digital_human_", "pipeline_lite_", "voicepro_")


@dataclass(frozen=True)
class Source:
    path: Path
    layer: str
    local: bool

    @property
    def rel(self) -> str:
        try:
            return str(self.path.relative_to(ROOT))
        except ValueError:
            return str(self.path)


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def local_sources(layer: str | None = None) -> list[Source]:
    out: list[Source] = []
    for path in HEVI.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        parts = path.relative_to(HEVI).parts
        if layer is None:
            if not set(parts) & set(CANONICAL):
                continue
            found = next((p for p in parts if p in CANONICAL), None)
        else:
            found = layer if layer in parts else None
        if found:
            out.append(Source(path, found, True))
    return sorted(out, key=lambda x: str(x.path))


def package_root(name: str) -> Path | None:
    spec = importlib.util.find_spec(name)
    if spec is None:
        return None
    if spec.submodule_search_locations:
        return Path(next(iter(spec.submodule_search_locations)))
    return Path(spec.origin).parent if spec.origin else None


def canonical_sources(layer: str | None = None) -> list[Source]:
    names = (layer,) if layer else CANONICAL
    out: list[Source] = []
    for name in names:
        root = package_root(name)
        if root is None or not root.exists():
            continue
        out.extend(
            Source(p, name, False) for p in root.rglob("*.py") if "__pycache__" not in p.parts
        )
    return sorted(out, key=lambda x: str(x.path))


def all_sources(layer: str | None = None) -> list[Source]:
    return local_sources(layer) + canonical_sources(layer)


def imported_layers(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in CANONICAL:
                    found.add(root)
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root in CANONICAL:
                found.add(root)
    return found


def import_edges(tree: ast.AST) -> list[tuple[str, str, int]]:
    edges: list[tuple[str, str, int]] = []
    for node in ast.walk(tree):
        module = None
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name
                root = module.split(".")[0]
                if root in CANONICAL:
                    edges.append((root, module, node.lineno))
        elif isinstance(node, ast.ImportFrom) and node.module:
            module = node.module
            root = module.split(".")[0]
            if root in CANONICAL:
                edges.append((root, module, node.lineno))
            elif root == "hevi":
                target = next((part for part in module.split(".") if part in CANONICAL), None)
                if target:
                    edges.append((target, module, node.lineno))
    return edges


def defined_functions(tree: ast.AST) -> Iterable[ast.FunctionDef | ast.AsyncFunctionDef]:
    return (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))


def has_real_implementation(tree: ast.Module) -> bool:
    """Whether a local namespace file contains code rather than a compatibility shim."""
    imported_names: set[str] = set()
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            imported_names.update(
                alias.asname or alias.name.split(".")[-1] for alias in statement.names
            )
        elif isinstance(statement, ast.ImportFrom):
            imported_names.update(alias.asname or alias.name for alias in statement.names)

    def is_delegate(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        body = list(node.body)
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body.pop(0)
        if body and isinstance(body[0], (ast.Import, ast.ImportFrom)):
            body.pop(0)
        if (
            len(body) != 1
            or not isinstance(body[0], ast.Return)
            or not isinstance(body[0].value, ast.Call)
        ):
            return False
        call = body[0].value
        return isinstance(call.func, ast.Name) and call.func.id in imported_names

    def is_module_alias(node: ast.Assign) -> bool:
        """Recognize a pure module identity alias used by compatibility paths."""
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Subscript):
            return False
        target = node.targets[0]
        if not (
            isinstance(target.value, ast.Attribute) and isinstance(target.value.value, ast.Name)
        ):
            return False
        if target.value.value.id != "sys" or target.value.attr != "modules":
            return False
        value = node.value
        return (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and isinstance(value.func.value, ast.Name)
            and value.func.value.id == "importlib"
            and value.func.attr == "import_module"
            and len(value.args) == 1
            and isinstance(value.args[0], ast.Constant)
        )

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and is_delegate(node):
                continue
            return True
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            # __all__ and direct imported aliases are shim metadata.
            if isinstance(node, ast.Assign) and is_module_alias(node):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not all(
                isinstance(t, ast.Name)
                and t.id in {"__all__", "__version__", "__3o_compatibility__"}
                for t in targets
            ):
                return True
        if isinstance(node, ast.Expr) and not (
            isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        ):
            return True
    return False


def public_functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        n
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_")
    ]


def call_names(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.append(node.func.attr)
    return names


def json_ready(items: list[str]) -> list[str]:
    return sorted(set(items))
