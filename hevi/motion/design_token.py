"""设计 token 提取 —— 产品设计系统 → 视觉 tokens(3O 内化 Phase B)。

来源: video-shotcraft 的核心理念 2:"整支视频的视觉语言必须从产品自身生长,不能另造
一套不相干的宣传片皮肤"。做 styleframe 前先从产品/网站的设计系统、源码或
computed styles 中提取并写入设计 spec:字体家族/字号层级/行高字距/栅格间距/
圆角/色板/材质。片内所有标题、字幕、数字、字卡、转场、粒子、光效配色都必须
复用或克制扩展这套 tokens。

本模块为 hevi 暂驻(待上游 `oprim.design_token_extract`):归一化 + 校验纯函数
可测;playwright 采集部分与 page_capture 同模式(可选依赖,失败给明确错误)。
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


class DesignTokenError(Exception):
    """设计 token 提取失败。"""


@dataclass
class DesignTokens:
    """从产品提取的视觉 tokens(片内一切复用的最小集)。"""

    font_families: list[str] = field(default_factory=list)
    font_weights: list[int] = field(default_factory=list)
    font_sizes: list[float] = field(default_factory=list)
    line_heights: list[float] = field(default_factory=list)
    colors: list[str] = field(default_factory=list)  # 十六进制,去重保序
    spacing: list[float] = field(default_factory=list)
    radii: list[float] = field(default_factory=list)
    surfaces: list[str] = field(default_factory=list)  # 背景/表面/正文/强调/状态
    source: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "font_families": self.font_families,
            "font_weights": self.font_weights,
            "font_sizes": self.font_sizes,
            "line_heights": self.line_heights,
            "colors": self.colors,
            "spacing": self.spacing,
            "radii": self.radii,
            "surfaces": self.surfaces,
            "source": self.source,
        }


def _norm_color(value: str) -> str | None:
    """把 rgb()/rgba()/named 归一为小写 hex;失败返回 None。"""
    v = value.strip()
    if v.startswith("#"):
        return v.lower()
    if v.startswith("rgb"):
        inner = v[v.index("(") + 1 : v.index(")")]
        parts = [p.strip() for p in inner.split(",")][:3]
        try:
            nums = [int(p) for p in parts]
        except ValueError:
            return None
        return "#{:02x}{:02x}{:02x}".format(*nums)
    return None


def normalize_design_tokens(
    raw: dict[str, object], *, source: str = ""
) -> DesignTokens:
    """把爬取的原始计算样式归一化为 DesignTokens(去重保序,非法值丢弃)。"""
    def _floats(key: str) -> list[float]:
        vals = raw.get(key)
        if not isinstance(vals, list):
            return []
        out: list[float] = []
        for v in vals:
            try:
                f = _css_px(str(v)) if not isinstance(v, (int, float)) else float(v)
            except (TypeError, ValueError):
                continue
            if f not in out:
                out.append(f)
        return out

    def _strings(key: str) -> list[str]:
        vals = raw.get(key)
        if not isinstance(vals, list):
            return []
        out: list[str] = []
        for v in vals:
            if isinstance(v, str) and v and v not in out:
                out.append(v)
        return out

    colors: list[str] = []
    raw_colors = raw.get("colors")
    if isinstance(raw_colors, list):
        for c in raw_colors:
            if isinstance(c, str):
                norm = _norm_color(c)
                if norm and norm not in colors:
                    colors.append(norm)

    raw_weights = raw.get("font_weights")
    weights = (
        [w for w in raw_weights if isinstance(w, int)]
        if isinstance(raw_weights, list)
        else []
    )

    return DesignTokens(
        font_families=_strings("font_families"),
        font_weights=weights,
        font_sizes=_floats("font_sizes"),
        line_heights=_floats("line_heights"),
        colors=colors,
        spacing=_floats("spacing"),
        radii=_floats("radii"),
        surfaces=_strings("surfaces"),
        source=source,
    )

def validate_tokens(tokens: DesignTokens) -> list[str]:
    """校验:关键维度非空 + 色板可解析。空 = 合规。"""
    issues: list[str] = []
    if not tokens.font_families:
        issues.append("no font families")
    if not tokens.colors:
        issues.append("no colors")
    issues.extend(
        f"bad color {c!r}"
        for c in tokens.colors
        if len(c) != 7 or not c.startswith("#")
    )
    return issues


def extract_tokens_from_page(
    url: str,
    *,
    selectors: list[str] | None = None,
    timeout_ms: int = 30_000,
    out_dir: str | Path | None = None,
) -> DesignTokens:
    """playwright 实测 computed styles 提取 tokens(带原始 JSON 落盘)。

    Args:
        url: 产品页面。
        selectors: 采样元素选择器;None 时采样 body + 常用标题/按钮。
        timeout_ms: 加载超时。
        out_dir: 可选,原始样式 JSON 落盘目录(可回放)。

    Returns:
        DesignTokens。

    Raises:
        DesignTokenError: playwright/浏览器不可用或页面加载失败。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:  # pragma: no cover - env guard
        raise DesignTokenError(f"playwright 未安装: {e}") from e

    sample_selectors = selectors or [
        "body",
        "h1",
        "h2",
        "button",
        "a",
        ".card",
        "[data-token]",
    ]
    raw: dict[str, object] = {
        "font_families": [],
        "font_weights": [],
        "font_sizes": [],
        "line_heights": [],
        "colors": [],
        "spacing": [],
        "radii": [],
        "surfaces": [],
    }
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            seen: dict[str, set[str | float]] = {k: set() for k in raw}
            for selector in sample_selectors:
                try:
                    handles = page.query_selector_all(selector)
                except Exception:  # pragma: no cover - invalid selector
                    continue
                for handle in handles[:8]:
                    style = handle.evaluate(
                        "el => { const s = getComputedStyle(el); return {"
                        "font: s.fontFamily, weight: s.fontWeight, size: s.fontSize,"
                        "lh: s.lineHeight, color: s.color, bg: s.backgroundColor,"
                        "pad: s.padding, radius: s.borderRadius }; }"
                    )
                    for key, val in (
                        ("font_families", style["font"]),
                        ("colors", style["color"]),
                    ):
                        if isinstance(val, str) and val:
                            seen[key].add(val)
                    with contextlib.suppress(TypeError, ValueError):
                        seen["font_weights"].add(int(float(style["weight"])))
                    with contextlib.suppress(TypeError, ValueError):
                        seen["font_sizes"].add(_css_px(style["size"]))
                        seen["line_heights"].add(_css_px(style["lh"]))
                    for key, val in (("colors", style["bg"]), ("surfaces", style["bg"])):
                        if isinstance(val, str) and val:
                            seen[key].add(val)
                    pad = style["pad"]
                    if isinstance(pad, str) and pad:
                        for part in pad.split():
                            with contextlib.suppress(TypeError, ValueError):
                                seen["spacing"].add(_css_px(part))
                    radius = style["radius"]
                    if isinstance(radius, str) and radius:
                        with contextlib.suppress(TypeError, ValueError):
                            seen["radii"].add(_css_px(radius))
            browser.close()
            for key in raw:
                raw[key] = sorted(seen[key])
    except Exception as e:
        raise DesignTokenError(f"token extraction failed for {url}: {e}") from e

    if out_dir is not None:
        import json

        p = Path(out_dir) / "raw_tokens.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    return normalize_design_tokens(raw, source=url)


def _css_px(value: str) -> float:
    """'16px' → 16.0;'1.5' → 1.5(行高无单位时原样)。"""
    v = value.strip()
    if v.endswith("px"):
        return float(v[:-2])
    return float(v)
