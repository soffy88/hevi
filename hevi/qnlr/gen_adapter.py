"""qnlr_gen_adapter — A0 v0 薄封装（tongjian avatar 通道）。

摸底文档：docs/specs/QNLR-AQIN-ADAPTER-001.md
立项/帽/熔断：docs/specs/QNLR-AQIN-PROJ-001.md（§1 ¥80 帽、§3 熔断第 5 条）

每个 adapter 调用 = 校验入参 → 调底层真实入口 → 记 cost/decision_trail →
（产物类）登记 vault → 返回 AdapterResult 信封。付费调用前过 check_and_reserve
卡累计帽，返回前过 §3.5 单价闸。不静默降级：熔断/超帽/单价越界一律 ok=False + reason。

只包不改（DR-1 约束 2）：底层入口全部延迟导入/可注入，本模块不改它们的内部。
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.cost.circuit_breaker import CostLimit, CostLimitExceeded, CostTracker
from hevi.cost.pricing_table import get_pricing_table

logger = logging.getLogger(__name__)

# Wiki 设定 2026-07-23（AQIN-PROJ §2.1）——provider 计费为 USD，金额帽为 ¥，需折算。
CNY_PER_USD = 6.75

# §3 熔断第 5 条阈值（人民币折算单价）。触阈视为路由异常信号，暂停核对。
VIDEO_PRICE_CNY_PER_S_CAP = 1.0
IMAGE_PRICE_CNY_PER_IMG_CAP = 0.1

# 默认路由（AQIN tranche 1）。
DEFAULT_VIDEO_PROVIDER = "happyhorse_1_1_maas"  # 唯一确认已充值付费路
DEFAULT_VIDEO_MODEL = "happyhorse_1_1"


@dataclass
class AdapterResult:
    """统一返回信封（摸底文档 §3）。"""

    ok: bool
    op: str  # "T-1" | "T-2" | "T-3" | "T-V"
    artifact_path: str | None = None
    pack_id: str | None = None  # vault fingerprint（产物类才有）
    cost_usd: float = 0.0
    unit_price_cny: float | None = None  # 折算单价（触发 §3.5 判定）
    decision_trail: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None  # 失败/降级原因（非 ok 时必填）


def _digest(inputs: dict[str, Any]) -> str:
    """输入指纹（确定性；非时钟非随机）。"""
    blob = repr(sorted((k, repr(v)) for k, v in inputs.items()))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


@dataclass
class GenAdapter:
    """A-QIN 生产调用的唯一入口（DR-1 约束 1）。

    在同一 run 里复用同一实例，`_breaker` 累计花费卡 ¥ 帽。产物登记走注入的
    `register_fn`（None → 跳过并记日志，供无 vault 基建时的烟测）。底层入口通过
    `*_fn` / `service` 注入，缺省时延迟导入真实实现——本模块导入时不拉重依赖。
    """

    cap_cny: float = 80.0
    cny_per_usd: float = CNY_PER_USD
    register_fn: Callable[..., str] | None = None
    _breaker: CostTracker = field(default_factory=CostTracker)

    # ---- 帽与花费 ----
    @property
    def _limit(self) -> CostLimit:
        return CostLimit(
            max_per_task_usd=self.cap_cny / self.cny_per_usd, max_per_task_seconds=1e12
        )

    @property
    def spent_usd(self) -> float:
        return float(self._breaker.spent_usd)

    @property
    def spent_cny(self) -> float:
        return float(self._breaker.spent_usd) * self.cny_per_usd

    def _price_usd(self, provider: str) -> tuple[float, str]:
        info = get_pricing_table().get(provider)
        if not info:
            raise ValueError(f"provider {provider!r} 不在 pricing_table——无法计价，拒绝付费调用")
        return float(info["price_usd"]), str(info["unit"])

    def _trail(
        self,
        *,
        op: str,
        provider: str | None,
        model: str | None,
        engine: str | None,
        seed: int | None,
        cost_usd: float,
        unit_price_cny: float | None,
        ts: str | None,
        inputs: dict[str, Any],
        fingerprint: str | None = None,
    ) -> dict[str, Any]:
        # ts 由调用方传入——adapter 不取时钟（可测 + 承接 no-clock 纪律）。
        return {
            "op": op,
            "provider": provider,
            "model_or_tier": model,
            "engine": engine,
            "seed": seed,
            "cost_usd": round(cost_usd, 6),
            "unit_price_cny": round(unit_price_cny, 4) if unit_price_cny is not None else None,
            "ts": ts,
            "inputs_digest": _digest(inputs),
            "fingerprint": fingerprint,
        }

    def _register(
        self, *, pack_type: str, name: str, artifact_path: str, provenance: dict[str, Any]
    ) -> str | None:
        if self.register_fn is None:
            logger.info(
                "qnlr_adapter: register_fn 未注入，跳过 vault 登记 (%s %s)",
                pack_type,
                artifact_path,
            )
            return None
        return self.register_fn(
            pack_type=pack_type, name=name, artifact_path=artifact_path, provenance=provenance
        )

    # ---- T-1 subject 摄取 / 身份锚（本地/免费）----
    async def ingest_subject(
        self,
        *,
        service: Any,
        kind: str,
        name: str,
        reference_images: list[str],
        want_3d: bool = True,
        ts: str | None = None,
    ) -> AdapterResult:
        try:
            subject = await service.create_subject(
                kind=kind, name=name, reference_images=reference_images
            )
            subject_id = subject["id"] if isinstance(subject, dict) else subject.id
            if want_3d:
                await service.generate_subject3d(subject_id)
        except Exception as e:
            return AdapterResult(ok=False, op="T-1", reason=f"subject 摄取失败: {e}")
        trail = self._trail(
            op="T-1",
            provider="local",
            model="clip+triposr",
            engine="local",
            seed=None,
            cost_usd=0.0,
            unit_price_cny=None,
            ts=ts,
            inputs={"kind": kind, "name": name, "refs": reference_images, "want_3d": want_3d},
        )
        pack_id = self._register(
            pack_type="aqin_char", name=name, artifact_path=str(subject_id), provenance=trail
        )
        trail["fingerprint"] = pack_id
        return AdapterResult(
            ok=True,
            op="T-1",
            artifact_path=str(subject_id),
            pack_id=pack_id,
            cost_usd=0.0,
            decision_trail=trail,
        )

    # ---- T-2 compose 合成（本地/免费）----
    def compose_layout(
        self,
        *,
        present: list[str],
        view_path_by_cid: dict[str, str],
        pos_desc_by_cid: dict[str, str],
        size: tuple[int, int],
        out_path: str,
        background: str | None = None,
        side_by_cid: dict[str, str] | None = None,
        ts: str | None = None,
        compose_fn: Callable[..., Any] | None = None,
    ) -> AdapterResult:
        fn = compose_fn
        if fn is None:
            from hevi.tongjian.scene_render_avatar import _compose_layout_base as fn  # type: ignore
        try:
            path = fn(
                present=present,
                view_path_by_cid=view_path_by_cid,
                pos_desc_by_cid=pos_desc_by_cid,
                size=size,
                out_path=out_path,
                background=background,
                side_by_cid=side_by_cid,
            )
        except Exception as e:
            return AdapterResult(ok=False, op="T-2", reason=f"compose 失败: {e}")
        if path is None:
            return AdapterResult(
                ok=False, op="T-2", reason="compose 返回 None（视图缺失，不静默降级）"
            )
        trail = self._trail(
            op="T-2",
            provider="local",
            model="compose_layout_base",
            engine="local",
            seed=None,
            cost_usd=0.0,
            unit_price_cny=None,
            ts=ts,
            inputs={"present": present, "size": size},
        )
        pack_id = self._register(
            pack_type="aqin_frame", name=out_path, artifact_path=str(path), provenance=trail
        )
        trail["fingerprint"] = pack_id
        return AdapterResult(
            ok=True,
            op="T-2",
            artifact_path=str(path),
            pack_id=pack_id,
            cost_usd=0.0,
            decision_trail=trail,
        )

    # ---- T-3 img2img 精修（含 txt2img 底版；本地/免费）----
    async def refine_image(
        self,
        *,
        prompt: str,
        output_path: str,
        init_image: str | None = None,
        negative: str = "",
        size: tuple[int, int] = (1024, 1024),
        seed: int | None = None,
        engine: str = "local",
        ts: str | None = None,
        gen_fn: Callable[..., Any] | None = None,
    ) -> AdapterResult:
        if engine != "local":
            # 云图像编辑路 2026-07-15 撞 FreeTierOnly 额度墙，v0 不启用（摸底文档 §4/§5）。
            return AdapterResult(
                ok=False,
                op="T-3",
                reason=f"engine={engine!r} 未启用（云图像编辑额度墙，v0 仅 local）",
            )
        fn = gen_fn
        if fn is None:
            from hevi.image.sdxl_local_service import sdxl_local_generate as fn  # type: ignore
        extra = {"init_image": init_image} if init_image else None
        try:
            await fn(
                prompt=prompt,
                negative_prompt=negative,
                width=size[0],
                height=size[1],
                output_path=output_path,
                seed=seed,
                extra=extra,
            )
        except Exception as e:
            return AdapterResult(ok=False, op="T-3", reason=f"本地 SDXL 失败: {e}")
        trail = self._trail(
            op="T-3",
            provider="sdxl_local",
            model="img2img" if init_image else "txt2img",
            engine="local",
            seed=seed,
            cost_usd=0.0,
            unit_price_cny=None,
            ts=ts,
            inputs={"prompt": prompt, "init": init_image, "size": size},
        )
        pack_id = self._register(
            pack_type="aqin_base", name=output_path, artifact_path=output_path, provenance=trail
        )
        trail["fingerprint"] = pack_id
        return AdapterResult(
            ok=True,
            op="T-3",
            artifact_path=output_path,
            pack_id=pack_id,
            cost_usd=0.0,
            decision_trail=trail,
        )

    # ---- T-V 视频（云/付费；G0 烟测路）----
    async def generate_video(
        self,
        *,
        prompt: str,
        output_path: str,
        provider: str = DEFAULT_VIDEO_PROVIDER,
        model: str = DEFAULT_VIDEO_MODEL,
        duration_s: int = 5,
        resolution: str = "720P",
        ratio: str = "16:9",
        seed: int | None = None,
        config: dict[str, Any] | None = None,
        name: str | None = None,
        ts: str | None = None,
        video_fn: Callable[..., Any] | None = None,
    ) -> AdapterResult:
        # 1) 计价 + §3.5 单价闸（付费前，已知价即拒越界路由）。
        try:
            price_usd, unit = self._price_usd(provider)
        except ValueError as e:
            return AdapterResult(ok=False, op="T-V", reason=str(e))
        if unit != "per_second":
            return AdapterResult(
                ok=False, op="T-V", reason=f"provider {provider!r} 计价单位 {unit!r} 非 per_second"
            )
        unit_price_cny = price_usd * self.cny_per_usd
        if unit_price_cny > VIDEO_PRICE_CNY_PER_S_CAP:
            return AdapterResult(
                ok=False,
                op="T-V",
                unit_price_cny=round(unit_price_cny, 4),
                reason=(
                    f"§3.5 视频单价 ¥{unit_price_cny:.3f}/s > ¥{VIDEO_PRICE_CNY_PER_S_CAP}/s，"
                    "路由异常，暂停核对"
                ),
            )
        # 2) 累计帽预留。
        est_usd = price_usd * duration_s
        try:
            await self._breaker.check_and_reserve(est_usd, self._limit)
        except CostLimitExceeded as e:
            return AdapterResult(
                ok=False,
                op="T-V",
                unit_price_cny=round(unit_price_cny, 4),
                reason=f"超金额帽 ¥{self.cap_cny}: {e}",
            )
        # 3) 真机调用。
        fn = video_fn
        if fn is None:
            from hevi.video.alibaba_maas_service import alibaba_maas_generate as fn  # type: ignore
        try:
            # alibaba_maas_generate 为全关键字签名，output_path 期望 Path。
            path = await fn(
                prompt=prompt,
                output_path=Path(output_path),
                model=model,
                resolution=resolution,
                ratio=ratio,
                duration=duration_s,
                seed=seed,
                config=config,
            )
        except Exception as e:
            self._breaker.spent_usd -= est_usd  # 调用失败，回滚预留
            return AdapterResult(ok=False, op="T-V", cost_usd=0.0, reason=f"provider 调用失败: {e}")
        # 4) 记账 + 留痕 + 登记。价来自 pricing_table（保守上限；真实账单以阿里控制台核对）。
        cost_usd = price_usd * duration_s
        trail = self._trail(
            op="T-V",
            provider=provider,
            model=model,
            engine="cloud",
            seed=seed,
            cost_usd=cost_usd,
            unit_price_cny=unit_price_cny,
            ts=ts,
            inputs={"prompt": prompt, "duration_s": duration_s, "resolution": resolution},
        )
        pack_id = self._register(
            pack_type="aqin_clip",
            name=name or output_path,
            artifact_path=str(path),
            provenance=trail,
        )
        trail["fingerprint"] = pack_id
        return AdapterResult(
            ok=True,
            op="T-V",
            artifact_path=str(path),
            pack_id=pack_id,
            cost_usd=cost_usd,
            unit_price_cny=round(unit_price_cny, 4),
            decision_trail=trail,
        )
