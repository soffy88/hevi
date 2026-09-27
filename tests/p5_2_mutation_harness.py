"""Safe mutation testing for the architecture guards.

A mutation test has to make the code wrong on purpose and then prove a guard
notices. The obvious way to undo that afterwards — ``git checkout -- <file>`` —
is also the way to destroy a colleague's uncommitted work, including the
mutation author's. That is not a hypothetical: it happened while these guards
were being written, and it silently reverted a real change to
``hevi/editable/jianying.py`` that was not yet committed.

So the rule this module exists to enforce is: **a mutation test never writes to
the working tree at all.** A mutation is evaluated against an isolated copy, and
the copy is thrown away. There is nothing to undo, so nothing can be lost.

    with isolated_mutation({"hevi/ops/p5_1_editable.py": "..."} ) as root:
        assert guard_fires(root)

The context manager copies only the files a check reads, redirects the check's
repository root at the copy, and restores the environment afterwards. The live
tree is never opened for writing.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT_ENV = "HEVI_P52_REPO_ROOT"

#: The files the P5.1 authorisation guard reads. Copying whole subtrees is
#: wasteful — ``hevi/`` alone is large enough that copying it several times turns
#: a fast guard into a slow one — and imprecise: the check only ever looks at
#: these paths, so these are the paths worth copying.
GUARD_READS: tuple[str, ...] = (
    "hevi/ops/p5_1_editable.py",
    "hevi/ops/p5_1_types.py",
    "hevi/editable/jianying.py",
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@contextmanager
def isolated_mutation(
    mutations: dict[str, str],
    *,
    files: tuple[str, ...] = GUARD_READS,
) -> Iterator[Path]:
    """Evaluate ``mutations`` against an isolated copy of the tree.

    ``mutations`` maps repo-relative paths to their *replacement* source; those
    are written. ``files`` names the unmodified context the check also reads,
    which is copied verbatim. Nothing outside the temporary copy is written.

    Yields the copy's root, with ``HEVI_P52_REPO_ROOT`` pointing at it. On exit
    the copy is deleted and the environment is restored.
    """
    import tempfile

    live = repo_root()
    with tempfile.TemporaryDirectory(prefix="hevi_mutation_") as raw:
        copy_root = Path(raw) / "tree"
        copy_root.mkdir()

        for relative in files:
            source = live / relative
            if not source.is_file():
                continue
            destination = copy_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Read-only on the source, write-only into the copy.
            shutil.copy2(source, destination)

        for relative, replacement in mutations.items():
            destination = copy_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(replacement, encoding="utf-8")

        previous = os.environ.get(REPO_ROOT_ENV)
        os.environ[REPO_ROOT_ENV] = str(copy_root)
        try:
            yield copy_root
        finally:
            if previous is None:
                os.environ.pop(REPO_ROOT_ENV, None)
            else:
                os.environ[REPO_ROOT_ENV] = previous


def live_source(relative: str) -> str:
    """Read a file from the live tree. Read-only, by construction."""
    return (repo_root() / relative).read_text(encoding="utf-8")


def append_symbol(relative: str, symbol: str) -> dict[str, str]:
    """A mutation that adds an unapproved top-level definition to a file."""
    return {relative: live_source(relative) + "\n\n" + symbol + "\n"}


#: The three violations the P5.1 authorisation guard has to catch. Expressed as
#: data so the safety test can prove the guard fires for each without any of this
#: code touching the working tree.
P51_VIOLATIONS: dict[str, str] = {
    "unapproved top-level symbol": (
        "def unapproved_helper():\n    return 1\n"
    ),
    "second validation authority inside P5.2": (
        "def _validate_parametric_text(element, material, material_path):\n"
        "    return []\n"
    ),
}
