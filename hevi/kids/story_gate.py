"""kids story gate — 幼儿故事闸门 (Hevi narrative quality gate for 2-6y kids).

Implements the 6-beat kids story structure from KIDS_ANIME_DIRECTION.md and the
kids story gate profile from RENOISE_EVAL §3.2 (P1). Reuses the structural shape
of hevi.narrative.quality.NarrativeQualityGate / continuity.ContinuityEngine but
is fully self-contained: no LLM, no network, CPU-only, deterministic.

Story beats (canonical order):
  1. greeting  开场问候
  2. problem   遇到问题
  3. attempt   尝试（允许失败一次）
  4. solution  解决
  5. recap     结尾复述主题（一句话 + 一个动作）
  6. farewell  告别 + 互动问句

Rules checked:
  R1  logline present and well-formed (non-empty, min length).
  R2  exactly 6 beats in canonical order.
  R3  THEREFORE/BUT causal transition ratio >= 30%.
  R4  adjacent beats must not share the same emotion.
  R5  single theme (exactly one theme defined).
  R6  at least one fixed IP character present (seed/voice locked).
  R7  spoken language locked (declared, non-empty).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

# ── 节拍定义 ──────────────────────────────────────────────────────────
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


# ── 输入模型（确定性，便于 fixture 与 dry-run）──────────────────────
class StoryBeat(BaseModel):
    """单节拍：类型 + 台词 + 情绪 + 到下一拍的转场。"""

    kind: str
    text: str
    emotion: str = ""
    transition: str | None = None  # 到下一拍的转场：THEREFORE/BUT/AND/THEN/MEANWHILE
    failed_once: bool = False  # attempt 拍允许失败一次

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
    """一个 story 输入（一集的故事草稿）。"""

    logline: str = ""
    theme: str | None = None
    spoken_language: str = ""
    fixed_characters: list[str] = Field(default_factory=list)  # 固定 IP 角色 id
    beats: list[StoryBeat] = Field(default_factory=list)

    @field_validator("beats")
    @classmethod
    def _beats_non_empty(cls, v: list[StoryBeat]) -> list[StoryBeat]:
        if not v:
            raise ValueError("beats must not be empty")
        return v


# ── 结果模型 ────────────────────────────────────────────────────────
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
    status: str  # PASS / WARN / FAIL
    findings: list[Finding] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "findings": [f.to_dict() for f in self.findings],
            "metrics": self.metrics,
        }


# ── 规则实现 ────────────────────────────────────────────────────────
def _check_logline(story: StoryInput) -> Finding:
    text = (story.logline or "").strip()
    if len(text) < 8:
        return Finding("R1_LOG_LINE", "FAIL", "logline 缺失或过短（应 ≥8 字）", "logline")
    return Finding("R1_LOG_LINE", "PASS", "logline 存在且格式合理", "logline")


def _check_six_beats(story: StoryInput) -> Finding:
    beats = story.beats
    if len(beats) != 6:
        return Finding(
            "R2_SIX_BEATS", "FAIL",
            f"节拍数应为 6，实际 {len(beats)}", "beats",
        )
    kinds = [BeatKind(b.kind) for b in beats]
    if kinds != list(CANONICAL_ORDER):
        got = " → ".join(k.value for k in kinds)
        want = " → ".join(k.value for k in CANONICAL_ORDER)
        return Finding(
            "R2_SIX_BEATS", "FAIL",
            f"节拍顺序不符：实际 [{got}]，应为 [{want}]", "beats",
        )
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


def _check_adjacent_emotion(story: StoryInput) -> Finding:
    beats = story.beats
    for i in range(1, len(beats)):
        prev, cur = beats[i - 1], beats[i]
        if prev.emotion and cur.emotion and prev.emotion == cur.emotion:
            return Finding(
                "R4_ADJACENT_EMOTION", "FAIL",
                f"相邻节拍情绪重复：第 {i} 与第 {i+1} 拍均为「{cur.emotion}」",
                f"beats[{i-1}..{i}].emotion",
            )
    return Finding("R4_ADJACENT_EMOTION", "PASS", "相邻节拍情绪不重复", "beats[].emotion")


def _check_single_theme(story: StoryInput) -> Finding:
    if not story.theme or not story.theme.strip():
        return Finding("R5_SINGLE_THEME", "FAIL", "缺主题（单集单主题）", "theme")
    return Finding("R5_SINGLE_THEME", "PASS", f"主题明确：{story.theme}", "theme")


def _check_fixed_characters(story: StoryInput) -> Finding:
    if not story.fixed_characters:
        return Finding("R6_FIXED_CHARACTER", "FAIL", "缺固定 IP 角色", "fixed_characters")
    return Finding(
        "R6_FIXED_CHARACTER", "PASS",
        f"固定 IP 角色 {len(story.fixed_characters)} 个：{story.fixed_characters}",
        "fixed_characters",
    )


def _check_spoken_language(story: StoryInput) -> Finding:
    lang = (story.spoken_language or "").strip()
    if not lang:
        return Finding("R7_SPOKEN_LANGUAGE", "FAIL", "未锁定口语语言", "spoken_language")
    return Finding("R7_SPOKEN_LANGUAGE", "PASS", f"口语语言已锁定：{lang}", "spoken_language")


def kids_story_gate(story: StoryInput | dict[str, Any], *, profile: str = "kids") -> GateReport:
    """运行幼儿故事闸门，返回确定性 GateReport。"""
    if isinstance(story, dict):
        story = StoryInput.model_validate(story)

    findings: list[Finding] = [
        _check_logline(story),
        _check_six_beats(story),
        _check_causal_ratio(story),
        _check_adjacent_emotion(story),
        _check_single_theme(story),
        _check_fixed_characters(story),
        _check_spoken_language(story),
    ]

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
    }

    return GateReport(status=status, findings=findings, metrics=metrics)


def gate_json(story: StoryInput | dict[str, Any], *, profile: str = "kids") -> str:
    """确定性 JSON 序列化（sort_keys + 紧凑分隔符），用于 SHA-256 比对。"""
    report = kids_story_gate(story, profile=profile)
    return json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
