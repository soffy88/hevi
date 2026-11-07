"""Catalogue-completeness guard (S-01): the G13 leak pattern must not recur.

Every module under ``hevi/capabilities/`` that defines a
``register_*_capabilities*`` function and constructs ``Capability``
objects inside it must be reachable from ``import hevi.capabilities``
alone — i.e. ``hevi/capabilities/__init__.py`` must import it.  The
check runs in a fresh subprocess so test-process imports (conftest,
other test modules importing a capability submodule directly) cannot
mask a missing ``__init__`` import: the subprocess imports only the
package, then lists names.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

import hevi.capabilities as caps

ROOT = Path(__file__).resolve().parents[1]
CAP_DIR = ROOT / "hevi" / "capabilities"

# The 14 capabilities the paradigm-normalization stage wired in.
PARADIGM_NAMES = [
    "story.shot_chain",
    "story.reference_bundle",
    "story.canvas_workflow",
    "story.novel_import",
    "story.narration_srt",
    "story.season_bible",
    "story.season_arc",
    "story.episode_prompts",
    "story.drama_gates",
    "story.reference_decompose",
    "story.edit_assemble",
    "story.model_test",
    "story.script_polish",
    "video.blender_mcp",
]


def _expected_names() -> set[str]:
    """Capability names constructed inside register_* functions (AST)."""
    expected: set[str] = set()
    for path in sorted(CAP_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not (
                node.name.startswith("register_")
                and "capabilit" in node.name
            ):
                continue
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call):
                    continue
                func = sub.func
                if not (isinstance(func, ast.Name) and func.id == "Capability"):
                    continue
                for kw in sub.keywords:
                    if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                        if isinstance(kw.value.value, str):
                            expected.add(kw.value.value)
    return expected


def test_paradigm_names_registered_on_package_import() -> None:
    names = set(caps.names())
    missing = [n for n in PARADIGM_NAMES if n not in names]
    assert not missing, f"capabilities missing after import hevi.capabilities: {missing}"


def test_every_self_registering_module_is_wired_in_subprocess() -> None:
    expected = _expected_names()
    assert expected, "AST scan found no Capability constructions; scan is broken"
    code = (
        "import json, hevi.capabilities as c; "
        "print(json.dumps(sorted(c.names())))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, f"subprocess import failed: {proc.stderr[-2000:]}"
    actual = set(json.loads(proc.stdout.strip().splitlines()[-1]))
    missing = sorted(expected - actual)
    assert not missing, (
        "self-registering modules NOT wired into hevi/capabilities/__init__.py "
        f"(import hevi.capabilities misses them): {missing}"
    )
