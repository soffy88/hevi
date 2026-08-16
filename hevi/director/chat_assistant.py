"""Xia 会话制片助理 —— 会话层(3O 内化 Round 3e,来源 dramaclaw Xia Director + chat)。

dramaclaw 的 Xia 是会话式生产助理:检查项目进度、推进剧本/镜头任务、审计交付、
建议下一步。hevi 已有确定性审计内核(assistant.py);这里补**会话层**:按项目维护
会话状态(JSON),用户消息 → 确定性意图识别(状态/推进/审计/修复/提升/帮助)→ 调
audit_production + repair_agents + promotion 执行 → 自然语言回复骨架。

3O 归属(待上游): `oskill.director_assistant`(会话层 + 审计内核)。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.director.assistant import EpisodeState, audit_production
from hevi.director.promotion import PromotionPool, score_and_promote_batch
from hevi.director.repair_agents import plan_repair

logger = logging.getLogger(__name__)

#: 确定性意图词表(按项目消息匹配)。
_INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "status": ("状态", "进度", "到哪", "status", "progress"),
    "advance": ("推进", "下一步", "继续", "advance", "next"),
    "audit": ("审计", "检查", "完整性", "audit", "check"),
    "repair": ("修复", "返工", "失败", "repair", "fix", "rework"),
    "promote": ("提升", "候选", "promote", "candidate"),
    "help": ("帮助", "能做什么", "help", "? ", "？"),
}


@dataclass
class XiaSession:
    """一个项目的会话状态。"""

    project_id: str
    episodes: list[EpisodeState] = field(default_factory=list)
    promotion: PromotionPool = field(default_factory=PromotionPool)
    turn_count: int = 0
    last_intent: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "episodes": [
                {
                    "episode_id": e.episode_id,
                    "title": e.title,
                    "status": e.status,
                    "shots": [
                        {
                            "index": s.index,
                            "status": s.status,
                            "passed": s.passed,
                            "diagnosis": s.diagnosis,
                        }
                        for s in e.shots
                    ],
                }
                for e in self.episodes
            ],
            "turn_count": self.turn_count,
            "last_intent": self.last_intent,
        }


def detect_intent(message: str) -> str:
    """确定性意图识别(词表命中,首个命中即定)。"""
    for intent, keywords in _INTENT_KEYWORDS.items():
        if any(k in message for k in keywords):
            return intent
    return "status"


def respond_status(session: XiaSession) -> str:
    result = audit_production(session.episodes)
    lines = [f"进度 {result.progress_pct:.0f}% — {result.summary}"]
    if result.completeness:
        lines.append("未达标交付:")
        lines.extend(f"  - {c}" for c in result.completeness[:5])
    lines.append("建议下一步:")
    lines.extend(f"  → {s}" for s in result.suggestions[:3])
    return "\n".join(lines)


def respond_repair(session: XiaSession, failures: list[dict[str, Any]] | None = None) -> str:
    if failures is None:
        failures = [
            {"shot_id": f"s{s.index}", "diagnosis": s.diagnosis, "passed": s.passed}
            for ep in session.episodes
            for s in ep.shots
            if s.passed is False
        ]
    if not failures:
        return "没有失败镜头,无需返工。"
    plan = plan_repair(failures)
    lines = [f"修复计划({plan.budget_used}/{plan.budget_limit} 预算):"]
    for action in plan.actions:
        lines.extend(
            f"  [{action.agent}] {action.diagnosis} → 拉 {action.lever}:{action.instruction}"
            for action in plan.actions
        )
    return "\n".join(lines)


def respond_promote(
    session: XiaSession, *, scorers: dict[str, Callable[[dict[str, Any]], tuple[float, str]]]
) -> str:
    results = score_and_promote_batch(session.promotion, scorers=scorers)
    promoted = [r for r in results if r["promoted"]]
    if not promoted:
        return "没有可提升的候选(评分未过线或池空)。"
    lines = [f"提升 {len(promoted)} 个候选为主线资产:"]
    lines.extend(f"  ✓ {r['name']}({r['kind']}, score {r['score']:.2f})" for r in promoted)
    return "\n".join(lines)


class XiaAssistant:
    """会话制片助理:按项目维护会话,处理消息并执行动作。"""

    def __init__(self, sessions: dict[str, XiaSession] | None = None) -> None:
        self._sessions: dict[str, XiaSession] = dict(sessions or {})

    def session(self, project_id: str) -> XiaSession:
        if project_id not in self._sessions:
            self._sessions[project_id] = XiaSession(project_id=project_id)
        return self._sessions[project_id]

    def handle(
        self,
        project_id: str,
        message: str,
        *,
        failures: list[dict[str, Any]] | None = None,
        scorers: dict[str, Callable[[dict[str, Any]], tuple[float, str]]] | None = None,
    ) -> dict[str, Any]:
        """处理一条用户消息:识别意图 → 执行 → 返回回复 + 意图。"""
        session = self.session(project_id)
        intent = detect_intent(message)
        session.turn_count += 1
        session.last_intent = intent

        if intent == "status":
            reply = respond_status(session)
        elif intent == "repair":
            reply = respond_repair(session, failures)
        elif intent == "promote":
            reply = respond_promote(session, scorers=scorers or {})
        elif intent == "advance":
            reply = self._advance(session)
        elif intent == "audit":
            reply = respond_status(session)  # audit 与 status 共用审计内核
        else:
            reply = "我能做:看进度/推进/审计/修复返工/提升候选。试试问'进度如何?'"
        return {"reply": reply, "intent": intent, "turn": session.turn_count}

    def _advance(self, session: XiaSession) -> str:
        """推进:找最紧急的未完成镜头 → 给下一步动作(确定性)。"""
        result = audit_production(session.episodes)
        if result.suggestions:
            return f"下一步: {result.suggestions[0]}"
        return "所有镜头已交付。"

    # ── 持久化 ──
    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {k: v.to_dict() for k, v in self._sessions.items()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> XiaAssistant:
        p = Path(path)
        if not p.exists():
            return cls()
        raw = json.loads(p.read_text(encoding="utf-8"))
        sessions: dict[str, XiaSession] = {}
        for project_id, data in raw.items():
            session = XiaSession(project_id=project_id, turn_count=data.get("turn_count", 0))
            for ep in data.get("episodes", []):
                from hevi.director.assistant import ShotState

                session.episodes.append(
                    EpisodeState(
                        episode_id=ep["episode_id"],
                        title=ep.get("title", ""),
                        status=ep.get("status", "planned"),
                        shots=[
                            ShotState(
                                index=s["index"],
                                status=s["status"],
                                passed=s.get("passed"),
                                diagnosis=s.get("diagnosis", ""),
                            )
                            for s in ep.get("shots", [])
                        ],
                    )
                )
            sessions[project_id] = session
        return cls(sessions=sessions)
