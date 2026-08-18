"""B7 活态制片状态板后端 —— 事件流/状态汇总测试。"""

from __future__ import annotations

from pathlib import Path

from hevi.backlot import (
    EVENT_COST,
    EVENT_HEARTBEAT,
    EVENT_NOTE,
    EVENT_SHOT_DONE,
    EVENT_STAGE_DONE,
    EVENT_STAGE_FAIL,
    EVENT_STAGE_START,
    BacklotEvent,
    BacklotEventLog,
    backlot_status,
)


class TestEmit:
    def test_emit_append_and_tail(self, tmp_path: Path) -> None:
        log = BacklotEventLog(tmp_path)
        log.emit(BacklotEvent(run_id="run-1", stage="script", event_type=EVENT_STAGE_START))
        log.emit(BacklotEvent(run_id="run-1", stage="script", event_type=EVENT_STAGE_DONE))
        assert log.count("run-1") == 2
        assert [e.event_type for e in log.events("run-1")] == [
            EVENT_STAGE_START,
            EVENT_STAGE_DONE,
        ]

    def test_persisted_to_jsonl(self, tmp_path: Path) -> None:
        log = BacklotEventLog(tmp_path)
        log.emit(BacklotEvent(run_id="run-1", stage="s", event_type=EVENT_STAGE_DONE))
        assert (tmp_path / "run-1.jsonl").exists()
        # 新实例从磁盘回放
        log2 = BacklotEventLog(tmp_path)
        replayed = log2.replay_from_disk("run-1")
        assert len(replayed) == 1
        assert replayed[0].event_type == EVENT_STAGE_DONE
        assert replayed[0].run_id == "run-1"

    def test_run_id_path_traversal_rejected(self, tmp_path: Path) -> None:
        log = BacklotEventLog(tmp_path)
        # emit 是 best-effort: 非法 run_id 不 raise、不落盘(降级为日志)
        log.emit(BacklotEvent(run_id="../../evil", stage="s", event_type=EVENT_NOTE))
        assert log.count("../../evil") == 0
        assert not any(tmp_path.iterdir())

    def test_emit_failure_degrades(self, tmp_path: Path) -> None:
        # root 是文件 → mkdir 失败 → emit 仅记日志不 raise
        blocker = tmp_path / "blocker"
        blocker.write_text("x", encoding="utf-8")
        log = BacklotEventLog(blocker / "sub")
        log.emit(BacklotEvent(run_id="r", stage="s", event_type=EVENT_NOTE))  # 不 raise
        assert log.count("r") == 0

    def test_replay_skips_corrupt_lines(self, tmp_path: Path) -> None:
        log = BacklotEventLog(tmp_path)
        log.emit(BacklotEvent(run_id="r", stage="s", event_type=EVENT_NOTE))
        f = tmp_path / "r.jsonl"
        f.write_text(f.read_text(encoding="utf-8") + "{bad json\n", encoding="utf-8")
        assert len(log.replay_from_disk("r")) == 1


class TestStatus:
    def _filled_log(self, tmp_path: Path) -> BacklotEventLog:
        log = BacklotEventLog(tmp_path)
        log.emit(BacklotEvent(run_id="r", stage="script", event_type=EVENT_STAGE_START))
        log.emit(BacklotEvent(run_id="r", stage="script", event_type=EVENT_STAGE_DONE))
        log.emit(BacklotEvent(run_id="r", stage="material", event_type=EVENT_STAGE_START))
        log.emit(
            BacklotEvent(run_id="r", stage="shot", event_type=EVENT_SHOT_DONE, payload={"n": 3})
        )
        log.emit(
            BacklotEvent(run_id="r", stage="cost", event_type=EVENT_COST, payload={"usd": 1.25})
        )
        log.emit(BacklotEvent(run_id="r", stage="", event_type=EVENT_HEARTBEAT))
        return log

    def test_status_derivation(self, tmp_path: Path) -> None:
        st = backlot_status(self._filled_log(tmp_path), "r")
        assert st["run_id"] == "r"
        assert st["event_count"] == 6
        assert st["stages"] == {"script": EVENT_STAGE_DONE, "material": EVENT_STAGE_START}
        assert st["cost_usd"] == 1.25
        assert st["last_heartbeat"] is not None
        assert st["failed"] is False

    def test_status_failed_flag(self, tmp_path: Path) -> None:
        log = BacklotEventLog(tmp_path)
        log.emit(BacklotEvent(run_id="r", stage="material", event_type=EVENT_STAGE_FAIL))
        assert backlot_status(log, "r")["failed"] is True

    def test_status_empty_run(self, tmp_path: Path) -> None:
        st = backlot_status(BacklotEventLog(tmp_path), "nope")
        assert st["event_count"] == 0
        assert st["stages"] == {}
        assert st["cost_usd"] == 0.0
        assert st["failed"] is False
