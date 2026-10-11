"""三层审稿 agent —— 决策 / 执行 / 监督互审回路（DRAMAPLAN）。

设计（对齐 Toonflow 的“多 Agent 分决策/执行/监督三层互审”思路，clean-room 自实现）：

  决策层 decision_layer   —— 定本集改编目标：覆盖哪些事件、节奏、镜头/时长预算。
  执行层 execution_layer  —— 按决策写分场/分镜稿（`EpisodeScript`）；LLM 优先，失败走
                             确定性模板（事件摘要→场景、原文对白→台词）。
  监督层 supervisor_layer —— 按清单审稿：确定性规则（镜头数/时长/字数/人物名是否在角色表/
                             因果引用/覆盖率/禁忌词）+ 可选 LLM 定性意见，给出结构化问题列表
                             与 0-100 分。

不通过 → 带问题列表回执行层，**只改有问题的场/镜**（`revise_episode_script`），最多 N 轮
（默认 2）；每轮记录 diff 与分数，落盘 `review_log.json`（`write_review_log`）。

确定性优先：能用规则检查的（镜头数、时长、字数、人物名）一律用规则，不靠 LLM 打分。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from hevi.storygraph.schemas import (
    AdaptationOutline,
    OutlineEpisode,
    StoryGraph,
)

logger = logging.getLogger(__name__)

# ── 确定性规则阈值 ────────────────────────────────────────────────────────────
MAX_DIALOGUE_CHARS = 60  # 单句台词上限（短剧口播）
MIN_SCENE_SHOTS = 1
DEFAULT_TABOO_KEYWORDS: tuple[str, ...] = (
    "赌博",
    "毒品",
    "自杀",
    "色情",
    "暴力血腥",
)
# 时长允许偏差（生成稿的估算时长 vs 目标）。
DURATION_TOLERANCE = 0.5
# 监督层通过线。
PASS_SCORE = 80


# ── 剧本/审稿数据结构 ─────────────────────────────────────────────────────────
class ScriptLine(BaseModel):
    speaker: str  # char_id 或 name
    text: str
    emotion: str = ""


class ScriptScene(BaseModel):
    scene_no: int
    location: str = ""
    event_ids: list[str] = Field(default_factory=list)
    summary: str = ""
    narration: str = ""
    dialogue: list[ScriptLine] = Field(default_factory=list)
    shot_count: int = 1
    duration_s: float = 0.0


class EpisodeScript(BaseModel):
    ep_number: int
    title: str = ""
    scenes: list[ScriptScene] = Field(default_factory=list)
    characters_present: list[str] = Field(default_factory=list)

    def total_shots(self) -> int:
        return sum(s.shot_count for s in self.scenes)

    def total_duration(self) -> float:
        return sum(s.duration_s for s in self.scenes)

    def covered_event_ids(self) -> set[str]:
        return {eid for s in self.scenes for eid in s.event_ids}


class ReviewIssue(BaseModel):
    code: str  # 确定性规则码或 llm:xxx
    message: str
    scope: str = "episode"  # "scene:2" / "episode"
    severity: str = "error"  # error | warning
    scene_no: int | None = None


class AdaptationDecision(BaseModel):
    ep_number: int
    title: str = ""
    event_ids: list[str] = Field(default_factory=list)
    target_shots: int = 0
    target_duration_s: float = 0.0
    emotion_arc: str = ""
    rationale: str = ""


class SupervisionResult(BaseModel):
    passed: bool
    score: int
    issues: list[ReviewIssue] = Field(default_factory=list)
    deterministic_issues: list[ReviewIssue] = Field(default_factory=list)
    llm_issues: list[ReviewIssue] = Field(default_factory=list)


class RoundRecord(BaseModel):
    round_index: int
    score: int
    passed: bool
    issues: list[ReviewIssue] = Field(default_factory=list)
    revised_scenes: list[int] = Field(default_factory=list)
    scene_diffs: list[dict[str, Any]] = Field(default_factory=list)


class EpisodeReviewLog(BaseModel):
    ep_number: int
    title: str = ""
    rounds: list[RoundRecord] = Field(default_factory=list)
    final_score: int = 0
    passed: bool = False
    script: EpisodeScript | None = None


class ReviewLog(BaseModel):
    story_source: str = ""
    target_episodes: int = 0
    max_rounds: int = 0
    llm_channel: str = ""
    llm_used: bool = False
    episodes: list[EpisodeReviewLog] = Field(default_factory=list)
    passed: bool = False


# ── 决策层 ────────────────────────────────────────────────────────────────────
def decision_layer(
    book: StoryGraph,
    outline: AdaptationOutline,
    ep_number: int,
    *,
    llm: Any = None,
) -> AdaptationDecision:
    """决策层：从大纲取本集覆盖事件 + 镜头/时长预算。确定性为主，LLM 仅可调情绪弧。"""
    outline_ep = _find_outline_episode(outline, ep_number)
    event_ids = list(outline_ep.event_ids) if outline_ep else []
    ev_by_id = {e.event_id: e for e in book.events}
    beats = [ev_by_id[e].beat_type for e in event_ids if e in ev_by_id and ev_by_id[e].beat_type]
    emotion_arc = outline_ep.emotion_arc if outline_ep and outline_ep.emotion_arc else "→".join(beats)
    return AdaptationDecision(
        ep_number=ep_number,
        title=outline_ep.title if outline_ep and outline_ep.title else f"第{ep_number}集",
        event_ids=event_ids,
        target_shots=outline_ep.shot_budget if outline_ep else 0,
        target_duration_s=outline_ep.target_duration_s if outline_ep else 0.0,
        emotion_arc=emotion_arc,
        rationale=f"覆盖 {len(event_ids)} 个事件，节奏 {emotion_arc or '未定'}",
    )


def _find_outline_episode(outline: AdaptationOutline, ep_number: int) -> OutlineEpisode | None:
    for ep in outline.episodes:
        if ep.ep_number == ep_number:
            return ep
    return None


# ── 执行层 ────────────────────────────────────────────────────────────────────
_EXECUTION_PROMPT = """你是短剧编剧。根据下面的本集改编决策，写一集分场剧本，只输出 JSON：
{{"title": "本集标题", "scenes": [{{"scene_no": 1, "location": "地点",
"event_ids": ["本场对应的事件ID，只能取自给定事件"],
"summary": "一句话场景摘要", "narration": "旁白(可空)",
"dialogue": [{{"speaker": "角色名(必须在角色表里)", "text": "台词(≤{max_dialogue}字)", "emotion": "情绪"}}],
"shot_count": 镜头数(整数), "duration_s": 估算秒数}}]}}

