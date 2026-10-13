"""stickdir 提案生成器测试 —— schema / 白名单 / 无编造 / 调度 / continuity。"""

from __future__ import annotations

import pytest

from hevi.layer4_legacy.stickdir import narration, proposal, schema, storyboard, whitelist

COPY = (
    "很多人以为效率来自更努力。其实真正的效率来自更少的选择。"
    "当选项变多，大脑每一步都要重新评估，决策成本会吃掉你全部的时间。"
    "顶尖的人不是做得更多，而是把不重要的事情直接删掉。"
    "删掉一件事，胜过完成三件事。所以别再问怎么才能做得更快，先问这件事到底该不该做。"
)


# ---------------------------------------------------------------------------
# setup gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("aspect,style", [(None, "1B"), ("9:16", None), (None, None)])
def test_setup_gate_requires_aspect_and_style(aspect, style):
    with pytest.raises(proposal.SetupError):
        proposal.build_proposal(copy=COPY, aspect=aspect, style=style, duration=30)


def test_setup_gate_rejects_unknown_values():
    with pytest.raises(proposal.SetupError):
        proposal.build_proposal(copy=COPY, aspect="4:3", style="1B", duration=30)
    with pytest.raises(proposal.SetupError):
        proposal.build_proposal(copy=COPY, aspect="9:16", style="9Z", duration=30)


def test_duration_defaults_to_60():
    p = proposal.build_proposal(copy=COPY, aspect="9:16", style="1B", duration=None)
    assert p.data["duration"] == 60
    assert len(p.data["storyboard"]["segments"]) == 6


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("style", whitelist.STYLE)
@pytest.mark.parametrize("aspect", whitelist.ASPECT)
def test_schema_validates_all_style_aspect(aspect, style):
    p = proposal.build_proposal(copy=COPY, aspect=aspect, style=style, duration=30)
    schema.validate(p.data)  # 不抛即通过


def test_schema_rejects_bad_accent_count():
    p = proposal.build_proposal(copy=COPY, aspect="9:16", style="1A", duration=30)
    bad = dict(p.data)
    bad["palette"] = dict(p.data["palette"], accents=list(whitelist.ACCENT[:4]))
    with pytest.raises(schema.SchemaError):
        schema.validate(bad)


def test_schema_rejects_bad_staging():
    p = proposal.build_proposal(copy=COPY, aspect="16:9", style="1A", duration=30)
    bad = dict(p.data)
    sb = dict(p.data["storyboard"])
    segs = [dict(s) for s in sb["segments"]]
    beats = [dict(b) for b in segs[0]["beats"]]
    beats[0]["staging"] = "foreground"  # 9:16 的调度, 不该出现在 16:9
    segs[0]["beats"] = beats
    sb["segments"] = segs
    bad["storyboard"] = sb
    with pytest.raises(schema.SchemaError):
        schema.validate(bad)


# ---------------------------------------------------------------------------
# 无编造校验
# ---------------------------------------------------------------------------


def test_no_fabrication_flags_invented_number():
    src = "效率来自更少的选择。"
    assert narration.verify_no_fabrication(src, "效率来自更少的选择。") == []
    assert any(
        v.startswith("number:") for v in narration.verify_no_fabrication(src, "效率提升了三倍。")
    )


def test_no_fabrication_number_matches_across_scripts():
    # 阿拉伯与中文数字互通
    assert narration.verify_no_fabrication("有三个办法", "一共 3 个办法") == []


def test_no_fabrication_flags_invented_name_and_quote():
    src = "专注能带来效率。"
    assert any(
        v.startswith("name:") for v in narration.verify_no_fabrication(src, "乔布斯说过这件事。")
    )
    assert any(
        v.startswith("quote:") for v in narration.verify_no_fabrication(src, "他说「专注最重要」。")
    )


def test_fallback_rewrite_never_fabricates():
    nar = narration.fallback_rewrite(COPY, 30, "1B")
    assert narration.verify_no_fabrication(COPY, nar.full_text) == []


def test_llm_rewrite_with_fabrication_is_rejected():
    # 伪造的 LLM: 凭空加数字 + 人名
    def fake(_prompt: str) -> str:
        return '{"stages":[{"stage":"hook","text":"爱因斯坦说效率能提升 300%。"}]}'

    nar = narration.rewrite(COPY, 30, "1B", complete=fake)
    assert nar.method == "fallback"
    assert narration.verify_no_fabrication(COPY, nar.full_text) == []


