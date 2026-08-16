"""教材↔古籍交叉弧测试（P1）—— 双述组装 + mneme 主述拉取。"""

from pathlib import Path

import pytest

from hevi.history_series.textbook_bridge import (
    assemble_textbook_run_request,
    lesson_contract_path,
    load_lesson_contract,
)

CONTRACT = Path("/data/soffy/projects/stratum/docs/history/contracts/sample.sanjiafenjin.json")


def test_lesson_contract_mapping():
    """七上『战国时期的社会变化』↔ 三家分晋契约（P1 手工标注）。"""
    p = lesson_contract_path("战国时期的社会变化")
    assert p is not None and p.is_file()
    assert lesson_contract_path("北京人") is None      # 无古籍对应


def test_load_lesson_contract():
    contract = load_lesson_contract("战国时期的社会变化")
    assert contract is not None
    assert contract["event"]["event_id"] == "ev:jinyang-zhizhan"


@pytest.mark.asyncio
async def test_assemble_textbook_mainline_override(monkeypatch):
    """教材主述传入 → raw_text 主述=教材，古籍全并陈（arc_adapter D5 路径）。"""
    async def _mock_text(*a, **k): return "战国时期，晋国六卿中的智氏最强，索地于韩赵魏三家。"
    monkeypatch.setattr(
        "hevi.history_series.textbook_bridge.textbook_mainline_from_mneme",
        _mock_text,
    )
    req = await assemble_textbook_run_request(
        "战国时期的社会变化", "TONGBIAN-G7-HISTORY-S", 7
    )
    assert req["source_name"] == "历史现场·TONGBIAN-G7-HISTORY-S·战国时期的社会变化"
    assert "（教材主述）" in req["raw_text"]
    assert "（并陈）" in req["raw_text"]              # 古籍并陈块
    assert "资治通鉴" in req["raw_text"] or "史记" in req["raw_text"]


@pytest.mark.asyncio
async def test_assemble_without_contract(monkeypatch):
    """无古籍契约课节 → 纯教材主述 RunRequest（不阻塞）。"""
    async def _mock_text2(*a, **k): return "北京人生活在距今约70万-20万年前的北京周口店。"
    monkeypatch.setattr(
        "hevi.history_series.textbook_bridge.textbook_mainline_from_mneme",
        _mock_text2,
    )
    req = await assemble_textbook_run_request("北京人", "TONGBIAN-G7-HISTORY-S", 1)
    assert "教材主述" in req["raw_text"]
    assert "并陈" not in req["raw_text"]
    assert req["source_name"].endswith("北京人")
