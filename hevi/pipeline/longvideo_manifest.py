"""3O §5 Task 5.2:长视频生产编排 Manifest(oservi.sequential_composer)。

Layer 4 声明式服务定义:以 oservi.SequentialComposerEngine 为骨架,注入 omodul
编排步骤。SPEC 目标分解:

    steps = [
        omodul.script_to_storyboard_workflow,  # 剧本与分镜
        omodul.shot_generation_workflow,       # 逐镜渲染
        omodul.video_assemble_workflow,        # 装配合成
    ]

当前 omodul (v1.36.0) 尚未提供这三个细粒度 workflow,端到端长视频生产由
``omodul.longvideo_produce.longvideo_produce`` 承载(其内部即剧本→分镜→逐镜→
装配)。此处 steps 以现有入口组装,并把 SPEC 的细粒度分解作为上游目标注明;
ServiceManifest 契约(inject/trigger/config)已按 SPEC 形状落地。

Layer 4 PII 脱敏约束:manifest 消费方在调起引擎前必须经
hevi.core.anon.sanitize_input_data 伪名化用户身份(见 make_longvideo_manifest)。
"""

from __future__ import annotations

from typing import Any

# SPEC 目标(上游 omodul 落地后替换 longvideo_produce 为三件套):
#   from omodul import script_to_storyboard_workflow, shot_generation_workflow
#   from omodul.video_assemble_workflow import video_assemble_workflow
# 当前 omodul 端到端入口:
from omodul.longvideo_produce import longvideo_produce
from oservi import ServiceManifest
from oservi.engines.sequential_composer import SequentialComposerEngine

from hevi.core.anon import anon_user_ref


def longvideo_production_manifest(
    *,
    user_id: str | None = None,
    config: dict[str, Any] | None = None,
) -> ServiceManifest:
    """构造长视频生产编排 Manifest(声明式、可复用于 on_demand 触发)。"""
    manifest_config = {
        "duration_archetype": "1-5min",
        "video_provider": "auto",
        "audio_provider": "vibevoice",
        "style": "cinematic",
        **(config or {}),
    }
    if user_id is not None:
        # Layer 4 强制脱敏:仅允许 anon_user_ref 进入 omodul 侧配置
        manifest_config["anon_user_ref"] = anon_user_ref(user_id)
    return ServiceManifest(
        name="longvideo_production",
        skeleton="sequential_composer",
        inject={
            "steps": [
                longvideo_produce,
            ],
            "router": None,
        },
        trigger={"mode": "on_demand"},
        config=manifest_config,
        depends_on=["obase.provider_registry", "obase.persistence.PgPool"],
    )


async def run_longvideo_composer(
    input_data: dict[str, Any],
    output_dir: Any = None,
    *,
    user_id: str | None = None,
    config: dict[str, Any] | None = None,
    on_step: Any = None,
) -> dict[str, Any]:
    """经 sequential_composer 引擎执行长视频生产(3O 编排入口)。

    input_data 先经伪名化清理再交给引擎/omodul;返回
    {"status": ..., "results": [...]}。
    """
    from hevi.core.anon import sanitize_input_data

    manifest = longvideo_production_manifest(user_id=user_id, config=config)
    engine = SequentialComposerEngine(
        steps=manifest.inject["steps"],
        router=None,
        trigger=manifest.trigger,
        config=manifest.config,
        name=manifest.name,
    )
    cleaned = sanitize_input_data(dict(input_data), user_id=user_id)
    return await engine.run(input_data=cleaned, output_dir=output_dir, on_step=on_step)
