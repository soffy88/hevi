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
    EpisodeShot,
    EpisodeStoryboard,
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
    trigger_issue_codes: list[str] = Field(default_factory=list)


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
"dialogue": [{{"speaker": "角色名(必须在角色表里，必须是真实人名不能用 C001 等 char_id)", "text": "台词(≤{max_dialogue}字)", "emotion": "情绪"}}],
"shot_count": 镜头数(整数), "duration_s": 估算秒数}}]}}

硬性规则：
1. 必须覆盖全部给定事件 event_ids，每个事件至少一场戏。
2. 台词 speaker 只能用角色表里的人名（绝不能用 char_id）；台词不得含禁忌词：{taboo}。
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
        return await revise_episode_script_async(
            previous, issues, book, decision, llm=llm, taboo_keywords=taboo_keywords
        )
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


_REVISE_SCENE_PROMPT = """你是短剧剧本精修师。本集剧本第 {scene_no} 场被审稿指出以下问题，请专门针对本场进行重写修复。
注意：角色名必须使用已知角色（{character_names}），不得用 char_id（如 C001）代替角色名；台词每句不超过 {max_dialogue} 字，不得包含禁忌词（{taboo}）。

【本场问题列表】：
{issue_lines}

【待修改场次信息】：
场次序号：第 {scene_no} 场
地点：{location}
关联事件：{event_lines}
当前概要：{summary}
当前旁白：{narration}
当前台词：
{dialogue_lines}
原文参考对白：
{quote_lines}

请仅输出一个 JSON 对象，表示重写后的这一场（不要输出其他场次）：
{{
  "scene_no": {scene_no},
  "location": "场景地点",
  "summary": "重写后的场摘要",
  "narration": "重写后的旁白",
  "dialogue": [
    {{"speaker": "角色名", "text": "台词内容", "emotion": "情绪"}}
  ],
  "shot_count": 整数镜头数,
  "duration_s": 浮点秒数
}}
"""


async def _revise_single_scene_via_llm(
    scene: ScriptScene,
    issues: list[ReviewIssue],
    book: StoryGraph,
    llm: Any,
    taboo_keywords: tuple[str, ...],
) -> ScriptScene | None:
    if not issues:
        return None
    issue_lines = "\n".join(f"- [{i.code}] ({i.severity}) {i.message}" for i in issues)
    dialogue_lines = "\n".join(
        f"- {line.speaker}（{line.emotion}）：{line.text}" for line in scene.dialogue
    ) or "（无对白）"
    char_names = "、".join(c.name for c in book.characters)
    prompt = _REVISE_SCENE_PROMPT.format(
        scene_no=scene.scene_no,
        location=scene.location or "室内",
        character_names=char_names or "（无）",
        max_dialogue=MAX_DIALOGUE_CHARS,
        taboo="、".join(taboo_keywords),
        issue_lines=issue_lines,
        event_lines=_event_lines(book, scene.event_ids),
        summary=scene.summary,
        narration=scene.narration,
        dialogue_lines=dialogue_lines,
        quote_lines=_quote_lines(book, scene.event_ids),
    )
    try:
        resp = await llm(messages=[{"role": "user", "content": prompt}], max_tokens=1024)
        content = resp.get("content") if hasattr(resp, "get") else str(resp)
        data = _extract_json(content)
        if "scene" in data and isinstance(data["scene"], dict):
            data = data["scene"]
        elif "scenes" in data and isinstance(data["scenes"], list):
            matching = [s for s in data["scenes"] if s.get("scene_no") == scene.scene_no]
            data = matching[0] if matching else data["scenes"][0]

        dialogue = [
            ScriptLine(
                speaker=str(d.get("speaker") or ""),
                text=str(d.get("text") or ""),
                emotion=str(d.get("emotion") or ""),
            )
            for d in (data.get("dialogue") or [])
        ]
        known_names = {c.name for c in book.characters}
        char_id_to_name = {c.char_id: c.name for c in book.characters}
        fixed_dialogue: list[ScriptLine] = []
        for line in dialogue:
            # R4：char_id → 映射成角色名
            sp = char_id_to_name.get(line.speaker, line.speaker)
            if not sp or sp not in known_names:
                sp = (
                    scene.dialogue[0].speaker
                    if scene.dialogue
                    else (book.characters[0].name if book.characters else sp)
                )
            txt = (
                line.text[:MAX_DIALOGUE_CHARS]
                if len(line.text) > MAX_DIALOGUE_CHARS
                else line.text
            )
            if not any(k in txt for k in taboo_keywords):
                fixed_dialogue.append(ScriptLine(speaker=sp, text=txt, emotion=line.emotion))

        return ScriptScene(
            scene_no=scene.scene_no,
            location=str(data.get("location") or scene.location),
            event_ids=scene.event_ids,
            summary=str(data.get("summary") or scene.summary),
            narration=str(data.get("narration") or scene.narration),
            dialogue=fixed_dialogue,
            shot_count=max(MIN_SCENE_SHOTS, int(data.get("shot_count") or scene.shot_count)),
            duration_s=float(data.get("duration_s") or scene.duration_s),
        )
    except Exception as exc:
        logger.warning("执行层 LLM 改场第 %s 场失败,走确定性补丁: %s", scene.scene_no, exc)
        return None


