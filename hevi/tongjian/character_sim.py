"""v9.1 角色权威推演 —— 多角色独立动线与知识边界分层。

移植自 novel-studio(Apache-2.0) 的 ``simulate_chapter_world`` 精简模式:
  * 每名角色拥有自己的 goal(目标) / pressure(压力) / resources(资源) /
    knowledge_boundary(知识边界: 知道/不知道/不能提前知道) /
    offscreen_action(离屏行动) —— 角色不再围着主角静止;
  * L2 剧本的每句对白只从该角色 knowledge_boundary 内可见的事实出发,
    隐藏世界状态不泄漏, 防止"角色提前知道秘密";
  * gate_character_states 门禁: 事件 actors 必须有档案、知识边界非空、
    离屏行动不与事件矛盾 —— 不过标只降级不阻断(通鉴"永不卡死")。

仅依赖 chapter_ir(事件/引语/角色名册) 与 LLM, 不引入外部知识。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from hevi.tongjian.schemas import ChapterIR, GateResult

logger = logging.getLogger(__name__)

# novel-studio 精简版角色状态: 与下游 L2 剧本 prompt 直接对应。
_SCHEMA_HINT = """{
  "characters": [
    {
      "character_id": "与 chapter_ir 中一致",
      "goal": "本章内该角色的核心目标(一句话, 具体动作)",
      "pressure": "该角色当前承受的压力(一句话)",
      "resources": ["可动用的资源/筹码"],
      "knowledge_boundary": [
        "知道: ...",
        "不知道: ...",
        "不能提前知道: ..."
      ],
      "offscreen_action": "镜头外该角色正在进行的行动(不能与本章事件矛盾)",
      "decision_model": "该角色做选择时的权衡(如'保全宗族优先于个人野心')"
    }
  ]
}"""


def _prompt(chapter_ir: ChapterIR) -> str:
    characters = "\n".join(
        f"  {c.character_id} = {c.canonical_name}"
        + (f"({', '.join(c.aliases)})" if c.aliases else "")
        + (f" — {c.role_in_chapter}" if c.role_in_chapter else "")
        for c in chapter_ir.characters
    )
    events = "\n".join(
        f"  {e.event_id}: {e.summary}  actor={e.actors}  location={e.location or '-'}"
        for e in chapter_ir.events
    )
    quotes = "\n".join(
        f"  {q.quote_id}({q.speaker}): {q.original}"
        for q in chapter_ir.quotes[:20]
    )
    return f"""你是历史剧角色推演师。基于以下章节原文事件与引语, 为每个角色推演独立状态。

角色名册:
{characters}

本章事件:
{events}

原文引语(史实红线, 推演依据):
{quotes}

硬性规则:
1. 只从以上事件/引语推导, 禁止引入外部知识、后世信息或本章未发生的结果;
2. 每个 knowledge_boundary 至少一条"不能提前知道"(该角色本章不知道的秘密);
3. offscreen_action 是镜头外行动, 不得与本章事件矛盾, 不得等于已发生事件本身;
4. 每个事件 actor 都必须在 characters 中有对应条目;
5. 只返回 JSON, 不要 markdown:
{_SCHEMA_HINT}"""


async def simulate_character_states(
    chapter_ir: ChapterIR,
    llm: Any,
) -> list[dict[str, Any]]:
    """为 chapter_ir.characters 推演角色权威状态(LLM, 失败返回空列表降级)。"""
    if not chapter_ir.characters:
        return []
    try:
        result = await llm(
            messages=[{"role": "user", "content": _prompt(chapter_ir)}],
            system="你只输出 JSON, 不输出任何解释。",
            max_tokens=4096,
        )
        raw = result.get("content") or ""
        data = _extract_json(raw)
        states = data.get("characters") or []
        # 归一化: 只保留与名册匹配的角色, 缺字段补默认。
        known = {c.character_id for c in chapter_ir.characters}
        normalized: list[dict[str, Any]] = []
        for s in states:
            if not isinstance(s, dict) or s.get("character_id") not in known:
                continue
            normalized.append(
                {
                    "character_id": s["character_id"],
                    "goal": str(s.get("goal") or ""),
                    "pressure": str(s.get("pressure") or ""),
                    "resources": [
                        str(r) for r in (s.get("resources") or []) if str(r).strip()
                    ],
                    "knowledge_boundary": [
                        str(k) for k in (s.get("knowledge_boundary") or []) if str(k).strip()
                    ],
                    "offscreen_action": str(s.get("offscreen_action") or ""),
                    "decision_model": str(s.get("decision_model") or ""),
                }
            )
        return normalized
    except Exception as exc:
        logger.warning("character_sim 推演失败, 降级空档案: %s", exc)
        return []


def gate_character_states(
    states: list[dict[str, Any]], chapter_ir: ChapterIR
) -> GateResult:
    """角色档案完整性门禁: 事件角色都有档案 + 知识边界非空 + 离屏行动非空。

    不过标 → GateResult(passed=False), 由 _gate_done 标 DEGRADED(不阻断)。
    """
    errors: list[str] = []
    by_id = {s.get("character_id"): s for s in states}
    event_actors = sorted(
        {actor for e in chapter_ir.events for actor in (e.actors or [])}
    )
    missing = [a for a in event_actors if a not in by_id]
    if missing:
        errors.append(f"事件角色缺少推演档案: {missing}")
    for cid, s in by_id.items():
        if not (s.get("knowledge_boundary") or []):
            errors.append(f"角色 {cid} 的 knowledge_boundary 为空(知识边界必须分层)")
        if not s.get("offscreen_action"):
            errors.append(f"角色 {cid} 缺 offscreen_action(离屏行动)")
    covered = len(event_actors) - len(missing) if event_actors else len(states)
    total = max(len(event_actors), 1)
    return GateResult(
        passed=not errors,
        coverage=round(covered / total, 3),
        errors=errors,
        warnings=[
            f"推演角色 {len(states)} 个; 事件角色 {len(event_actors)} 个"
        ],
    )


def _extract_json(text: str) -> dict[str, Any]:
    """剥 markdown 代码块后解析 JSON; 失败返回空 dict。"""
    import re

    text = text.strip()
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if match:
        text = match.group(1).strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def dump_character_states(states: list[dict[str, Any]], path: Path) -> None:
    """落盘角色档案(L2/character_sim.json), 断点续传读得到。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"characters": states}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_character_states(path: Path) -> list[dict[str, Any]] | None:
    """读已落盘角色档案; 缺失/损坏返回 None(触发重新推演)。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("characters") or []
    except (OSError, ValueError):
        return None


__all__ = [
    "dump_character_states",
    "gate_character_states",
    "load_character_states",
    "simulate_character_states",
]
