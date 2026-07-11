"""成本路由 v2 —— 经验质量分布(HEVI 路线图 Phase4 #46)。

从静态能力布尔值(selector.py::PROVIDER_QUALITY,人工按口碑定的分数)升级为
数据驱动:用 shot_verdict(#27 起持久化在 shot_states.selection_json 里的真实
consistency_score)算某个 provider(可选:+ 某个 StylePack 组合)的历史质量中位数,
例如"Kling 在国风水墨 StylePack 组合下的历史中位数是多少"。

样本量不够(冷启动 / 新 provider+组合从没跑过)→ 返回 None,调用方该退回静态表
——这不是"用假数据填坑",是诚实反映"这个组合还没攒够真实数据"。这条能力**这次
只做数据查询/聚合层**,不改 hevi/cost/selector.py 的既有路由行为(v1 继续用静态
表,不因为这层存在就自动切换)——等真实数据量真的攒起来,是否/何时切换是运营
决策,不该在数据还稀疏的时候就悄悄改变路由结果。
"""

from __future__ import annotations

from typing import Any

# 少于这个样本数,统计噪声太大,不该拿来做路由决策(尤其是中位数这种对小样本
# 敏感的统计量——3 个样本的"中位数"基本等于随手挑一个)。
_MIN_SAMPLES = 5


async def get_empirical_quality(
    pool: Any, *, provider: str, style_pack_id: str | None = None
) -> float | None:
    """→ 历史 consistency_score 中位数(0..1,越高越好)。

    样本量 < `_MIN_SAMPLES` → None(数据不够,不该被当成信号使用)。
    """
    from obase.persistence import query

    sql = (
        "SELECT percentile_cont(0.5) WITHIN GROUP ("
        "  ORDER BY (selection_json->>'consistency_score')::float8"
        ") AS median, COUNT(*) AS n "
        "FROM shot_states "
        "WHERE selection_json->>'provider' = $1 "
        "AND selection_json->>'consistency_score' IS NOT NULL"
    )
    params: list[Any] = [provider]
    if style_pack_id is not None:
        sql += " AND selection_json->>'style_pack_id' = $2"
        params.append(style_pack_id)

    rows = await query(pool, sql=sql, params=params)
    if not rows:
        return None
    row = rows[0]
    if int(row.get("n") or 0) < _MIN_SAMPLES:
        return None
    median = row.get("median")
    return float(median) if median is not None else None


async def rank_providers_by_empirical_quality(
    pool: Any, *, candidates: list[str], style_pack_id: str | None = None
) -> dict[str, float]:
    """给一组候选 provider 各查一次经验质量,返回 {provider: median}(样本不够的
    provider 不出现在结果里,而不是补 0 / 补默认值掺进排序——那会让"没数据"看起来
    比"数据显示质量差"更糟,两者含义完全不同)。"""
    result: dict[str, float] = {}
    for p in candidates:
        q = await get_empirical_quality(pool, provider=p, style_pack_id=style_pack_id)
        if q is not None:
            result[p] = q
    return result
