"""The 32 style rows shipped with anidoodle, and a deterministic recommender.

A style is a way of making marks, not a palette.  The catalog keeps the
medium, the hero plate and the drawing-process film so a caller can preview
the hand before writing a scene in it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from .engine import AnidoodleError, engine_dir

FAMILY_ORDER = (
    "pen & ink",
    "dry media",
    "watercolour",
    "marker comic",
    "paint",
    "oil",
    "print",
    "technical drawing",
    "engraving",
    "collage",
    "collage + print",
    "textile",
    "ink",
    "chalk",
    "digital",
    "3D in code",
    "modern flat illustration",
    "1950s-60s storybook",
    "1930s cartoon",
    "rendered",
)


@dataclass(frozen=True)
class StyleInfo:
    id: str
    name: str
    family: str
    medium: str
    nearest: str
    hero: str
    draw_film: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "family": self.family,
            "medium": self.medium,
            "nearest": self.nearest,
            "hero": self.hero,
            "draw_film": self.draw_film,
        }


@lru_cache(maxsize=1)
def _catalog() -> tuple[StyleInfo, ...]:
    path = engine_dir() / "styles.gen.json"
    if not path.is_file():
        raise AnidoodleError(f"style catalog missing: {path}")
    rows = json.loads(path.read_text(encoding="utf-8"))
    styles: list[StyleInfo] = []
    styles = [
        StyleInfo(
            id=str(row["id"]),
            name=str(row["name"]),
            family=str(row["family"]),
            medium=str(row["medium"]),
            nearest=str(row.get("nearest", "")),
            hero=str(row.get("hero", "")),
            draw_film=str(row["drawFilm"]),
        )
        for row in rows
    ]
    return tuple(styles)


def list_styles() -> list[StyleInfo]:
    return list(_catalog())


def get_style(style_id: str) -> StyleInfo:
    for style in _catalog():
        if style.id == style_id:
            return style
    raise AnidoodleError(f"unknown anidoodle style: {style_id}")


def families() -> list[dict[str, object]]:
    grouped: dict[str, list[StyleInfo]] = {}
    for style in _catalog():
        grouped.setdefault(style.family, []).append(style)
    order = {name: index for index, name in enumerate(FAMILY_ORDER)}
    names = sorted(grouped, key=lambda name: (order.get(name, 999), name))
    return [
        {
            "family": name,
            "styles": [{**style.to_dict(), **validation_for(style.id)} for style in grouped[name]],
        }
        for name in names
    ]


# Black-box acceptance (S29): a style is public only when its drawing clip
# passed the determinism gate (drawing dead-air profile) and export verification
# and a human scored it at least 4/5 on subject, medium, composition, process.
PUBLIC_SCORES: dict[str, int] = {
    "koi": 5,
    "fox": 4,
    "lighthouse": 5,
    "blueprint": 4,
    "moonPhases": 4,
    "flatVector": 4,
    "storybook": 4,
    "pixelArt": 4,
    "embroidery": 4,
}

# Measured failures: the drawing holds a still frame longer than the engine's
# documented drawing pause.  Kept for admin review, never advertised.
ADMIN_ONLY: dict[str, str] = {
    "isometric": "生产 Chromium 下 433–464 帧死空镜（门禁 12/13）",
    "halftone": "门禁通过，但 14 秒片渲染 156.4 秒（11.2× 实时），按负载仅管理员",
    "ranunculus": "绘制档死空镜：388–434 帧停 46 帧",
    "woodcut": "绘制档死空镜未过门禁",
}


def validation_for(style_id: str) -> dict[str, object]:
    """Public/administrative status and the evidence behind it."""

    if style_id in PUBLIC_SCORES:
        return {
            "status": "public",
            "score": PUBLIC_SCORES[style_id],
            "reason": "确定性门禁（绘制档）与导出校验通过 · 人工评分 ≥ 4",
        }
    if style_id in ADMIN_ONLY:
        return {
            "status": "admin",
            "score": 0,
            "reason": ADMIN_ONLY[style_id],
        }
    return {
        "status": "admin",
        "score": 0,
        "reason": "S29 未做黑盒验收，仅管理员可见",
    }


_KEYWORDS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (
        ("灯塔", "lighthouse", "海岸", "海", "ocean", "harbour", "港口"),
        "lighthouse",
        "印刷油墨的套版感适合海边日落与硬边形状",
    ),
    (
        ("锦鲤", "koi", "鱼", "fish", "池塘"),
        "koi",
        "马克笔平涂和粗轮廓适合水生动物与清亮的色彩",
    ),
    (
        ("机械", "mechanism", "原理", "how it works", "拆解", "蓝图", "blueprint", "工程"),
        "blueprint",
        "技术制图的标注、剖面和网格最适合解释结构",
    ),
    (
        ("黑板", "课堂", "教学", "chalkboard", "公式", "讲解"),
        "moonPhases",
        "粉笔的擦除与粉尘天然带教学现场感",
    ),
    (
        ("水彩", "植物", "花", "watercolour", "flower", "botanical", "自然"),
        "ranunculus",
        "水彩的渗化与留白适合植物和温柔的自然题材",
    ),
    (
        ("绘本", "故事", "storybook", "童话", "孩子", "child"),
        "storybook",
        "铅笔线加淡彩的角色最容易被当成故事里的活人",
    ),
    (
        ("品牌", "brand", "产品", "product", "广告", "promo", "flat"),
        "flatVector",
        "扁平矢量在大字号与缩略图上仍清晰，适合品牌与产品",
    ),
    (
        ("像素", "pixel", "游戏", "game", "复古", "retro"),
        "pixelArt",
        "固定 16 色与低分辨率网格是像素游戏的语法",
    ),
    (("漫画", "comic", "marker", "对白", "日常"), "koi", "马克笔平涂加粗轮廓，人物与动作读得快"),
    (
        ("版画", "木刻", "ukiyo", "woodcut", "东方", "浮世绘"),
        "woodcut",
        "木刻的分版与纸纹适合东方式风景与雨雪",
    ),
    (
        ("刺绣", "textile", "布", "手工", "embroidery"),
        "embroidery",
        "线迹和布纹把日常物件变成可触摸的手工",
    ),
    (
        ("油画", "oil", "古典", "静物", "still life"),
        "paintedOil",
        "厚涂笔触与调色油层次适合静物和庄重题材",
    ),
    (("剪贴", "collage", "纸", "paper", "拼贴"), "fox", "剪纸的边缘与层叠阴影适合黄昏、动物和剪影"),
    (("数据", "图表", "chart", "report", "报告"), "isometric", "等距剖面能同时给出总量和内部结构"),
    (("儿童", "小朋友", "kids", "幼儿园"), "balloon", "蜡笔的跳动笔触和饱满色块对儿童最友好"),
    (("夜景", "夜晚", "night", "月光", "moon"), "moonPhases", "粉笔在深色板上的反光适合夜色与月亮"),
    (
        ("速写", "sketch", "随身", "笔记本", "notebook"),
        "pocketWatch",
        "圆珠笔的细线和小小一笔阴影适合速写本气质",
    ),
)


def recommend_style(
    topic: str,
    *,
    intent: str = "",
    avoid: list[str] | None = None,
) -> dict[str, object]:
    """Recommend a style with one reason, and two alternatives.

    The rule is deliberately transparent: topic keywords first, then the stated
    intent, then a safe default per intent.  It never claims a look it has not
    seen rendered.
    """

    text = f"{topic} {intent}".strip().lower()
    blocked = set(avoid or ())
    picked: StyleInfo | None = None
    reason = ""
    for needles, style_id, why in _KEYWORDS:
        if style_id in blocked:
            continue
        if any(needle in text for needle in needles):
            picked = get_style(style_id)
            reason = why
            break
    if picked is None:
        defaults = {
            "explainer": ("blueprint", "讲解需要可读的结构线；蓝晒制图的标注与剖面最稳"),
            "story": ("storybook", "故事优先让角色可信，铅笔线加淡彩最不容易变成图标"),
            "brand": ("flatVector", "品牌画面要在缩略图里清楚，扁平矢量最抗缩放"),
            "education": ("moonPhases", "课堂画面要像现场板书，粉笔的擦除痕迹会保留思考过程"),
            "editorial": ("lighthouse", "编辑插图需要明确的印刷质感，套版油墨比数字渐变更有立场"),
        }
        style_id, reason = defaults.get(
            intent, ("ranunculus", "没有指定题材时，水彩的兼容性最好；它不挑主体")
        )
        if style_id in blocked:
            style_id, reason = "storybook", "首选被排除，退回铅笔加淡彩这一稳妥手"
        picked = get_style(style_id)

    alternatives: list[StyleInfo] = []
    for candidate in _catalog():
        if candidate.id == picked.id or candidate.id in blocked:
            continue
        if len(alternatives) < 2 and candidate.family != picked.family:
            alternatives.append(candidate)
    if len(alternatives) < 2:
        for candidate in _catalog():
            if candidate.id != picked.id and candidate not in alternatives:
                alternatives.append(candidate)
            if len(alternatives) >= 2:
                break

    return {
        "style": picked.to_dict(),
        "reason": reason,
        "alternatives": [style.to_dict() for style in alternatives],
        "source": "anidoodle style catalog (Apache-2.0); see NOTICE",
    }
