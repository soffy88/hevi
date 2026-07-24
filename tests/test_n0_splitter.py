"""post-W splitter(N0-D-003) 单测：确定性收尾把超窗拍拆到落窗，不碰 quote/ref/归属。"""

from __future__ import annotations

from hevi.n0.rhard import run_rhard
from hevi.n0.splitter import _beat_secs, split_overlong


def _refs() -> dict:
    return {
        "corpus": {"u:s": "本既弱矣其能久乎"},
        "ku_events": {"ev:e1": {}},
        "ku_accounts": {},
        "theses": {"thesis:t1": {}},
        "chronology": {},
        "number_claims": {},
        "name_registry": {"师服", "晋", "曲沃"},
        "pool_ids": set(),
        "e_tiers": {"ev:e1": "E2"},
        "episode_plan": {
            "beat_ids": ["b1"],
            "counterpoint_theses": [],
            "counterpoint_search_record": {"x": 1},
            "s12_conflicts": [],
            "beat_events": {"b1": ["ev:e1"]},
        },
    }


def _overwindow_draft() -> dict:
    # 单句 thesis 拍，含 8 字逐字引文 + 大量口播 → 分段估时 >15s；句中有多处分句边界（；，）。
    text = (
        "师服有言；晋以支庶封建而本既弱矣其能久乎；此本大末小之理，末大必折之应；"
        "曲沃三代经营，终以小宗并吞大宗，晋室之衰由此肇端，实为春秋权力下移之始，不可挽也。"
    )
    return {
        "episode_ref": "ep:x",
        "beats": [
            {
                "beat_id": "b1",
                "sentences": [
                    {
                        "sid": "b1-1",
                        "type": "thesis",
                        "thesis_refs": ["thesis:t1"],
                        "fact_refs": [],
                        "text": text,
                        "quote": {"ulid": "u:s", "text": "本既弱矣其能久乎"},
                        "entities": ["师服", "晋", "曲沃"],
                        "display": {"attribution": "我方按"},
                    }
                ],
            }
        ],
        "meta": {},
    }


def test_overwindow_beat_splits_and_passes_h8() -> None:
    refs, draft = _refs(), _overwindow_draft()
    assert _beat_secs(draft["beats"][0]) > 15.0  # 拆前超窗
    assert run_rhard(draft, refs)["by_gate"]["H8"] == "FAIL"

    split = split_overlong(draft)
    rep = run_rhard(split, refs)
    # 拆后 H8 过；H1/H2/H4 不受影响
    assert rep["by_gate"]["H8"] == "PASS", rep["failures"]
    assert rep["by_gate"]["H1"] == "PASS"
    assert rep["by_gate"]["H2"] == "PASS"
    assert rep["by_gate"]["H4"] == "PASS"
    assert len(split["beats"]) >= 2  # 确实拆成多拍
    # 每个子拍落窗
    assert all(_beat_secs(b) <= 15.0 for b in split["beats"])


def test_split_preserves_type_and_refs() -> None:
    _refs()
    split = split_overlong(_overwindow_draft())
    for b in split["beats"]:
        for s in b["sentences"]:
            assert s["type"] == "thesis"  # 归属不变
            assert s["thesis_refs"] == ["thesis:t1"]
            assert (s.get("display") or {}).get("attribution")  # attribution 继承


def test_quote_span_intact_after_split() -> None:
    split = split_overlong(_overwindow_draft())
    # 引文只应出现在含它的那半句，且逐字不动
    q_sids = [
        (s["sid"], s["quote"]["text"])
        for b in split["beats"]
        for s in b["sentences"]
        if "quote" in s
    ]
    assert len(q_sids) == 1  # 引文归一句
    assert q_sids[0][1] == "本既弱矣其能久乎"  # 一字不动


def test_unsplittable_pure_quote_beat_fails_not_hidden() -> None:
    """整句即长逐字引文、无引文外分句边界 → 不可拆 → 原样交 R-hard 判 FAIL（不掩盖）。"""
    long_q = (
        "本大而末小是以能固故天子建國諸侯立家卿置側室大夫有貳宗士有隸子弟庶人工商各有分親皆有等衰"
    )
    refs = _refs()
    refs["corpus"] = {"u:long": long_q}
    draft = {
        "episode_ref": "ep:x",
        "beats": [
            {
                "beat_id": "b1",
                "sentences": [
                    {
                        "sid": "b1-1",
                        "type": "thesis",
                        "thesis_refs": ["thesis:t1"],
                        "fact_refs": [],
                        "text": long_q,  # 整句=引文，无引文外边界
                        "quote": {"ulid": "u:long", "text": long_q},
                        "entities": [],
                        "display": {"attribution": "我方按"},
                    }
                ],
            }
        ],
    }
    assert _beat_secs(draft["beats"][0]) > 15.0
    split = split_overlong(draft)
    assert len(split["beats"]) == 1  # 不可拆，原样
    assert run_rhard(split, refs)["by_gate"]["H8"] == "FAIL"  # 不掩盖
