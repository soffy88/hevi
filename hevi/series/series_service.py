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
        return await self._repo.create(
            {
                "name": name.strip(),
                "user_id": user_id,
                "subject_ids": subject_ids or [],
                "style_preset": style_preset,
                "style_pack_id": uuid.UUID(style_pack_id) if style_pack_id else None,
                "style_pack_version": 1,
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
        self, series_id: str, *, topic: str, task_service: Any = None
    ) -> dict[str, Any]:
        """做第 N 集:继承 Series 的角色组/风格/规格,只写新 topic → 创建 inheriting VideoTask。"""
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

        # 其余 spec 键(num_characters / quality_profile / prompt_* / transition …)+ 风格 + 角色
        # → config_json(create_task 的 **kwargs)。这就是"继承全部"。
        ctrl: dict[str, Any] = dict(spec)
        if series.get("style_preset"):
            ctrl.setdefault("style_preset", series["style_preset"])
        subject_ids = series.get("subject_ids") or []
        if subject_ids:
            ctrl.setdefault("subject_id", subject_ids[0])

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
            except Exception:  # 解析失败 → 回退 style_preset,不阻断建集
                pass

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