def test_llm_rewrite_used_when_clean():
    def fake(_prompt: str) -> str:
        return (
            '{"stages":['
            '{"stage":"hook","text":"很多人以为效率来自更努力。"},'
            '{"stage":"disrupt","text":"其实真正的效率来自更少的选择。"},'
            '{"stage":"mechanism","text":"当选项变多，决策成本会吃掉你全部的时间。"},'
            '{"stage":"conclusion","text":"顶尖的人把不重要的事直接删掉。"},'
            '{"stage":"callback","text":"所以先问这件事到底该不该做。"}'
            "]}"
        )

    nar = narration.rewrite(COPY, 30, "1B", complete=fake)
    assert nar.method == "llm"
    assert narration.verify_no_fabrication(COPY, nar.full_text) == []


def test_llm_rewrite_failure_falls_back():
    def boom(_prompt: str) -> str:
        raise RuntimeError("ollama down")

    nar = narration.rewrite(COPY, 30, "1B", complete=boom)
    assert nar.method == "fallback"


# ---------------------------------------------------------------------------
# 白名单收敛
# ---------------------------------------------------------------------------


def test_sanitize_beats_corrects_out_of_whitelist():
    raw = [{"action": "fly", "prop": "none", "metaphor": "none", "camera": "zoom"}]
    plan = storyboard._STAGE_PLAN["hook"]
    rows, corr = storyboard.sanitize_beats(raw, "9:16", 0, plan)
    assert rows[0]["action"] == plan["beats"][0][0]  # 回退到确定性动作
    assert rows[0]["camera"] == plan["beats"][0][3]
    assert any("action='fly'" in c for c in corr)
    assert any("camera='zoom'" in c for c in corr)


def test_llm_beats_all_in_whitelist_after_sanitize():
    llm_beats = [
        [{"action": "fly", "prop": "banana", "metaphor": "zzz", "camera": "zoom"}] * 3,
        [{"action": "walk", "prop": "line", "metaphor": "ladder", "camera": "track"}] * 3,
        [{"action": "wave", "prop": "none", "metaphor": "none", "camera": "static"}] * 3,
    ]
    sb = storyboard.build_storyboard(
        aspect="9:16", duration=30, style="1B", narration_stages=[], llm_beats=llm_beats
    )
    for seg in sb.segments:
        for b in seg.beats:
            assert whitelist.is_valid("action", b.action)
            assert whitelist.is_valid("prop", b.prop)
            assert whitelist.is_valid("metaphor", b.metaphor)
            assert whitelist.is_valid("camera", b.camera)


# ---------------------------------------------------------------------------
# 调度差异 / continuity
# ---------------------------------------------------------------------------


def test_staging_differs_by_aspect():
    p9 = proposal.build_proposal(copy=COPY, aspect="9:16", style="1A", duration=30)
    p16 = proposal.build_proposal(copy=COPY, aspect="16:9", style="1A", duration=30)
    s9 = {b["staging"] for s in p9.data["storyboard"]["segments"] for b in s["beats"]}
    s16 = {b["staging"] for s in p16.data["storyboard"]["segments"] for b in s["beats"]}
    assert s9 <= set(whitelist.STAGING_9_16)
    assert s16 <= set(whitelist.STAGING_16_9)
    assert s9 != s16


@pytest.mark.parametrize("duration", [30, 60, 90])
def test_continuity_holds(duration):
    p = proposal.build_proposal(copy=COPY, aspect="16:9", style="2A", duration=duration)
    assert (
        storyboard.check_continuity(
            storyboard.Storyboard(
                aspect="16:9",
                duration=duration,
                style="2A",
                segments=[],
            )
        )
        == []
    )  # 空表无违规
    segs = p.data["storyboard"]["segments"]
    for i in range(len(segs) - 1):
        assert segs[i]["continuity_out"] == segs[i + 1]["continuity_in"]
        assert segs[i]["beats"][-1]["action"] == segs[i + 1]["beats"][0]["action"]


def test_segment_count_matches_duration():
    for dur, n in [(30, 3), (60, 6), (90, 9)]:
        p = proposal.build_proposal(copy=COPY, aspect="9:16", style="1B", duration=dur)
        assert len(p.data["storyboard"]["segments"]) == n


def test_arc_stage3_uses_setup_escalation_payoff():
    p = proposal.build_proposal(copy=COPY, aspect="16:9", style="3", duration=30)
    stages = [s["stage"] for s in p.data["storyboard"]["segments"]]
    assert stages[0] == "setup"
    assert stages[-1] == "payoff"


def test_actions_all_renderable():
    whitelist.assert_renderable(whitelist.ACTION)
