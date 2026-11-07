"""Tests for the ai-manju B3 publish pack generator (clean-room).

Two evidence groups (two different season packs) are run end to
end; every word of copy asserted here is supplied by the test
itself, never copied from the source templates. Negative cases
cover hook drift, wrong title counts, invented teasers, over-long
cover text, and season-gate failures.
"""

from __future__ import annotations

import pytest

from hevi.capabilities import get as _get_capability
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.publish_pack_generator import build_publish_pack


def _pack(episode_hooks):
    episodes = [
        {
            "episode_no": number,
            "duration_s": 240.0,
            "scenes": 5,
            "hook": hook,
        }
        for number, hook in enumerate(episode_hooks, start=1)
    ]
    return {
        "season_no": 1,
        "duration_tier_provider": "pixstag",
        "foreshadow_ledger": ["伏笔一"],
        "clue_ledger": ["线索一"],
        "episodes": episodes,
        "episode_synopses": {
            str(number): f"本集梗概，关键处是{hook}，由此展开。"
            for number, hook in enumerate(episode_hooks, start=1)
        },
    }


def _episode(number, hook, synopsis, *, next_hook=None, cover_text="封面短句"):
    entry = {
        "episode_no": number,
        "hook": hook,
        "synopsis": synopsis,
        "hook_titles": [f"标题一-{number}", f"标题二-{number}", f"标题三-{number}"],
        "hashtags": ["#短剧", "#原创"],
        "pinned_comment": f"置顶评论-{number}",
        "cover": {
            "subject": f"封面主体-{number}",
            "composition": f"封面构图-{number}",
            "text_on_cover": cover_text,
        },
    }
    if next_hook is not None:
        entry["next_hook"] = next_hook
    return entry


def _synopsis(hook, number):
    return f"本集梗概，关键处是{hook}，由此展开。"


# ---- Evidence group A: two episodes ----

def test_b3_group_a_two_episodes():
    hooks = ["钩子甲", "钩子乙"]
    pack = _pack(hooks)
    episodes = [
        _episode(1, hooks[0], _synopsis(hooks[0], 1), next_hook=hooks[1]),
        _episode(2, hooks[1], _synopsis(hooks[1], 2)),
    ]
    result = build_publish_pack(pack, episodes)
    assert result["status"] == "draft_not_published"
    assert result["season_no"] == 1
    assert result["episode_count"] == 2
    first, second = result["episodes"]
    assert first["end_card"]["status"] == "teaser_from_caller_hook"
    assert first["end_card"]["teaser_text"] == hooks[1]
    assert first["end_card"]["next_episode_no"] == 2
    assert second["end_card"]["status"] == "no_next_episode"
    assert second["end_card"]["teaser_text"] is None
    for episode in result["episodes"]:
        assert set(episode["cover"]["aspects"]) == {"3:4", "4:3"}
        assert "description_only" in episode["cover"]["image_status"]
        assert episode["cover"]["aspects"]["3:4"]["subject"] == episode["cover"]["aspects"]["4:3"]["subject"]
        assert episode["ai_label"]["ai_generated"] is True
        assert episode["ai_label"]["human_review"] == "pending"
        assert episode["ai_label"]["scale_declarations"] == "not_checked"
        assert len(episode["copy"]["hook_titles"]) == 3
    assert first["copy"]["hook_titles"] == ["标题一-1", "标题二-1", "标题三-1"]
    assert first["copy"]["synopsis"] == _synopsis(hooks[0], 1)


# ---- Evidence group B: three episodes, caller scale declarations ----

def test_b3_group_b_three_episodes_with_scale_declarations():
    hooks = ["钩子丙", "钩子丁", "钩子戊"]
    pack = _pack(hooks)
    episodes = [
        _episode(1, hooks[0], _synopsis(hooks[0], 1), next_hook=hooks[1]),
        _episode(2, hooks[1], _synopsis(hooks[1], 2), next_hook=hooks[2]),
        _episode(3, hooks[2], _synopsis(hooks[2], 3)),
    ]
    scale = {"minors": "no_minor_characters", "intimacy": "adults_only_implied"}
    result = build_publish_pack(pack, episodes, scale_declarations=scale)
    assert result["episode_count"] == 3
    assert result["episodes"][1]["end_card"]["teaser_text"] == hooks[2]
    assert result["episodes"][2]["end_card"]["status"] == "no_next_episode"
    for episode in result["episodes"]:
        assert episode["ai_label"]["scale_declarations"] == scale
        assert "not_checked" in episode["ai_label"]["platform_rules"]


def test_b3_registered_on_the_registry():
    capability = _get_capability("story.publish_pack_generator")
    assert capability.name == "story.publish_pack_generator"


# ---- Negative cases ----

def test_b3_hook_mismatch_with_pack_fails():
    hooks = ["钩子甲", "钩子乙"]
    pack = _pack(hooks)
    episodes = [
        _episode(1, "另一个钩子", _synopsis("另一个钩子", 1), next_hook=hooks[1]),
        _episode(2, hooks[1], _synopsis(hooks[1], 2)),
    ]
    with pytest.raises(CapabilityError):
        build_publish_pack(pack, episodes)


def test_b3_episode_count_mismatch_fails():
    pack = _pack(["钩子甲", "钩子乙"])
    with pytest.raises(CapabilityError):
        build_publish_pack(pack, [_episode(1, "钩子甲", _synopsis("钩子甲", 1))])


def test_b3_wrong_title_count_fails():
    pack = _pack(["钩子甲"])
    entry = _episode(1, "钩子甲", _synopsis("钩子甲", 1))
    entry["hook_titles"] = ["只有一个标题"]
    with pytest.raises(CapabilityError):
        build_publish_pack(pack, [entry])


def test_b3_teaser_on_last_episode_fails():
    pack = _pack(["钩子甲"])
    entry = _episode(1, "钩子甲", _synopsis("钩子甲", 1), next_hook="钩子甲")
    with pytest.raises(CapabilityError):
        build_publish_pack(pack, [entry])


def test_b3_teaser_must_quote_next_pack_hook():
    hooks = ["钩子甲", "钩子乙"]
    pack = _pack(hooks)
    episodes = [
        _episode(1, hooks[0], _synopsis(hooks[0], 1), next_hook="编造的预告"),
        _episode(2, hooks[1], _synopsis(hooks[1], 2)),
    ]
    with pytest.raises(CapabilityError):
        build_publish_pack(pack, episodes)


def test_b3_cover_text_over_limit_fails():
    pack = _pack(["钩子甲"])
    entry = _episode(1, "钩子甲", _synopsis("钩子甲", 1), cover_text="x" * 31)
    with pytest.raises(CapabilityError):
        build_publish_pack(pack, [entry])


def test_b3_synopsis_without_hook_fails():
    pack = _pack(["钩子甲"])
    entry = _episode(1, "钩子甲", "毫不相关的梗概文字。")
    with pytest.raises(CapabilityError):
        build_publish_pack(pack, [entry])


def test_b3_failing_season_pack_fails():
    pack = _pack(["钩子甲", "钩子乙"])
    pack["episodes"][1]["duration_s"] = 100.0
    episodes = [
        _episode(1, "钩子甲", _synopsis("钩子甲", 1), next_hook="钩子乙"),
        _episode(2, "钩子乙", _synopsis("钩子乙", 2)),
    ]
    with pytest.raises(CapabilityError):
        build_publish_pack(pack, episodes)