硬性规则：
1. 必须覆盖全部给定事件 event_ids，每个事件至少一场戏。
2. 台词 speaker 只能用角色表里的人名；台词不得含禁忌词：{taboo}。
3. 每场戏 shot_count 之和不得超过 {target_shots}；估算时长之和不得超过 {target_duration} 秒。
4. 单句台词不超过 {max_dialogue} 字。

本集决策：
标题：{title}
事件：{event_lines}
情绪弧：{emotion_arc}
角色表：{character_lines}
原文对白参考：
{quote_lines}
"""


async def execution_layer(
    decision: AdaptationDecision,
    book: StoryGraph,
    *,
    llm: Any = None,
    taboo_keywords: tuple[str, ...] = DEFAULT_TABOO_KEYWORDS,
    previous: EpisodeScript | None = None,
    issues: list[ReviewIssue] | None = None,
) -> EpisodeScript:
    """执行层：写/改分场稿。

    - 无 previous：整集生成（LLM 优先 → 确定性模板兜底）。
    - 有 previous + issues：**只改问题场**（确定性修订），其余场原样保留。
    """
    if previous is not None and issues:
        return revise_episode_script(previous, issues, book, decision)
    if llm is not None:
        script = await _execution_via_llm(decision, book, llm, taboo_keywords)
        if script is not None:
            return script
    return _execution_template(decision, book)


def _character_lines(book: StoryGraph) -> str:
    return "\n".join(f"- {c.char_id} {c.name}（{c.description or '无描写'}）" for c in book.characters)


def _event_lines(book: StoryGraph, event_ids: list[str]) -> str:
    by_id = {e.event_id: e for e in book.events}
    out = []
    for eid in event_ids:
        ev = by_id.get(eid)
        if ev:
            actors = "、".join(ev.actors)
            out.append(f"- {eid}: {ev.summary}（{ev.beat_type} 权重{ev.dramatic_weight} 出场{actors}）")
    return "\n".join(out) or "（无）"


def _quote_lines(book: StoryGraph, event_ids: list[str]) -> str:
    keep = set(event_ids)
    lines = [f"- {q.speaker}: {q.original}" for q in book.quotes if q.event_id in keep]
    return "\n".join(lines) or "（无）"


async def _execution_via_llm(
    decision: AdaptationDecision,
    book: StoryGraph,
    llm: Any,
    taboo_keywords: tuple[str, ...],
) -> EpisodeScript | None:
    prompt = _EXECUTION_PROMPT.format(
        max_dialogue=MAX_DIALOGUE_CHARS,
        taboo="、".join(taboo_keywords),
        target_shots=decision.target_shots or 6,
        target_duration=decision.target_duration_s or 60,
        title=decision.title,
        event_lines=_event_lines(book, decision.event_ids),
        emotion_arc=decision.emotion_arc,
        character_lines=_character_lines(book),
        quote_lines=_quote_lines(book, decision.event_ids),
    )
    try:
        resp = await llm(messages=[{"role": "user", "content": prompt}], max_tokens=2048)
        content = resp.get("content") if hasattr(resp, "get") else str(resp)
        data = _extract_json(content)
        scenes = [
            ScriptScene(
                scene_no=int(s.get("scene_no") or i),
                location=str(s.get("location") or ""),
                event_ids=[str(e) for e in (s.get("event_ids") or [])],
                summary=str(s.get("summary") or ""),
                narration=str(s.get("narration") or ""),
                dialogue=[
                    ScriptLine(
                        speaker=str(d.get("speaker") or ""),
                        text=str(d.get("text") or ""),
                        emotion=str(d.get("emotion") or ""),
                    )
                    for d in (s.get("dialogue") or [])
                ],
                shot_count=max(MIN_SCENE_SHOTS, int(s.get("shot_count") or 1)),
                duration_s=float(s.get("duration_s") or 0.0),
            )
            for i, s in enumerate(data.get("scenes") or [], start=1)
        ]
        if not scenes:
            return None
        return EpisodeScript(
            ep_number=decision.ep_number,
            title=str(data.get("title") or decision.title),
            scenes=scenes,
            characters_present=[c.char_id for c in book.characters],
        )
    except Exception as exc:
        logger.warning("执行层 LLM 失败,走确定性模板: %s", exc)
        return None


def _execution_template(decision: AdaptationDecision, book: StoryGraph) -> EpisodeScript:
    """确定性模板：每个事件一场戏（旁白=事件摘要，台词=该事件原文对白）。"""
    by_id = {e.event_id: e for e in book.events}
    quotes_by_event: dict[str, list[Any]] = {}
    for q in book.quotes:
        if q.event_id:
            quotes_by_event.setdefault(q.event_id, []).append(q)
    n = max(1, len(decision.event_ids))
    per_scene_shots = max(MIN_SCENE_SHOTS, round(decision.target_shots / n)) if decision.target_shots else 2
    per_scene_dur = (decision.target_duration_s / n) if decision.target_duration_s else 0.0
    scenes: list[ScriptScene] = []
    for i, eid in enumerate(decision.event_ids, start=1):
        ev = by_id.get(eid)
        if ev is None:
            continue
        dialogue = [
            ScriptLine(speaker=q.speaker, text=q.original, emotion=q.emotion)
            for q in quotes_by_event.get(eid, [])[:2]
        ]
        scenes.append(
            ScriptScene(
                scene_no=i,
                location=ev.location or "",
                event_ids=[eid],
                summary=ev.summary,
                narration=ev.summary,
                dialogue=dialogue,
                shot_count=per_scene_shots,
                duration_s=per_scene_dur,
            )
        )
    if not scenes:
        scenes = [
            ScriptScene(
                scene_no=1,
                summary="（无事件，占位场）",
                narration=decision.title,
                shot_count=max(MIN_SCENE_SHOTS, decision.target_shots or 1),
                duration_s=decision.target_duration_s,
            )
        ]
    return EpisodeScript(
        ep_number=decision.ep_number,
        title=decision.title,
        scenes=scenes,
        characters_present=[c.char_id for c in book.characters],
    )


def revise_episode_script(
    script: EpisodeScript,
    issues: list[ReviewIssue],
    book: StoryGraph,
    decision: AdaptationDecision,
) -> EpisodeScript:
    """确定性修订：只动被点名的场，其余场**原样保留**（对象级 diff 可验证）。"""
    flagged = {i.scene_no for i in issues if i.scene_no is not None}
    codes_by_scene: dict[int, set[str]] = {}
    episode_codes: set[str] = set()
    for issue in issues:
        if issue.scene_no is None:
            episode_codes.add(issue.code)
        else:
            codes_by_scene.setdefault(issue.scene_no, set()).add(issue.code)

    by_id = {e.event_id: e for e in book.events}
    known_names = {c.name for c in book.characters} | {c.char_id for c in book.characters}
    forbidden = DEFAULT_TABOO_KEYWORDS

    new_scenes: list[ScriptScene] = []
    for scene in script.scenes:
        if scene.scene_no not in flagged:
            new_scenes.append(scene)  # 未点名 → 原样复用（同一对象）
            continue
        codes = codes_by_scene.get(scene.scene_no, set())
        lines = []
        for line in scene.dialogue:
            text = line.text
            if "dialogue_too_long" in codes and len(text) > MAX_DIALOGUE_CHARS:
                text = text[:MAX_DIALOGUE_CHARS]
            if "taboo" in codes and any(k in text for k in forbidden):
                continue  # 删掉含禁忌词的台词
            speaker = line.speaker
            if "unknown_speaker" in codes and speaker not in known_names:
                # 回退到本场事件里第一个已知角色
                actors = []
                for eid in scene.event_ids:
                    actors.extend(by_id.get(eid).actors if by_id.get(eid) else [])
                speaker = actors[0] if actors else (next(iter(known_names), speaker))
            lines.append(ScriptLine(speaker=speaker, text=text, emotion=line.emotion))
        updated = scene.model_copy(
            update={
                "dialogue": lines,
                "narration": scene.narration or scene.summary,
            }
        )
        new_scenes.append(updated)

    # 覆盖率缺口：为缺失事件补场（追加，不动已通过的场）
    if "coverage_gap" in episode_codes or any("coverage_gap" in c for c in codes_by_scene.values()):
        covered = {eid for s in new_scenes for eid in s.event_ids}
        missing = [eid for eid in decision.event_ids if eid not in covered]
        for eid in missing:
            ev = by_id.get(eid)
            if ev is None:
                continue
            new_scenes.append(
                ScriptScene(
                    scene_no=max((s.scene_no for s in new_scenes), default=0) + 1,
                    location=ev.location or "",
                    event_ids=[eid],
                    summary=ev.summary,
                    narration=ev.summary,
                    shot_count=MIN_SCENE_SHOTS,
                    duration_s=0.0,
                )
            )

    # 时长超范围（整集级问题）：把各场估算时长等比缩放到目标总时长。
    if "duration_out_of_range" in episode_codes and decision.target_duration_s > 0 and new_scenes:
        total = sum(s.duration_s for s in new_scenes)
        if total > 0:
            scale = decision.target_duration_s / total
            new_scenes = [
                s.model_copy(update={"duration_s": s.duration_s * scale}) for s in new_scenes
            ]
        else:
            per = decision.target_duration_s / len(new_scenes)
            new_scenes = [s.model_copy(update={"duration_s": per}) for s in new_scenes]

    # 镜头预算超限（整集级问题）：先把各场镜头数缩到最小 1，再按比例/贪心削减到预算内。
    # 放在补场之后，保证补进来的场也纳入缩放。
    if "shot_budget_exceeded" in episode_codes and decision.target_shots > 0:
        counts = [max(MIN_SCENE_SHOTS, s.shot_count) for s in new_scenes]
        if sum(counts) > decision.target_shots:
            # 比例缩放（向下取整，避免超预算）
            total = sum(counts)
            counts = [
                max(MIN_SCENE_SHOTS, int(c * decision.target_shots / total)) for c in counts
            ]
            # 贪心从最大场继续削，直到落回预算（受每场至少 1 镜约束）
            while sum(counts) > decision.target_shots:
                i = max(range(len(counts)), key=lambda j: counts[j])
                if counts[i] <= MIN_SCENE_SHOTS:
                    break
                counts[i] -= 1
            new_scenes = [
                s.model_copy(update={"shot_count": c}) for s, c in zip(new_scenes, counts, strict=True)
            ]
    return script.model_copy(update={"scenes": new_scenes})


# ── 监督层 ────────────────────────────────────────────────────────────────────
def deterministic_checks(
    script: EpisodeScript,
    book: StoryGraph,
    decision: AdaptationDecision,
    *,
    taboo_keywords: tuple[str, ...] = DEFAULT_TABOO_KEYWORDS,
) -> list[ReviewIssue]:
    """确定性规则检查（不靠 LLM）。"""
    issues: list[ReviewIssue] = []
    known_names = {c.name for c in book.characters}
    known_ids = {c.char_id for c in book.characters}
    known_events = {e.event_id for e in book.events}
    present = set(script.characters_present) or known_ids

    # R1 人物一致性：speaker 必须在角色表
    for scene in script.scenes:
        for line in scene.dialogue:
            if line.speaker not in known_names and line.speaker not in known_ids:
                issues.append(
                    ReviewIssue(
                        code="unknown_speaker",
                        message=f"台词人物 {line.speaker!r} 不在角色表",
                        scope=f"scene:{scene.scene_no}",
                        scene_no=scene.scene_no,
                    )
                )
        # R4 台词长度
        for line in scene.dialogue:
            if len(line.text) > MAX_DIALOGUE_CHARS:
                issues.append(
                    ReviewIssue(
                        code="dialogue_too_long",
                        message=f"台词 {len(line.text)} 字 > 上限 {MAX_DIALOGUE_CHARS}",
                        scope=f"scene:{scene.scene_no}",
                        scene_no=scene.scene_no,
                    )
                )
            if any(k in line.text for k in taboo_keywords):
                issues.append(
                    ReviewIssue(
                        code="taboo",
                        message=f"台词含禁忌词: {line.text[:20]}",
                        scope=f"scene:{scene.scene_no}",
                        scene_no=scene.scene_no,
                    )
                )
        # R7 场非空
        if not scene.dialogue and not scene.narration and not scene.summary:
            issues.append(
                ReviewIssue(
                    code="empty_scene",
                    message="场景无对白/旁白/摘要",
                    scope=f"scene:{scene.scene_no}",
                    scene_no=scene.scene_no,
                )
            )
        # R2 因果/事件引用
        for eid in scene.event_ids:
            if eid not in known_events:
                issues.append(
                    ReviewIssue(
                        code="unknown_event",
                        message=f"引用不存在的事件 {eid}",
                        scope=f"scene:{scene.scene_no}",
                        scene_no=scene.scene_no,
                    )
                )
            elif eid not in decision.event_ids:
                issues.append(
                    ReviewIssue(
                        code="event_out_of_scope",
                        message=f"事件 {eid} 不属于本集决策",
                        scope=f"scene:{scene.scene_no}",
                        scene_no=scene.scene_no,
                    )
                )

    # R3 镜头/时长预算
    if decision.target_shots and script.total_shots() > decision.target_shots:
        issues.append(
            ReviewIssue(
                code="shot_budget_exceeded",
                message=f"镜头数 {script.total_shots()} > 预算 {decision.target_shots}",
                scope="episode",
            )
        )
    if decision.target_duration_s:
        lo = decision.target_duration_s * (1 - DURATION_TOLERANCE)
        hi = decision.target_duration_s * (1 + DURATION_TOLERANCE)
        total = script.total_duration()
        if total and not (lo <= total <= hi):
            issues.append(
                ReviewIssue(
                    code="duration_out_of_range",
                    message=f"估算时长 {total:.1f}s 超出目标 {decision.target_duration_s}s ±50%",
                    scope="episode",
                )
            )

    # R6 覆盖率：决策事件必须被覆盖
    covered = script.covered_event_ids()
    missing = [eid for eid in decision.event_ids if eid not in covered]
    if missing:
        issues.append(
            ReviewIssue(
                code="coverage_gap",
                message=f"未覆盖事件: {missing}",
                scope="episode",
            )
        )
    # R8 人物出场表与角色表一致
    for cid in script.characters_present:
        if cid not in known_ids:
            issues.append(
                ReviewIssue(
                    code="unknown_character_present",
                    message=f"出场表含未知角色 {cid}",
                    scope="episode",
                )
            )
    return issues


def _score_from_issues(issues: list[ReviewIssue]) -> int:
    errors = sum(1 for i in issues if i.severity == "error")
    warnings = sum(1 for i in issues if i.severity == "warning")
    return max(0, 100 - errors * 20 - warnings * 5)


async def supervisor_layer(
    script: EpisodeScript,
    book: StoryGraph,
    decision: AdaptationDecision,
    *,
    llm: Any = None,
    taboo_keywords: tuple[str, ...] = DEFAULT_TABOO_KEYWORDS,
) -> SupervisionResult:
    """监督层：确定性规则 + 可选 LLM 定性意见；规则问题永远计入。"""
    det = deterministic_checks(script, book, decision, taboo_keywords=taboo_keywords)
    llm_issues: list[ReviewIssue] = []
    if llm is not None:
        llm_issues = await _supervisor_via_llm(script, decision, llm)
    all_issues = det + llm_issues
    score = _score_from_issues(all_issues)
    # 硬门只看**确定性规则**的错误（镜头数/时长/字数/人物名/覆盖率/禁忌）——
    # 这是任务要求“能用规则检查的必须用规则”。LLM 定性意见只作 advisory warning，
    # 不改变通过与否（只影响 score，供人看）。
    passed = not any(i.severity == "error" for i in det)
    return SupervisionResult(
        passed=passed,
        score=score,
        issues=all_issues,
        deterministic_issues=det,
        llm_issues=llm_issues,
    )


_SUPERVISOR_PROMPT = """你是短剧审稿人。下面是本集剧本与改编决策。只输出 JSON：
{{"issues": [{{"scene_no": 整数或null, "code": "llm:问题类型", "message": "问题描述", "severity": "error|warning"}}],
"score": 0到100的整数}}
只报确定性规则查不出的**定性**问题（人物弧光、节奏、逻辑连贯、台词质量）；镜头数/时长/字数/
人物名是否在角色表这类已由规则检查，不要重复。

