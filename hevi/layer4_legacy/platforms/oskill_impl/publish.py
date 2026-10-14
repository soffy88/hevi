"""oskill:跨平台发布技能。组合 oprim.resolve + oprim.extract + oprim.risk。

对应 CreatorHub 的 app/engine/publish_task.py + app/platforms/ 发布逻辑。
"""

from __future__ import annotations

import logging
from typing import Any

from hevi.platforms.schemas import PublishResult, PublishTask

logger = logging.getLogger(__name__)


# ─── 发布任务创建 ───


def create_publish_task(
    account_id: int,
    platform: str,
    media_type: str = "images",
    title: str = "",
    desc: str = "",
    topics: str = "",
    location: str = "",
    visibility: str = "public",
    allow_save: bool = True,
    media_paths: list[str] | None = None,
) -> PublishTask:
    """创建发布任务。

    对应 CreatorHub API 的 /api/publish 端点逻辑。
    """
    from hevi.platforms.schemas import PublishTask

    media_paths = media_paths or []
    return PublishTask(
        id=None,
        platform=platform,
        account_id=account_id,
        media_type=media_type,
        title=title[:20] if len(title) > 20 else title,
        desc=desc,
        topics=topics,
        location=location,
        visibility=visibility,
        allow_save=allow_save,
        media_paths=media_paths,
    )


# ─── 平台发布 ───


async def publish_to_platform(
    task: PublishTask,
    engine_available: bool = True,
    browser_context: Any | None = None,
) -> PublishResult:
    """执行平台发布任务(fail-closed)。

    本函数**尚未实现真实上传**:登录态探测、媒体选择、编辑信息、点击发布、
    结果回填都不存在。此前版本在拿到 browser_context 后不做任何操作就返回
    ``status="published"`` / "发布成功",属于伪造结果,已移除。

    约定(与 ``hevi.publishers`` 一致,不 raise,降级返回):
    - 没有媒体文件 → ``failed``
    - 浏览器上下文未就绪 → ``failed``
    - 其余情况 → ``not_implemented``;trail 里绝不出现 ``publish ok=True``。
    真实发布请走 ``hevi.publishers`` / MatrixMedia 人工确认交接。
    """
    from hevi.platforms.schemas import PublishResult

    del engine_available  # 保留参数仅为兼容旧调用签名

    if not task.is_available() or not task.media_paths:
        return PublishResult(
            status="failed",
            platform=task.platform,
            reason=f"没有可用的媒体文件: {task.platform} 账号 {task.account_id}",
            trail=[{"step": "media_check", "ok": False}],
        )

    if not browser_context:
        return PublishResult(
            status="failed",
            platform=task.platform,
            reason="浏览器未就绪",
            trail=[
                {"step": "media_check", "ok": True},
                {"step": "browser_start", "ok": False},
            ],
        )

    logger.warning(
        "publish_to_platform: real upload not implemented for %s (account %s); "
        "returning not_implemented instead of a fabricated success",
        task.platform,
        task.account_id,
    )
    return PublishResult(
        status="not_implemented",
        platform=task.platform,
        reason="平台自动发布未实现:未执行任何上传,请使用 hevi.publishers / MatrixMedia 人工确认发布",
        trail=[
            {"step": "media_check", "ok": True},
            {"step": "browser_start", "ok": True},
            {"step": "publish", "ok": False, "reason": "not_implemented"},
        ],
    )


# ─── 跨平台转发 ───


async def repost_content(
    content_id: int,
    target_account_id: int,
    target_platform: str,
    title: str | None = None,
    desc: str | None = None,
    topics: str | None = None,
    visibility: str = "public",
    allow_save: bool = True,
    media_order: list[int] | None = None,
) -> dict[str, Any]:
    """把已下载作品转成目标平台的发布任务。

    对应 CreatorHub 的 /api/contents/{cid}/repost-xhs, repost-douyin 等端点。
    """
    # 转发需要浏览器自动化层,尚未实现:不创建任何任务,明确返回未实现。
    return {
        "ok": False,
        "status": "not_implemented",
        "task_id": f"repost_{content_id}_{target_platform}",
        "message": f"转发未实现,未创建任务: {content_id} -> {target_platform}",
    }
