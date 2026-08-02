"""素材与剧本对位校验算法 — oskill 边界纯算法(3O §3 Task 3.1)。

SPEC §3 要求的 ``oskill.match_score_calculator`` 增强功能,当前以 Hevi 项目侧
暂驻实现(stateless、无 IO、确定性),目标上游至 oskill 主库:
``oskill.match_score_calculator.calculate_stock_match_score``。

对位得分 (0.0-1.0) = 文本语义相似度(字符 n-gram 重合率,中英文通用)
                          × 0.7 + StylePack 关键词匹配率 × 0.3
"""

from __future__ import annotations

import itertools
import re
from collections import Counter
from typing import Any

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+")
_STOPWORDS = frozenset(
    {
        "的", "了", "和", "与", "及", "在", "是", "有", "这", "那", "一个", "之",
        "the", "a", "an", "of", "and", "or", "in", "on", "with", "to", "for",
    }
)


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


def _ngrams(tokens: list[str], n: int = 2) -> Counter[tuple[str, str]]:
    if len(tokens) >= n:
        return Counter(itertools.pairwise(tokens))
    if len(tokens) == 1:
        return Counter([(tokens[0], tokens[0])])
    return Counter()


def _textual_similarity(a: str, b: str) -> float:
    """字符 n-gram 重合率(Jaccard):对中英文混合描述稳健,不依赖词表。"""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    na, nb = _ngrams(ta), _ngrams(tb)
    if not na or not nb:
        return 0.0
    inter = sum((na & nb).values())
    union = sum((na | nb).values())
    return inter / union if union else 0.0


def _keyword_match_rate(
    shot_prompt: str, stock_metadata: dict[str, Any], style_keywords: list[str]
) -> float:
    """StylePack 关键词在分镜描述 / 素材元数据中的匹配率(双向覆盖)。"""
    haystacks = " ".join(
        [
            shot_prompt,
            str(stock_metadata.get("title", "")),
            str(stock_metadata.get("description", "")),
            " ".join(map(str, stock_metadata.get("tags", []) or [])),
        ]
    ).lower()
    if not style_keywords:
        return 0.0
    hit = sum(1 for kw in style_keywords if kw.strip().lower() in haystacks)
    return hit / len(style_keywords)


def calculate_stock_match_score(
    shot_prompt: str,
    stock_metadata: dict[str, Any],
    *,
    style_pack_keywords: list[str] | None = None,
) -> float:
    """计算分镜描述与素材元数据的对位校验得分 (0.0 - 1.0)。

    结合文本语义相似度 + StylePack 关键词匹配率。

    Args:
        shot_prompt: 分镜描述文本(如 "夜雨中的古城墙, 士兵举着火把")。
        stock_metadata: 素材元数据,支持键:
            title / description / tags(list[str]) 用于语义相似度与关键词匹配;
            provider / external_id / width / height 等字段仅透传不影响得分。
        style_pack_keywords: StylePack 风格关键词列表(可选)。

    Returns:
        float 0.0-1.0;无有效文本输入时返回 0.0(不匹配,由调用方决定回退)。

    Note:
        纯算法、stateless、确定性 —— 同一输入恒得同一输出,可安全上游至 oskill。
    """
    semantic = _textual_similarity(shot_prompt, _metadata_text(stock_metadata))
    keywords = style_pack_keywords or []
    kw_rate = _keyword_match_rate(shot_prompt, stock_metadata, keywords)
    # 加权:语义为主(0.7),StylePack 关键词为辅(0.3);有关键词但语义为 0 时
    # 不整体归零,避免"只有关键词命中"的素材被一刀切。
    score = 0.7 * semantic + 0.3 * kw_rate
    return round(min(max(score, 0.0), 1.0), 4)


def _metadata_text(stock_metadata: dict[str, Any]) -> str:
    return " ".join(
        [
            str(stock_metadata.get("title", "")),
            str(stock_metadata.get("description", "")),
            " ".join(map(str, stock_metadata.get("tags", []) or [])),
        ]
    )
