"""MCP: Veya 调 Hevi 成品 + 日更一拍。"""

from __future__ import annotations

from typing import Any

from obase.mcp_server import SkillDef

from hevi.mcp.schemas import (
    GET_PRODUCE_JOB_INPUT,
    GET_PRODUCE_JOB_OUTPUT,
    LIST_STUDIO_LINES_INPUT,
    LIST_STUDIO_LINES_OUTPUT,
    PRODUCE_FINISHED_INPUT,
    PRODUCE_FINISHED_OUTPUT,
    TICK_DAILY_INPUT,
    TICK_DAILY_OUTPUT,
)


def build_studio_skills() -> list[SkillDef]:
    async def _produce(args: dict[str, Any]) -> dict[str, Any]:
        from hevi.studio.veya import produce

        slots = dict(args.get("slots") or {})
        if args.get("topic") and "topic" not in slots:
            slots["topic"] = args["topic"]
        job = await produce(
            line_id=str(args["line_id"]),
            slots=slots,
            render_runtime=args.get("render_runtime"),
            execute=bool(args.get("execute")),
            publish=bool(args.get("publish")),
            platforms=args.get("platforms"),
        )
        body = job.to_dict()
        body["status_url"] = f"/api/studio/veya/jobs/{job.job_id}"
        return {
            "job_id": job.job_id,
            "status": job.status,
            "product": job.product,
            "render_runtime": job.render_runtime,
            "artifact": job.artifact,
            "status_url": body["status_url"],
        }

    async def _get(args: dict[str, Any]) -> dict[str, Any]:
        from hevi.studio.veya import get_job

        job = get_job(str(args["job_id"]))
        if job is None:
            return {
                "job_id": args["job_id"],
                "status": "not_found",
                "product": "",
                "render_runtime": "",
                "artifact": "",
                "status_url": f"/api/studio/veya/jobs/{args['job_id']}",
            }
        return {
            "job_id": job.job_id,
            "status": job.status,
            "product": job.product,
            "render_runtime": job.render_runtime,
            "artifact": job.artifact,
            "status_url": f"/api/studio/veya/jobs/{job.job_id}",
        }

    async def _lines(_args: dict[str, Any]) -> dict[str, Any]:
        from hevi.studio.veya import list_capabilities

        caps = list_capabilities()
        return {
            "lines": caps["lines"],
            "runtimes": caps["runtimes"],
            "daily_lines": caps["daily_lines"],
        }

    async def _tick(args: dict[str, Any]) -> dict[str, Any]:
        from hevi.studio.daily import tick

        jobs = await tick(
            now=args.get("now"),
            calendar_id=args.get("calendar_id"),
            publish=bool(args.get("publish", True)),
        )
        return {"jobs": [j.to_dict() for j in jobs], "count": len(jobs)}

    return [
        SkillDef(
            name="hevi.produce_finished",
            description="Veya 调 Hevi 成品:选产线填槽,返回工单/成片路径",
            input_schema=PRODUCE_FINISHED_INPUT,
            output_schema=PRODUCE_FINISHED_OUTPUT,
            handler=_produce,
        ),
        SkillDef(
            name="hevi.get_produce_job",
            description="查询 Veya/制片厂成品工单",
            input_schema=GET_PRODUCE_JOB_INPUT,
            output_schema=GET_PRODUCE_JOB_OUTPUT,
            handler=_get,
        ),
        SkillDef(
            name="hevi.list_studio_lines",
            description="列出可交接成品的产线与运行时",
            input_schema=LIST_STUDIO_LINES_INPUT,
            output_schema=LIST_STUDIO_LINES_OUTPUT,
            handler=_lines,
        ),
        SkillDef(
            name="hevi.tick_daily",
            description="解说/历史现场日更排产一拍(可带发布交接单)",
            input_schema=TICK_DAILY_INPUT,
            output_schema=TICK_DAILY_OUTPUT,
            handler=_tick,
        ),
    ]