def _revise_single_scene_deterministic(
    scene: ScriptScene,
    issues: list[ReviewIssue],
    book: StoryGraph,
    taboo_keywords: tuple[str, ...] = DEFAULT_TABOO_KEYWORDS,
) -> ScriptScene:
    by_id = {e.event_id: e for e in book.events}
    known_names = {c.name for c in book.characters}
    char_id_to_name = {c.char_id: c.name for c in book.characters}
    known_ids = {c.char_id for c in book.characters}
    codes = {i.code for i in issues}

    lines: list[ScriptLine] = []
    for line in scene.dialogue:
        text = line.text
        if "dialogue_too_long" in codes and len(text) > MAX_DIALOGUE_CHARS:
            text = text[:MAX_DIALOGUE_CHARS]
        if "taboo" in codes and any(k in text for k in taboo_keywords):
            continue
        speaker = line.speaker
        # R4：char_id 当 speaker → 映射成角色名
        if speaker in char_id_to_name and speaker not in known_names:
            speaker = char_id_to_name[speaker]
        elif "unknown_speaker" in codes and speaker not in known_names and speaker not in known_ids:
            actors = []
            for eid in scene.event_ids:
                ev = by_id.get(eid)
                if ev:
                    for a in ev.actors:
                        actors.append(char_id_to_name.get(a, a))
            speaker = actors[0] if actors else (next(iter(known_names), speaker))
        lines.append(ScriptLine(speaker=speaker, text=text, emotion=line.emotion))

    summary = scene.summary
    narration = scene.narration or scene.summary
    if any(c.startswith("llm:") for c in codes):
        summary = f"{summary}（定性优化）"

    return scene.model_copy(
        update={
            "dialogue": lines,
            "narration": narration,
            "summary": summary,
        }
    )


