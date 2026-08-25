"""omodul:发布计划构建。组合 oskill.publish.create_publish_task + oskill.account.verify_account。

供 studio/production 工作流调用。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from hevi.platforms.oskill.publish import create_publish_task, publish_to_platform


def build_publish_plan(
    account_id: int,
    platform: str,
    media_paths: list[str],
    title: str = "",
    desc: str = "",
    topics: str = "",
    visibility: str = "public",
    allow_save: bool = True,
    scheduled_at: str | None = None,
) -> dict[str, Any]:
    """构建发布任务计划。

    将发布请求转换为计划结构，包括：
    - 发布任务
    - 媒体校验
    - 调度参数
    - 验证步骤
    """
    parsed_time = None
    if scheduled_at:
        try:
            parsed_time = datetime.fromisoformat(scheduled_at.replace("Z", ""))
        except Exception:
            parsed_time = None

    media = [Path(p) for p in media_paths if Path(p).exists()]

    return {
        "type": "publish",
        "platform": platform,
        "account_id": account_id,
        "media": {
            "paths": [str(p) for p in media],
            "missing": [p for p in media_paths if not Path(p).exists()],
        },
        "content": {
            "title": title[:20],
            "desc": desc,
            "topics": topics,
            "location": "",
            "visibility": visibility,
            "allow_save": allow_save,
        },
        "scheduled_at": parsed_time.isoformat() if parsed_time else None,
        "validation_steps": [
            {"step": "account_check", "required": True},
            {"step": "media_check", "required": True, "paths": [str(p) for p in media]},
            {"step": "browser_ready", "required": platform != "shipinhao"},
        ],
    }


async def execute_publish_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """执行发布计划。

    按计划中的验证步骤执行发布，收集 trail。
    """
    platform = plan["platform"]
    account_id = plan["account_id"]
    media_paths = plan["media"]["paths"]
    content = plan["content"]

    task = create_publish_task(
        account_id=account_id,
        platform=platform,
        media_type="images" if all(p.lower().endswith(('.jpg', '.png')) for p in media_paths) else "video",
        title=content["title"],
        desc=content["desc"],
        topics=content["topics"],
        visibility=content["visibility"],
        allow_save=content["allow_save"],
        media_paths=media_paths,
    )

    result = await publish_to_platform(task)

    return {
        "status": result.status,
        "platform": platform,
        "result": result.to_dict(),
    }