"""国内矩阵发布 —— MatrixMedia 式交接契约(CLI/Webhook/落盘),不假装 OAuth。"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib import error, request

from hevi.publishers import Publisher, PublishResult

logger = logging.getLogger(__name__)

PLATFORM_DOUYIN = "douyin"
PLATFORM_KUAISHOU = "kuaishou"
PLATFORM_XIAOHONGSHU = "xiaohongshu"
PLATFORM_SHIPINHAO = "shipinhao"
PLATFORM_BILIBILI = "bilibili"

CN_PLATFORMS = (
    PLATFORM_DOUYIN,
    PLATFORM_KUAISHOU,
    PLATFORM_XIAOHONGSHU,
    PLATFORM_SHIPINHAO,
    PLATFORM_BILIBILI,
)

# MatrixMedia CLI 平台别名
_MM_ALIAS = {
    PLATFORM_DOUYIN: "dy",
    PLATFORM_KUAISHOU: "ks",
    PLATFORM_XIAOHONGSHU: "xhs",
    PLATFORM_SHIPINHAO: "sph",
    PLATFORM_BILIBILI: "blbl",
}


class MatrixPublisher(Publisher):
    """写交接单;有 webhook/CLI 再真正投递。本机永远 available。"""

    def __init__(self, platform: str) -> None:
        self.name = platform
        self.platforms = (platform,)

    def available(self) -> bool:
        return True

    async def publish(
        self,
        media_path: Path,
        *,
        title: str = "",
        description: str = "",
        tags: list[str] | None = None,
        **meta: Any,
    ) -> PublishResult:
        if not media_path.exists():
            return PublishResult(
                status="failed",
                platform=self.name,
                reason=f"media not found: {media_path}",
            )
        handoff = {
            "platform": self.name,
            "alias": _MM_ALIAS.get(self.name, self.name),
            "file": str(media_path.resolve()),
            "title": title,
            "description": description,
            "tags": list(tags or []),
            "account": str(meta.get("account") or ""),
            "cover_hint": str(meta.get("cover_hint") or ""),
            "meta": {k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool))},
        }
        ticket = media_path.with_suffix(media_path.suffix + f".{self.name}.publish.json")
        ticket.write_text(json.dumps(handoff, ensure_ascii=False, indent=2), encoding="utf-8")
        trail: list[dict[str, Any]] = [{"step": "write_handoff", "ok": True, "path": str(ticket)}]

        webhook = os.environ.get("HEVI_MATRIX_WEBHOOK", "").strip()
        if webhook:
            posted = _post_webhook(webhook, handoff)
            trail.append({"step": "webhook", "ok": posted[0], "detail": posted[1]})
            if posted[0]:
                return PublishResult(
                    status="published",
                    platform=self.name,
                    external_id=ticket.name,
                    url=webhook,
                    reason="webhook accepted",
                    trail=trail,
                )

        cli = os.environ.get("MATRIXMEDIA_BIN", "").strip()
        if cli:
            trail.append(
                {
                    "step": "cli",
                    "ok": False,
                    "detail": "handoff written; CLI not invoked in-process",
                }
            )

        return PublishResult(
            status="handoff",
            platform=self.name,
            external_id=str(ticket),
            reason="matrix handoff ticket written",
            trail=trail,
        )


def _post_webhook(url: str, body: dict[str, Any]) -> tuple[bool, str]:
    payload = json.dumps(body).encode("utf-8")
    req = request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=10) as resp:
            return True, f"http {resp.status}"
    except error.HTTPError as exc:
        return False, f"http {exc.code}"
    except Exception as exc:
        return False, str(exc)


def register_matrix_publishers() -> None:
    from hevi.publishers import register_publisher

    for platform in CN_PLATFORMS:
        register_publisher(MatrixPublisher(platform))
