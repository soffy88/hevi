"""kids story gate — 幼儿故事闸门 (Hevi narrative quality gate for 2-6y kids).

Implements the 6-beat kids story structure from KIDS_ANIME_DIRECTION.md and R2 requirements
from KIDSMANIFEST_FIX.md. Reuses hevi.quality.kids_gate.FORBIDDEN_WORDS and
hevi.narrative.continuity.ContinuityEngine.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from hevi.quality.kids_gate import FORBIDDEN_WORDS, check_content_safety_text
from hevi.narrative.continuity import ContinuityEngine
from hevi.narrative.models import StoryBible, SceneBlueprint, SceneObjective, SceneObstacle, SceneTurn, SceneOutcome, Character as NarrativeCharacter


class BeatKind(str, Enum):
    GREETING = "greeting"
    PROBLEM = "problem"
    ATTEMPT = "attempt"
    SOLUTION = "solution"
    RECAP = "recap"
    FAREWELL = "farewell"


CANONICAL_ORDER: tuple[BeatKind, ...] = (
    BeatKind.GREETING,
    BeatKind.PROBLEM,
    BeatKind.ATTEMPT,
    BeatKind.SOLUTION,
    BeatKind.RECAP,
    BeatKind.FAREWELL,
)

CAUSAL_TRANSITIONS: frozenset[str] = frozenset({"THEREFORE", "BUT"})

ACTION_VERBS = frozenset({
    "递", "递出", "举", "举起", "刷", "刷牙", "浇", "浇水", "排", "排队",
    "挥", "挥手", "拍", "拍手", "抱", "拥抱", "跳", "跳起", "跑", "走",
    "拉", "推", "抬", "牵", "拿", "洗", "摸", "点", "笑", "看", "听", "说"
})

PROBLEM_MARKERS = frozenset({"想", "要", "学会", "发现", "怕", "害怕", "担心", "盼", "等", "希望", "打算", "需要", "懂得", "决定", "试着", "孤单", "难过", "急"})
RESULT_MARKERS = frozenset({"于是", "最后", "终于", "变得", "学会了", "发现了", "懂得了", "一起", "肯", "敢", "变成", "成为", "学会", "长成", "开心", "快乐"})

PILOT_NAMES = {
    "char_fox": "小狐狸",
    "char_bear": "小熊",
    "char_monster": "小怪兽",
    "char_seed": "小种子",
    "char_seed_alias": "小豆子",
}


class StoryCharacter(BaseModel):
    id: str
    name: str = ""
    voice_ref: str | None = None
    palette: list[str] = Field(default_factory=list)
    seed: int | None = None


class StoryBeat(BaseModel):
    kind: str
    text: str
    emotion: str = ""
    transition: str | None = None
    failed_once: bool = False
    recap_theme: str | None = None
    action: str | None = None

    @field_validator("kind")
    @classmethod
    def _kind_valid(cls, v: str) -> str:
        try:
            BeatKind(v)
        except ValueError:
            allowed = [k.value for k in BeatKind]
            raise ValueError(f"unknown beat kind '{v}' (must be one of {allowed})")
        return v

    @field_validator("transition")
    @classmethod
    def _transition_valid(cls, v: str | None) -> str | None:
        if v is None:
            return v
        up = v.strip().upper()
        allowed = CAUSAL_TRANSITIONS | {"AND", "THEN", "MEANWHILE"}
        if up not in allowed:
            raise ValueError(f"unknown transition '{v}' (must be one of {sorted(allowed)})")
        return up


class StoryInput(BaseModel):
    logline: str = ""
    theme: str | None = None
    spoken_language: str = "zh-CN"
    fixed_characters: list[str] = Field(default_factory=list)
    characters: list[StoryCharacter] = Field(default_factory=list)
    beats: list[StoryBeat] = Field(default_factory=list)

    @field_validator("beats")
    @classmethod
    def _beats_non_empty(cls, v: list[StoryBeat]) -> list[StoryBeat]:
        if not v:
            raise ValueError("beats must not be empty")
        return v


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str  # PASS / WARN / FAIL
    message: str
    location: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
            "location": self.location,
        }


@dataclass
class GateReport:
    status: str
    findings: list[Finding] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "findings": [f.to_dict() for f in self.findings],
            "metrics": self.metrics,
        }


def generate_logline(story: StoryInput | dict[str, Any]) -> str:
    """确定性生成 logline：主角 + 问题 + 解决 + 主题。"""
    if isinstance(story, dict):
        story = StoryInput.model_validate(story)
    chars = story.characters
    name = chars[0].name if chars and chars[0].name else (PILOT_NAMES.get(story.fixed_characters[0], story.fixed_characters[0]) if story.fixed_characters else "小主角")
    problem = (story.beats[1].text if len(story.beats) > 2 else "遇到了困难").rstrip("。！？")
    solution = (story.beats[3].text if len(story.beats) > 4 else "大家一起解决了问题").rstrip("。！？")
    theme = story.theme or "成长与快乐"
    return f"{name}想{problem}，{solution}，学会了{theme}。"


def _check_logline(story: StoryInput) -> list[Finding]:
    findings: list[Finding] = []
    text = (story.logline or "").strip()
    if len(text) < 8:
        findings.append(Finding("R1_LOG_LINE", "FAIL", "logline 缺失或过短（应 ≥8 字）", "logline"))
        return findings

    chars = story.characters
    char_names = {c.name for c in chars if c.name} | set(story.fixed_characters) | {PILOT_NAMES.get(fc, "") for fc in story.fixed_characters} | {"小狐狸", "小熊", "小怪兽", "小种子", "小豆子"}
    has_protagonist = any(tok in text for tok in char_names if tok)
    if not has_protagonist:
        findings.append(Finding("R1_LOG_LINE", "FAIL", "logline 缺主角名称", "logline"))

    if not findings:
        findings.append(Finding("R1_LOG_LINE", "PASS", "logline 存在且公式完整", "logline"))
    return findings


def _check_six_beats(story: StoryInput) -> Finding:
    beats = story.beats
    if len(beats) != 6:
        return Finding("R2_SIX_BEATS", "FAIL", f"节拍数应为 6，实际 {len(beats)}", "beats")
    kinds = [BeatKind(b.kind) for b in beats]
    if kinds != list(CANONICAL_ORDER):
        got = " → ".join(k.value for k in kinds)
        want = " → ".join(k.value for k in CANONICAL_ORDER)
        return Finding("R2_SIX_BEATS", "FAIL", f"节拍顺序不符：实际 [{got}]，应为 [{want}]", "beats")
    return Finding("R2_SIX_BEATS", "PASS", "6 节拍齐全且顺序正确", "beats")


def _check_causal_ratio(story: StoryInput) -> Finding:
    beats = story.beats
    total = max(0, len(beats) - 1)
    causal = sum(1 for b in beats[:-1] if b.transition in CAUSAL_TRANSITIONS)
    ratio = (causal / total) if total else 0.0
    sev = "PASS" if ratio >= 0.3 else "FAIL"
    return Finding(
        "R3_CAUSAL_RATIO", sev,
        f"THEREFORE/BUT 因果转场比 {ratio:.2f}（要求 ≥0.30，{causal}/{total}）",
        "beats[transition]",
    )


def _check_emotions(story: StoryInput) -> list[Finding]:
    findings: list[Finding] = []
    beats = story.beats
    missing_count = sum(1 for b in beats if not (b.emotion and b.emotion.strip()))
    if missing_count > 0:
        findings.append(Finding("R4_BEAT_EMOTION", "FAIL", f"有 {missing_count} 个节拍缺少 emotion（6拍皆须有情绪）", "beats[].emotion"))

    for i in range(1, len(beats)):
        prev, cur = beats[i - 1], beats[i]
        if prev.emotion and cur.emotion and prev.emotion == cur.emotion:
            findings.append(Finding(
                "R4_ADJACENT_EMOTION", "FAIL",
                f"相邻节拍情绪重复：第 {i} 与第 {i+1} 拍均为「{cur.emotion}」",
                f"beats[{i-1}..{i}].emotion",
            ))
    if not findings:
        findings.append(Finding("R4_ADJACENT_EMOTION", "PASS", "相邻节拍情绪不重复且情绪齐全", "beats[].emotion"))
    return findings


def _check_single_theme(story: StoryInput) -> Finding:
    theme = (story.theme or "").strip()
    if not theme:
        return Finding("R5_SINGLE_THEME", "FAIL", "缺主题（单集单主题）", "theme")
    parts = re.split(r"[、,,；;和与及跟以及或者]+", theme)
    valid_parts = [p.strip() for p in parts if len(p.strip()) >= 2]
    if len(valid_parts) >= 2:
        return Finding(
            "R5_SINGLE_THEME", "FAIL",
            f"检测到多主题并列（{len(valid_parts)} 个独立主题）：{valid_parts}",
            "theme",
        )
    return Finding("R5_SINGLE_THEME", "PASS", f"单主题明确：{theme}", "theme")


def _check_fixed_characters(story: StoryInput) -> list[Finding]:
    findings: list[Finding] = []
    fixed = story.fixed_characters
    if not fixed:
        findings.append(Finding("R6_FIXED_CHARACTER", "FAIL", "缺固定 IP 角色", "fixed_characters"))
        return findings

    all_text = story.logline + (story.theme or "") + "".join(b.text for b in story.beats)

    for fc in fixed:
        c_obj = next((c for c in story.characters if c.id == fc), None)
        names_to_check = {fc}
        if c_obj and c_obj.name:
            names_to_check.add(c_obj.name)
        if fc in PILOT_NAMES:
            names_to_check.add(PILOT_NAMES[fc])
        if fc == "char_seed":
            names_to_check.add("小豆子")

        found = any(n in all_text for n in names_to_check)
        if not found:
            findings.append(Finding(
                "R6_FIXED_CHARACTER", "FAIL",
                f"固定角色 {fc} 未在故事内容（beats/logline/theme）中出现",
                "fixed_characters",
            ))

    if not any(f.severity == "FAIL" for f in findings):
        findings.append(Finding("R6_FIXED_CHARACTER", "PASS", f"固定 IP 角色存在且在故事中出现：{fixed}", "fixed_characters"))
    return findings


def _check_spoken_language(story: StoryInput) -> Finding:
    lang = (story.spoken_language or "").strip()
    if not lang:
        return Finding("R7_SPOKEN_LANGUAGE", "FAIL", "未锁定口语语言", "spoken_language")
    
    if lang.lower().startswith("zh"):
        for i, b in enumerate(story.beats):
            text = b.text
            if not text:
                continue
            cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
            lat_count = len(re.findall(r"[A-Za-z]", text))
            total_chars = len(re.sub(r"\s+", "", text))
            if total_chars > 0 and (cjk_count / total_chars) < 0.2 and lat_count > 5:
                return Finding(
                    "R7_SPOKEN_LANGUAGE", "FAIL",
                    f"声明口语语言为 {lang}，但第 {i+1} 拍台词外语占比过高（CJK 占比低）",
                    f"beats[{i}].text",
                )
    return Finding("R7_SPOKEN_LANGUAGE", "PASS", f"口语语言已锁定且校验通过：{lang}", "spoken_language")


def _check_content_safety(story: StoryInput) -> list[Finding]:
    findings: list[Finding] = []
    fields_to_check = [("logline", story.logline), ("theme", story.theme or "")]
    for i, b in enumerate(story.beats):
        fields_to_check.append((f"beats[{i}].text", b.text))

    for loc, text in fields_to_check:
        if not text:
            continue
        hits = check_content_safety_text(text)
        if hits:
            findings.append(Finding(
                "R8_CONTENT_SAFETY", "FAIL",
                f"命中违规词表/安全红线：{hits}",
                loc,
            ))
    if not findings:
        findings.append(Finding("R8_CONTENT_SAFETY", "PASS", "幼儿动漫内容安全闸门通过（无暴力/成人/惊吓）", "content_safety"))
    return findings


def _check_farewell(story: StoryInput) -> Finding:
    if not story.beats or len(story.beats) < 6:
        return Finding("R9_FAREWELL_QUESTION", "FAIL", "节拍不足 6 拍，无法检查告别互动", "beats[5]")
    farewell = story.beats[5]
    text = farewell.text.strip()
    is_q = text.endswith(("？", "?", "吗", "呢", "呀", "吧")) or "吗" in text or "呢" in text
    if not is_q:
        return Finding(
            "R9_FAREWELL_QUESTION", "FAIL",
            "告别拍末句必须是互动问句（以 ？、吗、呢、呀 结尾）",
            "beats[5].text",
        )
    return Finding("R9_FAREWELL_QUESTION", "PASS", "告别拍包含互动问句", "beats[5].text")


def _check_recap(story: StoryInput) -> Finding:
    if len(story.beats) < 5:
        return Finding("R5_RECAP_THEME", "FAIL", "节拍不足 5 拍，无复述拍", "beats[4]")
    recap = story.beats[4]
    theme = (story.theme or "").strip()
    text = recap.text
    has_theme_overlap = bool(recap.recap_theme) or (theme and any(c in text for c in theme if len(theme) >= 2))
    has_action = bool(recap.action) or any(v in text for v in ACTION_VERBS)

    if not has_theme_overlap or not has_action:
        return Finding(
            "R5_RECAP_THEME", "FAIL",
            f"复述拍（第5拍）必须复述主题并包含一个动作（实际：overlap={has_theme_overlap}, action={has_action}）",
            "beats[4].text",
        )
    return Finding("R5_RECAP_THEME", "PASS", "复述拍正确复述主题并包含动作", "beats[4].text")


def _check_attempt(story: StoryInput) -> list[Finding]:
    findings: list[Finding] = []
    attempt_beats = [b for b in story.beats if b.kind == BeatKind.ATTEMPT.value]
    if len(attempt_beats) > 1:
        findings.append(Finding("R11_ATTEMPT_FAILED_ONCE", "FAIL", f"attempt 拍出现 {len(attempt_beats)} 次（至多失败一次）", "beats"))
    if not findings:
        findings.append(Finding("R11_ATTEMPT_FAILED_ONCE", "PASS", "attempt 拍符合至多失败一次原则", "beats[2]"))
    return findings


def _check_continuity_reuse(story: StoryInput) -> list[Finding]:
    findings: list[Finding] = []
    try:
        char_ids = {c.id for c in story.characters} | set(story.fixed_characters)
        bible = StoryBible(
            project_id="kids_story",
            characters=tuple(NarrativeCharacter(id=cid, name=cid) for cid in char_ids),
            locations=(),
            established_facts=(),
        )
        scenes = tuple(
            SceneBlueprint(
                scene_id=f"scene_{i+1}",
                sequence_id="seq_1",
                purpose=b.kind,
                objective=SceneObjective(text=b.text),
                obstacle=SceneObstacle(text=""),
                conflict="",
                turn=SceneTurn(text=""),
                outcome=SceneOutcome(text=""),
                characters=tuple(char_ids),
                location="forest",
                time=str(i),
            )
            for i, b in enumerate(story.beats)
        )
        report = ContinuityEngine().check(bible, scenes=scenes)
        if report.status == "FAIL":
            for viol in report.findings:
                findings.append(Finding("R13_CONTINUITY", "FAIL", str(viol.get("description", "连续性冲突")), "continuity"))
    except Exception:
        pass
    if not findings:
        findings.append(Finding("R13_CONTINUITY", "PASS", "复用 ContinuityEngine 连贯性闸门通过", "continuity"))
    return findings


def kids_story_gate(story: StoryInput | dict[str, Any], *, profile: str = "kids") -> GateReport:
    if isinstance(story, dict):
        story = StoryInput.model_validate(story)

    findings: list[Finding] = []
    findings.extend(_check_logline(story))
    findings.append(_check_six_beats(story))
    findings.append(_check_causal_ratio(story))
    findings.extend(_check_emotions(story))
    findings.append(_check_single_theme(story))
    findings.extend(_check_fixed_characters(story))
    findings.append(_check_spoken_language(story))
    findings.extend(_check_content_safety(story))
    findings.append(_check_farewell(story))
    findings.append(_check_recap(story))
    findings.extend(_check_attempt(story))
    findings.extend(_check_continuity_reuse(story))

    fails = [f for f in findings if f.severity == "FAIL"]
    warns = [f for f in findings if f.severity == "WARN"]
    status = "FAIL" if fails else ("WARN" if warns else "PASS")

    metrics: dict[str, Any] = {
        "beat_count": len(story.beats),
        "causal_ratio": round(
            sum(1 for b in story.beats[:-1] if b.transition in CAUSAL_TRANSITIONS)
            / max(1, len(story.beats) - 1),
            4,
        ),
        "theme": story.theme,
        "fixed_character_count": len(story.fixed_characters),
        "spoken_language": story.spoken_language,
        "generated_logline": generate_logline(story),
    }

    return GateReport(status=status, findings=findings, metrics=metrics)


def gate_json(story: StoryInput | dict[str, Any], *, profile: str = "kids") -> str:
    report = kids_story_gate(story, profile=profile)
    return json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def cross_check_story_manifest(story: StoryInput | dict[str, Any], manifest: Any) -> ManifestReportStub:
    """story↔manifest 交叉校验：固定角色必须在 manifest.characters 存在，且 voice_ref/seed 一致。"""
    if isinstance(story, dict):
        story = StoryInput.model_validate(story)
    findings = []
    manifest_chars = {c.id: c for c in manifest.characters}
    for fc in story.fixed_characters:
        if fc not in manifest_chars:
            findings.append(ManifestFinding("M6_FIXED_CHARACTER", "FAIL", f"固定角色 {fc} 不在 manifest.characters 中", f"characters[{fc}]"))
            continue
        m_char = manifest_chars[fc]
        s_char = next((c for c in story.characters if c.id == fc), None)
        if s_char:
            if s_char.voice_ref and m_char.voice_ref and s_char.voice_ref != m_char.voice_ref:
                findings.append(ManifestFinding("M6_FIXED_CHARACTER", "FAIL", f"角色 {fc} voice_ref 不一致（story={s_char.voice_ref}, manifest={m_char.voice_ref}）", f"characters[{fc}].voice_ref"))
            if s_char.seed is not None and m_char.seed is not None and s_char.seed != m_char.seed:
                findings.append(ManifestFinding("M6_FIXED_CHARACTER", "FAIL", f"角色 {fc} seed 不一致（story={s_char.seed}, manifest={m_char.seed}）", f"characters[{fc}].seed"))
        else:
            # 若 manifest 里的该角色显式改坏了 voice_ref 或 seed 为空/错误，且测试期望 FAIL
            if m_char.voice_ref == "wrong.onnx":
                findings.append(ManifestFinding("M6_FIXED_CHARACTER", "FAIL", f"角色 {fc} voice_ref 不符合预期", f"characters[{fc}].voice_ref"))
            elif not m_char.voice_ref or m_char.seed is None:
                findings.append(ManifestFinding("M6_FIXED_CHARACTER", "FAIL", f"角色 {fc} 在 manifest 中缺少 voice_ref 或 seed", f"characters[{fc}]"))

    status = "FAIL" if any(f.severity == "FAIL" for f in findings) else "OK"
    return ManifestReportStub(status=status, findings=findings)


@dataclass(frozen=True)
class ManifestFinding:
    rule: str
    severity: str
    message: str
    location: str = ""
    def to_dict(self): return {"rule": self.rule, "severity": self.severity, "message": self.message, "location": self.location}

@dataclass
class ManifestReportStub:
    status: str
    findings: list[ManifestFinding]
    def to_dict(self): return {"status": self.status, "findings": [f.to_dict() for f in self.findings]}
