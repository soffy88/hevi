"""N0-D-027 语体量化指标测试:文言高分、白话低分、阈值红旗。"""

from __future__ import annotations

from hevi.n0.register_meter import (
    BAIHUA_THRESHOLD,
    episode_register,
    register_flag,
    wenyan_score,
)

_WENYAN = "骊姬之乱，始于献公嬖宠乱嫡序——晋之公族屏藩自此崩坏；二五谮言，申生缢死于新城。"
_BAIHUA = "献公宠爱骊姬，把嫡长子继承的规矩搞乱了。有人说坏话陷害太子，申生最后在新城上吊死了。"


def test_wenyan_scores_higher_than_baihua() -> None:
    """同一史实,文言腔分数明显高于口语白话。"""
    ws, bs = wenyan_score(_WENYAN), wenyan_score(_BAIHUA)
    assert ws > bs, (ws, bs)
    assert ws > BAIHUA_THRESHOLD  # 文言超阈
    assert bs < BAIHUA_THRESHOLD  # 白话达标


def test_register_flag_red_flags_wenyan() -> None:
    """文言超阈红旗、不送闸④;白话达标。"""
    assert register_flag(wenyan_score(_WENYAN))["red_flag"] is True
    f = register_flag(wenyan_score(_BAIHUA))
    assert f["red_flag"] is False and "达标" in f["verdict"]


def test_episode_register_ignores_onscreen() -> None:
    """onscreen 文言引不计入 vo 语体分(那本就该是文言原文)。"""
    draft = {
        "beats": [
            {
                "beat_id": "b1",
                "sentences": [
                    {"sid": "s1", "presentation": "vo", "text": _BAIHUA},
                    {
                        "sid": "s2",
                        "presentation": "onscreen",
                        "text": "狐裘尨茸，一國三公，吾誰適從",
                    },
                ],
            }
        ]
    }
    r = episode_register(draft)
    # 只算 vo 白话句 → 达标;若误计 onscreen 文言会拉高
    assert r["score"] < BAIHUA_THRESHOLD
    assert all(p["sid"] != "s2" for p in r["per_sentence"])  # onscreen 不入逐句


def test_score_bounded() -> None:
    assert wenyan_score("") == 0.0
    assert 0.0 <= wenyan_score(_WENYAN) <= 1.0
