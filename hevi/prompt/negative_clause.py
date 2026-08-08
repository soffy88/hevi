"""失败注册表 → 逐镜头负向子句(3O 内化 wire ①)。

把 `hevi/verdict/failure_registry.py` 的失败模式注册表接入导演管线的逐镜头负向
prompt:verdict 观测到的失败类别(崩手/脸漂移/乱码…)按层生成负向子句,与现有
`extra_negative`(角色专属负向)合并后随每镜下发 —— 这就是 HEVI-ARCH §5.3.4
"provider 默认行为对照表自我校正闭环"的失败侧实现:命中越多,负向越精准。

3O 归属(待上游): `oskill.failure_negative_clause`。
"""

from __future__ import annotations

from hevi.verdict.failure_registry import FailureRegistry, default_registry


def shot_negative_clause(layer: str, *, registry: FailureRegistry | None = None) -> str:
    """按生成层生成负向子句块;该层无定义 → 空串(不污染 prompt)。"""
    reg = registry or default_registry()
    return reg.build_negative_clause(layer)


def merge_negative_clauses(*clauses: str) -> str:
    """合并多条负向子句(去空、去重、句号归一),返回单条负向 prompt。

    - 全空 → ""(调用方保持原有行为)。
    - 非空 → 用 ", " 连接;保证以句号结尾,且不重复追加身份锁定句。
    """
    seen: list[str] = []
    for clause in clauses:
        c = clause.strip().rstrip("。.")
        if c and c not in seen:
            seen.append(c)
    if not seen:
        return ""
    return "。".join(seen) + "。"


def with_failure_registry_clause(
    base_negative: str, layer: str, *, registry: FailureRegistry | None = None
) -> str:
    """把注册表该层负向子句并入既有负向(base 可空)。"""
    clause = shot_negative_clause(layer, registry=registry)
    return merge_negative_clauses(base_negative, clause)
