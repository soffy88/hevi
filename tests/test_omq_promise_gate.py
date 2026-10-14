"""OMQUALITY 交付承诺 × 实测运动证据 —— 纯算法单测。

覆盖 cuts_from_segments / motion_evidence 的折算语义, 以及审片工作流
拿到 promise 后是否真的把"排产前定死的承诺"变成 violation(而不是只记一条
warning 放过去)。
"""

from __future__ import annotations

import pytest

from hevi.layer4_legacy.review.omodul_impl.review_workflow import review_finished_video_workflow
from hevi.layer4_legacy.review.oskill_impl.promise_gate import (
    cuts_from_segments,
    motion_evidence,
)


def test_still_segments_fold_into_non_motion_cuts() -> None:
    segments = [(0, 5), (5, 6), (6, 11)]
    deltas = [0.1] * 4 + [40.0] + [0.2] * 4
    cuts = cuts_from_segments(segments=segments, deltas=deltas, motion_floor=1.0)
    # 两段冻结的 5 帧静帧 + 一段只有 1 帧的切点间隙(量不出 → 记 motion)
    assert [c["type"] for c in cuts] == ["still_card", "video", "still_card"]
    ev = motion_evidence(cuts)
    assert ev["motion_ratio"] == 0.333
    assert ev["still_ratio"] == 0.667
    assert ev["cuts"] == 3


def test_segment_with_any_interframe_motion_counts_as_motion() -> None:
    segments = [(0, 4), (4, 9)]
    deltas = [0.1, 12.0, 0.1, 30.0, 0.1, 0.1, 0.1, 0.1]
    cuts = cuts_from_segments(segments=segments, deltas=deltas, motion_floor=1.0)
    assert [c["type"] for c in cuts] == ["video", "still_card"]
    assert motion_evidence(cuts)["motion_ratio"] == 0.5


def test_single_frame_segment_is_not_called_still() -> None:
    """量不出的段不当成缺陷: 单帧段是切点间隙, 记为 motion。"""
    cuts = cuts_from_segments(segments=[(0, 1), (1, 2)], deltas=[30.0], motion_floor=1.0)
    assert [c["type"] for c in cuts] == ["video", "video"]


def test_two_frame_frozen_run_is_still() -> None:
    """段长 ≥ 2 且全部帧差低于下限 → 证明得了的静帧。"""
    cuts = cuts_from_segments(segments=[(0, 3)], deltas=[0.0, 0.1], motion_floor=1.0)
    assert [c["type"] for c in cuts] == ["still_card"]


def test_no_segments_yields_no_cuts() -> None:
    assert cuts_from_segments(segments=[], deltas=[], motion_floor=1.0) == []
    assert motion_evidence([])["motion_ratio"] == 0.0


# --- 工作流层: promise 违规必须变成 violation -----------------------------


def _real_clip() -> str:
    return "artifacts/real_video/20261005T160434Z/final/FINAL.mp4"


def test_motion_promise_on_motioned_clip_is_not_a_violation(tmp_path) -> None:
    """真片有真实运动 → motion_led 承诺不应被判违约。"""
    report = review_finished_video_workflow(
        {"promise": {"promise_type": "motion_led", "motion_required": True}},
        {"input_path": _real_clip()},
        tmp_path / "motion_ok",
    )
    promise = report["metrics"]["promise"]
    assert promise["promise_type"] == "motion_led"
    assert promise["verdict"] in ("ok", "violation")
    # 真实运动片应测到 motion 切点, 否则说明折算没生效
    assert promise["evidence"]["motion_cuts"] >= 1
    if promise["verdict"] == "violation":
        assert report["verdict"] == "red"


def test_promise_with_unmeasurable_evidence_is_unmeasured() -> None:
    """没有切点证据 → 记 unmeasured, 不冒充违约。"""
    from hevi.layer4_legacy.review.omodul_impl.review_workflow import _reconcile_promise

    violations: list[str] = []
    out = _reconcile_promise(
        promise_raw={"promise_type": "motion_led", "motion_required": True},
        cuts=[],
        violations=violations,
    )
    assert out["verdict"] == "unmeasured"
    assert violations == []


def test_bad_promise_spec_does_not_crash_the_gate(tmp_path) -> None:
    report = review_finished_video_workflow(
        {"promise": {"promise_type": "not-a-real-type"}},
        {"input_path": _real_clip()},
        tmp_path / "bad_spec",
    )
    assert "error" in report["metrics"]["promise"]
    assert report["status"] == "ok"


@pytest.mark.parametrize(
    ("pipeline", "expected"),
    [("cinematic", "motion_led"), ("talking-head", "avatar_presenter")],
)
def test_promise_string_is_treated_as_a_pipeline_name(tmp_path, pipeline, expected) -> None:
    """裸字符串按 delivery_promise 的约定解释为管线名, 不是别名表。"""
    report = review_finished_video_workflow(
        {"promise": pipeline},
        {"input_path": _real_clip()},
        tmp_path / f"pipeline_{pipeline}",
    )
    assert report["metrics"]["promise"]["promise_type"] == expected


@pytest.mark.parametrize("alias", ["motion", "motion_led", "avatar_presenter", "any"])
def test_op_resolves_the_season_dispatcher_aliases(alias: str) -> None:
    """op 层负责把 dispatch 的别名表解析成结构化承诺。"""
    from hevi.studio.ops import _resolve_promise_spec

    spec = _resolve_promise_spec(alias)
    assert spec["promise_type"] in {"motion_led", "hybrid", "avatar_presenter"}
    if alias in ("motion", "motion_led", "avatar_presenter"):
        assert spec["motion_required"] is True
