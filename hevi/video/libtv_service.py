"""LibLib.tv (libtv) agent-im 客户端 —— 把创作指令中继给专业生视频平台,轮询、下载成片。

背景(2026-07-16):hevi 自造的导演产集管线出片是"大头念台词、穿戴像圣斗士、走位/动作丢失"。
根因是本地管线在吃力重造一整套电影生成能力,而 LibLib.tv 这类专业平台已经做好了(内部做分镜/
角色一致性/电影级生成)。soffy 指向 libtv-skills(github.com/libtv-labs/libtv-skills)的核心原则:
**"用户侧不做创作,只做传话"**。故 hevi 的定位改为:用 LLM 产出加厚剧本(它擅长的),把剧本作为
自然语言创作指令传给 agent-im 出片(它擅长的),各司其职。

本模块镜像 libtv-skill 的 scripts:create_session / query_session / 从消息提取结果 URL / 下载。
鉴权 Bearer settings.libtv_access_key(走 .env,未配置则抛,不硬编码)。API 见 libtv-skills README。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx

from hevi.core.config import settings

logger = logging.getLogger(__name__)

# libtv-res 上的结果资源 URL(图/视频)。见 download_results.py 的正则。
_RESULT_URL = re.compile(
    r"https://libtv-res\.liblib\.art/[^\s\"'<>]+\.(?:png|jpg|jpeg|webp|mp4|mov|webm)"
)
_VIDEO_EXTS = (".mp4", ".mov", ".webm")


class LibtvError(RuntimeError):
    pass


def _base() -> str:
    return (settings.libtv_im_base or "https://im.liblib.tv").rstrip("/")


def _headers() -> dict[str, str]:
    key = settings.libtv_access_key
    if not key:
        raise LibtvError("未配置 LIBTV_ACCESS_KEY(.env),无法调用 LibLib.tv agent-im")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


async def create_session(message: str = "", session_id: str = "") -> dict[str, Any]:
    """创建会话或向已有会话发消息(生图/生视频)。返回 {projectUuid, sessionId}。"""
    body: dict[str, Any] = {}
    if session_id:
        body["sessionId"] = session_id
    if message:
        body["message"] = message
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{_base()}/openapi/session", json=body, headers=_headers())
        r.raise_for_status()
        return (r.json() or {}).get("data", {}) or {}


async def query_session(session_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
    """查询会话消息列表(afterSeq 增量)。返回 messages。"""
    path = f"/openapi/session/{session_id}"
    if after_seq > 0:
        path += f"?afterSeq={after_seq}"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{_base()}{path}", headers=_headers())
        r.raise_for_status()
        return ((r.json() or {}).get("data", {}) or {}).get("messages", []) or []


def extract_result_urls(messages: list[dict[str, Any]]) -> list[str]:
    """从会话消息提取结果 URL(镜像 download_results.py):tool 消息的 task_result.images/videos
    的 previewPath + assistant 文本里的 libtv-res URL。保序去重。"""
    urls: list[str] = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, str) or not content:
            continue
        if msg.get("role") == "tool":
            with contextlib.suppress(Exception):
                tr = (json.loads(content) or {}).get("task_result", {}) or {}
                urls.extend(
                    img["previewPath"] for img in (tr.get("images") or []) if img.get("previewPath")
                )
                urls.extend(
                    p
                    for vid in (tr.get("videos") or [])
                    if (p := vid.get("previewPath") or vid.get("url"))
                )
        if msg.get("role") == "assistant":
            urls.extend(_RESULT_URL.findall(content))
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


async def _download(url: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as c:
        r = await c.get(url, headers={"User-Agent": "hevi-libtv/1.0"})
        r.raise_for_status()
        path.write_bytes(r.content)
    return path


async def generate_via_libtv(
    message: str,
    out_dir: Path,
    *,
    session_id: str = "",
    poll_interval_s: float = 15.0,
    timeout_s: float = 1800.0,
    want_video: bool = True,
    prefix: str = "libtv",
) -> dict[str, Any]:
    """把创作指令 message 发给 agent-im,轮询到出结果 URL,下载到 out_dir。
    返回 {session_id, project_uuid, project_url, urls, files, video}。
    want_video=True 时,轮询到出现视频 URL 才收(否则任何结果 URL 即收);超时抛 LibtvError。"""
    sess = await create_session(message=message, session_id=session_id)
    sid = sess.get("sessionId") or session_id
    project_uuid = sess.get("projectUuid", "")
    if not sid:
        raise LibtvError(f"agent-im 未返回 sessionId: {sess}")
    logger.info("libtv 会话 %s(project %s)已发指令,轮询出片…", sid, project_uuid)

    deadline_loops = max(1, int(timeout_s / max(1.0, poll_interval_s)))
    last_seq = 0
    urls: list[str] = []
    for _ in range(deadline_loops):
        await asyncio.sleep(poll_interval_s)
        msgs = await query_session(sid, after_seq=last_seq)
        for m in msgs:
            with contextlib.suppress(Exception):
                last_seq = max(last_seq, int(m.get("seq", last_seq)))
        found = extract_result_urls(msgs)
        for u in found:
            if u not in urls:
                urls.append(u)
        has_video = any(u.split("?")[0].lower().endswith(_VIDEO_EXTS) for u in urls)
        if urls and (has_video or not want_video):
            break
    if not urls:
        raise LibtvError(f"libtv 会话 {sid} 轮询 {timeout_s:.0f}s 未出任何结果 URL")

    files: list[str] = []
    for i, u in enumerate(urls, 1):
        ext = Path(u.split("?")[0]).suffix or ".png"
        p = await _download(u, out_dir / f"{prefix}_{i:02d}{ext}")
        files.append(str(p))
    video = next((f for f in files if Path(f).suffix.lower() in _VIDEO_EXTS), None)
    return {
        "session_id": sid,
        "project_uuid": project_uuid,
        "project_url": (
            f"https://www.liblib.tv/canvas?projectId={project_uuid}" if project_uuid else ""
        ),
        "urls": urls,
        "files": files,
        "video": video,
    }
