"""HEVI P5.1/P5.2 — mutation-test worktree safety.

A guard is only worth having if the machinery around it is safe. The
architecture guards in ``test_p5_2_architecture.py`` are mutation-tested: the
code is broken on purpose to prove they notice. Doing that in the working tree
and undoing it with ``git checkout`` is how uncommitted work gets destroyed —
including the mutation author's, which is exactly what happened once while
these guards were being written.

These tests make that failure mode impossible rather than merely discouraged:

* a sentinel uncommitted modification is created, the mutation harness runs, and
  the sentinel must be byte-identical afterwards;
* no test or script in the repository may invoke a destructive git command;
* the mutation harness is proven to be able to catch a real violation, so
  "nothing broke" cannot be confused with "nothing was checked".
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

import pytest

from tests.p5_2_mutation_harness import (
    REPO_ROOT_ENV,
    isolated_mutation,
    live_source,
    repo_root,
)

#: Commands that can destroy uncommitted work. Matched against both the argv-list
#: form (``["git", "checkout", ...]``) and the shell form (``git checkout``).
DESTRUCTIVE_GIT = (
    "checkout", "reset", "clean", "restore", "stash", "switch", "worktree",
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_calls(source: str) -> set[str]:
    """Git subcommands the code could actually execute.

    Parsed rather than pattern-matched. A regex over the raw text also matches
    prose — this file's own docstring says "git checkout", and a guard that
    fails on its own documentation is a guard that gets deleted rather than
    fixed. Only two shapes count: the literal ``"git", "<subcommand>"`` argv
    list, and a ``"git <subcommand> ..."`` string handed to a shell.
    """
    import ast

    found: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return found

    shell_calls = {"run", "Popen", "check_output", "check_call", "call", "system"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        # The argv is usually a list *literal*, so the constants have to be
        # gathered recursively. Collecting only direct Constant args silently
        # misses every real call -- which is exactly how the first version of this
        # guard passed a test that genuinely called `git checkout`.
        argv: list[str] = []
        for element in list(node.args) + [k.value for k in node.keywords]:
            for node_in in ast.walk(element):
                if (
                    isinstance(node_in, ast.Constant)
                    and isinstance(node_in.value, str)
                ):
                    argv.append(node_in.value)
        # argv-list form: a literal "git" followed by a literal subcommand.
        if "git" in argv:
            index = argv.index("git")
            if index + 1 < len(argv) and re.fullmatch(r"[a-z-]+", argv[index + 1]):
                found.add(argv[index + 1])
        # shell form: only counted when it is actually handed to a shell.
        if name in shell_calls:
            for value in argv:
                match = re.match(r"\s*git\s+([a-z-]+)", value)
                if match:
                    found.add(match.group(1))
    return found


# ── The harness cannot touch the working tree ────────────────────────────


def test_a_mutation_run_leaves_an_uncommitted_sentinel_untouched(tmp_path: Path) -> None:
    """The core safety property, proved on a real uncommitted modification.

    The sentinel is a genuinely uncommitted change to a tracked file — not a
    scratch file — so this is exactly the situation the destructive procedure used
    to destroy. It is created and removed by writing bytes, never by asking git
    to revert anything.
    """
    sentinel = repo_root() / "hevi" / "ops" / "p5_2_worktree_safety_sentinel.py"
    original_existed = sentinel.exists()
    original = sentinel.read_bytes() if original_existed else b""

    marker = b'"""SENTINEL: uncommitted work that must survive mutation testing."""\n'
    try:
        sentinel.write_bytes(marker)
        before = _digest(sentinel)
        assert sentinel.read_bytes() == marker

        with isolated_mutation(
            {"hevi/ops/p5_1_editable.py": live_source("hevi/ops/p5_1_editable.py")
             + "\n\ndef unapproved_helper():\n    return 1\n"}
        ) as root:
            assert root.is_dir()
            assert root != repo_root(), "the mutation ran against the live tree"
            # The mutation is genuinely present in the copy.
            assert "unapproved_helper" in (
                root / "hevi/ops/p5_1_editable.py"
            ).read_text(encoding="utf-8")

        assert _digest(sentinel) == before, (
            "running a mutation modified an uncommitted file in the working tree"
        )
        assert sentinel.read_bytes() == marker
    finally:
        if original_existed:
            sentinel.write_bytes(original)
        else:
            sentinel.unlink(missing_ok=True)


def test_the_environment_override_is_always_restored() -> None:
    """A leaked override would silently repoint every later check."""
    before = os.environ.get(REPO_ROOT_ENV)
    with isolated_mutation({"hevi/ops/p5_1_editable.py": "# mutated\n"}) as root:
        assert os.environ[REPO_ROOT_ENV] == str(root)
    assert os.environ.get(REPO_ROOT_ENV) == before


def test_the_mutation_copy_is_removed_afterwards() -> None:
    with isolated_mutation({"hevi/ops/p5_1_editable.py": "# mutated\n"}) as root:
        assert root.exists()
    assert not root.exists(), "the isolated copy outlived the mutation"


def test_the_live_tree_is_never_opened_for_writing_by_the_harness() -> None:
    """Structural check: the harness has no write call against a live path.

    Reading the source is a stronger guarantee than trusting a test to notice,
    because it also covers a mutation added later.
    """
    source = live_source("tests/p5_2_mutation_harness.py")
    # Every write in the harness must target a path inside the temporary copy.
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(("#", "*", '"""')) or not stripped:
            continue
        if "write_text" in stripped or "copy2(" in stripped or "copytree(" in stripped:
            assert "copy_root" in stripped or "destination" in stripped, stripped
    # And nothing in the harness can remove a live path.
    assert "rmtree(repo_root" not in source
    assert not re.search(r"unlink\(\s*\)", source)


