"""IP 安全改写 pass(HEVI 路线图 Phase2 #36)。

处理用户提交的自由文本(topic/角色描述)里涉及真人/名人/受版权保护角色/品牌 logo
的情况——改写成安全等价物,而不是简单拦截。这一条对 hevi 比对个人 prompt 工具
作者更重要:平台方是担责主体,而剧情输入/角色描述允许任意自由文本,风险敞口是
真实存在的,不是假设性的。

没有可维护的"名人/版权角色黑名单"(数量级不可穷举),这必须是 LLM 判断,不是
关键词匹配——同 identity_pack.py 的年代审核走的是同一个"默认通过、按需要才改写"
设计,不是逐字符串比对。

图片(角色库上传照片)是否描绘真人名人/版权角色是完全不同的判定问题("改写成
安全等价物"对图像没有直接对应的操作,不能像文本一样重写措辞)——这里只处理
文本,图像screening 是单独的、更受限的范围(见 hevi/subjects/ip_screening.py)。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_IP_SAFETY_PROMPT = """检查下面这段视频制作文本描述,判断是否涉及以下任意一类内容:
- 提及具体的真实人物/公众人物/名人姓名(不是泛指的"一个人"这类描述)
- 提及具体的受版权保护的虚构角色(已有影视/游戏/动漫作品里的角色名)
- 提及具体品牌/商标名称

如果涉及,把涉及的部分改写成安全的原创等价物(换成虚构名字 + 原创但意图相近的
外观/设定描述),不改变叙事其余部分;如果不涉及,原样返回,不要画蛇添足地改写
无关内容。

只输出 JSON:{{"flagged": ["原文里涉及的具体词"], "rewritten": "改写后(或原文不变,
两种情况都要给完整文本)的完整文本"}}

文本:{text}"""


async def rewrite_for_ip_safety(text: str, *, llm: Any = None) -> tuple[str, list[str]]:
    """→ (改写后文本, 命中的敏感词列表)。

    best-effort:LLM 不可用/调用失败/输出解析失败 → 原样返回原文、空命中列表——
    绝不能因为这一步而阻断生成或返回空/损坏的文本(同 hevi 其它 lint/审核步骤的
    既有惯例:安全检查本身的故障不该变成新的可用性故障)。
    """
    if not text or not text.strip():
        return text, []
    if llm is None:
        try:
            from obase.provider_registry import ProviderRegistry

            llm = ProviderRegistry.get().llm("default")
        except Exception as e:
            logger.warning("ip_safety: no LLM available, skip check: %s", e)
            return text, []
    try:
        resp = await llm(
            messages=[{"role": "user", "content": _IP_SAFETY_PROMPT.format(text=text)}],
            max_tokens=1024,
        )
        content = resp.get("content") if hasattr(resp, "get") else str(resp)
        m = re.search(r"\{.*\}", content, re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
        flagged = [str(x) for x in (data.get("flagged") or [])]
        rewritten = data.get("rewritten")
        if flagged and rewritten:
            logger.info("ip_safety: rewrote text, flagged=%s", flagged)
            return str(rewritten), flagged
        return text, flagged
    except Exception as e:
        logger.warning("ip_safety: rewrite failed, using original text: %s", e)
        return text, []
