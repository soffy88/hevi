"""G1a 弧适配器单测 —— §8 契约 → RunRequest 组装（P0 契约先行）。

数据源：stratum/docs/history/contracts/sample.sanjiafenjin.json（冻结样例）。
不依赖 LLM/网络，纯函数验证组装正确性。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hevi.history_series.arc_adapter import assemble_run_request, dump_g1a_report

_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "history_series" / "fixtures" / "sample.sanjiafenjin.json"
)


@pytest.fixture()
def contract() -> dict:
    """把 stratum 冻结契约样例复制进 hevi 测试 fixtures（单点留痕）。"""
    src = Path("/data/soffy/projects/stratum/docs/history/contracts/sample.sanjiafenjin.json")
    if not src.exists():
        pytest.skip("stratum 契约样例缺失")
    return json.loads(src.read_text())


def test_assemble_source_name_and_raw_text(contract):
    """source_name 带事件标题；raw_text 含主述（史记）并陈（通鉴/战国策）+ 出处。"""
    req = assemble_run_request(contract)
    assert req["source_name"] == "历史现场·晋阳之战（智伯之亡）"
    assert "史记·赵世家" in req["raw_text"]          # 主述出处标注
    assert "（并陈）" in req["raw_text"]              # 并陈块
    assert "资治通鉴·周纪一" in req["raw_text"]      # 并陈出处
    assert "战国策·赵策一" in req["raw_text"]
    assert "城中懸釜而炊" in req["raw_text"]  # 主述原文(史记·赵世家)


def test_mainline_account_choice(contract):
    """主述 = event.mainline_account_ref（史记·赵世家），不是第一条。"""
    next(a for a in contract["accounts"] if a["account_id"] == "ac:jinyang-shiji")
    req = assemble_run_request(contract)
    assert "知伯益驕" in req["raw_text"]              # 史记·赵世家原文（主述）
    assert "智伯請地於韓康子" in req["raw_text"]      # 通鉴原文（并陈）


def test_conflict_corner_note(contract):
    """冲突 presentation_hint=主线+角标 → 并陈角标追加进 raw_text。"""
    req = assemble_run_request(contract)
    assert "并陈角标" in req["raw_text"]
    assert "独立见证" in req["raw_text"] or "独立" in req["raw_text"]


def test_registry_injection(contract):
    """registry_bundle persons → layer_config L1 character_refs。"""
    req = assemble_run_request(contract)
    l1 = req["layer_config"].get("L1", {})
    refs = l1.get("character_refs", [])
    assert any(r["ref"] == "per:zhibo" for r in refs)
    zhibo = next(r for r in refs if r["ref"] == "per:zhibo")
    assert "智伯" in zhibo["names"]                    # 别名注入


def test_textbook_mainline_override(contract):
    """教材主述（D5）：textbook_text 传入时主述=教材，古籍全并陈。"""
    req = assemble_run_request(
        contract, textbook_text="春秋末期，晋国大权旁落于智、赵、韩、魏四卿。"
    )
    assert "（教材主述）" in req["raw_text"]
    assert "春秋末期" in req["raw_text"]
    # 教材主述时：史记原文也进并陈（不再独占主述位）
    assert "（并陈）" in req["raw_text"]
    assert "资治通鉴" in req["raw_text"]


def test_g1a_report(contract):
    """对拍报告可读：字段摘要 + 组装信息。"""
    req = assemble_run_request(contract)
    report = dump_g1a_report(contract, req)
    assert report["event_id"] == "ev:jinyang-zhizhan"
    assert report["mainline_account"] == "ac:jinyang-shiji"
    assert report["n_accounts"] == 3
    assert report["n_conflicts"] == 1
    assert report["registry_persons"] >= 4
    assert "历史现场·晋阳之战" in report["source_name"]