# ── No destructive git anywhere in the test or script surface ───────────


@pytest.mark.parametrize("subtree", ["tests", "scripts"])
def test_no_test_or_script_runs_a_destructive_git_command(subtree: str) -> None:
    """A permanent guard, so the defect cannot be reintroduced by a later test."""
    root = repo_root() / subtree
    assert root.is_dir(), root
    offenders: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        subcommands = _git_calls(source)
        # ``git worktree list`` and ``git rev-parse`` are read-only; the rest of
        # the destructive set is not, with the single exception of a read-only
        # subcommand sharing a name.
        for name in subcommands & set(DESTRUCTIVE_GIT):
            if name == "worktree" and "list" in source:
                continue
            offenders.append(f"{path.relative_to(repo_root())}: git {name}")
    assert not offenders, (
        "destructive git invocations found in the test/script surface:\n  "
        + "\n  ".join(offenders)
    )


def test_the_git_commands_the_suite_uses_are_all_read_only() -> None:
    """States the allow-list explicitly, so a new command is a visible choice."""
    allowed = {"status", "rev-parse", "diff", "show", "log", "worktree", "ls-files"}
    used: set[str] = set()
    for path in (repo_root() / "tests").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        used |= _git_calls(path.read_text(encoding="utf-8", errors="replace"))
    unexpected = used - allowed
    assert not unexpected, f"unexpected git subcommands in tests: {sorted(unexpected)}"


# ── The harness can actually catch something ────────────────────────────


def test_the_isolated_mutation_really_makes_the_guard_fail() -> None:
    """Safety is worthless if the mutation is not detected in the first place.

    Runs the real authorisation guard against a copy carrying an unapproved
    symbol. If this stops failing, "the working tree was preserved" would be
    vacuous — the guard would not have been exercised at all.
    """
    from tests.test_p5_2_architecture import (
        P51_ALLOWED_NEW_SYMBOLS,
        _top_level_symbols,
    )

    target = "hevi/ops/p5_1_editable.py"
    with isolated_mutation(
        {target: live_source(target) + "\n\ndef unapproved_helper():\n    return 1\n"}
    ) as root:
        mutated = (root / target).read_text(encoding="utf-8")
        live = live_source(target)
        introduced = _top_level_symbols(mutated) - _top_level_symbols(live)
        assert "unapproved_helper" in introduced
        assert not introduced <= P51_ALLOWED_NEW_SYMBOLS, (
            "the guard would not have noticed this violation"
        )

    # And the live file is untouched by having asked that question.
    assert "unapproved_helper" not in live_source(target)


def test_the_harness_can_express_a_violation_without_touching_git() -> None:
    """The whole point: no git call is needed to undo a mutation."""
    with isolated_mutation(
        {"hevi/ops/p5_1_editable.py": "# replaced\n"}
    ) as root:
        assert (root / "hevi/ops/p5_1_editable.py").read_text(encoding="utf-8") == "# replaced\n"
        assert (root / "hevi/ops/p5_1_types.py").is_file(), "context files were not copied"
    # Nothing to clean up because nothing in the live tree was written.
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, check=True, cwd=repo_root(),
    )
    assert "p5_1_editable" not in status.stdout
