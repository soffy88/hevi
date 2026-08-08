"""v9.1 生成契约 —— 因果锚点(Authority Receipt) + 防复读规则。

移植自 novel-studio 的 prompt 工程:
  * **Authority Receipt**: 每个生成项必须绑定输入中的因果锚点 —— 不得引入输入中
    不存在的人名/地点/资源/数量/秘密/后台机制, 不得使用事后信息或未来结果;
  * **防复读块**: 已验收内容的相似片段注入, 提示模型避免重复句式。

这些是纯字符串规则, 供 research / script / character_sim 等 prompt 注入。
"""

from __future__ import annotations

AUTHORITY_RECEIPT_RULE = """【因果锚点契约(违反即废稿)】
- 每一项生成内容必须能追溯到输入中的至少两个因果锚点(事件/引语/知识点);
- 禁止引入输入中不存在的人名、地名、官职、封号、资源、数量、秘密或后台机制;
- 禁止使用事后信息或未来结果冒充当前事实(如"后来称帝"不能在事件当下出现);
- 推理/扩写必须标注依据来源, 无法溯源的内容不得写入。"""

ANTI_REPEAT_HEADER = "【防复读记忆】以下句子此前已写过(已验收正文), 生成时避免重复句式与表达:"


def anti_repeat_block(similar_sentences: list[str], *, max_sentences: int = 3) -> str:
    """把检索到的相似已验收句子组成防复读 prompt 块; 空列表返回空串。"""
    if not similar_sentences:
        return ""
    lines = [ANTI_REPEAT_HEADER]
    lines.extend(f"- {s}" for s in similar_sentences[:max_sentences])
    return "\n".join(lines) + "\n\n"


__all__ = ["ANTI_REPEAT_HEADER", "AUTHORITY_RECEIPT_RULE", "anti_repeat_block"]
