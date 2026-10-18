"""Tests for oskill-003 through oskill-006: pure-algorithm stratum B2 group A elements."""

from __future__ import annotations

import sys
import types

# Stub the oskill package entry-point so __init__.py (which pulls in oprim/alembic)
# is never executed. The individual submodules are pure-Python and load fine.
if "oskill" not in sys.modules:
    _oskill_stub = types.ModuleType("oskill")
    _oskill_stub.__path__ = [str(__file__).replace("tests/test_stratum_b2_group_a.py", "oskill")]
    _oskill_stub.__package__ = "oskill"
    sys.modules["oskill"] = _oskill_stub

import pytest

from oskill._exceptions import OskillError
from oskill.check_reference_integrity import check_reference_integrity
from oskill.lint_substrate_graph import (
    ConceptRef,
    DerivativeRef,
    NoteRef,
    SubstrateRef,
    lint_substrate_graph,
)
from oskill.merge_platform_user_results import SearchResult, merge_platform_user_results
from oskill.resolve_conflict import resolve_conflict

# ---------------------------------------------------------------------------
# resolve_conflict — ≥8 tests
# ---------------------------------------------------------------------------


def _sr(id_: str, **kw: object) -> SearchResult:
    defaults = dict(type="doc", title=id_, score=1.0)
    defaults.update(kw)  # type: ignore[arg-type]
    return SearchResult(id=id_, **defaults)  # type: ignore[arg-type]


class TestResolveConflict:
    def test_highlight_merge_dedup(self) -> None:
        result = resolve_conflict(
            local_version={"items": ["a", "b"]},
            remote_version={"items": ["b", "c"]},
            conflict_type="highlight",
        )
        assert result.resolution_strategy == "merge"
        assert result.resolved["items"] == ["a", "b", "c"]

    def test_highlight_union_no_duplicate(self) -> None:
        """Items already equal — no conflict recorded."""
        result = resolve_conflict(
            local_version={"items": ["x"]},
            remote_version={"items": ["x"]},
            conflict_type="highlight",
        )
        assert result.resolved["items"] == ["x"]
        assert result.conflicts == []

    def test_note_keep_both(self) -> None:
        result = resolve_conflict(
            local_version={"body": "local text"},
            remote_version={"body": "remote text"},
            conflict_type="note",
        )
        assert result.resolution_strategy == "keep_both"
        assert len(result.conflicts) == 1
        assert result.conflicts[0].resolution == "both_kept"
        assert "_remote_version" in result.resolved

    def test_metadata_last_write_wins_local_newer(self) -> None:
        result = resolve_conflict(
            local_version={"title": "local", "_updated_at": "2025-01-02"},
            remote_version={"title": "remote", "_updated_at": "2025-01-01"},
            conflict_type="metadata",
        )
        assert result.resolution_strategy == "last_write_wins"
        assert result.resolved["title"] == "local"

    def test_metadata_last_write_wins_remote_newer(self) -> None:
        result = resolve_conflict(
            local_version={"title": "local", "_updated_at": "2025-01-01"},
            remote_version={"title": "remote", "_updated_at": "2025-01-02"},
            conflict_type="metadata",
        )
        assert result.resolved["title"] == "remote"

    def test_local_wins_override(self) -> None:
        result = resolve_conflict(
            local_version={"x": 1},
            remote_version={"x": 2},
            strategy="local_wins",
            conflict_type="highlight",
        )
        assert result.resolved == {"x": 1}
        assert result.resolution_strategy == "local_wins"
        assert result.conflicts == []

    def test_remote_wins_override(self) -> None:
        result = resolve_conflict(
            local_version={"x": 1},
            remote_version={"x": 2},
            strategy="remote_wins",
            conflict_type="highlight",
        )
        assert result.resolved == {"x": 2}
        assert result.resolution_strategy == "remote_wins"

    def test_unknown_conflict_type_raises(self) -> None:
        with pytest.raises(OskillError, match="Unknown conflict_type"):
            resolve_conflict(
                local_version={},
                remote_version={},
                conflict_type="bogus",
            )

    def test_no_base_version_ok(self) -> None:
        """base_version=None should not raise."""
        result = resolve_conflict(
            local_version={"a": 1},
            remote_version={"a": 1},
            base_version=None,
            conflict_type="metadata",
        )
        assert result.resolved["a"] == 1


# ---------------------------------------------------------------------------
# merge_platform_user_results — ≥7 tests
# ---------------------------------------------------------------------------