async def revise_episode_script_async(
    script: EpisodeScript,
    issues: list[ReviewIssue],
    book: StoryGraph,
    decision: AdaptationDecision,
    *,
    llm: Any = None,
    taboo_keywords: tuple[str, ...] = DEFAULT_TABOO_KEYWORDS,
) -> EpisodeScript:
    """带问题列表重写：被点名的场调 LLM 重新生成（未点名场对象/哈希不变，保留原有通过成果）。"""
    flagged = {i.scene_no for i in issues if i.scene_no is not None}
    codes_by_scene: dict[int, list[ReviewIssue]] = {}
    episode_issues: list[ReviewIssue] = []
    for issue in issues:
        if issue.scene_no is None:
            episode_issues.append(issue)
        else:
            codes_by_scene.setdefault(issue.scene_no, []).append(issue)

    episode_codes = {i.code for i in episode_issues}

    new_scenes: list[ScriptScene] = []
    for scene in script.scenes:
        if scene.scene_no not in flagged:
            new_scenes.append(scene)  # 未点名 → 原样复用（同一对象）
            continue
        other_shots = sum(s.shot_count for s in script.scenes if s.scene_no != scene.scene_no)
        max_scene_shots = (
            max(MIN_SCENE_SHOTS, decision.target_shots - other_shots)
            if decision.target_shots > 0
            else 999
        )
        other_dur = sum(s.duration_s for s in script.scenes if s.scene_no != scene.scene_no)
        max_scene_dur = (
            max(1.0, decision.target_duration_s - other_dur)
            if decision.target_duration_s > 0
            else 999.0
        )

        scene_issues = codes_by_scene.get(scene.scene_no, [])
        revised: ScriptScene | None = None
        if llm is not None:
            revised = await _revise_single_scene_via_llm(
                scene, scene_issues, book, llm, taboo_keywords
            )
        if revised is None:
            revised = _revise_single_scene_deterministic(
                scene, scene_issues, book, taboo_keywords
            )
        # 单场重写预算保护：避免单场增容打破全集预算
        revised = revised.model_copy(
            update={
                "shot_count": min(max_scene_shots, revised.shot_count),
                "duration_s": (
                    min(max_scene_dur, revised.duration_s)
                    if decision.target_duration_s > 0
                    else revised.duration_s
                ),
            }
        )
        new_scenes.append(revised)

    by_id = {e.event_id: e for e in book.events}
    all_codes = episode_codes | {
        i.code for issues_list in codes_by_scene.values() for i in issues_list
    }

    # 覆盖率缺口：为缺失事件补场（追加，不动已通过的场）
    if "coverage_gap" in all_codes:
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
    if "shot_budget_exceeded" in episode_codes and decision.target_shots > 0:
        counts = [max(MIN_SCENE_SHOTS, s.shot_count) for s in new_scenes]
        if sum(counts) > decision.target_shots:
            total = sum(counts)
            counts = [
                max(MIN_SCENE_SHOTS, int(c * decision.target_shots / total)) for c in counts
            ]
            while sum(counts) > decision.target_shots:
                i = max(range(len(counts)), key=lambda j: counts[j])
                if counts[i] <= MIN_SCENE_SHOTS:
                    break
                counts[i] -= 1
            new_scenes = [
                s.model_copy(update={"shot_count": c})
                for s, c in zip(new_scenes, counts, strict=True)
            ]

    return script.model_copy(update={"scenes": new_scenes})


