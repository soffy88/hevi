"""跨场/跨事件角色合并。

3O 归属(待上游): `oprim.character_fuse`。
青年/老年等同名不同特征应拆开——启发式看特征 Jaccard。
"""

from __future__ import annotations

import re

from hevi.script2video.oprim.idea_parse import slugify

_AGE_MARKERS = ("童年", "少年", "青年", "中年", "老年", "child", "young", "old", "elderly")


def feature_tokens(text: str) -> set[str]:
    return {tok for tok in re.findall(r"[\w\u4e00-\u9fff]+", (text or "").lower()) if len(tok) > 1}


def should_split_identities(left_features: str, right_features: str) -> bool:
    """特征集合过散或年龄段冲突 → 拆成两个角色。"""
    left, right = feature_tokens(left_features), feature_tokens(right_features)
    if not left or not right:
        return False
    ages_l = {m for m in _AGE_MARKERS if m in left}
    ages_r = {m for m in _AGE_MARKERS if m in right}
    if ages_l and ages_r and ages_l.isdisjoint(ages_r):
        return True
    union = left | right
    return len(left & right) / len(union) < 0.15


def canonical_identifier(name: str) -> str:
    return slugify(name)


def merge_feature_text(existing: str, incoming: str) -> str:
    if not incoming:
        return existing
    if not existing:
        return incoming
    if incoming in existing:
        return existing
    return f"{existing}; {incoming}"
