"""跨产线资产引用 —— 角色/镜头/成片/剧本可被历史现场、短剧、解说互引。"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

# 资产种类:角色锚 / 分镜 / 成片 / 剧本 / 参考片 / 素材
ASSET_KINDS = (
    "subject",
    "shot",
    "render",
    "script",
    "watch",
    "material",
    "voice",
    "font",
    "bgm",
    "motion",
    "corpus",
)


@dataclass(frozen=True)
class AssetRef:
    """跨产线稳定引用。payload 只放可 JSON 化的制片事实,不含 PII。"""

    asset_id: str
    kind: str
    line_id: str
    label: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_ASSETS: dict[str, AssetRef] = {}


def reset_assets() -> None:
    _ASSETS.clear()


def bind_asset(
    kind: str,
    *,
    line_id: str,
    label: str,
    payload: dict[str, Any] | None = None,
    asset_id: str | None = None,
) -> AssetRef:
    if kind not in ASSET_KINDS:
        raise ValueError(f"unknown asset kind: {kind}")
    ref = AssetRef(
        asset_id=asset_id or str(uuid.uuid4()),
        kind=kind,
        line_id=line_id,
        label=label,
        payload=dict(payload or {}),
        created_at=datetime.now(UTC).isoformat(),
    )
    _ASSETS[ref.asset_id] = ref
    return ref


def get_asset(asset_id: str) -> AssetRef | None:
    return _ASSETS.get(asset_id)


def list_assets(*, kind: str | None = None, line_id: str | None = None) -> list[AssetRef]:
    items = list(_ASSETS.values())
    if kind:
        items = [a for a in items if a.kind == kind]
    if line_id:
        items = [a for a in items if a.line_id == line_id]
    return items
