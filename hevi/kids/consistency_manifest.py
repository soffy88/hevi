"""KidsConsistencyManifest — 幼儿故事一致性清单 (RENOISE_EVAL §3.3 + 单元 K1).

- schema 字段按 §3.3：schema_version / project_id / episode / audience /
  theme / style_bible / characters / props / scenes / transition_table /
  spoken_language / shots[].shot_spec。
- 6 条绑定校验规则（§3.3 绑定与校验规则 + 验收标准 3）：
  M0  shots[].shot_spec 每个字段**委派**给 hevi.production.shot_spec.ShotSpec
      （未知 template/transition_in/sfx/style → 由 ShotSpec 校验器直接失败）。
  M1  style_bible 四段齐全且逐字前置（art_style/camera_language/color_grade/negative）。
  M2  transition_table 覆盖除 S1 外每个切点；中间段不得“frame holds steady”收尾。
  M3  spoken_language 覆盖每个说话镜（有 line 的镜必须有对应条目）。
  M4  @引用 必须能在 manifest 内解析（@char_x/@prop_x/@scene_x）。
  M5  duration ≥2.5s，整片平均 ≥3.5s（与 kids_gate.check_shot_duration 一致）。
- 与 ShotSpec 双向绑定：manifest.shots[].shot_spec ↔ 任务
  shot_states.selection_json["shot_spec"]（复用 hevi.production.shot_spec 的
  upsert_spec / read_spec）。
- 零网络、无 mock、确定性可复现。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from hevi.production import shot_spec as _ss
from hevi.production.shot_spec import ShotSpec

_SCHEMA_VERSION = "1.0"

_REF_RE = re.compile(r"@([A-Za-z0-9_]+)")
_FRAME_HOLDS_STEADY = "frame holds steady"


# ── schema 子模型 ────────────────────────────────────────────────────
class Audience(BaseModel):
    age_min: int = 2
    age_max: int = 6
    spoken_language: str = "zh-CN"


class Theme(BaseModel):
    one_line: str
    closing_line: str
    closing_action: str


class StyleBible(BaseModel):
    art_style: str = ""
    camera_language: str = ""
    color_grade: str = ""
    negative: str = ""


class Character(BaseModel):
    id: str
    name: str
    constant_traits: list[str] = Field(default_factory=list)
    anchor_ref: str | None = None
    voice_ref: str | None = None
    seed: int | None = None


class Prop(BaseModel):
    id: str
    name: str
    fixed_description: str = ""
    state: str = "constant"


class Scene(BaseModel):
    id: str
    location: str = ""
    environment_only_ref: str | None = None
    palette: list[str] = Field(default_factory=list)


class TransitionRow(BaseModel):
    cut: str  # e.g. "S1->S2" / "1->2"
    prev_out: str = ""
    next_in: str = ""
    technique: str = ""


class SpokenLanguageEntry(BaseModel):
    shot_index: int
    language: str


class ShotEntry(BaseModel):
    shot_index: int
    duration: float
    line: str = ""
    camera: str = ""
    framing: str = ""
    # M0：委派给 ShotSpec 既有校验器，未知字段值一律由 pydantic 抛 ValidationError。
    shot_spec: ShotSpec


# ── 主模型 ───────────────────────────────────────────────────────────
class KidsConsistencyManifest(BaseModel):
    schema_version: str = _SCHEMA_VERSION
    project_id: str
    episode: int = 1
    audience: Audience = Field(default_factory=Audience)
    theme: Theme
    style_bible: StyleBible = Field(default_factory=StyleBible)
    characters: list[Character] = Field(default_factory=list)
    props: list[Prop] = Field(default_factory=list)
    scenes: list[Scene] = Field(default_factory=list)
    transition_table: list[TransitionRow] = Field(default_factory=list)
    spoken_language: list[SpokenLanguageEntry] = Field(default_factory=list)
    shots: list[ShotEntry] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def _schema_version(cls, v: str) -> str:
        if v != _SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version '{v}' (expected '{_SCHEMA_VERSION}')")
        return v


# ── 校验报告 ────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ManifestFinding:
    rule: str
    severity: str  # OK / WARN / FAIL
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
class ManifestReport:
    status: str  # OK / FAIL
    findings: list[ManifestFinding] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "findings": [f.to_dict() for f in self.findings],
            "errors": self.errors,
        }


def _cut_key(a: int, b: int) -> str:
    return f"S{a}->S{b}"


def validate_manifest(
    manifest: "KidsConsistencyManifest | dict[str, Any]",
) -> ManifestReport:
    """校验 manifest：先走 ShotSpec 委派（M0），再逐条 M1–M5。

    返回 ManifestReport（OK / FAIL）+ 逐条 finding（规则名 + 位置）。
    """
    findings: list[ManifestFinding] = []

    # ── M0：ShotSpec 委派（未知 template/transition_in/sfx/style → 失败）──
    if isinstance(manifest, dict):
        try:
            manifest = KidsConsistencyManifest.model_validate(manifest)
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(p) for p in err.get("loc", []))
                findings.append(
                    ManifestFinding(
                        "M0_SHOTSPEC_DELEGATION", "FAIL",
                        f"ShotSpec 校验失败：{err.get('msg', '')}", loc,
                    )
                )
            return ManifestReport(status="FAIL", findings=findings, errors=[f"M0:{loc}" for f in findings])

    m: KidsConsistencyManifest = manifest

    # ── M1：Style Bible 四段齐全 ──
    sb = m.style_bible
    sb_missing = [
        name for name, val in [
            ("art_style", sb.art_style),
            ("camera_language", sb.camera_language),
            ("color_grade", sb.color_grade),
            ("negative", sb.negative),
        ] if not (val and val.strip())
    ]
    if sb_missing:
        findings.append(
            ManifestFinding(
                "M1_STYLE_BIBLE", "FAIL",
                f"Style Bible 缺段：{sb_missing}", "style_bible",
            )
        )
    else:
        findings.append(ManifestFinding("M1_STYLE_BIBLE", "OK", "Style Bible 四段齐全", "style_bible"))

    # 聚合所有可解析 id（用于 M4 的 @引用 校验）
    # §3.3：@char_fox / @prop_star / @scene_forest 引用的是 character/prop/scene 的 id 本身。
    all_ids = {c.id for c in m.characters}
    all_ids |= {p.id for p in m.props}
    all_ids |= {s.id for s in m.scenes}

    # 扫描带 @引用 的文本字段
    ref_texts: list[tuple[str, str]] = []
    for sh in m.shots:
        if sh.line:
            ref_texts.append((f"shots[{sh.shot_index}].line", sh.line))
    for tr in m.transition_table:
        ref_texts.append((f"transition_table[{tr.cut}].prev_out", tr.prev_out))
        ref_texts.append((f"transition_table[{tr.cut}].next_in", tr.next_in))

    unknown_refs: list[str] = []
    for loc, text in ref_texts:
        for mref in _REF_RE.findall(text):
            # §3.3：@char_fox / @prop_star / @scene_forest 即引用对应实体的 id。
            if mref not in all_ids:
                unknown_refs.append(f"{loc}:@{mref}")
    if unknown_refs:
        findings.append(
            ManifestFinding(
                "M4_REF_RESOLUTION", "FAIL",
                f"未知 @引用：{sorted(set(unknown_refs))}", "shots[].line / transition_table",
            )
        )
    else:
        findings.append(
            ManifestFinding("M4_REF_RESOLUTION", "OK", "@引用 全部可解析", "shots/transition_table")
        )

    # ── M2：Transition Table 覆盖每个切点（除 S1）；中间段不得 frame holds steady 收尾 ──
    n = len(m.shots)
    if n == 0:
        findings.append(ManifestFinding("M2_TRANSITION_TABLE", "FAIL", "无镜头，无法建转场表", "transition_table"))
    else:
        present = {tr.cut for tr in m.transition_table}
        expected = [_cut_key(i, i + 1) for i in range(1, n)]  # S1->S2 ... S(n-1)->S(n)
        missing_cuts = [c for c in expected if c not in present]
        if missing_cuts:
            findings.append(
                ManifestFinding(
                    "M2_TRANSITION_TABLE", "FAIL",
                    f"缺 Transition Table 切点：{missing_cuts}", "transition_table",
                )
            )
        else:
            findings.append(
                ManifestFinding("M2_TRANSITION_TABLE", "OK", f"Transition Table 覆盖全部 {len(expected)} 个切点", "transition_table")
            )
        # 中间段（非最终切点）的 prev_out 不得为 frame holds steady
        for tr in m.transition_table:
            is_final = tr.cut == _cut_key(n - 1, n)
            if not is_final and _FRAME_HOLDS_STEADY in (tr.prev_out or "").lower():
                findings.append(
                    ManifestFinding(
                        "M2_TRANSITION_TABLE", "FAIL",
                        f"中间切点 {tr.cut} 以「frame holds steady」收尾（不允许）",
                        f"transition_table[{tr.cut}].prev_out",
                    )
                )

    # ── M3：spoken_language 覆盖每个说话镜 ──
    covered = {e.shot_index for e in m.spoken_language}
    speaking = [sh.shot_index for sh in m.shots if sh.line and sh.line.strip()]
    uncovered = [s for s in speaking if s not in covered]
    if uncovered:
        findings.append(
            ManifestFinding(
                "M3_SPOKEN_LANGUAGE", "FAIL",
                f"说话镜缺口语语言条目：{uncovered}", "spoken_language",
            )
        )
    else:
        findings.append(
            ManifestFinding("M3_SPOKEN_LANGUAGE", "OK", "口语语言覆盖全部说话镜", "spoken_language")
        )

    # ── M5：duration 边界 ──
    if not m.shots:
        findings.append(ManifestFinding("M5_DURATION", "FAIL", "无镜头时长可校验", "shots[].duration"))
    else:
        short = [sh.shot_index for sh in m.shots if sh.duration < 2.5]
        avg = sum(sh.duration for sh in m.shots) / len(m.shots)
        if short:
            findings.append(
                ManifestFinding(
                    "M5_DURATION", "FAIL",
                    f"镜头时长 <2.5s：{short}（最小要求 2.5s）", "shots[].duration",
                )
            )
        elif avg < 3.5:
            findings.append(
                ManifestFinding(
                    "M5_DURATION", "FAIL",
                    f"平均镜头时长 {avg:.2f}s < 3.5s", "shots[*].duration",
                )
            )
        else:
            findings.append(
                ManifestFinding("M5_DURATION", "OK", f"单镜 ≥2.5s，平均 {avg:.2f}s ≥3.5s", "shots[].duration")
            )

    # ── M6：至少存在一个固定角色（一致性基础）──
    if not m.characters:
        findings.append(
            ManifestFinding("M6_FIXED_CHARACTER", "FAIL", "缺固定 IP 角色", "characters")
        )
    else:
        findings.append(
            ManifestFinding("M6_FIXED_CHARACTER", "OK", f"固定角色 {len(m.characters)} 个", "characters")
        )

    fails = [f for f in findings if f.severity == "FAIL"]
    status = "FAIL" if fails else "OK"
    return ManifestReport(status=status, findings=findings)


# ── 双向绑定：manifest ↔ 任务 shot_states.selection_json["shot_spec"] ──
def to_task_specs(manifest: KidsConsistencyManifest) -> dict[int, ShotSpec]:
    """manifest → 任务 shot_spec 字典（shot_index → ShotSpec）。"""
    return {sh.shot_index: sh.shot_spec for sh in manifest.shots}


def attach_to_task_shot_rows(
    manifest: KidsConsistencyManifest, shot_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """把 manifest 的 shot_spec 写回任务 shot_states 行（按 shot_index 对齐）。

    返回新的 shot_rows（不原地修改入参）。复用 shot_spec.upsert_spec。
    """
    by_idx = {sh.shot_index: sh.shot_spec for sh in manifest.shots}
    out: list[dict[str, Any]] = []
    for row in shot_rows:
        new_row = dict(row)
        idx = row.get("shot_index")
        if idx in by_idx:
            new_row = _ss.upsert_spec(new_row, by_idx[idx])
        out.append(new_row)
    return out


def read_specs_from_task_shot_rows(shot_rows: list[dict[str, Any]]) -> list[ShotSpec | None]:
    """从任务 shot_states 行回读 ShotSpec 列表（双向绑定：Spec → manifest）。"""
    return [_ss.read_spec(row) for row in shot_rows]


def manifest_from_task_specs(
    *,
    project_id: str,
    episode: int,
    audience: Audience,
    theme: Theme,
    style_bible: StyleBible,
    characters: list[Character],
    props: list[Prop],
    scenes: list[Scene],
    transition_table: list[TransitionRow],
    spoken_language: list[SpokenLanguageEntry],
    specs_by_index: dict[int, ShotSpec | None],
    durations: dict[int, float] | None = None,
    lines: dict[int, str] | None = None,
) -> KidsConsistencyManifest:
    """从任务 ShotSpec 回读重建 manifest（双向绑定另一方向）。"""
    durations = durations or {}
    lines = lines or {}
    shots = [
        ShotEntry(
            shot_index=idx,
            duration=durations.get(idx, 4.0),
            line=lines.get(idx, ""),
            shot_spec=spec,
        )
        for idx, spec in sorted(specs_by_index.items())
        if spec is not None
    ]
    return KidsConsistencyManifest(
        project_id=project_id,
        episode=episode,
        audience=audience,
        theme=theme,
        style_bible=style_bible,
        characters=characters,
        props=props,
        scenes=scenes,
        transition_table=transition_table,
        spoken_language=spoken_language,
        shots=shots,
    )


# ── 确定性序列化 ────────────────────────────────────────────────────
def canonical_json(manifest: KidsConsistencyManifest) -> str:
    """确定性 JSON（sort_keys + 紧凑分隔符），用于 SHA-256 比对与落库。"""
    return json.dumps(
        manifest.model_dump(exclude_none=False),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
