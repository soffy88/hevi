"""判例式审美准则库(aesthetic canon)—— 规则+判例+自检三要素(3O 内化 Phase B)。

来源: video-shotcraft aesthetic-rules.md —— 判例式 QA canon:
  - 每条 = 规则(一句可执行的话)+ 判例(用户原话/返工经过)+ 自检问题
  - 编号 R(节奏)/Q(质感运镜构图)/S(声音)/C(文案)/P(流程),一经发布不重排,
    新增只追加;可以有意识违反,但必须写进项目说明
  - 验收时逐条过一遍,输出自检报告:`编号 ✓` 或 `编号 ✗(位置)`

Hevi 已有确定性交付门(ffmpeg 检查),这里补上**人类判例沉淀资产** ——
另一种数据资产,随使用越攒越值钱。挂到 verdict 的成片交付门。

3O 归属(待上游): `oskill.aesthetic_canon`(判例库 + 自检报告生成)。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

#: 准则族(编号前缀)。编号一经发布不重排,新增只追加。
CANON_FAMILIES: tuple[str, ...] = ("R", "Q", "S", "C", "P")
_FAMILY_NAMES = {"R": "节奏", "Q": "质感·运镜·构图", "S": "声音", "C": "文案", "P": "流程"}


class CanonError(Exception):
    """判例库违规(编号重排/未知族/字段缺失)。"""


@dataclass(frozen=True)
class CanonRule:
    """一条判例式准则。"""

    code: str  # 如 "R1",族 + 序号,只增不重排
    rule: str  # 一句可执行的话
    precedent: str  # 用户原话/返工经过
    self_check: str  # 自检问题
    allow_violation: bool = False  # 允许有意违反(须记入项目说明)


def _parse_code(code: str) -> tuple[str, int]:
    if len(code) < 2 or code[0] not in CANON_FAMILIES:
        raise CanonError(f"invalid canon code {code!r}")
    try:
        return code[0], int(code[1:])
    except ValueError as e:
        raise CanonError(f"invalid canon code {code!r}") from e


class AestheticCanon:
    """判例库:按族保序 + 只增不重排校验 + 自检报告。"""

    def __init__(self, rules: list[CanonRule] | None = None) -> None:
        self._rules: list[CanonRule] = []
        if rules:
            for r in rules:
                self.add(r)

    def add(self, rule: CanonRule) -> None:
        family, number = _parse_code(rule.code)
        existing = [r for r in self._rules if _parse_code(r.code)[0] == family]
        if not rule.rule.strip() or not rule.self_check.strip():
            raise CanonError(f"{rule.code}: rule and self_check must not be empty")
        # 只增不重排:新序号必须 > 该族当前最大序号(允许中间补号,不允许降序插入)
        max_number = max((_parse_code(r.code)[1] for r in existing), default=0)
        if number <= max_number:
            raise CanonError(
                f"{rule.code}: numbering must only append (max {family}{max_number})"
            )
        self._rules.append(rule)
        self._rules.sort(key=lambda r: (_parse_code(r.code)[0], _parse_code(r.code)[1]))

    def by_family(self, family: str) -> list[CanonRule]:
        if family not in CANON_FAMILIES:
            raise CanonError(f"unknown family {family!r}")
        return [r for r in self._rules if r.code.startswith(family)]

    @property
    def rules(self) -> list[CanonRule]:
        return list(self._rules)

    def to_dict(self) -> list[dict[str, object]]:
        return [
            {
                "code": r.code,
                "rule": r.rule,
                "precedent": r.precedent,
                "self_check": r.self_check,
                "allow_violation": r.allow_violation,
            }
            for r in self._rules
        ]

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: str | Path) -> AestheticCanon:
        p = Path(path)
        if not p.exists():
            return cls()
        raw = json.loads(p.read_text(encoding="utf-8"))
        rules = [
            CanonRule(
                code=item["code"],
                rule=item["rule"],
                precedent=item.get("precedent", ""),
                self_check=item["self_check"],
                allow_violation=item.get("allow_violation", False),
            )
            for item in raw
        ]
        return cls(rules)


#: 种子判例库(来源 shotcraft 实战判例;仅示范,可持续追加)。
SEED_CANON: tuple[CanonRule, ...] = (
    CanonRule(
        code="R1",
        rule="关键信息落定后必须呼吸:承载信息的元素落定后静止 ≥1s 再切镜",
        precedent="用户:'第一个标题打出来之后停留一秒'。先停错对象、revert 后重做。",
        self_check="每个'想让观众记住的画面'是否有完整静止时刻?停顿给的是品牌/关键信息,还是随手给了普通元素?",
    ),
    CanonRule(
        code="R2",
        rule="速度感来自加速度:飞入/滚动一律非线性缓动+非均匀错峰;批量入场用硬加速节拍,满板静止 0.5s",  # noqa: E501
        precedent="用户:'卡片不断往下堆叠时,应该越来越快……并在最后停顿0.5秒'。抽象 flood 五轮不收敛,换发牌隐喻一轮通过。",  # noqa: E501
        self_check="有没有任何元素在做匀速直线运动?批量入场是否越来越快、末尾有无静止呼吸?",
    ),
    CanonRule(
        code="Q1",
        rule="复刻既有页面必须真实截图;手搓 UI 限非复刻场景且质量/表达达标;数据按风险口径处理",
        precedent="用户:'我希望的是用真实的页面,然后加入动画'。手搓纹理复刻版整体作废,改用真实 dashboard 重建。",  # noqa: E501
        self_check="每块 UI 素材:它在复刻既有页面吗?是则必须来自截图;源数据符合已确认的数据口径且不含未授权内容吗?",  # noqa: E501
    ),
    CanonRule(
        code="Q2",
        rule="3D 透视下 UI 纹理按原生尺寸 rasterize 后缩小使用;文字发糊先查纹理分辨率链路",
        precedent="用户三轮追打:'明显卡片变得模糊了'。先调 DoF 治标无效,改原生尺寸 rasterize 拿真正 4x 锐度根治。",  # noqa: E501
        self_check="放大/透视镜头逐帧截图看文字边缘:有没有像素方块?纹理源分辨率 ≥ 显示尺寸 2 倍吗?",
    ),
    CanonRule(
        code="Q4",
        rule="高光/扫光特效宁缺毋滥:不群发,一个镜头最多给主角一次,且必须裁进圆角边界",
        precedent="用户两次否决:'不需要每个卡片都闪烁一下'。据此去掉逐卡 glint、撤掉泛光划过。",
        self_check="数一数全片 glint/sweep 出现次数:有没有超过'主角元素一次'?每处光效被圆角裁剪了吗?",  # noqa: E501
    ),
    CanonRule(
        code="Q5",
        rule="开场只给一个主角:单主体 + 完整动作弧(聚光→推近→悬浮→归位),胜过群体群舞",
        precedent="用户:'第一个镜头,只需要聚焦在一张卡片,并让它更有质感'。开场一夜推倒六次,单卡结构定型后未再动。",
        self_check="开场镜头有几个'想让观众看'的东西?主角的动作弧是否完整(起-承-落)?",
    ),
    CanonRule(
        code="S1",
        rule="SFX 词汇表按'片种'选不按'事件'选:产品宣传片 = whoosh/impact/riser/sparkle/transition,禁用游戏音包音色",  # noqa: E501
        precedent="模板片第一版按 UI 事件语义选音(click/drop/confirmation),用户一耳朵判死刑'太像游戏了'。",  # noqa: E501
        self_check="这条 SFX 的音色属于什么片种?游戏音包音色(pluck/bloop/卡通弹跳)混进来了吗?",
    ),
    CanonRule(
        code="S3",
        rule="声音永远排在画面锁定之后:换 BGM 和画面重做不要混在同一轮改动里,否则 SFX 全表报废重钉",
        precedent="有一次把换 BGM 和画面重做混在同一轮,画面随后继续改,SFX 全表报废重钉。",
        self_check="当前轮次是否同时改了画面与音频?声音开始前画面结构是否基本锁定?",
    ),
    CanonRule(
        code="P1",
        rule="验收贯穿全程:逐镜头静帧自检收尾,每轮修改后整片重渲;交付前独立终检",
        precedent="阶段 5 起每个镜头 remotion still 静帧验收;交付前派干净上下文 subagent 独立终检。",  # noqa: E501
        self_check="最后一个镜头有没有被静帧看过?终检是否由与制作不同上下文的审查者执行?",
    ),
    CanonRule(
        code="C1",
        rule="片中所有文案/数字/字卡必须复用产品设计 token,不另造宣传腔调;数据按风险口径虚构/脱敏",
        precedent="用户:'不要用真实数据,造一份fake的,不要提到客户名字'。改用虚构/脱敏口径。",
        self_check="每条出现在片中的文案:来自产品原样吗?若是则已确认公开属性;若否已虚构/脱敏?",
    ),
)


def default_canon() -> AestheticCanon:
    return AestheticCanon(list(SEED_CANON))


def build_self_check_report(
    canon: AestheticCanon, results: dict[str, str | None]
) -> str:
    """生成自检报告:`编号 ✓` 或 `编号 ✗(位置)`;未检 = `编号 ?`。

    Args:
        canon: 判例库。
        results: {code: 位置或 None};None = 通过,非 None = 违规位置。

    Returns:
        多行报告文本。
    """
    lines: list[str] = []
    for rule in canon.rules:
        if rule.code in results:
            location = results[rule.code]
            lines.append(f"{rule.code} ✓" if location is None else f"{rule.code} ✗({location})")
        else:
            lines.append(f"{rule.code} ?")
    return "\n".join(lines)


def validate_canon(canon: AestheticCanon) -> list[str]:
    """整库校验:编号唯一且只增不重排(载入时已保证)、每族至少一条。"""
    return [
        f"family {family} ({_FAMILY_NAMES[family]}) has no rules"
        for family in CANON_FAMILIES
        if not canon.by_family(family)
    ]
