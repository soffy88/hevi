"""Rule Card Loader and Prompt Pack Generator.

Loads motion rule cards from YAML definitions and renders them into Chinese
prompt sections for LLM storyboard generation and animation code synthesis.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence
import yaml

DEFAULT_RULES_DIR = Path(__file__).resolve().parent / "rules"


@dataclass
class RuleCard:
    id: str
    title: str
    category: str
    trigger: list[str]
    counter_example: str
    correct_approach: str
    source_case_id: str
    source_author: str
    prompt_summary: str

    @classmethod
    def from_dict(cls, data: dict) -> RuleCard:
        triggers = data.get("trigger", [])
        if isinstance(triggers, str):
            triggers = [triggers]
        return cls(
            id=str(data.get("id", "")),
            title=str(data.get("title", "")),
            category=str(data.get("category", "")),
            trigger=list(triggers),
            counter_example=str(data.get("counter_example", "")).strip(),
            correct_approach=str(data.get("correct_approach", "")).strip(),
            source_case_id=str(data.get("source_case_id", "")),
            source_author=str(data.get("source_author", "")),
            prompt_summary=str(data.get("prompt_summary", "")).strip(),
        )


def load_rule_cards(rules_dir: Path | None = None) -> list[RuleCard]:
    """Load and parse all rule card YAML files from directory."""
    target_dir = Path(rules_dir) if rules_dir is not None else DEFAULT_RULES_DIR
    if not target_dir.exists() or not target_dir.is_dir():
        raise FileNotFoundError(f"Rules directory not found: {target_dir}")

    cards: list[RuleCard] = []
    yaml_files = sorted(target_dir.glob("*.yaml")) + sorted(target_dir.glob("*.yml"))
    for yf in yaml_files:
        try:
            with open(yf, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict) and "id" in data:
                    cards.append(RuleCard.from_dict(data))
        except Exception as e:
            raise RuntimeError(f"Error parsing rule card file {yf}: {e}") from e
    return cards


def render_prompt_pack(
    rule_ids: Sequence[str] | None = None,
    rules_dir: Path | None = None,
    mode: str = "detailed",
) -> str:
    """Render rule cards into a formatted Chinese prompt section.

    Modes:
    - detailed: Full breakdown with principles, counter-examples, and source attribution.
    - compact: Numbered bullet points using concise prompt summaries.
    - system_prompt: Structured XML block ready for LLM system prompt injection.
    """
    all_cards = load_rule_cards(rules_dir)
    if rule_ids:
        selected_ids = set(rule_ids)
        cards = [c for c in all_cards if c.id in selected_ids]
    else:
        cards = all_cards

    if not cards:
        return ""

    if mode == "compact":
        lines = ["【Hevi 动效工程核心准则】"]
        for idx, c in enumerate(cards, start=1):
            lines.append(f"{idx}. {c.prompt_summary}")
        return "\n".join(lines)

    if mode == "system_prompt":
        lines = [
            "<motion_design_rules>",
            "以下为视频动效生成的硬性规范，模型必须严格遵守，违者将在静态校验和视觉质检中被直接拦截：",
        ]
        for idx, c in enumerate(cards, start=1):
            lines.append(f"\n[{idx}] {c.title} (ID: {c.id})")
            lines.append(f"- 核心规范：{c.correct_approach}")
            lines.append(f"- 禁止做法：{c.counter_example}")
            lines.append(f"- 提示词要点：{c.prompt_summary}")
        lines.append("</motion_design_rules>")
        return "\n".join(lines)

    # Default: detailed markdown
    sections = [
        "# Hevi 动效设计与工程规则库 (Motion Design Rules)",
        "本规则库提炼自行业高标案例，所有代码生成与分镜设计须严格遵守以下原则：\n",
    ]
    for idx, c in enumerate(cards, start=1):
        sections.append(f"## {idx}. {c.title} (`{c.id}`)")
        sections.append(f"- **分类**：{c.category}")
        sections.append(f"- **触发条件**：{', '.join(c.trigger)}")
        sections.append(f"- **正确做法**：{c.correct_approach}")
        sections.append(f"- **错误反例**：{c.counter_example}")
        sections.append(f"- **规则总结**：{c.prompt_summary}")
        sections.append(f"- **来源案例**：Case {c.source_case_id} ({c.source_author})\n")

    return "\n".join(sections)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render motion rule cards for LLM prompts")
    parser.add_argument("--mode", choices=["detailed", "compact", "system_prompt"], default="detailed")
    parser.add_argument("--rules", help="Comma-separated rule IDs to filter")
    parser.add_argument("--output", help="Output file path (default stdout)")
    args = parser.parse_args()

    rule_ids = [r.strip() for r in args.rules.split(",") if r.strip()] if args.rules else None
    rendered = render_prompt_pack(rule_ids=rule_ids, mode=args.mode)

    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
        print(f"Rendered {len(rule_ids) if rule_ids else 'all'} rules to {args.output}")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