class TestMergePlatformUserResults:
    def test_empty_both(self) -> None:
        assert merge_platform_user_results(platform_results=[], user_results=[]) == []

    def test_only_platform(self) -> None:
        p = [_sr("p1"), _sr("p2")]
        results = merge_platform_user_results(platform_results=p, user_results=[])
        ids = [r.id for r in results]
        assert ids == ["p1", "p2"]
        assert all(r.source == "platform" for r in results)

    def test_only_user(self) -> None:
        u = [_sr("u1"), _sr("u2")]
        results = merge_platform_user_results(platform_results=[], user_results=u)
        assert [r.id for r in results] == ["u1", "u2"]
        assert all(r.source == "user" for r in results)

    def test_pinned_boost_elevates_rank(self) -> None:
        """A pinned user item ranked 3rd should outrank an unranked platform item at rank 0."""
        platform = [_sr("p1"), _sr("p2"), _sr("p3")]
        user = [_sr("u0"), _sr("u1"), _sr("u_pinned", is_pinned=True)]
        results = merge_platform_user_results(
            platform_results=platform,
            user_results=user,
            k=60,
            pinned_boost=10.0,
        )
        ids = [r.id for r in results]
        pinned_pos = ids.index("u_pinned")
        p1_pos = ids.index("p1")
        assert pinned_pos < p1_pos

    def test_ten_plus_ten_returns_twenty(self) -> None:
        platform = [_sr(f"p{i}") for i in range(10)]
        user = [_sr(f"u{i}") for i in range(10)]
        results = merge_platform_user_results(platform_results=platform, user_results=user)
        assert len(results) == 20

    def test_same_id_both_sources_deduplicates(self) -> None:
        """An ID appearing in both lists should appear once in output."""
        platform = [_sr("shared"), _sr("p_only")]
        user = [_sr("shared"), _sr("u_only")]
        results = merge_platform_user_results(platform_results=platform, user_results=user)
        ids = [r.id for r in results]
        assert ids.count("shared") == 1
        assert len(ids) == 3

    def test_zero_pinned_boost(self) -> None:
        """pinned_boost=0 should zero out pinned item contribution."""
        platform = [_sr("p1")]
        user = [_sr("u_pinned", is_pinned=True)]
        results = merge_platform_user_results(
            platform_results=platform,
            user_results=user,
            k=60,
            pinned_boost=0.0,
        )
        # pinned item has 0 score, platform item scores 1/61
        scores = {r.id: r.score for r in results}
        assert scores["u_pinned"] == 0.0
        assert scores["p1"] > 0.0


# ---------------------------------------------------------------------------
# lint_substrate_graph — ≥6 tests
# ---------------------------------------------------------------------------


class TestLintSubstrateGraph:
    def test_empty_returns_perfect_health(self) -> None:
        report = lint_substrate_graph(substrates=[], derivatives=[], notes=[], concepts=[])
        assert report.health_score == 100.0
        assert report.orphans == []
        assert report.broken_links == []
        assert report.stale_concepts == []

    def test_broken_derivative_ref(self) -> None:
        d = DerivativeRef(id="d1", parent_substrate_id="nonexistent")
        report = lint_substrate_graph(substrates=[], derivatives=[d], notes=[], concepts=[])
        assert len(report.broken_links) == 1
        assert report.broken_links[0].ref_type == "derivative_to_substrate"
        assert report.health_score < 100.0

    def test_orphan_substrate(self) -> None:
        s = SubstrateRef(id="s1")
        report = lint_substrate_graph(substrates=[s], derivatives=[], notes=[], concepts=[])
        assert "s1" in report.orphans

    def test_stale_concept(self) -> None:
        c = ConceptRef(id="c1", substrate_refs=[])
        report = lint_substrate_graph(substrates=[], derivatives=[], notes=[], concepts=[c])
        assert "c1" in report.stale_concepts
        assert report.health_score < 100.0

    def test_note_with_valid_refs_ok(self) -> None:
        s = SubstrateRef(id="s1")
        c = ConceptRef(id="c1", substrate_refs=["s1"])
        n = NoteRef(id="n1", substrate_refs=["s1"], concept_refs=["c1"])
        d = DerivativeRef(id="d1", parent_substrate_id="s1")
        report = lint_substrate_graph(substrates=[s], derivatives=[d], notes=[n], concepts=[c])
        assert report.broken_links == []
        assert report.stale_concepts == []

    def test_full_valid_graph_perfect_health(self) -> None:
        s1 = SubstrateRef(id="s1")
        s2 = SubstrateRef(id="s2")
        d1 = DerivativeRef(id="d1", parent_substrate_id="s1")
        c1 = ConceptRef(id="c1", substrate_refs=["s1", "s2"])
        n1 = NoteRef(id="n1", substrate_refs=["s1"], concept_refs=["c1"])
        report = lint_substrate_graph(
            substrates=[s1, s2], derivatives=[d1], notes=[n1], concepts=[c1]
        )
        assert report.broken_links == []
        assert report.stale_concepts == []
        assert report.health_score == 100.0


# ---------------------------------------------------------------------------
# check_reference_integrity — ≥5 tests
# ---------------------------------------------------------------------------


class TestCheckReferenceIntegrity:
    def test_all_present_valid(self) -> None:
        report = check_reference_integrity(
            ref_type="note_ref",
            source_id="note-1",
            target_ids=["s1", "s2"],
            available_ids={"s1", "s2"},
        )
        assert report.valid is True
        assert report.missing_refs == []

    def test_missing_refs_detected(self) -> None:
        report = check_reference_integrity(
            ref_type="note_ref",
            source_id="note-1",
            target_ids=["s1", "s2", "s99"],
            available_ids={"s1", "s2"},
        )
        assert report.valid is False
        assert report.missing_refs == ["s99"]

    def test_orphan_refs(self) -> None:
        report = check_reference_integrity(
            ref_type="concept_substrate",
            source_id="c-1",
            target_ids=["s1"],
            available_ids={"s1", "s2", "s3"},
        )
        assert report.valid is True
        assert sorted(report.orphan_refs) == ["s2", "s3"]

    def test_empty_targets(self) -> None:
        report = check_reference_integrity(
            ref_type="substrate_derivative",
            source_id="src",
            target_ids=[],
            available_ids={"a", "b"},
        )
        assert report.valid is True
        assert report.missing_refs == []
        assert sorted(report.orphan_refs) == ["a", "b"]

    def test_unknown_ref_type_raises(self) -> None:
        with pytest.raises(OskillError, match="Unknown ref_type"):
            check_reference_integrity(
                ref_type="bogus_type",  # type: ignore[arg-type]
                source_id="x",
                target_ids=[],
                available_ids=set(),
            )
