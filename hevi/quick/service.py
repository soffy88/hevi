"""hevi.quick —— 轻量「主题→短视频」快速通道(3O omodul 风格, 差距 A5)。

对标 MoneyPrinterTurbo 的一键极简路径(主题 → LLM 脚本 → 素材 → TTS → 合成),
补 hevi 差距: 此前全是重流程(制片厂), 无「一句话出片」档。

契约(3O omodul 标准签名):
    quick_video(config, input_data, output_dir) -> dict
      config:   {tts_provider, material_keys, aspect, target_duration_s, max_sources}
      input_data: {topic: str}
      output_dir: 产物目录
      返回: {status, video_path?, script, materials, tts_segments, notes}
    失败返回 status="failed"(不 raise), 满足 omodul 返回契约。

组合(≥2 个 oskill/oprim 的 omodul):
    plan_quick_script (LLM 脚本) + material 检索(A4 material_corpus) + TTS(现有
    audio_router 注入) + 轻量装配(ffmpeg 或 oprim 合成, 由 config 指定)。

装配是可选的: `quick_video` 默认产出「可装配清单」(script + materials + 音频),
调用方/上游可接现有 explainer/assembly; config.assemble=True 时才真合成。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 缺省产出规格: 15-60s 竖屏解说(MPT 默认同档)。
DEFAULT_ASPECT = "9:16"
DEFAULT_TARGET_S = 40.0


@dataclass
class QuickVideoConfig:
    aspect: str = DEFAULT_ASPECT
    target_duration_s: float = DEFAULT_TARGET_S
    max_lines: int = 6
    tts_provider: str = "voicebox"
    assemble: bool = False
    material_keys: dict[str, str] = field(default_factory=dict)  # {pexels/pixabay/coverr: key}
    include_archive: bool = True
    max_sources: int = 5
    output_name: str = "quick_video"

    def to_dict(self) -> dict[str, Any]:
        return {
            "aspect": self.aspect,
            "target_duration_s": self.target_duration_s,
            "max_lines": self.max_lines,
            "tts_provider": self.tts_provider,
            "assemble": self.assemble,
            "include_archive": self.include_archive,
            "max_sources": self.max_sources,
            "output_name": self.output_name,
        }


# LLM 注入点: 默认不依赖 LLM(确定性模板脚本), 可注入增强版。
ScriptPlanner = Callable[[str, QuickVideoConfig], list[dict[str, Any]]]


def _default_script_planner(topic: str, cfg: QuickVideoConfig) -> list[dict[str, Any]]:
    """确定性脚本模板: 钩子 + 展开 + 收尾(无 LLM, 零依赖可测)。"""
    hook = f"你知道吗?{topic}背后藏着这些细节。"
    lines = [hook]
    lines.extend(
        f"{topic}的第{i}个关键点:值得你记住。"
        for i in range(1, min(cfg.max_lines, 5) - 1)
    )
    lines.append(f"关于{topic},你还想了解什么?评论区告诉我。")
    return [{"text": t, "scene": i} for i, t in enumerate(lines)]


@dataclass
class QuickPlan:
    """可装配清单: 脚本行 + 素材建议 + 音频段(合成前置产物)。"""

    topic: str
    script_lines: list[dict[str, Any]]
    materials: list[dict[str, Any]]
    tts_segments: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "script_lines": self.script_lines,
            "materials": self.materials,
            "tts_segments": self.tts_segments,
            "notes": self.notes,
        }


async def plan_quick(
    topic: str,
    cfg: QuickVideoConfig,
    *,
    script_planner: ScriptPlanner | None = None,
    material_search: Callable[[str, QuickVideoConfig], list[dict[str, Any]]] | None = None,
) -> QuickPlan:
    """编排: 脚本规划 + 素材检索(注入式, 便于测试)。"""
    planner = script_planner or _default_script_planner
    lines = planner(topic, cfg)
    materials: list[dict[str, Any]] = []
    if material_search is not None:
        materials = material_search(topic, cfg)
    return QuickPlan(topic=topic, script_lines=lines, materials=materials)


async def quick_video(
    config: dict[str, Any] | None,
    input_data: dict[str, Any],
    output_dir: Path | str,
) -> dict[str, Any]:
    """3O omodul 入口: topic → 可装配清单(可选合成)。失败返回 status="failed"。"""
    cfg = QuickVideoConfig(**{**QuickVideoConfig().to_dict(), **(config or {})})
    out = Path(output_dir)
    try:
        topic = str(input_data.get("topic", "")).strip()
        if not topic:
            raise ValueError("input_data.topic is required")
        from hevi.quick.material import search_materials_for_topic

        plan = await plan_quick(
            topic,
            cfg,
            material_search=search_materials_for_topic,
        )
        out.mkdir(parents=True, exist_ok=True)
        manifest_path = out / f"{cfg.output_name}.plan.json"
        manifest_path.write_text(
            json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result: dict[str, Any] = {
            "status": "ok",
            "video_path": "",
            "plan_path": str(manifest_path),
            "topic": topic,
            "script_lines": plan.script_lines,
            "materials": plan.materials,
            "notes": plan.notes,
        }
        if cfg.assemble:
            from hevi.quick.assemble import assemble_quick

            video_path = await assemble_quick(plan, out, cfg)
            result["video_path"] = str(video_path)
            result["tts_segments"] = plan.tts_segments
        return result
    except Exception as exc:
        logger.exception("quick_video failed")
        return {"status": "failed", "error": str(exc), "topic": input_data.get("topic", "")}


__all__ = ["QuickPlan", "QuickVideoConfig", "plan_quick", "quick_video"]
