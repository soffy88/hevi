"""quick material —— 素材检索适配(material_corpus → QuickPlan.materials)。

把 A4 素材语料库的 MaterialInfo 归一化为 QuickPlan 可消费的 dict(带 aspect/时长/缓存路径),
并做画幅/时长过滤 + 关键词排序(pick_best 语义)。
"""

from __future__ import annotations

from typing import Any

from hevi.quick.service import QuickVideoConfig
from hevi.video.material_corpus import (
    MaterialInfo,
    dedupe,
    pick_best,
    search_all,
)


def _to_dicts(items: list[MaterialInfo]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in items:
        d = m.to_dict()
        d["aspect"] = m.aspect
        out.append(d)
    return out


def search_materials_for_topic(
    topic: str, cfg: QuickVideoConfig
) -> list[dict[str, Any]]:
    """主题 → 多源素材检索, 返回按相关性排序的归一化条目(每源取最优 1 条)。

    无 key 的源自动降级; 全部失败返回空列表(不阻断 quick_video)。
    """
    keys = cfg.material_keys
    merged = search_all(
        topic,
        pexels_key=keys.get("pexels", ""),
        pixabay_key=keys.get("pixabay", ""),
        coverr_key=keys.get("coverr", ""),
        include_archive=cfg.include_archive,
        per_source=cfg.max_sources,
    )
    if not merged:
        return []
    merged = dedupe(merged)
    # 每源取 1 条最优(画幅/时长/关键词综合)
    best_per_source: list[MaterialInfo] = []
    seen_sources: set[str] = set()
    for m in merged:
        if m.source in seen_sources:
            continue
        best = pick_best(
            [x for x in merged if x.source == m.source],
            topic,
            target_aspect=cfg.aspect,
            min_s=2.0,
            max_s=max(cfg.target_duration_s * 2.0, 30.0),
        )
        if best:
            seen_sources.add(m.source)
            best_per_source.append(best)
    return _to_dicts(best_per_source)
