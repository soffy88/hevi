"""Shared real-render fixtures for the Handdraw R2 acceptance tests."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(scope="session")
def handdraw_preview(tmp_path_factory: pytest.TempPathFactory):
    """Render a fresh 2-second preview in the worktree-local pytest temp root."""
    from hevi.capabilities import get

    out_dir = tmp_path_factory.mktemp("handdraw-r2-preview").resolve()
    if not out_dir.is_relative_to(REPO_ROOT):
        raise AssertionError(f"pytest temp directory escaped the worktree: {out_dir}")
    result = get("handdraw.full").render(
        {
            "topic": "小狐狸学会轮流",
            "aspect": "16:9",
            "style_id": "17",
            "hand_preset": "navy",
        },
        out_dir,
        duration=2.0,
        aspect="16:9",
        seed=20261014,
    )
    return SimpleNamespace(root=out_dir, result=result)
