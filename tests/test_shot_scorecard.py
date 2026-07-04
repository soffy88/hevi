"""C4: shot_scorecard — identity-anchored variant selection + omodul contract.

subject_embed is monkeypatched (per-path vectors) so the selection/aggregation logic
is tested deterministically without loading CLIP. Real-embedding selection is verified
manually (same-video 1.0 vs diff 0.799).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import hevi.verdict.scorecard as sc_mod
from hevi.verdict import make_scorecard_consistency_fn, shot_scorecard
from hevi.verdict.frame_extract import extract_representative_frame


def _png(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    p.write_bytes(b"\x89PNG\r\n")  # header only; content unused (subject_embed mocked)
    return p


@pytest.fixture
def fake_embed(monkeypatch):
    # map path basename → vector
    table: dict[str, list[float]] = {}

    def _fake(*, image_path, kind="face"):
        return table[Path(image_path).name]

    monkeypatch.setattr(sc_mod, "subject_embed", _fake)
    return table


def test_picks_higher_identity_not_first(tmp_path, fake_embed):
    a, b = _png(tmp_path, "a.png"), _png(tmp_path, "b.png")
    fake_embed["a.png"] = [1.0, 0.0, 0.0]
    fake_embed["b.png"] = [0.0, 1.0, 0.0]
    ref = [1.0, 0.0, 0.0]  # matches a

    # b FIRST — pick-first would wrongly pick b
    sc = shot_scorecard(candidate_frames=[b, a], subject_ref_embedding=ref)
    assert sc.best_index == 1
    assert sc.best_frame.name == "a.png"
    assert sc.identity_score == pytest.approx(1.0)
    assert [round(r["identity"], 3) for r in sc.per_candidate] == [0.0, 1.0]
    assert sc.passed is True


def test_low_identity_emits_hint_and_fails(tmp_path, fake_embed):
    a = _png(tmp_path, "a.png")
    fake_embed["a.png"] = [0.0, 1.0, 0.0]
    ref = [1.0, 0.0, 0.0]  # orthogonal → identity 0.0 < floor
    sc = shot_scorecard(candidate_frames=[a], subject_ref_embedding=ref, identity_floor=0.2)
    assert sc.passed is False
    assert any("身份匹配偏低" in h for h in sc.hints)


def test_no_anchor_picks_first_and_passes(tmp_path, fake_embed):
    a, b = _png(tmp_path, "a.png"), _png(tmp_path, "b.png")
    sc = shot_scorecard(candidate_frames=[a, b], subject_ref_embedding=None)
    assert sc.best_index == 0
    assert sc.passed is True  # no anchor → accept first, no needless retry


def test_empty_candidates_raises():
    with pytest.raises(ValueError):
        shot_scorecard(candidate_frames=[], subject_ref_embedding=[1.0])


async def test_consistency_fn_matches_omodul_contract(tmp_path, fake_embed):
    a, b = _png(tmp_path, "a.png"), _png(tmp_path, "b.png")
    fake_embed["a.png"] = [1.0, 0.0]
    fake_embed["b.png"] = [0.2, 0.98]
    fn = make_scorecard_consistency_fn([1.0, 0.0])
    res = await fn(mllm=None, candidate_frames=[b, a], reference=None, criteria=None)
    assert res.best_frame.name == "a.png"  # identity winner
    assert isinstance(res.passed, bool)
    assert res.scorecard.best_index == 1


def test_frame_extract_passes_images_through(tmp_path):
    img = _png(tmp_path, "frame.png")
    out = extract_representative_frame(img, tmp_path / "out.png")
    assert out == img  # image input returned as-is, no decode
