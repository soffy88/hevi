"""MCP tools: 3O 内化能力 —— watch / media_resolve / repair / promote / chat。

让 agent 在既有 MCP 面直接调用内化能力(对应 HyperFrames 19-skill + claude-video
skill 生态的分发形态)。全部 handler 为纯服务层调用,无网络依赖时优雅降级。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from obase.mcp_server import SkillDef

from hevi.director.chat_assistant import XiaAssistant
from hevi.director.promotion import PromotionCandidate, PromotionPool
from hevi.director.repair_agents import plan_repair, repair_decision
from hevi.mcp.schemas import (
    EMBRACE_CHAT_INPUT,
    EMBRACE_CHAT_OUTPUT,
    EMBRACE_MEDIA_RESOLVE_INPUT,
    EMBRACE_MEDIA_RESOLVE_OUTPUT,
    EMBRACE_PROMOTE_INPUT,
    EMBRACE_PROMOTE_OUTPUT,
    EMBRACE_REPAIR_PLAN_INPUT,
    EMBRACE_REPAIR_PLAN_OUTPUT,
    EMBRACE_WATCH_INPUT,
    EMBRACE_WATCH_OUTPUT,
)
from hevi.verdict.convergence import ConvergenceLog

#: 进程内状态(与 API 路由同模式;重启即失,可落盘)。
_CHAT = XiaAssistant()
_CONVERGENCE = ConvergenceLog()
_POOLS: dict[str, PromotionPool] = {}


def _pool(project_id: str) -> PromotionPool:
    if project_id not in _POOLS:
        _POOLS[project_id] = PromotionPool()
    return _POOLS[project_id]


def build_embrace_skills() -> list[SkillDef]:
    async def _watch(args: dict[str, Any]) -> dict[str, Any]:
        from hevi.ingest.video_frames import WatchDetail
        from hevi.ingest.video_watch import watch_video

        source = args["source"]
        work_dir = Path(args.get("work_dir", ".hevi_mcp_watch"))
        result = await asyncio.to_thread(
            watch_video,
            source,
            work_dir,
            detail=WatchDetail(args.get("detail", "balanced")),
            budget=args.get("budget") or None,
        )
        out: dict[str, Any] = {
            "frames": result.frame_count,
            "duration_s": round(result.duration_s, 2),
            "transcript_segments": len(result.transcript),
            "notes": result.notes,
        }
        if args.get("contact_sheet") and result.frames:
            from hevi.ingest.contact_sheet import build_contact_sheet

            sheet = build_contact_sheet(
                [f.path for f in result.frames],
                work_dir / "contact_sheet.jpg",
                cols=5,
                thumb_width=320,
            )
            out["contact_sheet"] = str(sheet)
        return out

    async def _media_resolve(args: dict[str, Any]) -> dict[str, Any]:
        from hevi.sourcing.media_providers import default_providers
        from hevi.sourcing.media_use import MediaLedger, ResolveError, resolve_media

        providers = default_providers()
        ledger = MediaLedger()
        try:
            resolution = await asyncio.to_thread(
                resolve_media,
                args["type"],
                args["intent"],
                providers=providers,
                ledger=ledger,
                verify_paths=True,
            )
            return {
                "resolved": True,
                "path": str(resolution.path),
                "source": resolution.source,
                "error": "",
            }
        except ResolveError as e:
            return {"resolved": False, "path": "", "source": "", "error": str(e)}

    async def _repair_plan(args: dict[str, Any]) -> dict[str, Any]:
        failures = args["failures"]
        plan = plan_repair(failures, budget_limit=args.get("budget_limit", 3))
        decision = repair_decision(plan, _CONVERGENCE)
        return {
            "actions": [a.to_dict() for a in plan.actions],
            "budget_used": plan.budget_used,
            "decision_status": decision.get("status"),
        }

    async def _promote(args: dict[str, Any]) -> dict[str, Any]:
        pool = _pool(args["project_id"])
        try:
            pool.add_candidate(
                PromotionCandidate(
                    candidate_id=args["candidate_id"],
                    kind=args["kind"],
                    name=args["name"],
                    source="mcp",
                    score=args.get("score", 0.0),
                )
            )
        except ValueError as e:
            return {"promoted": False, "asset_id": "", "issues": [str(e)]}
        asset, issues = pool.promote(args["candidate_id"])
        return {
            "promoted": asset is not None,
            "asset_id": asset.asset_id if asset else "",
            "issues": issues,
        }

    async def _chat(args: dict[str, Any]) -> dict[str, Any]:
        result = _CHAT.handle(args["project_id"], args["message"])
        return {"reply": result["reply"], "intent": result["intent"], "turn": result["turn"]}

    return [
        SkillDef(
            name="hevi.watch_video",
            description="看视频:URL/本地 → 帧+转写+联络表(摄入侧,参考 /watch)",
            input_schema=EMBRACE_WATCH_INPUT,
            output_schema=EMBRACE_WATCH_OUTPUT,
            handler=_watch,
        ),
        SkillDef(
            name="hevi.media_resolve",
            description="媒体台账:一个 resolve 动词(bgm/sfx/image/voice/grade/lut…)→ 冻结文件",
            input_schema=EMBRACE_MEDIA_RESOLVE_INPUT,
            output_schema=EMBRACE_MEDIA_RESOLVE_OUTPUT,
            handler=_media_resolve,
        ),
        SkillDef(
            name="hevi.repair_plan",
            description="失败镜头 → 修复计划(agent 表映射 + 尝试预算 + 收敛决策)",
            input_schema=EMBRACE_REPAIR_PLAN_INPUT,
            output_schema=EMBRACE_REPAIR_PLAN_OUTPUT,
            handler=_repair_plan,
        ),
        SkillDef(
            name="hevi.promote_candidate",
            description="候选提升双轨:探索候选 → 主线资产(评分过线+无冲突)",
            input_schema=EMBRACE_PROMOTE_INPUT,
            output_schema=EMBRACE_PROMOTE_OUTPUT,
            handler=_promote,
        ),
        SkillDef(
            name="hevi.chat",
            description="Xia 会话制片助理:状态/推进/审计/修复/提升",
            input_schema=EMBRACE_CHAT_INPUT,
            output_schema=EMBRACE_CHAT_OUTPUT,
            handler=_chat,
        ),
    ]
