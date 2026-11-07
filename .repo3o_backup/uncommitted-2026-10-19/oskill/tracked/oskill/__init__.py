"""Oskill — Composite financial analysis workflows built on oprim atomic operations. Lazy-loaded."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from typing import Any

from oskill._version import __version__

_ELEMENT_MAP: dict[str, str] = {}
_SUBMODULE_SET: set[str] = set()


def _build_element_map() -> None:
    pkg_dir = Path(__file__).parent
    pkg_name = __package__ or "oskill"
    for py in sorted(pkg_dir.rglob("*.py")):
        rel_path = py.relative_to(pkg_dir)
        if rel_path.parts == ("__init__.py",):
            continue
        mod_parts = list(rel_path.with_suffix("").parts)
        if mod_parts[-1] == "__init__":
            mod_parts.pop()
        if not mod_parts:
            continue
        mod_path = pkg_name + "." + ".".join(mod_parts)
        stem = mod_parts[-1]
        _SUBMODULE_SET.add(stem)
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in tree.body:
                names = []
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.append(node.name)
                elif isinstance(node, ast.ImportFrom) and rel_path.name == "__init__.py":
                    for alias in node.names:
                        if alias.name != "*":
                            names.append(alias.asname or alias.name)
                for name in names:
                    if not name.startswith("_"):
                        # Prefer non-prefixed modules; allow overwrite by public
                        if name not in _ELEMENT_MAP or (
                            not mod_path.split(".")[-1].startswith("_")
                            and _ELEMENT_MAP[name].split(".")[-1].startswith("_")
                        ):
                            _ELEMENT_MAP[name] = mod_path
        except Exception:
            continue


_build_element_map()

# 3O Paradigm Phase 3 — 元技能层: protocols/pure_parsers/code_auditor。
# 经 _ELEMENT_MAP 自动发现 + __getattr__ 惰性暴露, 不 eager-load obase。


def __getattr__(name: str) -> Any:
    if name == "__version__":
        return __version__
    if name in _ELEMENT_MAP:
        mod = importlib.import_module(_ELEMENT_MAP[name])
        # Special case for FusedResult/SearchResult aliases in merge_platform_user_results
        actual_name = name
        if name == "MergedFusedResult":
            actual_name = "FusedResult"
        if name == "MergedSearchResult":
            actual_name = "SearchResult"
        return getattr(mod, actual_name)
    if name in _SUBMODULE_SET:
        pkg_name = __package__ or "oskill"
        return importlib.import_module(f"{pkg_name}.{name}")
    raise AttributeError(f"module '{__name__}' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(list(_ELEMENT_MAP.keys()) + list(_SUBMODULE_SET) + ["__version__"]))


__all__ = sorted(_ELEMENT_MAP.keys())
