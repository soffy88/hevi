"""registry_consistency: canonical lines must be registered; extra
registered lines outside the canonical qualification set are tolerated.
"""

from __future__ import annotations

import pytest

from hevi.studio import production_catalog


def test_canonical_all_registered_with_extra_lines_passes() -> None:
    result = production_catalog.registry_consistency()
    # The real registry registers lines outside the canonical qualification set
    # (ai_drama and collage_broll are internal, handdraw and scene3d are extra);
    # they must not fail consistency.
    assert result["unqualified_registered_lines"] == ["ai_drama", "collage_broll", "handdraw", "scene3d"]
    assert result["unknown_qualification_lines"] == []
    assert result["registered_count"] == result["qualification_count"] + 4
    assert result["passed"] is True


def test_missing_canonical_line_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        production_catalog,
        "CANONICAL_LINES",
        (*production_catalog.CANONICAL_LINES, "nonexistent_line_xyz"),
    )
    result = production_catalog.registry_consistency()
    assert result["unknown_qualification_lines"] == ["nonexistent_line_xyz"]
    assert result["passed"] is False
