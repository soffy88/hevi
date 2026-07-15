"""SeriesService —— 系列资产 + "第 N 集 = 继承全部 + 只写新剧情"。

create_episode 是护城河的实体:从 Series 拉取角色组 / StylePack / 规格锁,组装成一个
inheriting 的 VideoTask,只有 topic 是新的 → 风格/角色/画幅跨集不漂移。迁移成本即护城河。
"""

from __future__ import annotations

import uuid
from typing import Any

from hevi.series.repository import SeriesRepository


class SeriesService:
    def __init__(
        self, repo: SeriesRepository, task_service: Any = None, style_service: Any = None
    ) -> None:
        self._repo = repo
        self._task_service = task_service
        self._style_service = style_service  # StylePackService,用于 create_episode 展开风格

    async def create_series(
        self,
        *,
        name: str,
        subject_ids: list[str] | None = None,
        style_preset: str = "",
        style_pack_id: str | None = None,
        spec: dict[str, Any] | None = None,
        user_id: str | None = None,
        intro_template_id: str | None = None,
        outro_template_id: str | None = None,
    ) -> dict[str, Any]:
        if not name.strip():
            raise ValueError("name must not be empty")
        # HEVI 路线图 Phase3 #39:建系列时如果引用了一个已存在的 StylePack,应该记它
        # 当前实际是第几版,而不是硬编码 1——用户完全可能引用一个已经改过好几次的
        # 老 pack,硬编码 1 会让这个字段从一开始就是错的(create_episode 每次建集时
        # 重新 resolve 拿的是实时版本,不受这个字段影响,但 API 直接把 Series 记录
        # 返回给前端,这个字段本身该反映事实)。
        style_pack_version = 1
        if style_pack_id and self._style_service is not None:
            try:
                pack = await self._style_service.get_pack(style_pack_id)
                if pack is not None:
                    style_pack_version = int(pack.get("version", 1))
            except Exception:  # 查不到就用默认值 1,不阻断建系列
                pass
        return await self._repo.create(
            {
                "name": name.strip(),
                "user_id": user_id,
                "subject_ids": subject_ids or [],
                "style_preset": style_preset,
                "style_pack_id": uuid.UUID(style_pack_id) if style_pack_id else None,
                "style_pack_version": style_pack_version,
                "spec_json": spec or {},
                "intro_template_id": intro_template_id,
                "outro_template_id": outro_template_id,
                "episode_count": 0,
            }
        )

    async def get_series(self, series_id: str) -> dict[str, Any] | None:
        return await self._repo.get(series_id)

    async def list_series(self, *, user_id: str | None = None) -> list[dict[str, Any]]:
        return await self._repo.list_series(user_id=user_id)

    async def list_episodes(self, series_id: str) -> list[dict[str, Any]]:
        return await self._repo.episodes(series_id)

    async def create_episode(
        self,
        series_id: str,
        *,
        topic: str,
        task_service: Any = None,
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """做第 N 集:继承 Series 的角色组/风格/规格,只写新 topic → 创建 inheriting VideoTask。

        overrides:逐集覆盖(如"这一集临时换角色/改风格"),键与 create_task 的
        config_json 同命名空间;给了就覆盖 Series 继承的默认值,没给的键仍按继承 ——
        覆盖在 StylePack 展开之后应用,即显式逐集覆盖 > StylePack > style_preset 名。
        """
        svc = task_service or self._task_service
        if svc is None:
            raise ValueError("task_service required (via ctor or arg)")
        series = await self._repo.get(series_id)
        if series is None:
            raise ValueError(f"Series {series_id} not found")

        spec = dict(series.get("spec_json") or {})
        video_provider = spec.pop("video_provider", "ltx2_cloud")
        audio_provider = spec.pop("audio_provider", "edge_tts")
        duration_archetype = spec.pop("duration_archetype", "1-5min")
        # SPEC-001 §6:季级预算熔断(独立于 create_task 内部的单任务/日预算熔断)。
        # 塞进 spec_json,不建新列——沿用本函数已有的"Series 配置走 spec_json JSONB"惯例。
        series_budget_usd = spec.pop("budget_usd", None)

        # 其余 spec 键(num_characters / quality_profile / prompt_* / transition …)+ 风格 + 角色
        # → config_json(create_task 的 **kwargs)。这就是"继承全部"。
        ctrl: dict[str, Any] = dict(spec)
        if series.get("style_preset"):
            ctrl.setdefault("style_preset", series["style_preset"])
        subject_ids = series.get("subject_ids") or []
        if subject_ids:
            ctrl.setdefault("subject_id", subject_ids[0])

        # 片头/片尾:此前只存不消费(orchestrate_longvideo 无从得知)。当前语义 =
        # 直接文件路径(非 canvas 模板渲染,那是更重的独立工程)——每集继承同一份。
        if series.get("intro_template_id"):
            ctrl.setdefault("intro_clip", series["intro_template_id"])
        if series.get("outro_template_id"):
            ctrl.setdefault("outro_clip", series["outro_template_id"])

        # StylePack↔Series 自动展开:series 引用 StylePack → resolve 成 prompt_*(覆盖 preset,
        # 保证该 Series 用的是它锁定的那份风格资产)。需注入 style_service。
        pack_id = series.get("style_pack_id")
        if pack_id and self._style_service is not None:
            try:
                resolved = await self._style_service.resolve(str(pack_id))
                for src, dst in (
                    ("style", "prompt_style"),
                    ("lighting", "prompt_lighting"),
                    ("camera", "prompt_camera"),
                    ("color_grade", "prompt_color_grade"),
                ):
                    if resolved.get(src):
                        ctrl[dst] = resolved[src]  # 显式覆盖(StylePack 优先于 preset 名)
                # shot_verdict 版本快照(HEVI 路线图 Phase1):记这一集生成时 StylePack 实际
                # 是哪个版本,而不是"当前版本引用"——StylePack 升级后,这一集的历史校验
                # 记录不应该跟着失真。
                pack = await self._style_service.get_pack(str(pack_id))
                if pack is not None:
                    ctrl["style_pack_id"] = str(pack_id)
                    ctrl["style_pack_version"] = pack.get("version")
            except Exception:  # 解析失败 → 回退 style_preset,不阻断建集
                pass

        # 逐集覆盖:显式给了值就覆盖 Series 继承的默认(不给的键仍按继承)。三个顶层参数
        # (provider/时长档)单独弹出,其余键直接并入 ctrl。
        ov = dict(overrides or {})
        video_provider = ov.pop("video_provider", video_provider)
        audio_provider = ov.pop("audio_provider", audio_provider)
        duration_archetype = ov.pop("duration_archetype", duration_archetype)
        ctrl.update(ov)

        # SPEC-001 §6:季级预算熔断——在真建 task(真花算力)之前查这一季迄今实际花费
        # + 这一集预估是否会突破 Series 自己配置的 budget_usd。series_budget_usd 为
        # None(该季没配)则不查,零额外开销。
        if series_budget_usd is not None:
            from hevi.cost.circuit_breaker import check_series_budget
            from hevi.cost.estimator import estimate_cost

            estimate = await estimate_cost(
                duration_archetype=duration_archetype,
                video_provider=video_provider,
                audio_provider=audio_provider,
                num_characters=ctrl.get("num_characters", 1),
            )
            await check_series_budget(
                svc.repository.pool,
                series_id=series_id,
                additional_usd=estimate.total_usd,
                series_budget_usd=float(series_budget_usd),
            )

        episode_index = int(series.get("episode_count", 0))
        task = await svc.create_task(
            topic=topic,
            duration_archetype=duration_archetype,
            video_provider=video_provider,
            audio_provider=audio_provider,
            user_id=series.get("user_id"),
            **ctrl,
        )
        # 绑定 Series FK + 集序号,递增集数。
        await svc.repository.update_task(
            task["id"], {"series_id": uuid.UUID(series_id), "episode_index": episode_index}
        )
        await self._repo.update(series_id, {"episode_count": episode_index + 1})
        return {**task, "series_id": series_id, "episode_index": episode_index}
