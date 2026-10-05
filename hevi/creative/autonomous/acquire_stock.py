"""P2-A:Stock Acquirer —— provider → 物化 → canonical 校验 → **候选**(不选)。

纪律(与本包既有 S2 纪律一致,并加一条 P2 才有的):

- **探测复用** `hevi/qualification/media.py::validate_media`(canonical,path-in);
- **兼容性判定** 委托 `p7/constraint_check`(p7 语义,本包不重写);
- **不评分**:不打分、不排序、不挑 provider;
- **不选择**(P2 invariant):Acquirer 的职责是「我能提供一个满足这个
  requirement 的 candidate」,**不是**「我决定 HEVI 最终用这个 asset」。
  选谁永远回到 `scorer → selector → ShotResolution`。

## 为什么本类不实现 `Acquirer` 协议

`hevi.creative.autonomous.resolver.Acquirer.acquire` 的返回类型是
`tuple[str, AssetEvidence]` —— **单值**。单值返回本身就是一次选择。

因此 P2-A 的 `StockAssetAcquirer` 提供 `propose()`,返回**全部**合规候选,
并且**刻意不声称**自己是 `Acquirer`。在协议能表达「多候选」之前,声称实现它
就是在撒谎。既有的 `LocalAssetAcquirer.acquire` 返回第一个 `usable` 文件
(见 F9),本类不复制该模式。

## provider 事实的来源

`StockAssetAcquirer` 自己声明 `ProviderProfile` 并构造 `ProviderCatalogue`,
**不改** `hevi/providers/facts.py` 的全局 `_SEED`。事实缺失必须表现为
`UNRESOLVED` 并 fail closed,而不是被猜出来。

## 物化约定

`MATERIAL_CACHE_DIR` env → 否则 `data/material_cache`;
文件名 `<slug>-<sha256(url)[:16]><suffix>`;`.part` → `replace()` 原子落盘。
沿用 `hevi/sourcing/media_providers.py` 的既有做法,不是新发明。
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from hevi.creative.autonomous.acquire import (
    NormalizedCandidate,
    normalize_local_asset,
)
from hevi.creative.autonomous.canonical import AssetRequirement
from hevi.production.p7.asset_contract import AssetStatus
from hevi.production.p7.evidence import AssetEvidence
from hevi.providers.facts import (
    ProviderCapabilityState,
    ProviderCatalogue,
    ProviderKind,
    ProviderLicenseClass,
    ProviderLocality,
    ProviderProfile,
)

#: 物化文件后缀白名单 —— 与 `MEDIA_SUFFIXES` 同源,只取本包需要的部分。
STOCK_SUFFIX_BY_MEDIA_TYPE = {
    "VIDEO": ".mp4",
    "IMAGE": ".jpg",
    "AUDIO": ".mp3",
}

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class StockItem:
    """provider 返回的一条 stock 检索结果(**还没有**任何本地字节)。

    `license` 是自由文本,与全仓现状一致(p7 只要求非空即可审计);
    空值会导致证据无法标 AVAILABLE —— 见 `normalize_local_asset`。
    """

    external_id: str
    url: str
    title: str = ""
    media_type: str = "VIDEO"
    license: str = ""
    attribution: str = ""

    def __post_init__(self) -> None:
        if not self.external_id:
            raise ValueError("STOCK_ITEM_WITHOUT_EXTERNAL_ID")
        if not self.url:
            raise ValueError(f"STOCK_ITEM_WITHOUT_URL:{self.external_id}")
        if self.media_type not in STOCK_SUFFIX_BY_MEDIA_TYPE:
            raise ValueError(f"STOCK_ITEM_UNKNOWN_MEDIA_TYPE:{self.media_type}")


@runtime_checkable
class StockSource(Protocol):
    """stock provider 的窄接口:检索 + 取字节。

    网络实现属于 provider 层;本包**不放** HTTP 客户端,理由同
    `hevi/acquisition/acquire.py`:"No network client lives here."
    """

    provider_id: str

    async def search(self, query: str, *, media_type: str,
                     limit: int) -> tuple[StockItem, ...]: ...

    async def fetch(self, item: StockItem, destination: Path) -> Path: ...


def default_cache_dir() -> Path:
    return Path(os.getenv("MATERIAL_CACHE_DIR", "") or "data/material_cache")


def materialize_name(item: StockItem) -> str:
    """`<slug>-<sha256(url)[:16]><suffix>`。

    slug 让磁盘上的资产可读(人能看到它是什么),sha 消歧(同标题不同 URL 不撞车)。
    注意:slug 会被 domain scorer 读到 —— 这是 F3 的依赖,见 docs/p10/p2a_entry_audit.md。
    """
    suffix = STOCK_SUFFIX_BY_MEDIA_TYPE[item.media_type]
    words = _SLUG_STRIP.sub("-", item.title.lower()).strip("-")
    digest = hashlib.sha256(item.url.encode("utf-8")).hexdigest()[:16]
    return f"{words[:60] or item.external_id}-{digest}{suffix}"


class StockAssetAcquirer:
    """按 canonical requirement 提出**全部**可用的 stock 候选。

    刻意不是 `Acquirer`:见模块 docstring。

    `declared_license_class` 是 provider 级声明(进入 `ProviderProfile`),
    与 `StockItem.license` 的 per-asset 声明是两层,不可互相替代。
    """

    def __init__(
        self,
        source: StockSource,
        *,
        cache_dir: Path | None = None,
        declared_license_class: ProviderLicenseClass = ProviderLicenseClass.LICENSED,
        kind: ProviderKind = ProviderKind.IMAGE,
    ) -> None:
        self._source = source
        self._cache_dir = Path(cache_dir) if cache_dir is not None else default_cache_dir()
        self._license_class = declared_license_class
        self._kind = kind

    @property
    def provider_id(self) -> str:
        return self._source.provider_id

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    @property
    def declared_license_class(self) -> ProviderLicenseClass:
        return self._license_class

    def provider_profile(self) -> ProviderProfile:
        """本 acquirer 对自己 provider 的**声明**(不写全局 catalogue)。"""
        return ProviderProfile(
            provider_id=self.provider_id,
            kind=self._kind,
            locality=ProviderLocality.REMOTE,
            license_class=self._license_class,
            capability_state=ProviderCapabilityState.AVAILABLE,
            notes="P2-A stock; facts declared here so the catalogue stays the only source",
        )

    def provider_catalogue(self) -> ProviderCatalogue:
        return ProviderCatalogue((self.provider_profile(),))

    def provider_policy(self) -> Any:
        """canonical provider policy。stock provider 不声明 mode 门槛。

        与 `ProceduralAcquirer.provider_policy()` 同形 —— acquisition 链对两者
        一视同仁,只要求「这个对象能给出自己的 policy」。
        """
        from hevi.provider_policy.policy import ProviderPolicy

        return ProviderPolicy(candidates=[self.provider_id], quality_floor=0)

    async def propose(
        self,
        requirement: AssetRequirement,
        *,
        limit: int = 5,
    ) -> tuple[NormalizedCandidate, ...]:
        """检索 + 物化 + canonical 校验,返回**全部**合规候选。

        不排序、不挑最高分、不返回「赢家」。取舍是
        `scorer → selector` 的职责,不是本方法的。
        """
        query = requirement.query() or requirement.semantic_role.value
        try:
            items = await self._source.search(
                query, media_type=requirement.media_type.value, limit=limit)
        except Exception:
            return ()
        if not items:
            return ()
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        out: list[NormalizedCandidate] = []
        for item in items:
            destination = self._cache_dir / materialize_name(item)
            try:
                path = await self._source.fetch(item, destination)
            except Exception:
                continue
            normalized = normalize_local_asset(
                requirement, Path(path), source=f"{self.provider_id}:{item.external_id}",
                license_name=item.license)
            # 只提「证据可用」的候选;不合规的留在 CompatibilityReport 里可查。
            if normalized.evidence.status is AssetStatus.AVAILABLE:
                out.append(normalized)
        return tuple(out)


def acquisition_outcome_evidence(
    requirement: AssetRequirement, acquirer: StockAssetAcquirer, reason: str,
) -> AssetEvidence:
    """acquisition 阶段失败的证据。fail-closed:永远不是 AVAILABLE。"""
    return AssetEvidence(
        asset_id=f"stock:{requirement.requirement_id}:{acquirer.provider_id}",
        source=f"stock:{acquirer.provider_id}",
        status=AssetStatus.BLOCKED,
        license=acquirer.declared_license_class.value,
        validation=reason,
    )


__all__ = [
    "STOCK_SUFFIX_BY_MEDIA_TYPE",
    "StockAssetAcquirer",
    "StockItem",
    "StockSource",
    "acquisition_outcome_evidence",
    "default_cache_dir",
    "materialize_name",
]