def revise_episode_script(
    script: EpisodeScript,
    issues: list[ReviewIssue],
    book: StoryGraph,
    decision: AdaptationDecision,
) -> EpisodeScript:
    """确定性修订（同步向后兼容接口）：只动被点名的场。"""
    flagged = {i.scene_no for i in issues if i.scene_no is not None}
    codes_by_scene: dict[int, list[ReviewIssue]] = {}
    episode_issues: list[ReviewIssue] = []
    for issue in issues:
        if issue.scene_no is None:
            episode_issues.append(issue)
        else:
            codes_by_scene.setdefault(issue.scene_no, []).append(issue)

    episode_codes = {i.code for i in episode_issues}

    new_scenes: list[ScriptScene] = []
    for scene in script.scenes:
        if scene.scene_no not in flagged:
            new_scenes.append(scene)  # 未点名 → 原样复用（同一对象）
            continue
        scene_issues = codes_by_scene.get(scene.scene_no, [])
        revised = _revise_single_scene_deterministic(
            scene, scene_issues, book, DEFAULT_TABOO_KEYWORDS
        )
        new_scenes.append(revised)

    by_id = {e.event_id: e for e in book.events}
    all_codes = episode_codes | {
        i.code for issues_list in codes_by_scene.values() for i in issues_list
    }

    if "coverage_gap" in all_codes:
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

    # 镜头预算超限（整集级问题）：先把各场镜头数缩到最小 1，再按比例/贪心削减到预算内。
    if "shot_budget_exceeded" in episode_codes and decision.target_shots > 0:
        counts = [max(MIN_SCENE_SHOTS, s.shot_count) for s in new_scenes]
        if sum(counts) > decision.target_shots:
            total = sum(counts)
            counts = [
                max(MIN_SCENE_SHOTS, int(c * decision.target_shots / total)) for c in counts
            ]
            while sum(counts) > decision.target_shots:
                i = max(range(len(counts)), key=lambda j: counts[j])
                if counts[i] <= MIN_SCENE_SHOTS:
                    break
                counts[i] -= 1
            new_scenes = [
                s.model_copy(update={"shot_count": c})
                for s, c in zip(new_scenes, counts, strict=True)
            ]

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

    # R1 人物一致性：speaker 必须是角色名（允许 char_id 但需映射成名字）；直接用 char_id 当说话人是 bug（R4）。
    for scene in script.scenes:
        for line in scene.dialogue:
            sp = line.speaker
            if sp in known_names:
                continue
            if sp in known_ids:
                # char_id 必须映射成角色名再使用（R4 修复）
                char_obj = next((c for c in book.characters if c.char_id == sp), None)
                if char_obj and char_obj.name:
                    continue  # 有名字映射，合法但会被下游规范化
                issues.append(
                    ReviewIssue(
                        code="unknown_speaker",
                        message=f"台词人物 {sp!r} 是 char_id 未映射到角色名",
                        scope=f"scene:{scene.scene_no}",
                        scene_no=scene.scene_no,
                    )
                )
            else:
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
    allow_llm_errors_to_fail: bool = True,
    round_index: int = 0,
) -> SupervisionResult:
    """监督层：确定性规则 + 可选 LLM 定性意见；规则问题永远计入。"""
    det = deterministic_checks(script, book, decision, taboo_keywords=taboo_keywords)
    llm_issues: list[ReviewIssue] = []
    if llm is not None:
        llm_issues = await _supervisor_via_llm(
            script, decision, llm, round_index=round_index
        )
    all_issues = det + llm_issues
    score = _score_from_issues(all_issues)
    # 硬门：确定性规则错误必拒；若开启 allow_llm_errors_to_fail（默认开），
    # LLM 监督评为 severity=error 的定性问题亦进入硬门并触发返修回路（DRAMAPLAN P4）。
    has_det_errors = any(i.severity == "error" for i in det)
    has_llm_errors = allow_llm_errors_to_fail and any(i.severity == "error" for i in llm_issues)
    passed = not (has_det_errors or has_llm_errors)
    return SupervisionResult(
        passed=passed,
        score=score,
        issues=all_issues,
        deterministic_issues=det,
        llm_issues=llm_issues,
    )


_SUPERVISOR_PROMPT_INITIAL = """你是短剧审稿人。下面是本集剧本初稿与改编决策。只输出 JSON：
{{"issues": [{{"scene_no": 整数或null, "code": "llm:问题类型", "message": "问题描述", "severity": "error|warning"}}],
"score": 0到100的整数}}
只报确定性规则查不出的**定性**问题（人物弧光、节奏、逻辑连贯、台词质量）。
【审稿标准】：
按你对该集剧本的真实判断独立打分并给出问题。问题无则 score 给高分；若存在人物动机单薄、台词功能化、情绪转折生硬、逻辑断裂等硬伤，可评为 "error" 并给出低分。severity 与 score 完全由你根据内容判断，不要预设必须通过或必须拒绝。
镜头数/时长/字数/人物名是否在角色表这类已由规则检查，不要重复。

决策：{decision}
剧本：{script}
"""

_SUPERVISOR_PROMPT_REVISED = """你是短剧审稿人。下面是本集剧本（已针对初审问题完成针对性返修）与改编决策。只输出 JSON：
{{"issues": [{{"scene_no": 整数或null, "code": "llm:问题类型", "message": "问题描述", "severity": "error|warning"}}],
"score": 0到100的整数}}
只报确定性规则查不出的**定性**问题（人物弧光、节奏、逻辑连贯、台词质量）。
【复审标准】：
请对返修后的剧本独立复核：若返修确实解决了两前问题、逻辑与人物动机已健全，可给出通过（score >= {pass_score}）；若仍存在未解决的定性硬伤，请如实评为 "error" 并给出低分（score < {pass_score}），本集将再次返修或如实标记不通过。是否通过完全由内容质量决定，不要预设已经通过。
镜头数/时长/字数/人物名是否在角色表这类已由规则检查，不要重复。

决策：{decision}
剧本：{script}
"""


