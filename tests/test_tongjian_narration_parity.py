"""narration 考据对勘门测试(SPEC-005-V2)——商鞅立木首跑撞见的缺口:G2 不查 narration
地名/数字精度。纯确定性字符串对勘,不碰 LLM。"""

from __future__ import annotations

from hevi.tongjian.gates import lint_narration_source_parity
from hevi.tongjian.schemas import Script, ScriptLine

_RAW = (
    "秦孝公用卫鞅之谋,乃立三丈之木于国都市南门,募民有能徙置北门者予十金。"
    "复曰:「能徙者予五十金!」有一人徙之,辄予五十金。"
)


def _script(*narration_texts: str) -> Script:
    return Script(
        lines=[
            ScriptLine(line_id=f"n{i}", type="narration", text=t)
            for i, t in enumerate(narration_texts)
        ]
    )


def test_number_conflict_is_error() -> None:
    # narration 一丈 vs 原文 三丈 → 硬错(商鞅立木首跑实证的那一个)
    g = lint_narration_source_parity(_script("一丈长的圆木立于南门"), _RAW)
    assert g.passed is False
    assert any("一丈" in e and "三丈" in e for e in g.errors)


def test_number_matching_source_is_clean() -> None:
    # narration 三丈(与原文一致)+ 十金(原文有)→ 无冲突
    g = lint_narration_source_parity(_script("三丈之木,赏十金"), _RAW)
    assert g.passed is True
    assert not g.errors


def test_place_not_in_source_is_speculation_warning() -> None:
    # 咸阳 原文未载 → speculation 警告(非硬错,需人确认年代)
    g = lint_narration_source_parity(_script("咸阳市东,青石铺地"), _RAW)
    assert g.passed is True  # warning 不阻断
    assert any("咸阳" in w for w in g.warnings)
    # 修正版栎阳同样原文未载 → 也标 speculation(交人确认年代正确),这是设计如此
    g2 = lint_narration_source_parity(_script("栎阳市东"), _RAW)
    assert any("栎阳" in w for w in g2.warnings)


def test_anachronism_term_is_warning() -> None:
    g = lint_narration_source_parity(_script("商鞅坐在椅子上,翻着纸卷"), _RAW)
    warns = " ".join(g.warnings)
    assert "椅" in warns and "纸" in warns


def test_dialogue_lines_ignored() -> None:
    # 只查 narration;dialogue 行的数字/地名不参与对勘(对白已由 G2 quote_id 溯源管)
    s = Script(
        lines=[ScriptLine(line_id="d1", type="dialogue", speaker="C", text="搬到咸阳去,赏一丈布")]
    )
    g = lint_narration_source_parity(s, _RAW)
    assert g.passed is True and not g.errors and not g.warnings
