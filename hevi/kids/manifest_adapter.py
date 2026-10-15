"""manifest 适配点（kids 线消费 manifest 的唯一入口）。

REVIEWSHEET_TASK 硬规则：所有消费 manifest 的代码只通过本模块访问，便于日后把
K1（feat/kids-manifest）的正式 ``KidsConsistencyManifest`` 换成底层实现。

当前底层实现：``hevi/kids/manifest_draft`` 的 §3.3 草案只读层。日后 K1 合并后，
只需改 ``_load_impl`` 让它优先 import 并适配 K1 的正式类即可，**调用方零改动**。

适配器对外只暴露稳定协议：
  - ``load_manifest(path) -> ManifestProtocol``
  - ``ManifestProtocol``：``shots() / shot(i) / style_bible() / transition_table() /
    characters() / props() / scenes() / spoken_language() / theme() / episode() /
    title() / total_duration() / language_for_shot(i) / validate() / to_dict()``
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .manifest_draft import (
    MANIFEST_SCHEMA_VERSION,
    ManifestValidationError,
    KidsConsistencyManifestDraft,
    ShotEntry,
)


@runtime_checkable
class ManifestProtocol(Protocol):
    """manifest 消费方看到的稳定协议（与底层实现解耦）。"""

    source_path: Path | None

    def shots(self) -> list[ShotEntry]: ...
    def shot(self, idx: int) -> ShotEntry | None: ...
    def style_bible(self) -> dict[str, Any]: ...
    def transition_table(self) -> list[dict[str, Any]]: ...
    def characters(self) -> list[dict[str, Any]]: ...
    def props(self) -> list[dict[str, Any]]: ...
    def scenes(self) -> list[dict[str, Any]]: ...
    def spoken_language(self) -> list[dict[str, Any]]: ...
    def theme(self) -> dict[str, Any]: ...
    def episode(self) -> int: ...
    def title(self) -> str: ...
    def total_duration(self) -> float: ...
    def language_for_shot(self, idx: int) -> str | None: ...
    def validate(self) -> list[str]: ...
    def to_dict(self) -> dict[str, Any]: ...


def _load_impl(path: str | Path) -> ManifestProtocol:
    """底层实现选择：优先 K1 正式实现，否则用本分支草案层。

    当前 K1（feat/kids-manifest）未合并到本 worktree，这里只加载草案层。
    TODO(K1): 待 K1 合并后，在此优先尝试
        ``from hevi.kids.consistency_manifest import KidsConsistencyManifest``
    并把其对象适配为 ``ManifestProtocol``。
    """
    return KidsConsistencyManifestDraft.load(path)


def load_manifest(path: str | Path) -> ManifestProtocol:
    """读取并校验一个 manifest（§3.3 草案）。非法则抛 ``ManifestValidationError``。"""
    manifest = _load_impl(path)
    errors = manifest.validate()
    if errors:
        raise ManifestValidationError(
            "manifest 校验失败: " + "; ".join(errors)
        )
    return manifest


def draft_manifest(data: dict[str, Any]) -> ManifestProtocol:
    """从内存 dict 构造草案 manifest（不落盘，便于测试）。"""
    return KidsConsistencyManifestDraft(data=data)


__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "ManifestProtocol",
    "ManifestValidationError",
    "ShotEntry",
    "KidsConsistencyManifestDraft",
    "load_manifest",
    "draft_manifest",
]
