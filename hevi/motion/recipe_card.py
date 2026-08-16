"""镜头配方卡 —— 可执行的运镜/动效词汇表(3O 内化 Phase B,来源 video-shotcraft)。

shotcraft 的 104 张镜头配方卡是"把 StylePack 设备包/genre router 从文档变成
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
    ]
    return {card.name: card for card in cards}


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
        return build_seed_library()
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
