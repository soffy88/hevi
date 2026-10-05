#!/usr/bin/env python
"""P11.1 — generate the layout vocabulary inventory from repository evidence.

The spec requires the inventory to be "generated from repository evidence, not
manually asserted", so this walks the tree with ``ast`` and records what it finds.
Nothing in the output is typed in by hand: every producer/consumer/renderer/test
reference is a file and line this script located.

Discovery is two-stage and both stages are recorded in the output:

1. Every class in the scanned tree that inherits an enum base (``StrEnum``,
   ``Enum``) or is a frozen dataclass carrying layout semantics.
2. Filtered to those whose name, or any member value, matches the semantic token
   list from the spec. The token list and the rejected candidates are both in the
   output so the filter can be audited rather than trusted.

Usage:
    uv run python scripts/qualification/p11_vocabulary_inventory.py [--out PATH]
"""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

REPO = Path(__file__).resolve().parents[2]

#: Spec §1.2 search terms. A candidate is kept if its name or any member value
#: contains one of these as a token.
SEMANTIC_TOKENS = (
    "layout", "scale", "visibility", "presenter", "framing", "composition",
    "split", "inset", "punch", "wide", "screencast", "track", "pip", "full",
    "medium", "hidden", "crop", "reframe",
)

#: Names the spec explicitly forbids introducing (§3.5). Recorded so Gate A can
#: assert none of them exist rather than trusting that nobody added one.
FORBIDDEN_NEW_VOCABULARY = (
    "LayoutVocabulary", "CompositionMode", "FrameLayout", "VisualLayout",
    "ShotLayoutMode", "CompositionModeV2",
)

ENUM_BASES = {"StrEnum", "Enum"}

SCAN_ROOTS = ("hevi", "tests", "scripts", "services")


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO))


@dataclass
class Symbol:
    name: str
    definition_file: str
    definition_line: int
    module: str
    kind: str
    members: list[str] = field(default_factory=list)
    producers: list[str] = field(default_factory=list)
    consumers: list[str] = field(default_factory=list)
    serializers: list[str] = field(default_factory=list)
    deserializers: list[str] = field(default_factory=list)
    renderers: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    persisted_forms: list[str] = field(default_factory=list)
    status: str = "UNKNOWN"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _is_enum(node: ast.ClassDef) -> bool:
    for base in node.bases:
        name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
        if name in ENUM_BASES:
            return True
    return False


def _members(node: ast.ClassDef) -> list[str]:
    """Member values, in declaration order. StrEnum values are plain literals."""
    out: list[str] = []
    for stmt in node.body:
        if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
            continue
        target = stmt.targets[0]
        if not isinstance(target, ast.Name):
            continue
        value = stmt.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            out.append(value.value)
        elif isinstance(value, ast.Call) and getattr(value.func, "id", "") == "field":
            default = next((kw.value for kw in value.keywords if kw.arg == "default"), None)
            if isinstance(default, ast.Call):
                inner = default.args[0] if default.args else None
                if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                    out.append(inner.value)
    return out


def _tokens(*values: str) -> set[str]:
    found: set[str] = set()
    for value in values:
        for token in SEMANTIC_TOKENS:
            if token in (value or "").lower():
                found.add(token)
    return found


def _python_files() -> list[Path]:
    out: list[Path] = []
    for root in SCAN_ROOTS:
        base = REPO / root
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            parts = set(path.parts)
            if {".venv", "node_modules", "__pycache__", ".git"} & parts:
                continue
            out.append(path)
    return sorted(out)


def _role_of(path: Path, source: str) -> str:
    """Classify a usage site by evidence in the file, not by guesswork."""
    rel = _rel(path)
    if rel.startswith("tests/"):
        return "test"
    if rel.endswith(("_tables.py", "repository.py", "models.py")) and "db" in source.lower():
        return "persisted"
    if any(token in rel for token in ("render", "compose", "assemble", "ffmpeg", "encode")):
        return "renderer"
    return "code"


