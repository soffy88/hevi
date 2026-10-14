"""发布前套件契约（oprim 层：纯数据、无 IO、无第三方调用）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


class PublishError(RuntimeError):
    """发布套件的可预期失败（缺输入、非法文稿、gate 未过）。"""


class ScriptError(PublishError):
    """文稿缺失或格式不支持——不允许用视频/二进制冒充文稿。"""


@dataclass(frozen=True)
class PlatformSpec:
    """一个平台的文案规格（上游 八平台发布文案-模板.md）。"""

    id: str
    label: str
    title_limit: int
    topics_separator: str
    has_pinned_comment: bool = True
    has_chapters: bool = False
    brand_in_title: bool = True


PLATFORMS: tuple[PlatformSpec, ...] = (
    PlatformSpec("douyin", "抖音", 30, " "),
    PlatformSpec("kuaishou", "快手", 30, " "),
    PlatformSpec("bilibili", "B站", 40, " ", has_chapters=True),
    PlatformSpec("wechat_channels", "视频号", 30, " "),
    PlatformSpec("xiaohongshu", "小红书", 20, " ", brand_in_title=False),
    PlatformSpec("youtube", "YouTube", 40, ",", has_chapters=True),
    PlatformSpec("zhihu", "知乎", 40, "、", has_pinned_comment=False),
    PlatformSpec("wechat_mp", "公众号", 64, " "),
)

PLATFORMS_BY_ID = {p.id: p for p in PLATFORMS}


@dataclass(frozen=True)
class ScriptLine:
    """旁白的一句：文本 + 成片里的实际时间点（未知时为 None）。"""

    index: int
    text: str
    start_s: float | None = None
    end_s: float | None = None

    @property
    def char_len(self) -> int:
        return len(re.sub(r"\s+", "", self.text))


@dataclass(frozen=True)
class ScriptDoc:
    """成片对应的文稿：逐句旁白 + 章节 + 品牌（全部取自输入）。"""

    path: str
    topic: str
    lines: tuple[ScriptLine, ...]
    chapters: tuple[tuple[str, float], ...] = ()
    brand: str = ""
    account: str = ""
    source_kind: str = ""

    @property
    def full_text(self) -> str:
        return "".join(line.text for line in self.lines)

    @property
    def timed(self) -> bool:
        return all(line.start_s is not None for line in self.lines) and bool(self.lines)


@dataclass(frozen=True)
class FactClaim:
    """一个需要出处的事实点（数字/日期/引语/断言）。"""

    kind: str
    text: str
    line_index: int
    supported_by: str
    sourced: bool = False
    note: str = ""


@dataclass(frozen=True)
class PlatformCopy:
    """一个平台的成套文案。"""

    platform: str
    label: str
    title: str
    alt_title: str
    body: str
    topics: tuple[str, ...]
    pinned_comment: str
    chapters: tuple[tuple[str, float], ...] = ()
    summary: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "label": self.label,
            "title": self.title,
            "alt_title": self.alt_title,
            "title_len": len(self.title),
            "alt_title_len": len(self.alt_title),
            "body": self.body,
            "topics": list(self.topics),
            "pinned_comment": self.pinned_comment,
            "chapters": [{"time": timecode(t), "title": name} for name, t in self.chapters],
            "summary": self.summary,
        }


@dataclass(frozen=True)
class PublishGate:
    """发布前的一条硬 gate（全部实测，不接受占位值）。"""

    name: str
    passed: bool
    value: Any
    threshold: str

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "value": self.value, "threshold": self.threshold}


@dataclass(frozen=True)
class ComplianceFinding:
    rule: str
    passed: bool
    hits: tuple[str, ...] = ()
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"rule": self.rule, "passed": self.passed, "hits": list(self.hits), "detail": self.detail}


@dataclass
class PublishBundleResult:
    """整套发布产物的落盘位置与 gate 汇总。"""

    output_dir: str
    cover_paths: dict[str, str] = field(default_factory=dict)
    copy_json_path: str = ""
    copy_md_path: str = ""
    qa_report_path: str = ""
    fact_sources_path: str = ""
    cover_qa_path: str = ""
    compliance_path: str = ""
    gates: tuple[PublishGate, ...] = ()
    llm_degraded: bool = True
    llm_reason: str = ""

    @property
    def passed(self) -> bool:
        return all(g.passed for g in self.gates)

    def as_dict(self) -> dict[str, Any]:
        return {
            "output_dir": self.output_dir,
            "cover_paths": self.cover_paths,
            "copy_json_path": self.copy_json_path,
            "copy_md_path": self.copy_md_path,
            "qa_report_path": self.qa_report_path,
            "fact_sources_path": self.fact_sources_path,
            "cover_qa_path": self.cover_qa_path,
            "compliance_path": self.compliance_path,
            "gates": [g.as_dict() for g in self.gates],
            "passed": self.passed,
            "llm_degraded": self.llm_degraded,
            "llm_reason": self.llm_reason,
        }


def timecode(seconds: float) -> str:
    """秒 → MM:SS（章节用；与成片实际时间戳一致）。"""

    total = max(round(seconds), 0)
    return f"{total // 60:02d}:{total % 60:02d}"