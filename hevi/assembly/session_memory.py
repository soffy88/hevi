"""会话记忆 / project.md 持久化（对标 video-use project.md 模式）。

在多次对话/agent 轮次间保持：
  - 剪辑策略（strategy）
  - 已做决策记录（decisions）
  - 推理过程（reasoning）
  - 待解决问题（outstanding）
  - 关键约束（constraints）

持久化为 Markdown（project.md），人类可读、可编辑、可 git 追踪。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── 数据模型 ──────────────────────────────────────────────────────────


@dataclass
class Decision:
    """一条剪辑决策。"""

    what: str  # 做了什么
    why: str  # 为什么
    when: str = ""  # ISO timestamp
    source: str = ""  # 决策来源（agent/user/auto）

    def __post_init__(self):
        if not self.when:
            self.when = datetime.now(tz=None).isoformat(timespec="seconds")


@dataclass
class OutstandingItem:
    """待解决问题。"""

    description: str
    priority: str = "medium"  # high | medium | low
    blocker: bool = False


@dataclass
class SessionMemory:
    """完整的会话记忆。"""

    strategy: str = ""
    decisions: list[Decision] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)
    outstanding: list[OutstandingItem] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)

    def add_decision(self, what: str, why: str, source: str = "auto") -> Decision:
        d = Decision(what=what, why=why, source=source)
        self.decisions.append(d)
        return d

    def add_reasoning(self, text: str) -> None:
        self.reasoning.append(text)

    def add_outstanding(
        self, description: str, priority: str = "medium", blocker: bool = False
    ) -> None:
        self.outstanding.append(OutstandingItem(description, priority, blocker))

    def resolve_outstanding(self, description: str) -> bool:
        """标记一个 outstanding 为已解决（移除）。"""
        before = len(self.outstanding)
        self.outstanding = [
            o for o in self.outstanding if o.description != description
        ]
        return len(self.outstanding) < before

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "decisions": [
                {"what": d.what, "why": d.why, "when": d.when, "source": d.source}
                for d in self.decisions
            ],
            "reasoning": list(self.reasoning),
            "outstanding": [
                {
                    "description": o.description,
                    "priority": o.priority,
                    "blocker": o.blocker,
                }
                for o in self.outstanding
            ],
            "constraints": list(self.constraints),
            "metadata": dict(self.metadata),
        }


# ── Markdown 持久化 ──────────────────────────────────────────────────


def save_project_md(memory: SessionMemory, path: Path) -> None:
    """将 SessionMemory 写入 project.md（人类可读格式）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    lines.append("# Project Memory")
    lines.append("")

    # Metadata
    if memory.metadata:
        lines.append("## Metadata")
        for k, v in memory.metadata.items():
            lines.append(f"- **{k}**: {v}")
        lines.append("")

    # Strategy
    if memory.strategy:
        lines.append("## Strategy")
        lines.append("")
        lines.append(memory.strategy)
        lines.append("")

    # Constraints
    if memory.constraints:
        lines.append("## Constraints")
        for c in memory.constraints:
            lines.append(f"- {c}")
        lines.append("")

    # Decisions
    if memory.decisions:
        lines.append("## Decisions")
        for d in memory.decisions:
            lines.append(f"- **[{d.when}]** {d.what} — _{d.why}_ (source: {d.source})")
        lines.append("")

    # Reasoning
    if memory.reasoning:
        lines.append("## Reasoning")
        for r in memory.reasoning:
            lines.append(f"- {r}")
        lines.append("")

    # Outstanding
    if memory.outstanding:
        lines.append("## Outstanding")
        for o in memory.outstanding:
            blocker_tag = " 🚧 BLOCKER" if o.blocker else ""
            lines.append(f"- [{o.priority}]{blocker_tag} {o.description}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("saved project.md → %s", path)


def load_project_md(path: Path) -> SessionMemory:
    """从 project.md 解析 SessionMemory。

    简化解析：基于行前缀和 section header。
    用于 agent 重启时恢复上下文。
    """
    memory = SessionMemory()

    if not path.exists():
        return memory

    text = path.read_text(encoding="utf-8")
    current_section = ""

    for line in text.splitlines():
        stripped = line.strip()

        # Section headers
        if stripped.startswith("## "):
            current_section = stripped[3:].strip().lower()
            continue

        if not stripped or stripped.startswith("# "):
            continue

        if current_section == "metadata":
            if stripped.startswith("- **") and "**:" in stripped:
                # - **key**: value
                inner = stripped[4:]  # after "- **"
                key, _, val = inner.partition("**:")
                memory.metadata[key.strip()] = val.strip()

        elif current_section == "strategy":
            if memory.strategy:
                memory.strategy += "\n" + stripped
            else:
                memory.strategy = stripped

        elif current_section == "constraints":
            if stripped.startswith("- "):
                memory.constraints.append(stripped[2:])

        elif current_section == "decisions":
            if stripped.startswith("- **["):
                # - **[when]** what — _why_ (source: xxx)
                inner = stripped[5:]  # after "- **["
                when, _, rest = inner.partition("]**")
                rest = rest.strip()
                what_part = rest
                why_part = ""
                source = "auto"
                if " — _" in rest:
                    what_part, _, tail = rest.partition(" — _")
                    if "_ (source:" in tail:
                        why_part, _, src_tail = tail.partition("_ (source:")
                        source = src_tail.rstrip(")").strip()
                    else:
                        why_part = tail.rstrip("_")
                memory.decisions.append(Decision(
                    what=what_part.strip(),
                    why=why_part.strip(),
                    when=when.strip(),
                    source=source,
                ))

        elif current_section == "reasoning":
            if stripped.startswith("- "):
                memory.reasoning.append(stripped[2:])

        elif current_section == "outstanding":
            if stripped.startswith("- ["):
                inner = stripped[3:]  # after "- ["
                priority, _, rest = inner.partition("]")
                blocker = "🚧 BLOCKER" in rest
                desc = rest.replace("🚧 BLOCKER", "").strip()
                memory.outstanding.append(OutstandingItem(
                    description=desc,
                    priority=priority.strip(),
                    blocker=blocker,
                ))

    return memory


def load_or_create(edit_dir: Path) -> SessionMemory:
    """加载或创建 edit_dir/project.md。"""
    md_path = edit_dir / "project.md"
    return load_project_md(md_path)


def save(memory: SessionMemory, edit_dir: Path) -> None:
    """保存 SessionMemory 到 edit_dir/project.md。"""
    save_project_md(memory, edit_dir / "project.md")
