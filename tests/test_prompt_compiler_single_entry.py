"""Single canonical generation-ready ``compile_shot_prompt`` (audit fix 9).

The honest state at HEAD, enforced here so it cannot silently
regress:

* exactly one canonical generation-ready implementation:
  ``hevi/capabilities/prompt_compiler.py``;
* one separate kids Style-Bible preamble renderer of the same
  name (``hevi/kids/prompt_compile.py``) -- a different contract
  (manifest + Style Bible), not a generation-ready compiler;
* one LEGACY storyboard-table renderer of the same name
  (``hevi/avcraft/oskill/shotprompt.py``) -- untracked in HEAD,
  wired into ``sequence_plan``/``storyboard_enrich``, already
  LEGACY-marked; when it is present on disk it must stay marked,
  and it must not be swept into a HEAD commit by this line.
  Tracking it, delegating it to the canonical implementation,
  or deleting it is a separate decision for its owner, not a
  side effect of a prompt-audit commit.

No fourth ``def compile_shot_prompt`` may appear anywhere under
``hevi/``. The audit's literal "only one def in the whole repo"
cannot hold while the kids renderer exists; this test enforces
the achievable form: one canonical entry, named exceptions, no
new duplicates.
"""

from __future__ import annotations

import ast
import warnings
from pathlib import Path

from hevi.capabilities import prompt_compiler as canonical

_CANONICAL = Path(canonical.__file__).resolve()
_REPO = _CANONICAL.parents[2]
_ALLOWED = {
    "hevi/capabilities/prompt_compiler.py",
    "hevi/kids/prompt_compile.py",
    "hevi/avcraft/oskill/shotprompt.py",
}


def _definitions() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in sorted((_REPO / "hevi").rglob("*.py")):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "compile_shot_prompt":
                rel = str(path.resolve().relative_to(_REPO))
                found[rel] = path
    return found


def _docstring(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "compile_shot_prompt":
            return ast.get_docstring(node) or ""
    return ""


def test_canonical_compile_shot_prompt_is_the_generation_ready_entry() -> None:
    assert "canonical generation-ready" in canonical.compile_shot_prompt.__doc__
    assert "hevi/capabilities/prompt_compiler.py" in str(_CANONICAL)


def test_no_fourth_compile_shot_prompt_definition() -> None:
    found = _definitions()
    assert "hevi/capabilities/prompt_compiler.py" in found
    assert set(found) <= _ALLOWED, sorted(set(found) - _ALLOWED)


def test_kids_renderer_is_a_separate_style_bible_contract() -> None:
    path = _REPO / "hevi/kids/prompt_compile.py"
    if not path.is_file():
        return
    doc = _docstring(path)
    assert "Style Bible" in doc


def test_avcraft_renderer_stays_legacy_when_present() -> None:
    path = _REPO / "hevi/avcraft/oskill/shotprompt.py"
    if not path.is_file():
        # Untracked in HEAD: nothing to mark, nothing to sweep in.
        return
    assert "LEGACY" in _docstring(path)
    assert "LEGACY" in path.read_text(encoding="utf-8").split('"""')[1]


def test_avcraft_call_chain_still_uses_its_own_renderer_when_present() -> None:
    # sequence_plan / storyboard_enrich keep calling the avcraft
    # renderer; this line does not rewire them. When the files
    # are absent (not in HEAD), there is no chain to check.
    for name in ("sequence_plan.py", "storyboard_enrich.py"):
        path = _REPO / "hevi/avcraft/omodul" / name
        if path.is_file():
            assert "compile_shot_prompt" in path.read_text(encoding="utf-8")
