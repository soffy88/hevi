"""KidsConsistencyManifest — 幼儿故事一致性清单 (RENOISE_EVAL §3.3 + 单元 K1/R2).

- schema 字段按 §3.3：schema_version / project_id / episode / audience /
  theme / style_bible / characters / props / scenes / transition_table /
  spoken_language / shots[].shot_spec。
- 绑定与校验规则：
  M0  shots[].shot_spec 每个字段**委派**给 hevi.production.shot_spec.ShotSpec
      （未知 template/transition_in/sfx/style → 由 ShotSpec 校验器直接失败）。
      manifest 层拒绝 shot_spec 未知字段（如 tempalte 拼写错误）。
  M1  style_bible 四段齐全。
  M2  transition_table 覆盖按排序真实 shot_index 生成的每个切点；中间段不得“frame holds steady”收尾。
  M3  spoken_language 覆盖每个说话镜且语言与 audience 匹配；未知 shot_index 失败。
  M4  @引用 必须能在 manifest 内解析（扫描所有字符串字段）。
  M5  duration ≥2.5s，整片平均 ≥3.5s；且 shot_spec.duration 须与 shot.duration 一致（容差 0.05s）。
  M6  固定角色 anchor_ref/seed/voice_ref 必须锁定。
  M7  shot_index 唯一且连续/有序。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from hevi.production import shot_spec as _ss
from hevi.production.shot_spec import ShotSpec

_SCHEMA_VERSION = "1.0"
_REF_RE = re.compile(r"@([A-Za-z0-9_]+)")
_FRAME_HOLDS_STEADY = "frame holds steady"


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
    palette: list[str] = Field(default_factory=list, exclude=True)


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
    cut: str  # e.g. "S1->S2"
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
    shot_spec: ShotSpec

    @model_validator(mode="before")
    @classmethod
    def _check_shot_spec_extra_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            spec = data.get("shot_spec")
            if isinstance(spec, dict):
                allowed_fields = ShotSpec.model_fields.keys()
                unknown = [k for k in spec if k not in allowed_fields]
                if unknown:
                    raise ValueError(f"ShotSpec 存在未知字段: {unknown}")
        return data


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


def _recursive_find_refs(obj: Any, path: str = "") -> list[tuple[str, str]]:
    """递归扫描任意嵌套结构中的字符串字段。"""
    out: list[tuple[str, str]] = []
    if isinstance(obj, str):
        out.append((path, obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            sub_path = f"{path}.{k}" if path else k
            out.extend(_recursive_find_refs(v, sub_path))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            sub_path = f"{path}[{idx}]"
            out.extend(_recursive_find_refs(item, sub_path))
    return out


class ShotIndexMismatchError(ValueError):
    """任务行镜号与 manifest 不匹配。"""
    pass


def validate_manifest(
    manifest: KidsConsistencyManifest | dict[str, Any],
) -> ManifestReport:
    findings: list[ManifestFinding] = []
    errors: list[str] = []

    if isinstance(manifest, dict):
        try:
            manifest = KidsConsistencyManifest.model_validate(manifest)
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(p) for p in err.get("loc", []))
                # 检查是否为 shot_spec 相关错误
                is_shotspec = "shot_spec" in loc
                rule = "M0_SHOTSPEC_DELEGATION" if is_shotspec else "M_SCHEMA"
                findings.append(
                    ManifestFinding(
                        rule, "FAIL",
                        f"清单校验失败：{err.get('msg', '')}", loc,
                    )
                )
                errors.append(f"{rule}:{loc}")
            return ManifestReport(status="FAIL", findings=findings, errors=errors)

    m: KidsConsistencyManifest = manifest

    # M1：Style Bible 四段齐全
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
        findings.append(ManifestFinding("M1_STYLE_BIBLE", "FAIL", f"Style Bible 缺段：{sb_missing}", "style_bible"))
        errors.append("M1_STYLE_BIBLE:style_bible")
    else:
        findings.append(ManifestFinding("M1_STYLE_BIBLE", "OK", "Style Bible 四段齐全", "style_bible"))

    # M4：@引用 扫描全部字符串字段
    all_ids = {c.id for c in m.characters}
    all_ids |= {p.id for p in m.props}
    all_ids |= {s.id for s in m.scenes}

    dump_data = m.model_dump()
    all_strings = _recursive_find_refs(dump_data)
    unknown_refs: list[str] = []
    for path, text in all_strings:
        # 跳过 anchor_ref / environment_only_ref 等文件路径中的 @ 误判
        if any(w in path for w in ["anchor_ref", "environment_only_ref", "voice_ref"]):
            continue
        for mref in _REF_RE.findall(text):
            if mref not in all_ids:
                unknown_refs.append(f"{path}:@{mref}")

    if unknown_refs:
        findings.append(ManifestFinding("M4_REF_RESOLUTION", "FAIL", f"未知 @引用：{sorted(set(unknown_refs))}", "manifest.fields"))
        errors.append("M4_REF_RESOLUTION:manifest.fields")
    else:
        findings.append(ManifestFinding("M4_REF_RESOLUTION", "OK", "@引用 全部可解析", "manifest.fields"))

    # M2 / M7：Shot Index 唯一与 Transition Table 覆盖切点
    shot_indices = [sh.shot_index for sh in m.shots]
    if len(shot_indices) != len(set(shot_indices)):
        findings.append(ManifestFinding("M7_SHOT_INDEX", "FAIL", f"shot_index 存在重复：{shot_indices}", "shots[].shot_index"))
        errors.append("M7_SHOT_INDEX:shots[].shot_index")
    
    sorted_indices = sorted(shot_indices)
    n = len(sorted_indices)
    if n >= 2:
        expected_cuts = [_cut_key(sorted_indices[i], sorted_indices[i + 1]) for i in range(n - 1)]
        present_cuts = {tr.cut for tr in m.transition_table}
        missing_cuts = [c for c in expected_cuts if c not in present_cuts]
        if missing_cuts:
            findings.append(ManifestFinding("M2_TRANSITION_TABLE", "FAIL", f"缺 Transition Table 切点：{missing_cuts}", "transition_table"))
            errors.append("M2_TRANSITION_TABLE:transition_table")
        else:
            findings.append(ManifestFinding("M2_TRANSITION_TABLE", "OK", "Transition Table 完整覆盖所有切点", "transition_table"))

        # 中间段不得以 frame holds steady 收尾
        for tr in m.transition_table:
            is_final = tr.cut == expected_cuts[-1] if expected_cuts else False
            if not is_final and _FRAME_HOLDS_STEADY in (tr.prev_out or "").lower():
                findings.append(ManifestFinding("M2_TRANSITION_TABLE", "FAIL", f"中间切点 {tr.cut} 以 frame holds steady 收尾", f"transition_table[{tr.cut}].prev_out"))
                errors.append(f"M2_TRANSITION_TABLE:transition_table[{tr.cut}]")

    # M3：spoken_language 校验
    aud_lang = m.audience.spoken_language
    valid_shot_idxs = set(shot_indices)
    spoken_map = {e.shot_index: e.language for e in m.spoken_language}
    lang_errors: list[str] = []
    for entry in m.spoken_language:
        if entry.shot_index not in valid_shot_idxs:
            lang_errors.append(f"未知镜号 {entry.shot_index}")
        elif entry.language != aud_lang:
            lang_errors.append(f"镜 {entry.shot_index} 语言 {entry.language} 与 audience {aud_lang} 不符")

    speaking_shots = [sh.shot_index for sh in m.shots if sh.line and sh.line.strip()]
    missing_spoken = [s for s in speaking_shots if s not in spoken_map]
    if missing_spoken:
        lang_errors.append(f"说话镜缺口语语言条目：{missing_spoken}")

    if lang_errors:
        findings.append(ManifestFinding("M3_SPOKEN_LANGUAGE", "FAIL", f"Spoken Language 校验失败：{lang_errors}", "spoken_language"))
        errors.append("M3_SPOKEN_LANGUAGE:spoken_language")
    else:
        findings.append(ManifestFinding("M3_SPOKEN_LANGUAGE", "OK", "Spoken Language 校验通过", "spoken_language"))

    # M5：duration 边界与绑定一致性
    if not m.shots:
        findings.append(ManifestFinding("M5_DURATION", "FAIL", "无镜头", "shots"))
        errors.append("M5_DURATION:shots")
    else:
        short_shots: list[int] = []
        binding_errors: list[str] = []
        effective_durations: list[float] = []

        for sh in m.shots:
            eff = sh.duration
            if sh.shot_spec.duration is not None:
                if abs(sh.shot_spec.duration - sh.duration) > 0.05:
                    binding_errors.append(f"镜 {sh.shot_index} duration={sh.duration} 与 shot_spec.duration={sh.shot_spec.duration} 不一致")
                eff = sh.shot_spec.duration
            effective_durations.append(eff)
            if eff < 2.5:
                short_shots.append(sh.shot_index)

        avg_dur = sum(effective_durations) / len(effective_durations) if effective_durations else 0.0

        if binding_errors:
            findings.append(ManifestFinding("M5_DURATION_BINDING", "FAIL", f"时长绑定不一致：{binding_errors}", "shots[].shot_spec.duration"))
            errors.append("M5_DURATION_BINDING:shots[].shot_spec.duration")

        if short_shots:
            findings.append(ManifestFinding("M5_DURATION", "FAIL", f"镜头时长 <2.5s：{short_shots}", "shots[].duration"))
            errors.append("M5_DURATION:shots[].duration")
        elif avg_dur < 3.5:
            findings.append(ManifestFinding("M5_DURATION", "FAIL", f"平均镜头时长 {avg_dur:.2f}s < 3.5s", "shots[*].duration"))
            errors.append("M5_DURATION:shots[*].duration")
        else:
            findings.append(ManifestFinding("M5_DURATION", "OK", f"时长合规（平均 {avg_dur:.2f}s）", "shots[].duration"))

    # M6：固定角色 anchor_ref / seed / voice_ref 必须锁定
    char_errors: list[str] = []
    for i, c in enumerate(m.characters):
        missing_fields = []
        if not c.anchor_ref: missing_fields.append("anchor_ref")
        if c.seed is None: missing_fields.append("seed")
        if not c.voice_ref: missing_fields.append("voice_ref")
        if missing_fields:
            char_errors.append(f"角色 {c.id} 缺失锚点字段：{missing_fields}")
            findings.append(ManifestFinding("M6_FIXED_CHARACTER", "FAIL", f"固定角色 {c.id} 缺少锁定字段 {missing_fields}", f"characters[{i}].anchor_ref"))
            errors.append(f"M6_FIXED_CHARACTER:characters[{i}]")

    if not m.characters:
        findings.append(ManifestFinding("M6_FIXED_CHARACTER", "FAIL", "无固定 IP 角色", "characters"))
        errors.append("M6_FIXED_CHARACTER:characters")
    elif not char_errors:
        findings.append(ManifestFinding("M6_FIXED_CHARACTER", "OK", "固定角色锚点全部锁定", "characters"))

    status = "FAIL" if any(f.severity == "FAIL" for f in findings) else "OK"
    return ManifestReport(status=status, findings=findings, errors=errors)


def to_task_specs(manifest: KidsConsistencyManifest) -> dict[int, ShotSpec]:
    return {sh.shot_index: sh.shot_spec for sh in manifest.shots}


def attach_to_task_shot_rows(
    manifest: KidsConsistencyManifest, shot_rows: list[dict[str, Any]], *, strict: bool = True
) -> list[dict[str, Any]]:
    by_idx = {sh.shot_index: sh.shot_spec for sh in manifest.shots}
    out: list[dict[str, Any]] = []
    row_indices = {r.get("shot_index") for r in shot_rows}
    
    if strict:
        for idx in by_idx:
            if idx not in row_indices:
                raise ShotIndexMismatchError(f"Manifest shot_index {idx} 不在任务行中")
        for row in shot_rows:
            idx = row.get("shot_index")
            if idx not in by_idx:
                raise ShotIndexMismatchError(f"任务行 shot_index {idx} 不在 manifest 中")

    for row in shot_rows:
        new_row = dict(row)
        idx = row.get("shot_index")
        if idx in by_idx:
            new_row = _ss.upsert_spec(new_row, by_idx[idx])
        out.append(new_row)
    return out


def read_specs_from_task_shot_rows(shot_rows: list[dict[str, Any]]) -> list[ShotSpec | None]:
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
    durations = durations or {}
    lines = lines or {}
    shots: list[ShotEntry] = []
    for idx, spec in sorted(specs_by_index.items()):
        if spec is None:
            continue
        dur = durations.get(idx)
        if dur is None:
            dur = spec.duration
        if dur is None:
            raise ValueError(f"Shot {idx} 缺少 duration（既无 durations 传参，其 ShotSpec.duration 也为 None）")
        shots.append(
            ShotEntry(
                shot_index=idx,
                duration=dur,
                line=lines.get(idx, ""),
                shot_spec=spec,
            )
        )
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


def canonical_json(manifest: KidsConsistencyManifest) -> str:
    return json.dumps(
        manifest.model_dump(exclude_none=False),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
