"""W build_prompt 分门迭代(N0-D-012) 单测——冻结清单 + 本轮仅修目标门。"""

from __future__ import annotations

from hevi.n0.writer import build_prompt

_EP = {"episode_id": "ep:x", "beat_ids": ["b1"]}
_REFS = {"corpus": {}, "ku_events": {}, "theses": {}, "name_registry": []}


def test_prompt_no_feedback_is_full_generation() -> None:
    """首轮无 feedback → 无冻结/修复段(全新生成)。"""
    p = build_prompt(_EP, _REFS)
    assert "冻结清单" not in p
    assert "本轮首要任务" not in p


def test_prompt_frozen_and_target_gates() -> None:
    """有 feedback+frozen → 列冻结 sid 逐字保留 + 仅修目标门。"""
    fb = [{"gate": "H2", "sid": "b2-1", "reason": "未标引文", "fix": "挂 quote"}]
    frozen = [{"sid": "b1-1", "text": "前745年封桓叔。"}, {"sid": "b3-1", "text": "灭翼。"}]
    p = build_prompt(_EP, _REFS, rhard_feedback=fb, frozen=frozen)
    assert "冻结清单" in p
    assert "b1-1" in p and "前745年封桓叔。" in p  # 冻结句逐字入 prompt
    assert "仅修复门 ['H2']" in p  # 本轮只修 H2
    assert "b2-1" in p and "挂 quote" in p  # 目标句 + 修法


def test_prompt_feedback_without_frozen() -> None:
    """有 feedback 无 frozen → 有修复段、无冻结段(向后兼容修正指令化)。"""
    fb = [{"gate": "H4", "sid": "b1-1", "reason": "名缺", "fix": "改述"}]
    p = build_prompt(_EP, _REFS, rhard_feedback=fb)
    assert "本轮首要任务" in p
    assert "冻结清单" not in p
