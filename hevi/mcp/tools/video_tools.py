"""MCP tool: generate_longvideo — wraps P10.D orchestrator."""

from __future__ import annotations

from typing import Any

from obase.mcp_server import SkillDef

from hevi.mcp.schemas import GENERATE_LONGVIDEO_INPUT, GENERATE_LONGVIDEO_OUTPUT
from hevi.pipeline.longvideo_orchestrator import orchestrate_longvideo


def build_video_skills() -> list[SkillDef]:
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = await orchestrate_longvideo(
            topic=args["topic"],
            duration_archetype=args["duration_archetype"],
            video_provider=args["video_provider"],
            audio_provider=args["audio_provider"],
            style=args.get("style", "cinematic"),
            language=args.get("language", "zh"),
        )
        return result

    return [
        SkillDef(
            name="hevi.generate_longvideo",
            description="AI触发长视频生成，基于主题/时长档/provider编排完整视频管线",
            input_schema=GENERATE_LONGVIDEO_INPUT,
            output_schema=GENERATE_LONGVIDEO_OUTPUT,
            handler=_handler,
        )
    ]
