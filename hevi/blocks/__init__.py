"""Block 组件目录 — 可复用视觉组件库。

对标 HyperFrames Catalog(50+ 预置 block)。

用法:
    from hevi.blocks import get_block, list_blocks

    title_html = get_block("title_card", title="第一章", subtitle="秦统一中国")
    subtitle_html = get_block("subtitle", text="讲解内容...", position="bottom")

对标: https://hyperframes.heygen.com/catalog/blocks/data-chart
"""
from __future__ import annotations

from typing import Any

__all__ = [
    "get_block",
    "list_blocks",
    "BLOCKS",
]


# 预置 block 模板
BLOCKS: dict[str, str] = {
    "title_card": """
<div class="title-card" style="
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    text-align: center;
    color: white;
    font-family: 'Noto Sans SC', sans-serif;
">
    <h1 class="title" style="
        font-size: 72px;
        font-weight: 700;
        margin-bottom: 20px;
        text-shadow: 2px 2px 8px rgba(0,0,0,0.8);
    ">{title}</h1>
    <p class="subtitle" style="
        font-size: 36px;
        font-weight: 400;
        opacity: 0.85;
        text-shadow: 1px 1px 4px rgba(0,0,0,0.6);
    ">{subtitle}</p>
</div>
""",

    "subtitle": """
<div class="subtitle" style="
    position: absolute;
    {position_style}
    padding: 16px 32px;
    background: rgba(0, 0, 0, 0.75);
    color: white;
    font-size: 32px;
    font-family: 'Noto Sans SC', sans-serif;
    border-radius: 8px;
    max-width: 80%;
    text-align: center;
">{text}</div>
""",

    "data_chart": """
<div class="data-chart" style="
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: 80%;
    height: 70%;
    background: rgba(0, 0, 0, 0.9);
    border-radius: 12px;
    padding: 32px;
    color: white;
    font-family: 'Noto Sans SC', sans-serif;
">
    <h2 class="chart-title" style="font-size: 36px; margin-bottom: 24px;">{title}</h2>
    <div class="chart-content" style="
        display: flex;
        align-items: flex-end;
        justify-content: space-around;
        height: calc(100% - 80px);
    ">
        {bars_html}
    </div>
</div>
""",

    "lower_third": """
<div class="lower-third" style="
    position: absolute;
    bottom: 60px;
    left: 60px;
    background: linear-gradient(90deg, rgba(0,0,0,0.9) 0%, rgba(0,0,0,0.7) 100%);
    padding: 16px 32px;
    border-left: 4px solid {accent_color};
    color: white;
    font-family: 'Noto Sans SC', sans-serif;
">
    <div class="name" style="font-size: 28px; font-weight: 700;">{name}</div>
    <div class="title" style="font-size: 20px; opacity: 0.85;">{title}</div>
</div>
""",

    "kinetic_text": """
<div class="kinetic-text" style="
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    text-align: center;
    color: white;
    font-family: 'Noto Sans SC', sans-serif;
">
    <h1 class="text" style="
        font-size: 96px;
        font-weight: 900;
        text-shadow: 4px 4px 12px rgba(0,0,0,0.9);
        letter-spacing: 4px;
    ">{text}</h1>
</div>
""",

    "quote": """
<div class="quote" style="
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: 70%;
    text-align: center;
    color: white;
    font-family: 'Noto Sans SC', sans-serif;
">
    <div class="quote-mark" style="font-size: 120px; opacity: 0.3; line-height: 0.5;">"</div>
    <p class="quote-text" style="
        font-size: 36px;
        font-style: italic;
        line-height: 1.6;
        margin: 20px 0;
    ">{text}</p>
    <div class="quote-author" style="
        font-size: 24px;
        opacity: 0.7;
        margin-top: 24px;
    ">— {author}</div>
</div>
""",
}


def get_block(block_name: str, **kwargs: Any) -> str:
    """获取 block HTML。

    Args:
        block_name: block 名称(title_card/subtitle/data_chart/lower_third/kinetic_text/quote)
        **kwargs: 模板变量(title/subtitle/text/name/author/accent_color 等)

    Returns:
        HTML 字符串
    """
    if block_name not in BLOCKS:
        raise ValueError(f"Unknown block: {block_name}. Available: {list(BLOCKS.keys())}")

    template = BLOCKS[block_name]

    # 特殊处理
    if block_name == "subtitle":
        position = kwargs.get("position", "bottom")
        position_styles = {
            "top": "top: 60px; left: 50%; transform: translateX(-50%);",
            "bottom": "bottom: 60px; left: 50%; transform: translateX(-50%);",
            "center": "top: 50%; left: 50%; transform: translate(-50%, -50%);",
        }
        kwargs["position_style"] = position_styles.get(position, position_styles["bottom"])

    elif block_name == "data_chart":
        data = kwargs.get("data", [])
        bars = []
        max_val = max(data, key=lambda x: x.get("value", 0), default={"value": 1})["value"] or 1
        for item in data:
            label = item.get("label", "")
            value = item.get("value", 0)
            height_pct = (value / max_val) * 100
            color = item.get("color", "#4F46E5")
            bars.append(f"""
                <div class="bar" style="
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    flex: 1;
                ">
                    <div class="bar-value" style="font-size: 24px; margin-bottom: 8px;">{value}</div>
                    <div class="bar-fill" style="
                        width: 60%;
                        height: {height_pct}%;
                        background: {color};
                        border-radius: 4px 4px 0 0;
                    "></div>
                    <div class="bar-label" style="font-size: 18px; margin-top: 12px; opacity: 0.8;">{label}</div>
                </div>
            """)
        kwargs["bars_html"] = "\n".join(bars)

    # 填充模板
    return template.format(**kwargs)


def list_blocks() -> list[str]:
    """列出所有可用 block。"""
    return list(BLOCKS.keys())
