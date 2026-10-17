#!/usr/bin/env python3
"""Lint the changed package **and its dependency surface**.

Why this exists
---------------
P8.4 shipped a duplicate ``ValidationCheck`` import inside ``hevi/artifact/`` that
survived every check, because lint was scoped to "packages I own" and
``hevi/artifact/`` was one of them. Scoping lint to your own work is what hid it: the
defect was *in* the scoped set, and the scope was chosen to exclude the rest of the
repository — including the places a change actually propagates to.

So scope is now derived, not chosen:

1. every package containing a changed file
2. every package that imports one of those
3. every package imported by one of those

That is the transitive closure, and it is what a change can actually break.

Usage:
    python scripts/ci/check_lint_scope.py [--base REF] [--quiet]

Exits non-zero when lint or type errors appear in the computed scope.
"""

from __future__ import annotations

import argparse
import ast
import os
import pathlib
import subprocess
import sys
import warnings

REPO = pathlib.Path(__file__).resolve().parents[2]
HEVI = REPO / "hevi"
DIRTY_ONLY = pathlib.Path("hevi/ops")


def _run(cmd: list[str]) -> str:
    env = dict(os.environ, MYPYPATH=str(REPO))
    result = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, env=env)
    return result.stdout + result.stderr


def _package_of(path: pathlib.Path) -> str | None:
    """The importable package a file belongs to.

    Walks down from the first path component for as long as the directory is itself a
    package, so ``hevi/execution/execute.py`` resolves to ``execution`` and not to
    ``execution/execute.py`` — which is what an earlier version returned, and which
    then matched no directory on disk.
    """
    parts = path.parts
    if len(parts) < 2 or parts[0] != "hevi":
        return None
    candidate = parts[1]
    for depth in range(2, len(parts)):
        nested = "/".join(parts[1:depth])
        if (HEVI / nested / "__init__.py").exists():
            candidate = nested
    return candidate


def changed_packages(base: str | None) -> set[str]:
    """Packages holding a changed file."""
    if base:
        diff = _run(["git", "diff", "--name-only", base])
        if not diff.strip():
            diff = _run(["git", "diff", "--name-only", "HEAD"])
    else:
        diff = _run(["git", "status", "--porcelain"])
    packages: set[str] = set()
    for line in diff.splitlines():
        path = line.split()[-1] if line.strip() else ""
        if not path.startswith("hevi/"):
            continue
        package = _package_of(pathlib.Path(path))
        if package:
            packages.add(package)
    return packages


def _module_imports(path: pathlib.Path) -> set[str]:
    try:
        with warnings.catch_warnings():
            # a SyntaxWarning in an unrelated file must not abort the closure walk
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(path.read_text())
    except (SyntaxError, ValueError):
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("hevi."):
            found.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("hevi."):
                    found.add(alias.name)
    return found


def _top_package(module: str) -> str | None:
    """A dotted module path as a slash-separated package path.

    Both sides of the graph must speak the same language: seeds come from file paths
    (``production/p5_3``) and targets come from imports (``hevi.production.p5_3``).
    Mixed formats silently produce an empty closure.
    """
    parts = module.split(".")
    if len(parts) < 2 or parts[0] != "hevi":
        return None
    return parts[1] if len(parts) == 2 else "/".join(parts[1:3])


def dependency_closure(seeds: set[str]) -> set[str]:
    """Every hevi package reachable from ``seeds``, in either direction."""
    graph: dict[str, set[str]] = {}
    for path in HEVI.rglob("*.py"):
        owner = "/".join(path.relative_to(REPO).with_suffix("").parts[:-1]).rstrip(".")
        if not owner:
            continue
        graph.setdefault(owner, set())
        for module in _module_imports(path):
            target = _top_package(module)
            if target:
                graph[owner].add(target)

    closure = set(seeds)
    frontier = set(seeds)
    while frontier:
        nxt: set[str] = set()
        for owner, targets in graph.items():
            if owner in frontier:
                nxt |= targets
            elif targets & frontier:
                nxt.add(owner)
        nxt -= closure
        nxt = {p for p in nxt if p in graph or p in seeds}
        closure |= nxt
        frontier = nxt
    return closure


def lint_targets(packages: set[str]) -> list[pathlib.Path]:
    targets = [HEVI / package for package in sorted(packages)]
    return [t for t in targets if t.exists()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="git ref to diff against, e.g. main")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    changed = changed_packages(args.base)
    if not changed:
        print("lint-scope: no changed hevi packages detected")
        return 0

    scope = dependency_closure(changed)
    if not args.quiet:
        print(f"lint-scope: changed packages  {sorted(changed)}")
        print(f"lint-scope: with dependencies {sorted(scope)}")

    targets = lint_targets(scope)
    if not targets:
        print("lint-scope: nothing to lint")
        return 0

    # Collapse nested packages to their top-level directory: mypy resolves modules
    # relative to the given roots, and passing hevi/production/p5_3 makes it treat
    # p5_3 as a top-level package.
    tops: set[str] = set()
    for t in targets:
        tops.add(str(t.relative_to(REPO)).split("/")[0])
    rel = sorted(tops)
    failures = 0
    for label, cmd in (
        ("ruff", [".venv/bin/ruff", "check", *rel]),
        # CI runs `mypy --strict hevi`; scoping to subdirectories needs the package
        # bases made explicit or mypy cannot resolve nested packages.
        ("mypy", [".venv/bin/mypy", "--strict", "--explicit-package-bases", *rel]),
    ):
        out = _run(cmd)
        if out.strip() and "Success" not in out:
            failures += 1
            print(f"\nlint-scope: {label} reported problems in scope:\n{out}")
    if failures == 0:
        print(f"lint-scope: clean across {len(rel)} packages")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
