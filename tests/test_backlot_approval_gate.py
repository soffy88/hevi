"""Backlot 分镜联系表审批门 + REPLAY 回放 —— 后端测试。

用的是仓库里**真实**的成片(artifacts/real_video/...), 质量分与回放时长都
由 ffprobe / 解码实测, 不塞假数字。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hevi.backlot.replay import build_replay, render_replay_video
from hevi.backlot.storyboard import (
    SHOT_APPROVED,
    SHOT_PENDING,
    SHOT_REJECTED,
    StoryboardBoard,
    StoryboardShot,
    measure_quality,
)

REAL_DIR = Path("artifacts/real_video/20261005T160434Z/artifacts")
BROLL = str(REAL_DIR / "scene_broll_720p.mp4")
COLLINS = str(REAL_DIR / "nasa-collins-0001_finecut.mp4")

pytestmark = pytest.mark.skipif(
    not Path(BROLL).is_file(), reason="real media fixture not present in this checkout"
)


# --- 质量分:量出来的 -------------------------------------------------------


def test_quality_is_measured_not_declared(tmp_path) -> None:
    q = measure_quality(BROLL, work_dir=tmp_path / "q")
    assert q["score"] is not None, "真实视频必须能测出总分"
    assert 0.0 <= q["score"] <= 1.0
    assert q["unmeasured"] == []
    # 标尺要公开, 分数才可复核
    assert set(q["components"]) == {"exposure", "contrast", "motion"}
    assert q["weights"]["motion"] > q["weights"]["exposure"]
    assert Path(q["thumbnail"]).is_file()


def test_quality_refuses_to_score_a_missing_source(tmp_path) -> None:
    q = measure_quality(tmp_path / "nope.mp4", work_dir=tmp_path / "q2")
    assert q.get("score") is None
    assert set(q["unmeasured"]) == {"exposure", "contrast", "motion"}
    assert q["notes"], "量不到必须有明写的原因"


def test_declared_score_is_recorded_but_never_used(tmp_path) -> None:
    board = StoryboardBoard(tmp_path, "run-declared")
    q = measure_quality(BROLL, work_dir=tmp_path / "q3")
    board.upsert(
        StoryboardShot(
            scene_id="s1",
            source_path=BROLL,
            quality=q,
            declared_score=0.01,
        )
    )
    shot = board.get("s1")
    assert shot is not None
    assert shot.declared_score == 0.01
    assert shot.quality["score"] != 0.01  # 审批看的是实测分


# --- 审批写回 --------------------------------------------------------------


def _board(tmp_path, run_id="run-x") -> StoryboardBoard:
    board = StoryboardBoard(tmp_path, run_id)
    board.upsert(StoryboardShot(scene_id="a", index=0, source_path=BROLL, cost_usd=0.4))
    board.upsert(StoryboardShot(scene_id="b", index=1, source_path=COLLINS, cost_usd=0.2))
    return board


def test_reject_without_a_reason_is_refused(tmp_path) -> None:
    board = _board(tmp_path)
    with pytest.raises(ValueError, match="理由"):
        board.decide("a", decision=SHOT_REJECTED, reason="   ")
    assert board.get("a").status == SHOT_PENDING


def test_approve_and_reject_write_back_and_persist(tmp_path) -> None:
    board = _board(tmp_path)
    board.decide("a", decision=SHOT_APPROVED, reason="运动达标", reviewer="omq")
    board.decide("b", decision=SHOT_REJECTED, reason="构图偏空", reviewer="omq")

    # 重新打开 = 从磁盘恢复, 裁决没有丢
    reloaded = StoryboardBoard(tmp_path, "run-x")
    assert reloaded.get("a").status == SHOT_APPROVED
    assert reloaded.get("b").status == SHOT_REJECTED
    assert reloaded.get("b").decisions[-1].reason == "构图偏空"
    assert reloaded.get("a").decisions[-1].reviewer == "omq"

    s = reloaded.summary()
    assert s["approved"] == 1
    assert s["rejected"] == 1
    assert s["pending"] == 0
    assert s["gate"] == "resolved_with_rejects"
    assert s["approved_cost_usd"] == 0.4
    assert s["rejected_cost_usd"] == 0.2


def test_upsert_does_not_wipe_an_existing_decision(tmp_path) -> None:
    board = _board(tmp_path)
    board.decide("a", decision=SHOT_REJECTED, reason="太暗", reviewer="omq")
    board.upsert(StoryboardShot(scene_id="a", index=0, source_path=BROLL, cost_usd=0.4))
    shot = board.get("a")
    assert shot.status == SHOT_REJECTED
    assert len(shot.decisions) == 1


def test_decision_history_is_append_only(tmp_path) -> None:
    board = _board(tmp_path)
    board.decide("a", decision=SHOT_REJECTED, reason="第一版太暗", reviewer="omq")
    board.decide("a", decision=SHOT_APPROVED, reason="重渲后可用", reviewer="omq")
    shot = board.get("a")
    assert [d.decision for d in shot.decisions] == [SHOT_REJECTED, SHOT_APPROVED]
    assert shot.status == SHOT_APPROVED


def test_unknown_scene_is_not_silently_created(tmp_path) -> None:
    board = _board(tmp_path)
    with pytest.raises(KeyError):
        board.decide("nope", decision=SHOT_APPROVED)


def test_invalid_decision_value_is_refused(tmp_path) -> None:
    board = _board(tmp_path)
    with pytest.raises(ValueError):
        board.decide("a", decision="maybe")


# --- 联系表 PNG ------------------------------------------------------------


def test_contact_sheet_is_a_real_png_of_measured_thumbnails(tmp_path) -> None:
    board = _board(tmp_path)
    for sid in ("a", "b"):
        q = measure_quality(board.get(sid).source_path, work_dir=tmp_path / "q" / sid)
        board.upsert(
            StoryboardShot(
                scene_id=sid,
                index=board.get(sid).index,
                source_path=board.get(sid).source_path,
                quality=q,
                cost_usd=board.get(sid).cost_usd,
            )
        )
    out = board.contact_sheet()
    assert out["sheet"] is not None, "两格都有缩略图时必须拼出联络表"
    assert Path(out["sheet"]["path"]).is_file()
    assert out["sheet"]["width"] > 0 and out["sheet"]["frames"] == 2
    assert len(out["thumbnails"]) == 2


def test_contact_sheet_without_thumbnails_says_so(tmp_path) -> None:
    board = _board(tmp_path)
    out = board.contact_sheet()
    assert out["sheet"] is None
    assert len(out["thumbnails"]) == 2  # 仍列出每格的缩略图状态


# --- REPLAY ----------------------------------------------------------------


def test_replay_timeline_uses_measured_durations(tmp_path) -> None:
    board = _board(tmp_path)
    for sid in ("a", "b"):
        board.decide(sid, decision=SHOT_APPROVED, reason="ok", reviewer="omq")
    rp = build_replay(board)
    shots = [s for s in rp["segments"] if s["kind"] == "shot"]
    assert len(shots) == 2
    # broll 14.00s + collins 22.65s(实测), 而不是配置里的名义值
    assert shots[0]["duration_s"] == pytest.approx(14.0, abs=0.2)
    assert shots[1]["duration_s"] == pytest.approx(22.65, abs=0.2)
    assert rp["total_s"] == pytest.approx(14.0 + 22.65 + 2 * 1.5, abs=0.4)
    assert rp["renderable"] is True


def test_replay_only_takes_approved_shots_by_default(tmp_path) -> None:
    board = _board(tmp_path)
    board.decide("a", decision=SHOT_APPROVED, reason="ok", reviewer="omq")
    board.decide("b", decision=SHOT_REJECTED, reason="no", reviewer="omq")
    approved = build_replay(board)
    assert [s["scene_id"] for s in approved["segments"] if s["kind"] == "shot"] == ["a"]
    rejected = build_replay(board, include=SHOT_REJECTED)
    assert [s["scene_id"] for s in rejected["segments"] if s["kind"] == "shot"] == ["b"]


def test_replay_marks_shots_without_media_unmeasured(tmp_path) -> None:
    board = StoryboardBoard(tmp_path, "run-nomedia")
    board.upsert(StoryboardShot(scene_id="ghost", source_path="", cost_usd=0.1))
    board.decide("ghost", decision=SHOT_APPROVED, reason="ok", reviewer="omq")
    rp = build_replay(board)
    assert rp["renderable"] is False
    assert rp["unmeasured"][0]["scene_id"] == "ghost"
    out = render_replay_video(rp, tmp_path / "never.mp4")
    assert out["ok"] is False
    assert not (tmp_path / "never.mp4").exists(), "不可渲染时不得留下占位视频"


def test_replay_renders_a_real_mp4(tmp_path) -> None:
    board = _board(tmp_path)
    for sid in ("a", "b"):
        board.decide(sid, decision=SHOT_APPROVED, reason="ok", reviewer="omq")
    rp = build_replay(board)
    out = render_replay_video(rp, tmp_path / "replay.mp4")
    assert out["ok"] is True
    assert Path(out["path"]).is_file()
    assert out["duration_s"] == pytest.approx(36.65, abs=0.5)
    assert out["has_audio"] is True
    assert len(out["sha256"]) == 64


def test_replay_manifest_round_trips_as_json(tmp_path) -> None:
    board = _board(tmp_path)
    board.decide("a", decision=SHOT_APPROVED, reason="ok", reviewer="omq")
    rp = build_replay(board)
    assert json.loads(json.dumps(rp, ensure_ascii=False))["run_id"] == "run-x"


def test_board_rejects_path_traversal_run_id(tmp_path) -> None:
    with pytest.raises(ValueError):
        StoryboardBoard(tmp_path, "../escape")
