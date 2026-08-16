"""media-use 台账 —— 一个 resolve 动词 + ledger 记录(3O 内化 Round 3,来源 HyperFrames media-use)。

HyperFrames 的 media-use 是"媒体 OS":任何媒体需求(bgm/sfx/image/icon/logo/voice/grade/
lut/video)→ 一条 `resolve` 动词 → 冻结本地文件 + 台账记录;目录缺则生成(TTS/音乐/图),
资产跨项目复用。这正对应 HEVI-ARCH"资产供应链(矿工采集→检索→锁定)"的落地形态。

本模块为 hevi 暂驻(待上游 `oskill.media_use`):
  - resolve_media:确定性供应链(本地库 → 素材检索 → 生成 → 报错),provider 链注入可测。
  - MediaLedger:JSON 台账(manifest),记录每次 resolve 的 id/类型/路径/来源/元数据,
    支持 reuse_candidates(跨项目复用,同一 intent 先查台账)。
  - 全部纯逻辑可单测;真实 provider 是注入的 callable(接 audio_library / sourcing /
    edge_tts / design_token 等既有零件)。
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: 支持的媒体类型(与 hyperframes media-use resolve --type 对齐)。
MEDIA_TYPES: tuple[str, ...] = (
    "bgm", "sfx", "image", "icon", "logo", "voice", "grade", "lut", "video",
)

#: 供应链顺序:先台账复用 → 本地库 → 素材检索 → 生成。
PROVIDER_KINDS: tuple[str, ...] = ("local", "stock", "generate")


@dataclass(frozen=True)
class MediaResolution:
    """一次 resolve 的产物:冻结文件 + 台账记录。"""

    id: str
    media_type: str
    intent: str
    path: Path
    source: str  # local | stock | generate | reuse
    provider: str = ""  # 实际命中的 provider 名
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "media_type": self.media_type,
            "intent": self.intent,
            "path": str(self.path),
            "source": self.source,
            "provider": self.provider,
            "metadata": self.metadata,
        }


class MediaLedger:
    """JSON 台账:记录每次 resolve,支持按 intent 复用。"""

    def __init__(self, entries: list[MediaResolution] | None = None) -> None:
        self._entries: list[MediaResolution] = list(entries or [])

    def add(self, resolution: MediaResolution) -> None:
        self._entries.append(resolution)

    @property
    def entries(self) -> list[MediaResolution]:
        return list(self._entries)

    def reuse_candidates(
        self, media_type: str, intent: str, *, top: int = 3
    ) -> list[MediaResolution]:
        """同类型 + intent 关键词交集的既有产物(跨项目复用)。"""
        intent_tokens = set(intent.lower().split())
        scored: list[tuple[int, MediaResolution]] = []
        for entry in self._entries:
            if entry.media_type != media_type:
                continue
            hit = sum(1 for t in intent_tokens if t in entry.intent.lower())
            scored.append((hit, entry))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [entry for hit, entry in scored if hit > 0][:top]

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                [e.to_dict() for e in self._entries], ensure_ascii=False, indent=2
            ),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> MediaLedger:
        p = Path(path)
        if not p.exists():
            return cls()
        raw = json.loads(p.read_text(encoding="utf-8"))
        return cls(
            [
                MediaResolution(
                    id=item["id"],
                    media_type=item["media_type"],
                    intent=item["intent"],
                    path=Path(item["path"]),
                    source=item["source"],
                    provider=item.get("provider", ""),
                    metadata=dict(item.get("metadata", {})),
                )
                for item in raw
            ]
        )


#: provider 链契约:media_type → 按 kind 序的 callable(intent) -> Path | None。
#: callable 找不到/不适用时返回 None(继续下一个 kind);全部落空 → ResolveError。
MediaProviders = dict[str, dict[str, Callable[[str], Path | None]]]


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class ResolveError(Exception):
    """媒体需求无法满足(供应链全部落空)。"""


def resolve_media(
    media_type: str,
    intent: str,
    *,
    providers: MediaProviders,
    ledger: MediaLedger | None = None,
    out_dir: str | Path | None = None,
    force_reuse: bool = True,
) -> MediaResolution:
    """媒体 resolve:台账复用 → 本地库 → 素材检索 → 生成。

    Args:
        media_type: MEDIA_TYPES 之一。
        intent: 一句话需求(如 "温暖背景钢琴 BGM")。
        providers: {media_type: {"local": fn, "stock": fn, "generate": fn}},
            缺省 kind 视为跳过;fn 返回 Path 或 None。
        ledger: 可选,先查复用候选。
        out_dir: 产物落盘目录(默认 Path.cwd()/".media_assets")。
        force_reuse: 允许直接复用台账命中(不重新 resolve)。

    Returns:
        MediaResolution(冻结文件路径 + 台账记录)。

    Raises:
        ResolveError: media_type 非法或供应链全落空。
    """
    if media_type not in MEDIA_TYPES:
        raise ResolveError(f"unknown media_type {media_type!r}; expected one of {MEDIA_TYPES}")
    if not intent.strip():
        raise ResolveError("intent must not be empty")

    out = Path(out_dir) if out_dir is not None else Path.cwd() / ".media_assets"
    out.mkdir(parents=True, exist_ok=True)

    # 0) 台账复用
    if ledger is not None and force_reuse:
        candidates = ledger.reuse_candidates(media_type, intent)
        if candidates:
            best = candidates[0]
            logger.info("media_use: reuse %s -> %s", best.id, best.path)
            return MediaResolution(
                id=best.id,
                media_type=media_type,
                intent=intent,
                path=best.path,
                source="reuse",
                provider=best.provider,
                metadata={"reused_from": best.id},
            )

    # 1-3) 供应链:local → stock → generate
    chain = providers.get(media_type, {})
    for kind in PROVIDER_KINDS:
        fn = chain.get(kind)
        if fn is None:
            continue
        try:
            path = fn(intent)
        except Exception as e:  # provider 内部失败不阻断整链
            logger.warning("media_use %s.%s failed: %s", media_type, kind, e)
            continue
        if path is None:
            continue
        resolution = MediaResolution(
            id=_new_id(),
            media_type=media_type,
            intent=intent,
            path=Path(path),
            source=kind,
            provider=f"{media_type}:{kind}",
        )
        if ledger is not None:
            ledger.add(resolution)
        return resolution

    raise ResolveError(f"media chain exhausted for {media_type}: {intent!r}")


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
