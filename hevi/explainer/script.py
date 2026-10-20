"""Explainer Script — 文章/资料 → 口播稿（本地分段、口语化、时长估算、编辑与版本化）。

能力: explainer.script
纯 CPU、本地规则与启发式，无付费 API 依赖。
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import Capability, CapabilityResult, register

logger = logging.getLogger(__name__)

#: 中文口语平均语速 (约 4.0 ~ 4.5 字/秒)
CHINESE_CHARS_PER_SECOND = 4.2
#: 句读停顿补偿 (秒)
PAUSE_PER_PUNCTUATION_S = 0.25

#: 书面语到口语化转换规则映射
_ORALIZATION_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"众所周知[，,]?"), "大家肯定经常听说，"),
    (re.compile(r"显而易见[，,]?"), "其实很明显，"),
    (re.compile(r"换言之[，,]?|简而言之[，,]?"), "说白了，"),
    (re.compile(r"因而[，,]?|故而[，,]?"), "所以呢，"),
    (re.compile(r"例如[，,]?|譬如[，,]?"), "比方说，"),
    (re.compile(r"然而[，,]?"), "不过，"),
    (re.compile(r"毋庸置疑[，,]?"), "毫无疑问，"),
    (re.compile(r"由此可见[，,]?"), "这么一来就能看出，"),
    (re.compile(r"综上所述[，,]?|总而言之[，,]?"), "总结一下，"),
    (re.compile(r"究其原因[，,]?"), "这背后的原因是什么呢？"),
    (re.compile(r"第一[，、]"), "首先第一点，"),
    (re.compile(r"第二[，、]"), "接下来第二点，"),
    (re.compile(r"第三[，、]"), "再看第三点，"),
]

#: 角色段落定义
SECTION_ROLES = ("hook", "concept", "breakdown", "mechanism", "summary")


@dataclass
class ScriptSection:
    section_id: str
    role: str
    original_text: str
    oral_text: str
    key_terms: list[str] = field(default_factory=list)
    visual_intent: str = "presenter_full"
    char_count: int = 0
    estimated_duration_s: float = 0.0

    def compute_stats(self) -> None:
        clean = re.sub(r"\s+", "", self.oral_text)
        self.char_count = len(clean)
        punc_count = len(re.findall(r"[，。！？；：、,!?]", self.oral_text))
        base_dur = self.char_count / CHINESE_CHARS_PER_SECOND if self.char_count > 0 else 0.0
        self.estimated_duration_s = round(base_dur + punc_count * PAUSE_PER_PUNCTUATION_S, 2)


@dataclass
class OralScript:
    script_id: str
    title: str
    source_article: str
    sections: list[ScriptSection] = field(default_factory=list)
    revision: int = 1
    version_id: str = ""
    parent_version_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    total_chars: int = 0
    total_estimated_duration_s: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.version_id:
            self.version_id = f"v{self.revision}_{_content_hash(self.source_article)[:8]}"
        self.recompute_totals()

    def recompute_totals(self) -> None:
        total_c = 0
        total_d = 0.0
        for s in self.sections:
            s.compute_stats()
            total_c += s.char_count
            total_d += s.estimated_duration_s
        self.total_chars = total_c
        self.total_estimated_duration_s = round(total_d, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "script_id": self.script_id,
            "title": self.title,
            "source_article": self.source_article,
            "revision": self.revision,
            "version_id": self.version_id,
            "parent_version_id": self.parent_version_id,
            "created_at": self.created_at,
            "total_chars": self.total_chars,
            "total_estimated_duration_s": self.total_estimated_duration_s,
            "metadata": self.metadata,
            "sections": [asdict(s) for s in self.sections],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OralScript:
        sections = [
            ScriptSection(
                section_id=s["section_id"],
                role=s["role"],
                original_text=s.get("original_text", ""),
                oral_text=s.get("oral_text", ""),
                key_terms=s.get("key_terms", []),
                visual_intent=s.get("visual_intent", "presenter_full"),
                char_count=s.get("char_count", 0),
                estimated_duration_s=s.get("estimated_duration_s", 0.0),
            )
            for s in data.get("sections", [])
        ]
        obj = cls(
            script_id=data["script_id"],
            title=data.get("title", ""),
            source_article=data.get("source_article", ""),
            sections=sections,
            revision=data.get("revision", 1),
            version_id=data.get("version_id", ""),
            parent_version_id=data.get("parent_version_id"),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            metadata=data.get("metadata", {}),
        )
        return obj


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def oralize_text(raw_text: str) -> str:
    """对单段文本进行口语化润色：替换书面连接词，断开过长句子，增加口播亲和力。"""
    text = raw_text.strip()
    if not text:
        return ""
    for pat, rep in _ORALIZATION_REPLACEMENTS:
        text = pat.sub(rep, text)

    # 长句切分：超过 40 字且有逗号时适当保持韵律
    sentences = re.split(r"([。！？\n])", text)
    reconstructed: list[str] = []
    i = 0
    while i < len(sentences):
        sent = sentences[i].strip()
        delim = sentences[i + 1] if i + 1 < len(sentences) else "。"
        i += 2
        if not sent:
            continue
        if len(sent) > 40 and "，" in sent:
            subparts = sent.split("，")
            reconstructed.append("，".join(subparts) + delim)
        else:
            reconstructed.append(sent + delim)
    return "".join(reconstructed).strip()


def extract_key_terms(text: str, max_terms: int = 5) -> list[str]:
    """提取关键词供视觉规划层做高亮与图示展开。"""
    quotes = re.findall(r"[\"“《]([^\"”》]+)[\"”》]", text)
    candidates = list(dict.fromkeys(quotes))

    tech_matches = re.findall(r"([A-Za-z0-9_\-\+]{2,}|[\u4e00-\u9fa5]{2,6}(?:模型|理论|效应|算法|机制|系统|网络|原子|光子|能量|结构|细胞|基因|函数|公式|原理|现象))", text)
    for m in tech_matches:
        if m not in candidates and len(m) >= 2:
            candidates.append(m)

    if len(candidates) < max_terms:
        words = re.findall(r"[\u4e00-\u9fa5]{2,4}", text)
        freq: dict[str, int] = {}
        for w in words:
            if w not in ("我们", "大家", "可以", "这个", "那个", "因为", "所以", "如果", "但是", "其实", "比方"):
                freq[w] = freq.get(w, 0) + 1
        sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        for w, _ in sorted_words:
            if w not in candidates:
                candidates.append(w)
            if len(candidates) >= max_terms:
                break

    return candidates[:max_terms]


def create_oral_script(
    source_text: str,
    title: str = "",
    *,
    target_duration_s: float | None = None,
    script_id: str | None = None,
) -> OralScript:
    """文章/资料 → 口播稿：自动段落切分、角色分配、口语化转换、关键词提取与时长估算。"""
    clean_src = source_text.strip()
    if not clean_src:
        raise ValueError("source_text cannot be empty")

    sid = script_id or f"script_{uuid.uuid4().hex[:12]}"
    auto_title = title or clean_src.split("\n")[0][:30].strip("# ")

    raw_paras = [p.strip() for p in re.split(r"\n\s*\n|\n", clean_src) if p.strip()]
    if not raw_paras:
        raw_paras = [clean_src]

    sections: list[ScriptSection] = []
    role_sequence = ["hook", "concept", "breakdown", "mechanism", "summary"]
    visual_intents = ["presenter_full", "diagram_flow", "image_card", "diagram_flow", "presenter_full"]

    for idx, para in enumerate(raw_paras):
        role = role_sequence[idx % len(role_sequence)]
        v_intent = visual_intents[idx % len(visual_intents)]
        oral = oralize_text(para)
        key_terms = extract_key_terms(oral)
        sec = ScriptSection(
            section_id=f"sec_{idx:02d}",
            role=role,
            original_text=para,
            oral_text=oral,
            key_terms=key_terms,
            visual_intent=v_intent,
        )
        sec.compute_stats()
        sections.append(sec)

    script = OralScript(
        script_id=sid,
        title=auto_title,
        source_article=clean_src,
        sections=sections,
        revision=1,
    )

    if target_duration_s and target_duration_s > 0:
        script.metadata["target_duration_s"] = target_duration_s
        ratio = round(target_duration_s / max(script.total_estimated_duration_s, 1.0), 2)
        script.metadata["pace_factor"] = ratio

    return script


def edit_section(
    script: OralScript,
    section_index: int,
    *,
    new_oral_text: str | None = None,
    new_key_terms: list[str] | None = None,
    new_visual_intent: str | None = None,
    new_role: str | None = None,
) -> OralScript:
    """编辑口播稿特定分段并生成新版本，记录修订版本链 (Lineage)。"""
    if section_index < 0 or section_index >= len(script.sections):
        raise IndexError(f"section_index {section_index} out of range (0..{len(script.sections)-1})")

    new_sections: list[ScriptSection] = []
    for i, sec in enumerate(script.sections):
        if i == section_index:
            updated_oral = new_oral_text if new_oral_text is not None else sec.oral_text
            updated_terms = new_key_terms if new_key_terms is not None else list(sec.key_terms)
            updated_intent = new_visual_intent if new_visual_intent is not None else sec.visual_intent
            updated_role = new_role if new_role is not None else sec.role
            new_sec = ScriptSection(
                section_id=sec.section_id,
                role=updated_role,
                original_text=sec.original_text,
                oral_text=updated_oral,
                key_terms=updated_terms,
                visual_intent=updated_intent,
            )
            new_sec.compute_stats()
            new_sections.append(new_sec)
        else:
            new_sections.append(copy.deepcopy(sec))

    next_rev = script.revision + 1
    new_version_id = f"v{next_rev}_{_content_hash(''.join(s.oral_text for s in new_sections))[:8]}"

    new_script = OralScript(
        script_id=script.script_id,
        title=script.title,
        source_article=script.source_article,
        sections=new_sections,
        revision=next_rev,
        version_id=new_version_id,
        parent_version_id=script.version_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        metadata=dict(script.metadata),
    )
    new_script.metadata["modified_section_index"] = section_index
    return new_script


def compute_script_diff(old_script: OralScript, new_script: OralScript) -> dict[str, Any]:
    """对比两版口播稿，返回受影响的分段 ID 列表与改动详情（供增量重算使用）。"""
    old_map = {s.section_id: s for s in old_script.sections}
    new_map = {s.section_id: s for s in new_script.sections}

    modified_ids: list[str] = []
    added_ids: list[str] = []
    deleted_ids: list[str] = []
    unchanged_ids: list[str] = []

    for sid, nsec in new_map.items():
        if sid not in old_map:
            added_ids.append(sid)
        else:
            osec = old_map[sid]
            if (
                osec.oral_text != nsec.oral_text
                or osec.key_terms != nsec.key_terms
                or osec.visual_intent != nsec.visual_intent
            ):
                modified_ids.append(sid)
            else:
                unchanged_ids.append(sid)

    for sid in old_map:
        if sid not in new_map:
            deleted_ids.append(sid)

    affected_ids = modified_ids + added_ids + deleted_ids
    return {
        "old_version_id": old_script.version_id,
        "new_version_id": new_script.version_id,
        "affected_section_ids": affected_ids,
        "modified_ids": modified_ids,
        "added_ids": added_ids,
        "deleted_ids": deleted_ids,
        "unchanged_ids": unchanged_ids,
        "is_identical": len(affected_ids) == 0,
    }


def save_script(script: OralScript, out_dir: Path | str) -> Path:
    """持久化口播稿为标准 JSON 格式。"""
    out_path = Path(out_dir) / f"{script.script_id}_{script.version_id}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(script.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def load_script(path: Path | str) -> OralScript:
    """从 JSON 加载口播稿。"""
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    return OralScript.from_dict(data)


# ─────────────────────────────────────────────────────────────────────────────
# 统一能力注册: explainer.script
# ─────────────────────────────────────────────────────────────────────────────
def _render_explainer_script(
    params: dict[str, Any],
    out_dir: Path,
    *,
    duration: float,
    aspect: str,
    seed: int,
) -> CapabilityResult:
    """explainer.script 渲染接口。支持 create 与 edit 动作。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    action = params.get("action", "create")
    if action == "create":
        text = params.get("text", "")
        if not text:
            raise CapabilityError("explainer.script: 'text' parameter is required for 'create'")
        title = params.get("title", "")
        target_dur = float(params.get("target_duration_s") or duration or 0.0)
        script = create_oral_script(text, title=title, target_duration_s=target_dur)
    elif action == "edit":
        script_dict = params.get("script")
        if not script_dict:
            raise CapabilityError("explainer.script: 'script' is required for 'edit'")
        base_script = OralScript.from_dict(script_dict)
        sec_idx = int(params.get("section_index", 0))
        new_text = params.get("new_oral_text")
        new_terms = params.get("new_key_terms")
        new_intent = params.get("new_visual_intent")
        script = edit_section(
            base_script,
            sec_idx,
            new_oral_text=new_text,
            new_key_terms=new_terms,
            new_visual_intent=new_intent,
        )
    else:
        raise CapabilityError(f"explainer.script: unsupported action '{action}'")

    save_path = save_script(script, out_dir)
    sha = hashlib.sha256(save_path.read_bytes()).hexdigest()

    return CapabilityResult(
        png=None,
        mp4=None,
        wav=None,
        duration_s=script.total_estimated_duration_s,
        sha256=sha,
        qa={
            "action": action,
            "script_id": script.script_id,
            "version_id": script.version_id,
            "revision": script.revision,
            "total_chars": script.total_chars,
            "section_count": len(script.sections),
            "json_path": str(save_path),
            "script_dict": script.to_dict(),
        },
    )


def register_explainer_script_capability() -> Capability:
    cap = Capability(
        name="explainer.script",
        kind="line",
        aspects=["16:9", "9:16"],
        cpu_cost_hint=0.05,
        render=_render_explainer_script,
        description="文章/资料转化为口播稿，支持自动分段、口语化重构、时长估算与版本增量编辑。能力线：纯 CPU 自含链（FFmpeg/PIL，无 Node/Remotion 依赖），与 Studio explainer 线（assembly+Remotion 生产核，供 6 条 Studio 线与 API）是两条独立链；本线供能力目录按名调用与 lanshu styled explainer。",
        line="explainer",
        params_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create", "edit"]},
                "text": {"type": "string"},
                "title": {"type": "string"},
                "target_duration_s": {"type": "number"},
                "script": {"type": "object"},
                "section_index": {"type": "integer"},
                "new_oral_text": {"type": "string"},
                "new_key_terms": {"type": "array", "items": {"type": "string"}},
                "new_visual_intent": {"type": "string"},
            },
        },
    )
    register(cap)
    return cap
