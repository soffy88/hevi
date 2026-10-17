"""N0-D-029 双向语体门测试:文言腔/口语腔两头都拦,只放规范书面史述。"""

from __future__ import annotations

from hevi.n0.register_meter import (
    KOUTOU_MAX,
    WENYAN_MAX,
    episode_register,
    koutou_score,
    register_flag,
    wenyan_score,
)

_WIKI = "晋献公宠爱骊姬，为了让骊姬之子继位，骊姬设计诬陷，逼死了太子申生。公子重耳与夷吾预感大祸临头，先后逃离晋国。"
_WENYAN = "骊姬之乱，始于献公嬖宠乱嫡序；二五谮言，申生缢死于新城，重耳夷吾相继出奔。"
_KOUYU = "骊姬那事儿其实就是因为献公特别宠她，结果太子被使坏逼死了，重耳夷吾俩吓得赶紧跑了。"


def test_wiki_anchor_passes_both() -> None:
    """Wiki 锚定目标样句:文言度、口语度双低 → 达标。"""
    wy, ko = wenyan_score(_WIKI), koutou_score(_WIKI)
    assert wy < WENYAN_MAX and ko < KOUTOU_MAX
    assert register_flag(wy, ko)["red_flag"] is False


def test_wenyan_flagged() -> None:
    """文言腔:文言度超标红旗(夷吾人名不误伤、诬陷不误判)。"""
    wy, ko = wenyan_score(_WENYAN), koutou_score(_WENYAN)
    assert wy > WENYAN_MAX
    f = register_flag(wy, ko)
    assert f["red_flag"] is True and "文言" in f["verdict"]


def test_kouyu_flagged() -> None:
    """口语聊天腔:口语度超标红旗。"""
    wy, ko = wenyan_score(_KOUYU), koutou_score(_KOUYU)
    assert ko > KOUTOU_MAX
    f = register_flag(wy, ko)
    assert f["red_flag"] is True and "口语" in f["verdict"]


def test_name_not_false_positive() -> None:
    """夷吾(人名含吾)、诬陷(书面)不被当文言误判。"""
    assert wenyan_score("重耳与夷吾预感大祸临头") < WENYAN_MAX
    assert wenyan_score("骊姬设计诬陷太子") < WENYAN_MAX


def test_episode_register_bidirectional() -> None:
    draft = {
        "beats": [
            {
                "beat_id": "b1",
                "sentences": [
                    {"sid": "s1", "presentation": "vo", "text": _WIKI},
                    {"sid": "s2", "presentation": "onscreen", "text": "缢死于新城嬖宠乱嫡"},
                ],
            }
        ]
    }
    r = episode_register(draft)
    assert r["wenyan"] < WENYAN_MAX and r["koutou"] < KOUTOU_MAX  # onscreen 文言不计
    assert all(p["sid"] != "s2" for p in r["per_sentence"])
