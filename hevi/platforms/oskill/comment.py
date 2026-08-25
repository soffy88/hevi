"""oskill:评论规则技能。组合 oprim.resolve + oprim.extract + oprim.risk。

对应 CreatorHub 的 app/api/comment-endpoints.py + CommentRule/CommentTask 逻辑。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from hevi.platforms.schemas import CommentRule

logger = logging.getLogger(__name__)


# ─── 评论规则创建 ───


def create_comment_rule(
    platform: str,
    name: str,
    mode: str,
    account_id: int,
    target_kind: str,
    target: str,
    templates: list[str],
    use_ai: bool = False,
    require_review: bool = False,
    reply_filter: str = "",
    skip_keywords: str = "",
    daily_cap: int = 20,
    min_gap_seconds: int = 90,
    max_per_run: int = 5,
    interval_seconds: int = 1800,
    enabled: bool = False,
) -> CommentRule:
    """创建自动评论/回复规则。

    对应 CreatorHub 的 /api/comment-rules 端点逻辑。
    """
    from hevi.platforms.schemas import CommentRule

    # 解析目标: 转换 target/target_kind 结构
    kind = target_kind
    keyword = ""
    sec_uid = ""
    aweme_id = ""
    xsec_token = ""

    if mode == "auto_comment":
        if target_kind == "keyword":
            keyword = target.strip()
        elif target_kind in ("creator",):
            # 解析创作者链接
            xsec_token = extract_xsec_token_from_target(target)
    elif mode == "auto_reply":
        kind = "self"  # 回复本账号

    return CommentRule(
        id=None,
        platform=platform,
        name=name,
        mode=mode,
        account_id=account_id,
        target_kind=kind,
        keyword=keyword,
        sec_uid=sec_uid,
        aweme_id=aweme_id,
        xsec_token=xsec_token,
        templates=templates,
        use_ai=use_ai,
        require_review=require_review,
        reply_filter=reply_filter,
        skip_keywords=skip_keywords,
        daily_cap=max(0, daily_cap),
        min_gap_seconds=max(1, min_gap_seconds),
        max_per_run=max(1, max_per_run),
        interval_seconds=max(60, interval_seconds),
        enabled=enabled,
    )


def extract_xsec_token_from_target(target: str) -> str:
    """从目标 URL 提取 xsec_token。

    CreatorHub 小红书自动评论/监控需要 xsec_token。
    """
    from hevi.platforms.oprim.resolve import extract_xsec_token_from_url
    return str(extract_xsec_token_from_url(target) or "")


# ─── 目标解析 ───


def parse_comment_target(target: str, platform: str) -> dict[str, Any]:
    """解析评论目标。

    对应 CreatorHub 的 _resolve_rule_target 逻辑。
    """
    sec_uid = aweme_id = xsec_token = keyword = ""

    if platform == "xhs":
        from hevi.platforms.oprim.resolve import (
            extract_sec_uid_from_url,
            extract_xsec_token_from_url,
        )
        uid = extract_sec_uid_from_url(target)
        token = extract_xsec_token_from_url(target)
        if uid:
            sec_uid = uid
        if token:
            xsec_token = token
    elif platform == "douyin":
        # 抖音关键词模式或创作者模式
        m = __import__("re").search(r"aweme_id=(\d+)", target)
        if m:
            aweme_id = m.group(1)
        m = __import__("re").search(r"sec_uid=([A-Za-z0-9_-]+)", target)
        if m:
            sec_uid = m.group(1)
    elif platform == "kuaishou":
        from hevi.platforms.oprim.resolve import extract_ks_photo_id_from_url
        pid = extract_ks_photo_id_from_url(target)
        if pid:
            aweme_id = pid  # 快手使用 photo_id 作为类似字段

    return {"sec_uid": sec_uid, "aweme_id": aweme_id, "keyword": keyword, "xsec_token": xsec_token}


# ─── 任务执行 ───


async def execute_comment_rule(rule: CommentRule) -> dict[str, Any]:
    """执行单条评论规则。

    对应 CreatorHub 的 engine.execute_comment_task + run_comment_rule_now 逻辑。
    """
    # 检查风控状态
    # if not rule.account.is_available():
    #     return {"status": "blocked", "reason": "账号处于风控"}
    # ... 实际执行浏览器自动化

    return {
        "status": "pending",
        "message": "规则已就绪, 等待调度",
        "rule_id": rule.id,
    }


# ─── 剩余间隔校验 ───


def check_interval_safety(
    rule: CommentRule,
    last_run: datetime | None = None,
) -> dict[str, Any]:
    """检查是否满足规则的时间间隔要求。"""
    now = __import__("datetime").datetime.now()
    if last_run is None:
        return {"safe": True, "message": "从未运行过"}

    elapsed = (now - last_run).total_seconds()
    gap_seconds = max(1, rule.min_gap_seconds)

    if elapsed < gap_seconds:
        remaining = gap_seconds - elapsed
        return {
            "safe": False,
            "remaining_seconds": remaining,
            "message": f"距离上次运行仅 {remaining:.0f}s, 需等待 {remaining:.0f}s",
        }

    # 检查日配额
    if rule.daily_cap > 0:
        # 这里需要查询当天已发布次数，简化处理
        pass

    return {"safe": True, "message": "间隔安全"} if elapsed >= gap_seconds else {"safe": False}
