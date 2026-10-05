"""P2-B1:Procedural Acquirer —— 本地代码渲出真实画面,产出**候选**(不选)。

第一版只支持**一种能力** `PROCEDURAL_MOTION_GRAPHICS`,**一个 backend** Manim。
不做 Blender / Remotion / HTML-GSAP —— 那会变成并行实施,不是垂直切片。

纪律与 `acquire_stock.py` 完全一致,并额外加一条 B1 才有的:

- **不选择**:Acquirer 只产出候选,选谁永远回到 `scorer → selector → ShotResolution`;
- **`substitute_kind` 必须诚实**:由 **recipe** 声明(配方的固有属性),
  **不得**由 `propose()` 根据 requirement 的禁止清单挑选。否则 acquirer
  就成了「看约束挑标签」的角色,等于自己给自己发通行证。
  `test_p2b1_02` 钉住:同一 recipe 无论 requirement 禁什么,kind 恒定。

## `substitute_kind` 为什么必须自报

B0 把「禁止替代物」接进了 canonical seam,但 seam 需要 `observed["substitute_kind"]`。
不自报 → `undecidable_keys` 非空 → `compatible` False → **全部拒绝**。

所以 B0 的 fail-closed 正好在这里生效:程序化素材**必须**诚实申报自己是什么,
否则连候选都进不了。这不是可选的元数据,是准入条件。

## 复用既有能力

渲染走 `hevi/providers/manim/provider.py::manim_generate` —— canonical Manim 能力。
本包**不**自己 spawn manim CLI,渲染器归 provider 层。
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from hevi.creative.autonomous.acquire import (
    NormalizedCandidate,
    normalize_local_asset,
)
from hevi.creative.autonomous.canonical import AssetRequirement
from hevi.production.p7.asset_contract import AssetStatus
from hevi.production.p7.asset_requirement import FORBIDDEN_SUBSTITUTES_SEPARATOR
from hevi.providers.facts import PROVIDER_CATALOGUE, ProviderCatalogue

#: B1 唯一支持的能力。复用 catalogue **已有**的拼写 —— `remotion` / `html_gsap`
#: 的 `capabilities` 里就是 `"motion_graphics"`,不引入第二种大小写风格。
PROCEDURAL_MOTION_GRAPHICS = "motion_graphics"

#: Manim 在 `PROVIDER_LIMITS.modes` 里只声明 `code_scene`。
#: 实测 `mode="t2v"` 会被拒(`mode_unsupported:t2v`)。
MANIM_PROVIDER_ID = "manim"
MANIM_POLICY_MODE = "code_scene"

#: 程序化素材的授权声明。与 provider 级 `GENERATED` 同向,不冒充 licensed。
PROCEDURAL_LICENSE = "HEVI-GENERATED"

#: B1 第一版**只**支持这一种能力。构造时校验,不做运行期降级。
SUPPORTED_CAPABILITIES: frozenset[str] = frozenset({PROCEDURAL_MOTION_GRAPHICS})

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


@runtime_checkable
class ProceduralBackend(Protocol):
    """程序化渲染后端。渲染器归 provider 层;本包只要求「给我一段代码,渲成文件」。"""

    backend_id: str

    async def render(self, *, source_code: str, output_path: Path, duration_s: float,
                     width: int, height: int, fps: int) -> Path: ...


@dataclass(frozen=True)
class ProceduralRecipe:
    """一个程序化配方:能力 + **诚实的** substitute_kind + Manim 源码生成。

    `substitute_kind` 是这个配方的**固有属性**。它不随 requirement 变化,
    否则「禁止替代物」就失去了意义。
    """

    recipe_id: str
    substitute_kind: str
    #: (requirement, slug) → Manim 源码。**不得**读 requirement 的禁止清单。
    build_source: object

    def __post_init__(self) -> None:
        if not self.recipe_id:
            raise ValueError("PROCEDURAL_RECIPE_WITHOUT_ID")
        if not self.substitute_kind:
            raise ValueError(f"PROCEDURAL_RECIPE_WITHOUT_SUBSTITUTE_KIND:{self.recipe_id}")
        # 与 B0 的取值校验同形:构造期失败,不留到运行期
        for token in self.substitute_kind.split(FORBIDDEN_SUBSTITUTES_SEPARATOR):
            if not token or not re.fullmatch(r"[a-z0-9_]+", token):
                raise ValueError(
                    f"MALFORMED_SUBSTITUTE_KIND:{token!r} in {self.recipe_id}")


def default_cache_dir() -> Path:
    return Path(os.getenv("MATERIAL_CACHE_DIR", "") or "data/material_cache")


def slugify(text: str) -> str:
    return _SLUG_STRIP.sub("-", text.lower()).strip("-")


class ProceduralAcquirer:
    """按 canonical requirement 提出程序化**候选**。

    刻意不是 `Acquirer`:该协议单值返回,单值返回本身就是选择(见 F10)。

    `capability` 是本 acquirer 唯一支持的能力,构造时校验
    (`SUPPORTED_CAPABILITIES`)。不在集合里直接抛错,不做运行期降级。

    能力校验落在本类而不是 `required_capabilities`,原因见
    docs/p10/p2_b1_decision.md 的 F16:policy 检查的是 `ProviderLimits` 的
    **字段名**,而 catalogue 声明的 `motion_graphics` 这类 token 永远无法通过。
    """

    def __init__(
        self,
        backend: ProceduralBackend,
        recipes: tuple[ProceduralRecipe, ...],
        *,
        capability: str = PROCEDURAL_MOTION_GRAPHICS,
        provider_id: str = MANIM_PROVIDER_ID,
        policy_mode: str = MANIM_POLICY_MODE,
        cache_dir: Path | None = None,
        width: int = 1280,
        height: int = 720,
        fps: int = 24,
    ) -> None:
        if not recipes:
            raise ValueError("PROCEDURAL_ACQUIRER_REQUIRES_RECIPES")
        if capability not in SUPPORTED_CAPABILITIES:
            raise ValueError(
                f"PROCEDURAL_CAPABILITY_UNSUPPORTED:{capability}; the first version "
                "supports PROCEDURAL_MOTION_GRAPHICS only")
        self._backend = backend
        self._recipes = recipes
        self._capability = capability
        self._provider_id = provider_id
        self._policy_mode = policy_mode
        self._cache_dir = Path(cache_dir) if cache_dir is not None else default_cache_dir()
        self._width = width
        self._height = height
        self._fps = fps

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def capability(self) -> str:
        return self._capability

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    def provider_policy(self) -> object:
        """provider policy 对象。mode 必须对上 `PROVIDER_LIMITS.modes`。"""
        from hevi.provider_policy.policy import ProviderPolicy

        return ProviderPolicy(mode=self._policy_mode, candidates=[self._provider_id],
                              quality_floor=0)

    def provider_catalogue(self) -> ProviderCatalogue:
        """用既有全局 catalogue。

        `manim` 已在册(LOCAL / GENERATED / ADOPTED),重复 `register` 会抛
        `PROVIDER_PROFILE_DUPLICATE` —— 所以这里**不**新建 profile。
        与 `acquire_stock.py` 的差别就在这里:stock provider 不在册。
        """
        return PROVIDER_CATALOGUE

    def supports(self, capability: str) -> bool:
        return capability == self._capability

    async def propose(
        self,
        requirement: AssetRequirement,
        *,
        limit: int = 5,
    ) -> tuple[NormalizedCandidate, ...]:
        """渲染 + canonical 校验,返回**全部**可用候选。不排序、不挑赢家。

        每张片子都走:`manim_generate` → `normalize_local_asset`
        (内含 `validate_media` + `check_compatibility`)→ 带 `substitute_kind` 自报。
        任何一步失败都只是**这一条**不产出候选,不会中断整批。
        """
        query = requirement.query() or requirement.semantic_role.value
        duration = _duration_from_requirement(requirement, default=4.0)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        out: list[NormalizedCandidate] = []
        for recipe in self._recipes[:limit]:
            slug = slugify(query) or slugify(recipe.recipe_id)
            digest = hashlib.sha256(
                f"{recipe.recipe_id}:{self._backend.backend_id}:{slug}".encode()
            ).hexdigest()[:16]
            destination = self._cache_dir / f"{recipe.substitute_kind}-{slug}-{digest}.mp4"
            source_code = str(recipe.build_source(requirement, slug))  # type: ignore[operator]
            try:
                rendered = await self._backend.render(
                    source_code=source_code, output_path=destination,
                    duration_s=duration, width=self._width, height=self._height,
                    fps=self._fps)
            except Exception:
                continue
            normalized = normalize_local_asset(
                requirement, Path(rendered),
                source=f"{self._provider_id}:{recipe.recipe_id}",
                license_name=PROCEDURAL_LICENSE,
                # B0 的准入条件:不 self-report 就进不了候选。
                observed_extra={"substitute_kind": recipe.substitute_kind},
            )
            if normalized.evidence.status is AssetStatus.AVAILABLE:
                out.append(normalized)
        return tuple(out)


def _duration_from_requirement(requirement: AssetRequirement, *, default: float) -> float:
    """`duration` 约束是**下限**(见 check_duration),所以取下限当目标时长。"""
    raw = requirement.constraint_map().get("duration", "")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if value <= 0:
        return default
    return value if value > 0.5 else 0.5


__all__ = [
    "MANIM_POLICY_MODE",
    "MANIM_PROVIDER_ID",
    "PROCEDURAL_LICENSE",
    "PROCEDURAL_MOTION_GRAPHICS",
    "SUPPORTED_CAPABILITIES",
    "ProceduralAcquirer",
    "ProceduralBackend",
    "ProceduralRecipe",
    "default_cache_dir",
    "slugify",
]