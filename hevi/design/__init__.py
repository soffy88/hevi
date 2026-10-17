"""Frame.md 设计系统 — 品牌视觉规范 token 化。

对标 HyperFrames frame.md。

核心:把品牌 design.md 翻译为视频适配层(字体/色彩/间距/缩放规则)。
可量化的品牌视觉规范,不再靠 LLM 每次猜。

用法:
    from hevi.design import DesignSystem, load_design

    # 加载设计系统
    ds = load_design(Path("hevi/designs/default.yaml"))

    # 使用 token
    title_size = ds.get("typography.title.size")  # 72
    brand_primary = ds.get("colors.primary")       # "#4F46E5"
    spacing_lg = ds.get("spacing.lg")              # 32

    # 内联到 HTML
    html = f'<h1 style="font-size: {title_size}px; color: {brand_primary};">标题</h1>'

对标: HyperFrames frame.md
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = [
    "DesignSystem",
    "load_design",
    "DEFAULT_DESIGN",
]


# 默认设计系统(对应 Hevi 通鉴/短剧风格)
DEFAULT_DESIGN: dict[str, Any] = {
    "typography": {
        "font_family": "'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', sans-serif",
        "title": {
            "size": 72,
            "weight": 700,
            "line_height": 1.2,
            "letter_spacing": 2,
        },
        "subtitle": {
            "size": 36,
            "weight": 400,
            "line_height": 1.4,
        },
        "body": {
            "size": 28,
            "weight": 400,
            "line_height": 1.6,
        },
        "caption": {
            "size": 20,
            "weight": 400,
            "line_height": 1.4,
        },
    },
    "colors": {
        "primary": "#4F46E5",      # Indigo 600
        "secondary": "#7C3AED",    # Violet 600
        "accent": "#EC4899",       # Pink 500
        "success": "#10B981",      # Emerald 500
        "warning": "#F59E0B",      # Amber 500
        "error": "#EF4444",        # Red 500
        "text_primary": "#FFFFFF",
        "text_secondary": "#E5E7EB",
        "background": "#000000",
        "overlay": "rgba(0, 0, 0, 0.75)",
    },
    "spacing": {
        "xs": 8,
        "sm": 16,
        "md": 24,
        "lg": 32,
        "xl": 48,
        "xxl": 64,
    },
    "border": {
        "radius_sm": 4,
        "radius_md": 8,
        "radius_lg": 12,
        "radius_xl": 16,
        "width": 2,
    },
    "shadow": {
        "sm": "2px 2px 4px rgba(0,0,0,0.3)",
        "md": "4px 4px 8px rgba(0,0,0,0.4)",
        "lg": "8px 8px 16px rgba(0,0,0,0.5)",
    },
    "animation": {
        "duration_fast": 0.3,
        "duration_normal": 0.5,
        "duration_slow": 1.0,
        "ease_default": "power2.out",
        "ease_in": "power2.in",
        "ease_out": "power2.out",
    },
    "layout": {
        "safe_margin": 60,       # 安全边距(px)
        "title_position": "center",
        "subtitle_position": "bottom",
        "lower_third_position": "bottom_left",
    },
}


class DesignSystem:
    """设计系统。"""

    def __init__(self, tokens: dict[str, Any] | None = None):
        self._tokens = tokens or dict(DEFAULT_DESIGN)

    def get(self, key: str, default: Any = None) -> Any:
        """获取 token 值。

        Args:
            key: 点分隔路径(如 "typography.title.size")
            default: 默认值

        Returns:
            token 值
        """
        parts = key.split(".")
        current: Any = self._tokens
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default
        return current

    def set(self, key: str, value: Any) -> None:
        """设置 token 值。"""
        parts = key.split(".")
        current = self._tokens
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

    def to_css_variables(self) -> str:
        """导出为 CSS 变量。"""
        lines = [":root {"]
        self._flatten_to_css(self._tokens, "", lines)
        lines.append("}")
        return "\n".join(lines)

    def _flatten_to_css(self, obj: Any, prefix: str, lines: list[str]) -> None:
        """递归展开为 CSS 变量。"""
        if isinstance(obj, dict):
            for key, value in obj.items():
                new_prefix = f"{prefix}-{key}" if prefix else key
                self._flatten_to_css(value, new_prefix, lines)
        else:
            # 转换值
            css_value = self._to_css_value(obj)
            lines.append(f"  --{prefix}: {css_value};")

    def _to_css_value(self, value: Any) -> str:
        """转换为 CSS 值。"""
        if isinstance(value, (int, float)):
            # 数值加单位(px)
            if value < 10:  # 小数值可能是秒/比例
                return str(value)
            return f"{value}px"
        return str(value)

    def save(self, output_path: Path) -> None:
        """保存为 YAML/JSON。"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.suffix in (".yaml", ".yml"):
            import yaml
            output_path.write_text(
                yaml.dump(self._tokens, allow_unicode=True, default_flow_style=False),
                encoding="utf-8",
            )
        else:
            output_path.write_text(
                json.dumps(self._tokens, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    def __repr__(self) -> str:
        return f"DesignSystem(tokens={len(self._tokens)} groups)"


def load_design(path: Path) -> DesignSystem:
    """加载设计系统。

    Args:
        path: 设计文件路径(YAML/JSON)

    Returns:
        DesignSystem
    """
    if not path.exists():
        return DesignSystem()

    content = path.read_text(encoding="utf-8")

    if path.suffix in (".yaml", ".yml"):
        import yaml
        tokens = yaml.safe_load(content)
    else:
        tokens = json.loads(content)

    return DesignSystem(tokens or {})
