"""omodul:评论规则计划构建。组合 oskill.comment.create_comment_rule + oskill.account.verify_account。

供 studio/production 工作流调用。
"""

from __future__ import annotations

from typing import Any


def build_comment_plan(
    platform: str,
    mode: str,
    account_id: int,
    target: str,
    templates: list[str],
    name: str = "",
    use_ai: bool = False,
    require_review: bool = False,
    daily_cap: int = 20,
    min_gap_seconds: int = 90,
    max_per_run: int = 5,
    interval_seconds: int = 1800,
    enabled: bool = False,
    target_kind: str = "self",
) -> dict[str, Any]:
    """构建评论规则计划。

    将评论配置转换为计划结构，包括：
    - 规则定义
    - 目标解析
    - 节流参数
    - 审核流程（如启用）
    """
    from hevi.platforms.oskill.comment import create_comment_rule

    rule = create_comment_rule(
        platform=platform,
        name=name or ("自动回复" if mode == "auto_reply" else "自动评论"),
        mode=mode,
        account_id=account_id,
        target_kind=target_kind,
        target=target,
        templates=templates,
        use_ai=use_ai,
        require_review=require_review,
        daily_cap=daily_cap,
        min_gap_seconds=min_gap_seconds,
        max_per_run=max_per_run,
        interval_seconds=interval_seconds,
        enabled=enabled,
    )

    return {
        "type": "comment",
        "platform": platform,
        "rule": rule.model_dump(),
        "resolves": {
            "target_kind": rule.target_kind,
            "keyword": rule.keyword,
            "sec_uid": rule.sec_uid,
            "aweme_id": rule.aweme_id,
            "xsec_token": rule.xsec_token,
        },
        "throttle": {
            "daily_cap": rule.daily_cap,
            "min_gap_seconds": rule.min_gap_seconds,
            "max_per_run": rule.max_per_run,
            "interval_seconds": rule.interval_seconds,
        },
        "review": {
            "required": rule.require_review,
            "ai_fallback": rule.use_ai,
        },
        "validation_steps": [
            {"step": "account_check", "required": True},
            {"step": "target_resolve", "required": True},
            {"step": "rate_limit", "required": True},
        ],
    }