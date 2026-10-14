"""Make the local enhancement interpreter visible without touching the shared venv.

The repository's ``.venv`` is a symlink into the main Hevi checkout, so the
OMQUALITY work installs its optional enhancement dependencies (``basicsr`` /
``gfpgan`` / ``facexlib``) into an **isolated** ``.venv-om`` inside this
worktree.  When Hevi runs under the shared interpreter we transparently append
that local site-packages directory so ``import gfpgan`` resolves.

Set ``HEVI_ENHANCE_SITE`` to override the location; the default is
``<repo>/.venv-om/lib/python<X.Y>/site-packages``.
"""

from __future__ import annotations

import os
import site
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]


def candidate_sites() -> list[Path]:
    out: list[Path] = []
    env = os.environ.get("HEVI_ENHANCE_SITE")
    if env:
        out.append(Path(env))
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    for venv in (".venv-om", ".venv-enhance"):
        out.append(_REPO / venv / "lib" / version / "site-packages")
        out.append(_REPO / venv / "Lib" / "site-packages")
    # already-visible dirs are not candidates
    visible = {Path(p).resolve() for p in site.getsitepackages() + [site.getusersitepackages()]}
    return [p for p in out if p.is_dir() and p.resolve() not in visible]


def ensure_importable(module: str) -> bool:
    """Try to import ``module``; if missing, extend ``sys.path`` and retry."""
    try:
        __import__(module)
        return True
    except ImportError:
        pass
    for path in candidate_sites():
        sp = str(path)
        if sp not in sys.path:
            sys.path.append(sp)
    try:
        __import__(module)
        return True
    except ImportError:
        return False


__all__ = ["candidate_sites", "ensure_importable"]
