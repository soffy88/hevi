"""publish_to_platform must never fabricate a successful publish (fail-closed)."""

from __future__ import annotations

import pytest

from hevi.layer4_legacy.platforms.omodul_impl.plan_publish import execute_publish_plan
from hevi.platforms.oskill.publish import (
    create_publish_task,
    publish_to_platform,
    repost_content,
)


def _no_fake_success(result) -> None:
    assert result.status not in {"published", "success", "ok"}
    assert "发布成功" not in result.reason
    assert not any(step.get("step") == "publish" and step.get("ok") for step in result.trail)


@pytest.mark.asyncio
async def test_browser_context_present_returns_not_implemented() -> None:
    task = create_publish_task(1, "douyin", title="t", media_paths=["video.mp4"])
    result = await publish_to_platform(task, browser_context=object())
    assert result.status == "not_implemented"
    _no_fake_success(result)


@pytest.mark.asyncio
async def test_no_browser_fails() -> None:
    task = create_publish_task(1, "xhs", media_paths=["a.jpg"])
    result = await publish_to_platform(task, browser_context=None)
    assert result.status == "failed"
    _no_fake_success(result)


@pytest.mark.asyncio
async def test_no_media_fails_not_skipped() -> None:
    task = create_publish_task(1, "douyin")
    result = await publish_to_platform(task, browser_context=object())
    assert result.status == "failed"
    assert result.trail == [{"step": "media_check", "ok": False}]
    _no_fake_success(result)


@pytest.mark.asyncio
async def test_execute_publish_plan_never_reports_published(tmp_path) -> None:
    media = tmp_path / "v.mp4"
    media.write_bytes(b"x")
    plan = {
        "platform": "douyin",
        "account_id": 1,
        "media": {"paths": [str(media)], "missing": []},
        "content": {
            "title": "t",
            "desc": "",
            "topics": "",
            "visibility": "public",
            "allow_save": True,
        },
    }
    out = await execute_publish_plan(plan)
    assert out["status"] != "published"


@pytest.mark.asyncio
async def test_repost_is_not_faked() -> None:
    out = await repost_content(5, 1, "xhs")
    assert out["ok"] is False and out["status"] == "not_implemented"
