"""v9.1 防复读记忆 + 生成契约单测。"""

from __future__ import annotations

import pytest

from hevi.prompting.anti_repeat import AntiRepeatMemory, memory_fingerprint
from hevi.prompting.contracts import AUTHORITY_RECEIPT_RULE, anti_repeat_block


def test_remember_and_retrieve_similar(tmp_path: pytest.TempPathFactory) -> None:
    m = AntiRepeatMemory("资治通鉴·周纪一", root=tmp_path)
    assert m.size == 0
    # 吸收一段已验收剧本。
    added = m.remember("智伯恃强向赵襄子索地，赵襄子坚辞不与。双方剑拔弩张，晋阳城外风声鹤唳。")
    assert added >= 1
    assert m.size >= 1
    # 检索近字面重复(防复读核心: 同一句式复用必须被抓到)。
    similar = m.similar_to("智伯恃强向赵襄子索地，赵襄子坚辞不与。")
    assert similar, "近字面重复句应被检索到"
    assert any("智伯" in s for s in similar)
    # 完全不同的内容不误报。
    assert m.similar_to("春天来了，燕子飞回北方筑巢。") == []


def test_remember_dedup(tmp_path: pytest.TempPathFactory) -> None:
    m = AntiRepeatMemory("s1", root=tmp_path)
    text = "同样的句子。同样的句子。"
    first = m.remember(text)
    second = m.remember(text)
    assert second == 0  # 去重: 二次吸收无新增
    assert m.size == first


def test_similar_to_empty_when_no_memory(tmp_path: pytest.TempPathFactory) -> None:
    m = AntiRepeatMemory("empty", root=tmp_path)
    assert m.similar_to("任意文本") == []
    assert m.remember("") == 0


def test_fingerprint_changes_with_content() -> None:
    assert memory_fingerprint(["甲"]) != memory_fingerprint(["乙"])
    assert memory_fingerprint(["甲", "乙"]) == memory_fingerprint(["甲", "乙"])


def test_anti_repeat_block() -> None:
    block = anti_repeat_block(["旧句式一", "旧句式二"])
    assert "防复读记忆" in block
    assert "旧句式一" in block
    assert anti_repeat_block([]) == ""
    limited = anti_repeat_block(["a", "b", "c", "d"], max_sentences=2)
    assert limited.count("- ") <= 2


def test_authority_receipt_rule_present() -> None:
    assert "因果锚点" in AUTHORITY_RECEIPT_RULE
    assert "禁止引入输入中不存在" in AUTHORITY_RECEIPT_RULE
    assert "未来结果" in AUTHORITY_RECEIPT_RULE