决策：{decision}
剧本：{script}
"""


async def _supervisor_via_llm(
    script: EpisodeScript, decision: AdaptationDecision, llm: Any
) -> list[ReviewIssue]:
    prompt = _SUPERVISOR_PROMPT.format(
        decision=decision.model_dump_json(),
        script=script.model_dump_json(),
    )
    try:
        resp = await llm(messages=[{"role": "user", "content": prompt}], max_tokens=1024)
        content = resp.get("content") if hasattr(resp, "get") else str(resp)
        data = _extract_json(content)
        return [
            ReviewIssue(
                code=str(i.get("code") or "llm:issue"),
                message=str(i.get("message") or ""),
                scope=f"scene:{i['scene_no']}" if i.get("scene_no") else "episode",
                # LLM 定性意见一律 advisory warning（不构成硬门，只进 score/问题列表）
                severity="warning",
                scene_no=int(i["scene_no"]) if i.get("scene_no") else None,
            )
            for i in (data.get("issues") or [])
        ]
    except Exception as exc:
        logger.warning("监督层 LLM 失败,只用确定性规则: %s", exc)
        return []


# ── 三层回路 ──────────────────────────────────────────────────────────────────
def _scene_hash(scene: ScriptScene) -> str:
    return hashlib.sha256(scene.model_dump_json().encode()).hexdigest()[:12]


def _diff_scenes(before: EpisodeScript, after: EpisodeScript) -> list[dict[str, Any]]:
    before_by_no = {s.scene_no: s for s in before.scenes}
    after_by_no = {s.scene_no: s for s in after.scenes}
    diffs: list[dict[str, Any]] = []
    for no in sorted(set(before_by_no) | set(after_by_no)):
        b = before_by_no.get(no)
        a = after_by_no.get(no)
        bh = _scene_hash(b) if b else None
        ah = _scene_hash(a) if a else None
        if bh != ah:
            diffs.append({"scene_no": no, "before": bh, "after": ah})
    return diffs


async def review_episode(
    book: StoryGraph,
    outline: AdaptationOutline,
    ep_number: int,
    *,
    llm: Any = None,
    max_rounds: int = 2,
    taboo_keywords: tuple[str, ...] = DEFAULT_TABOO_KEYWORDS,
) -> EpisodeReviewLog:
    """单集三层回路：执行 → 监督 → 带问题只改问题场 → 再监督，最多 max_rounds 轮。"""
    decision = decision_layer(book, outline, ep_number, llm=None)
    script = await execution_layer(decision, book, llm=llm, taboo_keywords=taboo_keywords)
    rounds: list[RoundRecord] = []
    supervision = await supervisor_layer(
        script, book, decision, llm=llm, taboo_keywords=taboo_keywords
    )
    rounds.append(
        RoundRecord(
            round_index=0,
            score=supervision.score,
            passed=supervision.passed,
            issues=supervision.issues,
        )
    )
    r = 0
    while not supervision.passed and r < max_rounds:
        r += 1
        before = script
        script = await execution_layer(
            decision,
            book,
            llm=llm,
            taboo_keywords=taboo_keywords,
            previous=before,
            issues=supervision.issues,
        )
        supervision = await supervisor_layer(
            script, book, decision, llm=llm, taboo_keywords=taboo_keywords
        )
        revised = sorted({i.scene_no for i in rounds[-1].issues if i.scene_no is not None})
        rounds.append(
            RoundRecord(
                round_index=r,
                score=supervision.score,
                passed=supervision.passed,
                issues=supervision.issues,
                revised_scenes=revised,
                scene_diffs=_diff_scenes(before, script),
            )
        )
    return EpisodeReviewLog(
        ep_number=ep_number,
        title=script.title,
        rounds=rounds,
        final_score=rounds[-1].score,
        passed=rounds[-1].passed,
        script=script,
    )


async def run_three_layer_review(
    book: StoryGraph,
    outline: AdaptationOutline,
    *,
    llm: Any = None,
    max_rounds: int = 2,
    taboo_keywords: tuple[str, ...] = DEFAULT_TABOO_KEYWORDS,
    on_step: Any = None,
) -> ReviewLog:
    """对大纲里每一集跑三层审稿回路，返回 `ReviewLog`。"""
    episodes: list[EpisodeReviewLog] = []
    for ep in outline.episodes:
        if on_step is not None:
            on_step(ep.ep_number, len(outline.episodes))
        episodes.append(
            await review_episode(
                book,
                outline,
                ep.ep_number,
                llm=llm,
                max_rounds=max_rounds,
                taboo_keywords=taboo_keywords,
            )
        )
    return ReviewLog(
        story_source=book.meta.source,
        target_episodes=outline.target_episodes,
        max_rounds=max_rounds,
        llm_used=llm is not None,
        episodes=episodes,
        passed=all(e.passed for e in episodes),
    )


def write_review_log(log: ReviewLog, path: str | Path) -> Path:
    """落盘 review_log.json（含每轮 diff 与分数、最终剧本）。"""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(log.model_dump_json(indent=2), encoding="utf-8")
    return out


# ── helpers ───────────────────────────────────────────────────────────────────
def _extract_json(content: str | None) -> dict[str, Any]:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        pass
    # 扫描第一个能 raw_decode 成功的 JSON 对象（容忍前后噪音/截断尾巴）
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    raise ValueError("no JSON object found in LLM response")


__all__ = [
    "AdaptationDecision",
    "DEFAULT_TABOO_KEYWORDS",
    "EpisodeReviewLog",
    "EpisodeScript",
    "MAX_DIALOGUE_CHARS",
    "PASS_SCORE",
    "ReviewIssue",
    "ReviewLog",
    "RoundRecord",
    "ScriptLine",
    "ScriptScene",
    "SupervisionResult",
    "decision_layer",
    "deterministic_checks",
    "execution_layer",
    "revise_episode_script",
    "review_episode",
    "run_three_layer_review",
    "supervisor_layer",
    "write_review_log",
]