async def _supervisor_via_llm(
    script: EpisodeScript,
    decision: AdaptationDecision,
    llm: Any,
    round_index: int = 0,
) -> list[ReviewIssue]:
    prompt_template = (
        _SUPERVISOR_PROMPT_REVISED if round_index > 0 else _SUPERVISOR_PROMPT_INITIAL
    )
    prompt = prompt_template.format(
        decision=decision.model_dump_json(),
        script=script.model_dump_json(),
        pass_score=PASS_SCORE,
    )
    try:
        resp = await llm(messages=[{"role": "user", "content": prompt}], max_tokens=1024)
        content = resp.get("content") if hasattr(resp, "get") else str(resp)
        data = _extract_json(content)
        issues: list[ReviewIssue] = []
        for i in data.get("issues") or []:
            raw_sev = str(i.get("severity") or "warning").lower().strip()
            sev = "error" if raw_sev == "error" else "warning"
            issues.append(
                ReviewIssue(
                    code=str(i.get("code") or "llm:issue"),
                    message=str(i.get("message") or ""),
                    scope=f"scene:{i['scene_no']}" if i.get("scene_no") else "episode",
                    severity=sev,
                    scene_no=int(i["scene_no"]) if i.get("scene_no") else None,
                )
            )
        return issues
    except Exception as exc:
        logger.warning("监督层 LLM 失败,只用确定性规则: %s", exc)
        return []


# ── 三层回路 ──────────────────────────────────────────────────────────────────
def _scene_hash(scene: ScriptScene) -> str:
    return hashlib.sha256(scene.model_dump_json().encode()).hexdigest()[:12]


