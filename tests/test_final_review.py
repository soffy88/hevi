"""hevi.director.final_review 测试 — vlm 用 AsyncMock 直接注入,不碰真实模型。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from hevi.director.final_review import (
    SeamReview,
    review_seam,
    synthesize_final_checklist,
)
from hevi.director.segment_qc import SegmentQCResult


async def test_review_seam_parses_valid_json_response(tmp_path: Path) -> None:
    vlm = AsyncMock(
        return_value={
            "content": (
                '{"spatial_jump": false, "camera_looks_repeated": false, '
                '"identity_consistent": true, "color_mismatch": false, "reason": "自然衔接"}'
            )
        }
    )
    result = await review_seam(tmp_path / "a.png", tmp_path / "b.png", seam="2->3", vlm=vlm)
    assert result.unverified is False
    assert result.spatial_jump is False
    assert result.identity_consistent is True
    assert result.reason == "自然衔接"


async def test_review_seam_retries_on_garbage_then_succeeds(tmp_path: Path) -> None:
    # 前两次乱码,第三次才给出有效 JSON——本地小 VLM 实测过的真实退化模式。
    vlm = AsyncMock(
        side_effect=[
            {"content": "???????????????????????????????"},
            {"content": "???????????????????????????????"},
            {
                "content": (
                    '{"spatial_jump": true, "camera_looks_repeated": false, '
                    '"identity_consistent": true, "color_mismatch": false, "reason": "跳变"}'
                )
            },
        ]
    )
    result = await review_seam(tmp_path / "a.png", tmp_path / "b.png", seam="1->2", vlm=vlm)
    assert result.unverified is False
    assert result.spatial_jump is True
    assert vlm.await_count == 3


async def test_review_seam_marks_unverified_after_exhausting_retries(tmp_path: Path) -> None:
    vlm = AsyncMock(return_value={"content": "???????????????????????????????"})
    result = await review_seam(tmp_path / "a.png", tmp_path / "b.png", seam="1->2", vlm=vlm)
    assert result.unverified is True
    assert result.spatial_jump is None  # 没判出来就是没判出来,不能默认当"没有跳变"


def test_synthesize_final_checklist_all_clean() -> None:
    seam_reviews = [
        SeamReview(
            seam="1->2",
            spatial_jump=False,
            camera_looks_repeated=False,
            identity_consistent=True,
            color_mismatch=False,
        ),
        SeamReview(
            seam="2->3",
            spatial_jump=False,
            camera_looks_repeated=False,
            identity_consistent=True,
            color_mismatch=False,
        ),
    ]
    qc_results = [
        SegmentQCResult(segment_id="1", identity_scores={"王生": 0.8}, dialogue_fits=True),
        SegmentQCResult(segment_id="2", identity_scores={"王生": 0.75}, dialogue_fits=True),
    ]
    report = synthesize_final_checklist(
        seam_reviews=seam_reviews,
        qc_results=qc_results,
        color_reports=[{"segment_id": "1", "gain": (1.0, 1.0, 1.0)}],
        camera_lint_findings=[],
    )
    assert len(report["items"]) == 6
    assert all(item["passed"] for item in report["items"])
    assert report["unverified_seams"] == []


def test_synthesize_final_checklist_flags_bad_scenes() -> None:
    seam_reviews = [
        SeamReview(
            seam="2->3",
            spatial_jump=True,
            camera_looks_repeated=False,
            identity_consistent=True,
            color_mismatch=False,
            reason="跳变",
        ),
    ]
    qc_results = [
        SegmentQCResult(segment_id="1", identity_scores={"王生": 0.5}, dialogue_fits=False),
    ]
    report = synthesize_final_checklist(
        seam_reviews=seam_reviews,
        qc_results=qc_results,
        color_reports=[{"segment_id": "1", "gain": (0.7, 1.0, 1.0)}],  # 触顶 clamp
        camera_lint_findings=["相邻段运镜重复"],
    )
    items_by_name = {item["name"]: item for item in report["items"]}
    assert items_by_name["空间连贯性"]["passed"] is False
    assert items_by_name["空间连贯性"]["bad_scenes"] == [2, 3]
    assert items_by_name["运镜多样性"]["passed"] is False
    assert items_by_name["身份保真度"]["passed"] is False
    assert "1" in items_by_name["身份保真度"]["bad_scenes"]
    assert items_by_name["对白/时间线连续性"]["passed"] is False
    assert items_by_name["色彩/影调一致性"]["passed"] is False


def test_synthesize_final_checklist_surfaces_unverified_seams() -> None:
    seam_reviews = [SeamReview(seam="1->2", unverified=True, reason="重试耗尽")]
    report = synthesize_final_checklist(
        seam_reviews=seam_reviews, qc_results=[], color_reports=[], camera_lint_findings=[]
    )
    assert report["unverified_seams"] == ["1->2"]