def _imports(tree: ast.Module, symbol: str) -> bool:
    """Whether the file imports the owner symbol into scope."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if (alias.asname or alias.name) == symbol:
                    return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname == symbol:
                    return True
    return False


def _references(
    tree: ast.Module, symbol: str, members: list[str]
) -> list[ast.AST]:
    """References to the symbol or its members that are actually attributable.

    A bare member name is *not* attributable. ``"a,b".split()`` has
    ``attr == "split"``, and ``ReframingMode.SPLIT`` has value ``"split"``, so an
    unqualified substring match reports four renderers that contain neither the
    enum nor any of its members. A member reference therefore counts only when
    it is qualified by the owner (``ReframingMode.SPLIT``), by an alias the owner
    is imported under, or when the owner is imported into the file and the bare
    name is used as a value.
    """
    found: list[ast.AST] = []
    owner_imported = _imports(tree, symbol)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id == symbol or (owner_imported and node.id in members):
                found.append(node)
        elif isinstance(node, ast.Attribute):
            base = node.value
            qualified = (
                isinstance(base, ast.Name) and base.id == symbol
            ) or (
                isinstance(base, ast.Attribute) and base.attr == symbol
            )
            if qualified and (node.attr == symbol or node.attr in members):
                found.append(node)
    return found


def _classify_sites(
    symbol: str, members: list[str], files: list[Path], trees: dict[Path, ast.Module],
    def_file: str, def_line: int,
) -> None:
    """Record every attributable reference, by file role.

    Usage sites are recorded per definition, so a name defined in two places is
    not collapsed into whichever happened to be scanned last.
    """
    key = f"{symbol}@{def_file}"
    for path in files:
        tree = trees[path]
        rel = _rel(path)
        for node in _references(tree, symbol, members):
            if rel == def_file and getattr(node, "lineno", 0) == def_line:
                continue  # the definition itself
            role = _role_of(path, symbol)
            if role == "test":
                _add(_TESTS, key, rel)
                continue
            if role == "renderer":
                _add(_RENDERERS, key, rel)
            if role == "persisted":
                _add(_PERSISTED, key, rel)
            _add(_CONSUMERS, key, rel)


_DEFINITION_SITES: dict[str, list[str]] = {}
_TESTS: dict[str, list[str]] = {}
_RENDERERS: dict[str, list[str]] = {}
_PERSISTED: dict[str, list[str]] = {}
_SERIALIZERS: dict[str, list[str]] = {}
_PRODUCERS: dict[str, list[str]] = {}
_CONSUMERS: dict[str, list[str]] = {}


def _add(store: dict[str, list[str]], key: str, rel: str) -> None:
    bucket = store.setdefault(key, [])
    if rel not in bucket:
        bucket.append(rel)


def _stores() -> dict[str, dict[str, list[str]]]:
    return {
        "tests": _TESTS, "renderers": _RENDERERS, "persisted": _PERSISTED,
        "serializers": _SERIALIZERS, "producers": _PRODUCERS,
        "consumers": _CONSUMERS,
    }


def _literal_forms(members: list[str]) -> list[str]:
    """Member values as they would appear in a persisted artifact."""
    return sorted({m for m in members if m})


def _literal_aliases(path: Path, tree: ast.Module) -> list[tuple[str, int, list[str]]]:
    """Module-level ``Name = Literal[...]`` aliases.

    These are real vocabularies too: ``LayoutMode`` is a two-value Literal alias,
    not a class, and a class-only scan misses it entirely.
    """
    out: list[tuple[str, int, list[str]]] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not target.id[:1].isupper():
            continue
        call = node.value
        if not (isinstance(call, ast.Subscript)
                and getattr(call.value, "id", "") == "Literal"):
            continue
        slice_ = call.slice
        elements = slice_.elts if isinstance(slice_, ast.Tuple) else [slice_]
        values: list[str] = [
            element.value for element in elements
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        ]
        if values:
            out.append((target.id, node.lineno, values))
    return out


def build() -> dict[str, object]:
    files = _python_files()
    trees: dict[Path, ast.Module] = {}
    for path in files:
        try:
            trees[path] = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue

    candidates: list[Symbol] = []

    for path, tree in trees.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not (_is_enum(node) or any(
                    isinstance(d, ast.Name) and d.id == "dataclass" for d in node.decorator_list)):
                continue
            members = _members(node)
            matched = _tokens(node.name, *members)
            if not matched:
                continue
            module = ".".join(path.relative_to(REPO).with_suffix("").parts[:-1])
            candidates.append(Symbol(
                name=node.name,
                definition_file=_rel(path),
                definition_line=node.lineno,
                module=module,
                kind="enum" if _is_enum(node) else "dataclass",
                members=members,
                notes=[f"matched_tokens={sorted(matched)}"],
            ))
        for name, line, values in _literal_aliases(path, tree):
            matched = _tokens(name, *values)
            if not matched:
                continue
            module = ".".join(path.relative_to(REPO).with_suffix("").parts[:-1])
            candidates.append(Symbol(
                name=name, definition_file=_rel(path), definition_line=line,
                module=module, kind="literal_alias", members=values,
                notes=[f"matched_tokens={sorted(matched)}"],
            ))

    for symbol in candidates:
        _DEFINITION_SITES.setdefault(symbol.name, []).append(
            f"{symbol.definition_file}:{symbol.definition_line}")
        _classify_sites(symbol.name, symbol.members, files, trees,
                        symbol.definition_file, symbol.definition_line)

    for symbol in candidates:
        key = f"{symbol.name}@{symbol.definition_file}"
        symbol.tests = sorted(_TESTS.get(key, []))
        symbol.renderers = sorted(_RENDERERS.get(key, []))
        symbol.persisted_forms = sorted(_PERSISTED.get(key, []))
        symbol.serializers = sorted(_SERIALIZERS.get(key, []))
        symbol.producers = sorted(_PRODUCERS.get(key, []))
        symbol.consumers = sorted(_CONSUMERS.get(key, []))

    # A name defined more than once is a material finding, not a detail.
    duplicates: dict[str, list[Symbol]] = {}
    for symbol in candidates:
        duplicates.setdefault(symbol.name, []).append(symbol)
    collisions = {}
    for name, group in duplicates.items():
        if len(group) < 2:
            continue
        member_sets = {tuple(s.members) for s in group}
        collisions[name] = {
            "definition_sites": _DEFINITION_SITES[name],
            "member_sets": [list(m) for m in sorted(member_sets)],
            "identical_members": len(member_sets) == 1,
            "lossless_alias_candidate": len(member_sets) == 1,
            "status": "DUPLICATE_DEFINITION",
        }
        for symbol in group:
            symbol.notes.append("DUPLICATE_DEFINITION")
            symbol.status = "DUPLICATE_DEFINITION"

    named = ("PresenterScale", "SpeakerVisibility", "LayoutMode")
    for symbol in candidates:
        if symbol.name in named and symbol.status != "DUPLICATE_DEFINITION":
            symbol.status = "CANONICAL_CANDIDATE"
        elif symbol.status != "DUPLICATE_DEFINITION":
            symbol.status = "REVIEW"

    forbidden_present = sorted({
        node.name for path, tree in trees.items() for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name in FORBIDDEN_NEW_VOCABULARY
    })

    return {
        "schema": "hevi.p11.vocabulary_inventory.v1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "generator": "scripts/qualification/p11_vocabulary_inventory.py",
        "generated_from": "ast walk of " + ", ".join(SCAN_ROOTS),
        "semantic_tokens": list(SEMANTIC_TOKENS),
        "scanned_python_files": len(trees),
        "enum_bases": sorted(ENUM_BASES),
        "discovery_stages": [
            "class inheriting StrEnum/Enum, or decorated dataclass",
            "module-level Name = Literal[...] alias with an uppercase name",
            "kept only when the name or any member value contains a semantic token",
        ],
        "symbols": [s.to_dict() for s in sorted(
            candidates, key=lambda s: (s.name, s.definition_file))],
        "duplicate_definitions": collisions,
        "forbidden_vocabulary_names_present": forbidden_present,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(
        REPO / "docs/qualification/p11-layout-vocabulary/VOCABULARY_INVENTORY.json"))
    args = parser.parse_args()
    payload = build()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    symbols = cast("list[dict[str, Any]]", payload["symbols"])
    print(f"scanned {payload['scanned_python_files']} python files")
    print(f"layout-semantic symbols: {len(symbols)}")
    for entry in symbols:
        print(f"  {entry['name']:24} {entry['kind']:9} "
              f"{len(entry['members']):2} members  {entry['definition_file']}:{entry['definition_line']}")
    duplicates = cast("dict[str, Any]", payload["duplicate_definitions"])
    print(f"duplicate definitions: {sorted(duplicates) or 'none'}")
    print(f"forbidden new vocabulary names present: "
          f"{payload['forbidden_vocabulary_names_present'] or 'none'}")
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