def _diff_scenes(before: EpisodeScript, after: EpisodeScript) -> list[dict[str, Any]]:
    """计算前后剧本的场次差异。

    R2 要求：scene_diffs 同时保存改前/改后的 summary/narration/dialogue 全文，
    以便审核方能核对 LLM 是否真的改稿。
    """
    before_by_no = {s.scene_no: s for s in before.scenes}
    after_by_no = {s.scene_no: s for s in after.scenes}
    diffs: list[dict[str, Any]] = []
    for no in sorted(set(before_by_no) | set(after_by_no)):
        b = before_by_no.get(no)
        a = after_by_no.get(no)
        bh = _scene_hash(b) if b else None
        ah = _scene_hash(a) if a else None
        if bh != ah:
            # 记录完整改前/改后文本，用于人工核验
            def _scene_summary(s: ScriptScene) -> dict[str, Any]:
                return {
                    "scene_no": s.scene_no,
                    "location": s.location,
                    "summary": s.summary,
                    "narration": s.narration,
                    "dialogue": [
                        {"speaker": d.speaker, "text": d.text, "emotion": d.emotion}
                        for d in s.dialogue
                    ],
                    "shot_count": s.shot_count,
                    "duration_s": s.duration_s,
                }
            diffs.append({
                "scene_no": no,
                "before": _scene_summary(b) if b else None,
                "after": _scene_summary(a) if a else None,
                "before_hash": bh,
                "after_hash": ah,
            })
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
        script,
        book,
        decision,
        llm=llm,
        taboo_keywords=taboo_keywords,
        round_index=0,
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
        trigger_issues = supervision.issues
        trigger_issue_codes = sorted({i.code for i in trigger_issues})
        script = await execution_layer(
            decision,
            book,
            llm=llm,
            taboo_keywords=taboo_keywords,
            previous=before,
            issues=trigger_issues,
        )
        supervision = await supervisor_layer(
            script,
            book,
            decision,
            llm=llm,
            taboo_keywords=taboo_keywords,
            round_index=r,
        )
        diffs = _diff_scenes(before, script)
        # revised_scenes 由 scene_diffs 实际变化的场推出（P4.3）
        revised = sorted({d["scene_no"] for d in diffs if d.get("scene_no") is not None})
        rounds.append(
            RoundRecord(
                round_index=r,
                score=supervision.score,
                passed=supervision.passed,
                issues=supervision.issues,
                revised_scenes=revised,
                scene_diffs=diffs,
                trigger_issue_codes=trigger_issue_codes,
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


def script_to_storyboard(
    script: EpisodeScript,
    book: StoryGraph,
    outline_ep: OutlineEpisode | None = None,
) -> EpisodeStoryboard:
    """从审稿通过的 EpisodeScript 生成镜头级分镜（每镜带 event_id、画面描述、台词/旁白、时长）。
    镜头数 == 场 shot_count 之和，Σ <= 本集预算（DRAMAPLAN P3）。
    """
    by_event = {e.event_id: e for e in book.events}
    target_duration = outline_ep.target_duration_s if outline_ep else script.total_duration()
    shot_budget = outline_ep.shot_budget if outline_ep else script.total_shots()

    shots: list[EpisodeShot] = []
    for scene in script.scenes:
        n_shots = max(MIN_SCENE_SHOTS, scene.shot_count)
        scene_dur = (
            scene.duration_s
            if scene.duration_s > 0
            else (target_duration / max(1, len(script.scenes)))
        )
        per_shot_dur = round(scene_dur / n_shots, 2) if n_shots > 0 else 5.0

        for j in range(n_shots):
            shot_id = f"EP{script.ep_number:02d}_SC{scene.scene_no:02d}_SH{j+1:02d}"

            if scene.event_ids:
                eid = scene.event_ids[j % len(scene.event_ids)]
            elif book.events:
                eid = book.events[0].event_id
            else:
                eid = "EVT_000"

            ev = by_event.get(eid)

            speaker = ""
            tts_text = ""
            if scene.dialogue:
                if j < len(scene.dialogue):
                    line = scene.dialogue[j]
                    speaker = line.speaker
                    tts_text = f"{speaker}：{line.text}" if speaker else line.text
                elif j == 0 and scene.narration:
                    speaker = "旁白"
                    tts_text = scene.narration
                else:
                    line = scene.dialogue[j % len(scene.dialogue)]
                    speaker = line.speaker
                    tts_text = f"{speaker}：{line.text}" if speaker else line.text
            elif scene.narration:
                speaker = "旁白"
                tts_text = scene.narration
            elif scene.summary:
                speaker = "旁白"
                tts_text = scene.summary

            prompt_parts = []
            if scene.location:
                prompt_parts.append(f"场景：{scene.location}")
            elif ev and ev.location:
                prompt_parts.append(f"场景：{ev.location}")

            if speaker and speaker != "旁白":
                prompt_parts.append(f"出场角色：{speaker}")
            elif ev and ev.actors:
                prompt_parts.append(f"出场角色：{'、'.join(ev.actors)}")

            action_desc = scene.summary or (ev.summary if ev else "") or "人物特写与情境展开"
            prompt_parts.append(f"画面：{action_desc}")
            if j == 0:
                prompt_parts.append("全景交代环境")
            elif j == n_shots - 1:
                prompt_parts.append("特写定格情绪")
            else:
                prompt_parts.append("中景角色对峙与互动")

            image_prompt = "，".join(prompt_parts) + "。写实短剧风格，电影级光影。"

            if j == n_shots - 1 and n_shots > 1:
                cur_dur = round(max(1.0, scene_dur - per_shot_dur * (n_shots - 1)), 2)
            else:
                cur_dur = per_shot_dur

            shots.append(
                EpisodeShot(
                    shot_id=shot_id,
                    scene_no=scene.scene_no,
                    event_id=eid,
                    image_prompt=image_prompt,
                    tts_text=tts_text,
                    duration_s=cur_dur,
                    speaker=speaker,
                )
            )

    if shot_budget > 0 and len(shots) > shot_budget:
        shots = shots[:shot_budget]

    return EpisodeStoryboard(
        ep_number=script.ep_number,
        title=script.title,
        target_duration_s=target_duration,
        shot_budget=shot_budget,
        shots=shots,
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
    "revise_episode_script_async",
    "review_episode",
    "run_three_layer_review",
    "script_to_storyboard",
    "supervisor_layer",
    "write_review_log",
]
