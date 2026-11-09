"""S16: internal drama lines are only listed/allowed for admins or allowlist."""

from __future__ import annotations

import pytest

from hevi.auth.dependencies import can_view_internal_lines
from hevi.studio.recipes import get_recipe, line_availability


def test_ai_drama_is_internal() -> None:
    assert line_availability("ai_drama") == "internal"
    rec = get_recipe("ai_drama")
    assert rec is not None
    assert "drama.series_topics" in rec.tools


def test_internal_visibility_requires_admin_or_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEVI_ADMIN_USER_IDS", "admin-1")
    monkeypatch.delenv("HEVI_INTERNAL_LINE_ALLOWLIST", raising=False)
    assert can_view_internal_lines({"id": "admin-1", "email": "a@x"})
    assert not can_view_internal_lines({"id": "user-2", "email": "u@x"})
    assert not can_view_internal_lines(None)
    monkeypatch.setenv("HEVI_INTERNAL_LINE_ALLOWLIST", "beta@x")
    assert can_view_internal_lines({"id": "user-3", "email": "beta@x"})
