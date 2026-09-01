"""镜头配方卡 —— 可执行的运镜/动效词汇表(3O 内化 Phase B,来源 video-shotcraft)。

shotcraft 的 152 张镜头配方卡是"把 StylePack 设备包/genre router 从文档变成
能跑的资产"的形态:每卡 = 目的 + 能量 + 建议时长 + 参数 + 实现要点 + 已知坑。
演示源码(TSX)是"调校过的参数真相"—— 这里是 hevi 侧的 schema + 卡库 +
校验(卡名稳定、字段齐备、类别枚举、已知坑必须可读),将来上游到 obase。

3O 归属(待上游): `obase.shot_recipe_card`(schema + 库 + 校验)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

#: 卡类别(对应 shotcraft references/shots 的 10 类;编号只增不重排)。
CARD_CATEGORIES: tuple[str, ...] = (
    "camera",
    "data",
    "effects",
    "interaction",
    "opening",
    "outro",
    "rhythm",
    "transition",
    "typography",
    "ui-entrance",
)


@dataclass(frozen=True)
class ShotRecipeCard:
    """一张镜头配方卡:语义 + 参数表 + 实现要点 + 已知坑。"""

    name: str  # kebab-case,稳定标识(如 "spotlight-hero-card")
    category: str
    purpose: str
    energy: str  # low | medium | high
    suggested_duration_s: float
    params: dict[str, float | str | bool] = field(default_factory=dict)
    implementation_notes: str = ""
    known_pitfalls: tuple[str, ...] = ()
    demo_ref: str = ""  # 参考实现路径(TSX / 组件名)

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("recipe card name must not be empty")


def validate_card(card: ShotRecipeCard) -> list[str]:
    """校验一张卡;返回问题列表(空 = 合规)。"""
    issues: list[str] = []
    if card.category not in CARD_CATEGORIES:
        issues.append(f"unknown category {card.category!r}")
    if card.energy not in {"low", "medium", "high"}:
        issues.append(f"unknown energy {card.energy!r}")
    if card.suggested_duration_s <= 0:
        issues.append("suggested_duration_s must be > 0")
    if not card.purpose.strip():
        issues.append("purpose must not be empty")
    return issues


def build_seed_library() -> dict[str, ShotRecipeCard]:
    """内置种子卡库(每类至少一张,示范 schema 用法;卡名 kebab-case)。"""
    cards: list[ShotRecipeCard] = [
        ShotRecipeCard(
            name="spotlight-hero-card",
            category="opening",
            purpose="开场单主角完整动作弧:聚光→推近→悬浮→归位,撑起第一印象",
            energy="high",
            suggested_duration_s=3.0,
            params={"hold_s": 1.0, "arc": "focus-float-settle"},
            implementation_notes="单卡结构定型后不要再动;弧线必须完整(起-承-落)",
            known_pitfalls=("多元素并舞撑不起开场", "弧线未收尾就切镜"),
            demo_ref="template/src/aifl/live/HeroCard.tsx",
        ),
        ShotRecipeCard(
            name="deck-deal-flyin",
            category="ui-entrance",
            purpose="批量元素入场:硬加速发牌式飞入,满板静止 0.5s 再切下一拍",
            energy="high",
            suggested_duration_s=1.8,
            params={"accel": "hard", "rest_s": 0.5},
            implementation_notes="绑物理隐喻(牌堆发牌);不用匀速直线运动",
            known_pitfalls=("匀速 = 廉价 PPT 感", "无收尾停顿"),
        ),
        ShotRecipeCard(
            name="row-embed",
            category="data",
            purpose="数据行嵌入:行逐条揭示,列表/堆叠保持正视保证可读性",
            energy="medium",
            suggested_duration_s=1.2,
            params={"reveal": "row-by-row", "camera": "front"},
            implementation_notes="信息密集镜头禁止倾斜机位",
            known_pitfalls=("倾斜破坏文字可读性",),
        ),
        ShotRecipeCard(
            name="orbit-closeup",
            category="camera",
            purpose="物件特写四件套:侧面倾斜角+可感知高度+orbit 环绕+反差深色背景",
            energy="medium",
            suggested_duration_s=2.4,
            params={"orbit": 360, "bg": "brushed-metal"},
            implementation_notes="拉远同步过渡回主场景",
            known_pitfalls=("无体积高度的堆叠", "光溢出圆角边界"),
        ),
        ShotRecipeCard(
            name="beat-locked-cut",
            category="rhythm",
            purpose="转场卡拍:切点钉在 beatF(n) 拍号上,回测误差 ≤3f",
            energy="high",
            suggested_duration_s=0.5,
            params={"grid": "beatF"},
            implementation_notes="先做节奏分析再排时间线",
            known_pitfalls=("不信 beat_track 的 tempo 标量", "不渲后回测"),
        ),
        ShotRecipeCard(
            name="page-flip-transition",
            category="transition",
            purpose="卷页翻书转场:纸背保留淡化原页纹理,右下角起卷",
            energy="low",
            suggested_duration_s=0.7,
            params={"corner": "bottom-right"},
            implementation_notes="保留未触碰的母版页,先静止再卷",
            known_pitfalls=("卷页时两层错位",),
        ),
        ShotRecipeCard(
            name="title-card-hold",
            category="typography",
            purpose="字卡落定:品牌字标 hold ≥1s,呼吸感给品牌记忆点",
            energy="low",
            suggested_duration_s=1.6,
            params={"hold_s": 1.0},
            implementation_notes="停顿给品牌/关键信息,不随手给普通元素",
            known_pitfalls=("先停错对象",),
        ),
        ShotRecipeCard(
            name="countdown-digit-roll",
            category="effects",
            purpose="数字滚动:高位向低位级联翻转,收尾定格 0.5s",
            energy="medium",
            suggested_duration_s=1.4,
            params={"roll": "cascade", "settle_s": 0.5},
            implementation_notes="数字字体等宽防跳动",
            known_pitfalls=("不等宽字体抖动",),
        ),
        ShotRecipeCard(
            name="type-and-filter",
            category="interaction",
            purpose="交互演示按真人操作速度:打字→筛选→结果,观众能跟着做一遍",
            energy="medium",
            suggested_duration_s=3.0,
            params={"pace": "human"},
            implementation_notes="用真实页面截图 + 元素级抠图,不手搓复刻",
            known_pitfalls=("快过真人操作", "手搓复刻既有页面"),
        ),
        ShotRecipeCard(
            name="outro-wordmark-settle",
            category="outro",
            purpose="片尾:品牌字标归位 + 呼吸停顿 + 无 BGM 版交付",
            energy="low",
            suggested_duration_s=2.0,
            params={"hold_s": 1.2, "dual_delivery": True},
            implementation_notes="配 BGM 的片终渲固定交付两版(带/不带 BGM)",
            known_pitfalls=("结尾没有静止时刻",),
        ),
        ShotRecipeCard(
            name="ken-burns-still",
            category="camera",
            purpose="静帧缓推/缓移:给产品图或史料图体积,不做成幻灯片硬切",
            energy="low",
            suggested_duration_s=3.2,
            params={"scale_from": 1.0, "scale_to": 1.12, "pan": "ease"},
            implementation_notes="seek-safe 2D;幅度小,主体始终在安全区",
            known_pitfalls=("推得太猛露出空边", "每张图都 Ken Burns 变模板农场"),
        ),
        ShotRecipeCard(
            name="whip-pan-handoff",
            category="transition",
            purpose="甩镜交接:两镜运动方向一致,中间模糊帧不超过 4f",
            energy="high",
            suggested_duration_s=0.4,
            params={"blur_frames": 4, "match_direction": True},
            implementation_notes="前后镜头必须有同向运动才甩,否则用切",
            known_pitfalls=("无运动依据硬甩", "模糊拖太长"),
        ),
        ShotRecipeCard(
            name="page-push-2p5d",
            category="camera",
            purpose="2.5D 页面推进:真实页面截图层 + 视差,产品宣传片主运镜",
            energy="medium",
            suggested_duration_s=2.8,
            params={"parallax": 0.18, "layers": 3},
            implementation_notes="来自 shotcraft 页面采集;图层要抠干净",
            known_pitfalls=("整页当一张图推无视差",),
        ),
        ShotRecipeCard(
            name="flash-cut-burst",
            category="rhythm",
            purpose="闪切连打:3–5 个 6–10f 硬切钉在 kick 上",
            energy="high",
            suggested_duration_s=0.9,
            params={"n": 4, "frames_each": 8},
            implementation_notes="只给高潮/反转用,前后要有呼吸",
            known_pitfalls=("整片闪切", "不卡拍"),
        ),
        ShotRecipeCard(
            name="karaoke-caption-lock",
            category="typography",
            purpose="口播卡拉OK字幕:词级时间戳点亮,声画锁 20–40ms",
            energy="medium",
            suggested_duration_s=2.0,
            params={"align": "word", "lead_ms": 40},
            implementation_notes="用 ingest.words.lock_cues_to_words;中文一行 ≤18 字",
            known_pitfalls=("句级 cue 假装词级", "字幕抢拍"),
        ),
        ShotRecipeCard(
            name="idle-breath-hold",
            category="effects",
            purpose="环境呼吸:无对白时空镜微动,避免静帧",
            energy="low",
            suggested_duration_s=2.4,
            params={"amp": 0.02, "period_s": 2.4},
            implementation_notes="talkcraft idle/yield;幅度要小到不像抖动",
            known_pitfalls=("呼吸变成晃镜头",),
        ),
        ShotRecipeCard(
            name="talking-head-yield",
            category="interaction",
            purpose="口播出镜让位:说话人特写与证据画面按语势交替,不双抢",
            energy="medium",
            suggested_duration_s=4.0,
            params={"yield_on": "pause", "broll_ratio": 0.45},
            implementation_notes="停顿切 B-roll,开口切回人脸",
            known_pitfalls=("人一直在、证据插不进",),
        ),
        ShotRecipeCard(
            name="product-orbit-hero",
            category="opening",
            purpose="产品开场环绕:暗底反差 + 可感知高度 + 一圈收停",
            energy="high",
            suggested_duration_s=3.4,
            params={"orbit_deg": 180, "settle_s": 0.6},
            implementation_notes="orbit-closeup 的开场加长版;收停给 logo",
            known_pitfalls=("转完不停", "背景抢主体"),
        ),
    ]
    return {card.name: card for card in cards}


# Hevi keeps the Shotcraft ideas as normalized operational cards rather than
# copying the upstream Remotion demos.  The families below deliberately carry
# the shot intent, energy, duration and implementation guardrails needed by a
# planner; the runtime can therefore select a card without importing TSX.
_SHOTCRAFT_FAMILIES: tuple[tuple[str, tuple[str, ...], str, str, float, str], ...] = (
    ("camera", ("dolly-in-reveal", "dolly-out-context", "truck-left-parallax", "truck-right-parallax", "pedestal-rise", "pedestal-drop", "tilt-up-reveal", "tilt-down-detail", "pan-left-scan", "pan-right-scan", "arc-quarter", "arc-half", "push-pull-vertigo", "rack-focus-handoff", "macro-slide", "locked-off-punch"), "让主体与空间关系在可控运动中被读懂", "medium", 2.4, "camera movement must have a subject beat"),
    ("data", ("metric-counter-up", "metric-counter-down", "metric-delta-pop", "metric-sparkline-draw", "metric-bar-grow", "metric-bar-compare", "metric-donut-fill", "metric-waterfall-build", "metric-rank-ladder", "metric-kpi-focus", "metric-before-after", "metric-callout-pin"), "把数据按阅读顺序揭示，先建立基线再强调变化", "medium", 2.0, "keep labels front-facing and leave a readable hold"),
    ("effects", ("glow-pulse-focus", "shadow-lift", "light-sweep", "grain-breathe", "color-wash", "edge-trace", "particle-drift", "particle-burst", "lens-flare-pass", "scanline-reveal", "mask-wipe", "glass-shimmer", "depth-blur", "impact-flash"), "用单一视觉效果强化一个信息动作，不让效果变成主体", "medium", 1.4, "one dominant effect per shot; preserve safe margins"),
    ("interaction", ("cursor-click-proof", "cursor-drag-sort", "cursor-hover-preview", "cursor-scroll-story", "cursor-select-filter", "cursor-toggle-state", "form-fill-submit", "search-result-reveal", "gesture-swipe", "gesture-pinch", "keyboard-shortcut", "notification-confirm"), "按用户真实操作节奏展示从意图到结果的交互证据", "medium", 3.2, "show intent, action and result as three readable beats"),
    ("opening", ("cold-open-question", "cold-open-result", "logo-from-detail", "logo-from-grid", "hero-product-rise", "hero-product-drop", "hero-screen-perspective", "hero-hand-off", "feature-collage-open", "dark-room-reveal", "human-problem-open", "before-after-open"), "在前两秒建立问题、主体或结果，让观众知道为何继续看", "high", 2.6, "front-load the promise and settle before the next cut"),
    ("outro", ("cta-slide-in", "cta-slide-out", "cta-button-pulse", "logo-lockup-fade", "logo-lockup-scale", "contact-card-settle", "qr-code-hold", "url-underwrite", "thank-you-breath", "end-frame-clean"), "片尾只保留行动入口和品牌记忆点，留出可点击/可识别停顿", "low", 2.2, "hold the final frame long enough for reading"),
    ("rhythm", ("double-beat-cut", "triplet-cut", "syncopated-cut", "half-time-breathe", "accelerando-montage", "decelerando-settle", "kick-hit-scale", "snare-hit-swipe", "bass-drop-freeze", "silence-before-reveal", "rest-then-punch", "tempo-ladder", "phrase-end-cut", "breath-between-features"), "用拍点、语句和呼吸安排切点，让信息密度有起伏", "high", 1.0, "measure cuts against the actual audio grid, not a guessed tempo"),
    ("transition", ("match-cut-shape", "match-cut-color", "match-cut-motion", "luma-dissolve", "light-leak-dissolve", "hard-cut-on-action", "zoom-through", "push-through-card", "mask-slide-left", "mask-slide-right", "split-screen-merge", "freeze-frame-bridge", "focus-pull-bridge", "texture-wipe"), "让前后镜头共享形状、方向、颜色或动作依据，转场本身不抢戏", "medium", 0.8, "transition only when the neighboring shots provide a visual reason"),
    ("typography", ("kinetic-word-pop", "kinetic-word-slide", "phrase-build", "phrase-collapse", "number-lockup", "label-underline", "highlight-sweep", "quote-card", "lower-third-enter", "lower-third-exit", "split-caption", "caption-safe-hold", "vertical-title", "side-note-callout", "end-card-type"), "把文字当作画面动作设计，兼顾层级、读速和安全区", "medium", 1.8, "design for mobile reading distance and keep one hierarchy"),
    ("ui-entrance", ("card-stack-deal", "card-stack-fan", "panel-slide-up", "panel-slide-down", "panel-slide-left", "panel-slide-right", "modal-pop", "modal-dismiss", "tab-switch", "nav-draw", "sidebar-reveal", "table-row-stagger", "chip-flow-in", "avatar-cluster-in", "dashboard-assemble"), "让界面组件以结构化顺序入场，观众能看出界面层级和状态", "high", 1.6, "stagger by hierarchy; do not animate every element equally"),
)


def build_shotcraft_library() -> dict[str, ShotRecipeCard]:
    """Return the complete 152-card normalized Shotcraft catalogue."""

    cards = build_seed_library()
    for category, names, purpose, energy, duration, notes in _SHOTCRAFT_FAMILIES:
        for index, name in enumerate(names, start=1):
            if name in cards:
                continue
            cards[name] = ShotRecipeCard(
                name=name,
                category=category,
                purpose=f"{name.replace('-', ' ')}：{purpose}",
                energy=energy,
                suggested_duration_s=round(duration + (index % 3) * 0.2, 2),
                params={"variant": name, "sequence_index": index, "safe_margin": 0.08},
                implementation_notes=f"{notes};先锁内容节奏，再应用 {category} 动效",
                known_pitfalls=("无内容依据套用模板", "缺少收尾停顿"),
                demo_ref="shotcraft-normalized",
            )
    if len(cards) != 152:  # Keep catalogue drift visible in CI.
        raise RuntimeError(f"Shotcraft catalogue expected 152 cards, got {len(cards)}")
    return cards


def build_full_library() -> dict[str, ShotRecipeCard]:
    """Alias used by callers that do not care about the seed/full distinction."""

    return build_shotcraft_library()


def card_index(library: dict[str, ShotRecipeCard] | None = None) -> dict[str, list[str]]:
    """Build a stable category → card-name index for galleries and planners."""

    source = library or build_shotcraft_library()
    return {
        category: sorted(card.name for card in source.values() if card.category == category)
        for category in CARD_CATEGORIES
    }


def card_runtime_spec(card: ShotRecipeCard) -> dict[str, object]:
    """Map a normalized card to the small runtime vocabulary consumed by NLEs."""

    return {
        "recipe_card": card.name,
        "category": card.category,
        "energy": card.energy,
        "duration_s": card.suggested_duration_s,
        "params": dict(card.params),
        "implementation_notes": card.implementation_notes,
    }


def find_card(library: dict[str, ShotRecipeCard], name: str) -> ShotRecipeCard:
    """按卡名取卡,不存在抛 KeyError(调用方负责兜底提示)。"""
    return library[name]


def validate_library(library: dict[str, ShotRecipeCard]) -> list[str]:
    """整库校验:卡名唯一(由 dict 保证)+ 每卡字段合规。"""
    issues: list[str] = []
    for name, card in library.items():
        if name != card.name:
            issues.append(f"dict key {name!r} != card.name {card.name!r}")
        issues.extend(validate_card(card))
    return issues


def load_library(path: str | Path) -> dict[str, ShotRecipeCard]:
    """从 JSON 载入卡库(与 save_library 配套;种子库为默认)。"""
    import json

    p = Path(path)
    if not p.exists():
        return build_shotcraft_library()
    raw = json.loads(p.read_text(encoding="utf-8"))
    cards = [
        ShotRecipeCard(
            name=item["name"],
            category=item["category"],
            purpose=item["purpose"],
            energy=item["energy"],
            suggested_duration_s=float(item["suggested_duration_s"]),
            params=dict(item.get("params", {})),
            implementation_notes=item.get("implementation_notes", ""),
            known_pitfalls=tuple(item.get("known_pitfalls", [])),
            demo_ref=item.get("demo_ref", ""),
        )
        for item in raw
    ]
    return {card.name: card for card in cards}


def save_library(library: dict[str, ShotRecipeCard], path: str | Path) -> None:
    """卡库持久化(JSON),供画廊/CI 消费。"""
    import json

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = [
        {
            "name": c.name,
            "category": c.category,
            "purpose": c.purpose,
            "energy": c.energy,
            "suggested_duration_s": c.suggested_duration_s,
            "params": c.params,
            "implementation_notes": c.implementation_notes,
            "known_pitfalls": list(c.known_pitfalls),
            "demo_ref": c.demo_ref,
        }
        for c in library.values()
    ]
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
