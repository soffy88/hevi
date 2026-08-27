"""场景块工作流 —— 3D 视角条件帧组 + 空间契约(3GS G2 落地,omodul 三件套)。

SPEC-3GS-world-set.md 门 1/2 的运行时:给定场景道具 + 机位方位角组 → Prop3D provider
逐方位渲条件帧(3D 视角结构)+ scene_contract 空间契约报告。消费模式 3 落地:
3D 视角结构帧 + 2D 身份参考一起喂 i2v(身份由 2D 保证,视角由 3D 保证)。

3O 归属(待上游): `omodul.scene_block_workflow`。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.director.prop3d import Prop3DError, render_azimuth_frames

logger = logging.getLogger(__name__)

#: 标准机位方位角组(正反打/越轴演示用):正对/左 45/右 45/背后。
DEFAULT_AZIMUTHS: tuple[float, ...] = (0.0, 45.0, -45.0, 180.0)


@dataclass
class SceneBlockConfig:
    """场景块配置。"""

    out_dir: Path
    prop_name: str
    azimuths: tuple[float, ...] = DEFAULT_AZIMUTHS
    width: int = 512
    height: int = 512
    camera: dict[str, float] = field(default_factory=dict)


@dataclass
class SceneBlockInput:
    """输入:道具参考图 + 可选 LLM(blueprint 生成)。"""

    reference_image: Path
    llm: Callable[..., str] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


async def scene_block_workflow(
    config: SceneBlockConfig,
    input_data: SceneBlockInput,
    output_dir: Path,
    *,
    on_step: Any = None,
) -> dict[str, Any]:
    """标准 omodul:blueprint → threejs 代码 → 逐方位条件帧 + 空间契约。

    失败不 raise;LLM/浏览器缺失 → status=failed 带配置指引。
    """
    _enabled_pillars = {"report", "cost", "decision_trail"}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    def _step(stage: str, pct: float) -> None:
        if callable(on_step):
            on_step({"stage": stage, "pct": pct})

    try:
        from hevi.director.prop3d import (
            Prop3DError as PE,
        )
        from hevi.director.prop3d import (
            blueprint_to_threejs,
            build_prop_blueprint,
        )
        from hevi.director.scene_contract import check_camera_continuity

        if not input_data.reference_image.exists():
            return {
                "status": "failed",
                "error": f"reference image not found: {input_data.reference_image}",
            }
        _step("reference", 10.0)

        # G2:图生 3D(blueprint → threejs 代码);LLM 缺失 → 明确指引
        try:
            blueprint = build_prop_blueprint(
                input_data.reference_image, llm=input_data.llm
            )
            model_code = blueprint_to_threejs(blueprint, llm=input_data.llm)
        except (Prop3DError, PE) as e:
            return {
                "status": "failed",
                "error": f"图生3D失败(需 LLM 注入,img2threejs 方法论): {e}",
            }
        _step("blueprint", 45.0)

        # 机位 → 条件帧(浏览器渲染;同步 playwright 必须在线程里跑)
        frames_dir = output_dir / "frames"
        try:
            frames = await __import__("asyncio").to_thread(
                render_azimuth_frames,
                model_code,
                azimuths=list(config.azimuths),
                out_dir=frames_dir,
                width=config.width,
                height=config.height,
                camera=config.camera,
            )
        except Exception as e:
            # Keep the failure contract explicit: browser/render failures are
            # recoverable workflow failures, and callers need to distinguish
            # them from blueprint/LLM validation errors.
            return {"status": "failed", "error": f"playwright render failed: {e}"}
        _step("render", 80.0)

        # 空间契约:机位方向推导 + 相邻机位无越轴(确定性,复用 ShotListItem)
        from hevi.director.pipeline_schemas import ShotListItem

        shots = [
            ShotListItem(
                shot_id=f"prop-{config.prop_name}-az{az:03.0f}",
                scene_no=1,
                camera_angle=f"azimuth {az}",
                azimuth_deg=az,
            )
            for az in config.azimuths
        ]
        contract = check_camera_continuity(shots)

        report = {
            "status": "completed",
            "prop": config.prop_name,
            "frames": [str(f) for f in frames],
            "azimuths": list(config.azimuths),
            "spatial_contract": contract.__dict__,
            "consumption_note": (
                "消费模式 3:3D 视角结构帧(本 workflow)+ 2D 身份参考一起喂 i2v;"
                "身份由 2D 保证,视角由 3D 保证"
            ),
        }
        report_path = output_dir / "scene_block_report.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"status": "completed", **report, "report_path": str(report_path)}
    except Exception as e:
        logger.exception("scene_block_workflow failed")
        return {"status": "failed", "error": str(e)}
