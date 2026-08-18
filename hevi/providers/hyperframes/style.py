"""Playbook → HyperFrames CSS 变量 + DESIGN.md。

读 OpenMontage playbook 同名字段,不 fork schema。缺字段走默认暗色片头盘。
"""

from __future__ import annotations

from typing import Any

_FALLBACK = {
    "--color-bg": "#0B0F1A",
    "--color-fg": "#F5F5F5",
    "--color-accent": "#F59E0B",
    "--color-primary": "#2563EB",
    "--color-muted": "#6B7280",
    "--font-heading": "Noto Sans CJK SC",
    "--font-body": "Noto Sans CJK SC",
    "--ease-primary": "cubic-bezier(0.65, 0, 0.35, 1)",
    "--duration-entrance": "0.6s",
}


def _first(raw: Any, default: str) -> str:
    if isinstance(raw, list) and raw:
        return str(raw[0])
    if isinstance(raw, str) and raw:
        return raw
    return default


def _font(typo: dict[str, Any], key: str, default: str) -> str:
    node = typo.get(key) or {}
    if isinstance(node, dict):
        return str(node.get("font") or node.get("family") or default)
    if isinstance(node, str):
        return node
    return default


def style_bridge(
    playbook: dict[str, Any] | None,
    edit_decisions: dict[str, Any] | None = None,
) -> tuple[dict[str, str], str]:
    """返回 (css_vars, design_md)。"""
    book = playbook or {}
    palette = book.get("palette") or book.get("visual_language") or {}
    if isinstance(palette, dict) and "palette" in palette:
        palette = palette.get("palette") or {}
    typo = book.get("typography") or {}
    motion = book.get("motion") or {}
    pace = str(motion.get("pace") or "moderate").lower()
    duration = {"fast": "0.4s", "slow": "0.9s"}.get(pace, "0.6s")

    css = dict(_FALLBACK)
    css["--color-bg"] = _first(palette.get("bg") or palette.get("background"), css["--color-bg"])
    css["--color-fg"] = _first(palette.get("fg") or palette.get("foreground"), css["--color-fg"])
    css["--color-accent"] = _first(palette.get("accent"), css["--color-accent"])
    css["--color-primary"] = _first(palette.get("primary"), css["--color-primary"])
    css["--font-heading"] = _font(typo, "heading", css["--font-heading"])
    css["--font-body"] = _font(typo, "body", css["--font-body"])
    css["--duration-entrance"] = duration
    if edit_decisions and edit_decisions.get("accent"):
        css["--color-accent"] = str(edit_decisions["accent"])

    name = str(book.get("name") or book.get("id") or "hevi-default")
    design = (
        f"# DESIGN\n\nplaybook: `{name}`\n\n"
        f"- bg `{css['--color-bg']}` / fg `{css['--color-fg']}`\n"
        f"- accent `{css['--color-accent']}`\n"
        f"- heading `{css['--font-heading']}`\n"
        f"- motion pace `{pace}` ({duration})\n"
    )
    return css, design
