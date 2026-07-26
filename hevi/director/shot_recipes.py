"""历史正剧镜头配方卡库(2026-07-26)。

把散在 lint/schema/prompt 模板里的镜头语言收成**命名配方**——镜头语言成为可积累资产,SceneScript
生成/produce_v2 按卡名调用注入,不再每集重写。每张卡:适用场景 / 机位景别 / 运镜 / 构图约束 /
已知坑 + 可注入生成端的 `directive` 文本(参数化卡是函数)。

首批从已实证的形态起(廷议过肩反打/君主御座裁决/城门市井全景/文物道具特写已验;宫殿纵深仰拍治
"大殿不宏伟",本轮新建)。新增镜头形态先在这里立卡,再接生成端——不再散落。
"""

from __future__ import annotations

from dataclasses import dataclass

_OPP_SIDE = {"画左": "画右", "画右": "画左"}


@dataclass(frozen=True)
class ShotRecipe:
    """一张镜头配方卡(元数据;directive 文本由下面的 *_directive 函数按卡生成)。"""

    name: str
    applies_to: str  # 适用场景
    framing: str  # 机位/景别
    movement: str  # 运镜
    composition: str  # 构图约束
    pitfalls: str  # 已知坑
    validated: bool  # 是否已实证


# ── directive 生成(注入 produce_v2/plate 生成端的实际文本)──────────────────────
def ots_directive(*, speaker: str, speaker_side: str, foreground: str) -> str:
    """廷议过肩反打:说话人恒在己侧清晰,对手肩背虚焦入前景,只动说话人脸。"""
    fg_side = _OPP_SIDE.get(speaker_side, "画右")
    return (
        f"【本段构图·过肩反打(OTS)】说话人是{speaker},必须清晰、正面/四分之三面、位于画面{speaker_side};"
        f"{foreground}只露肩膀与后脑在{fg_side}前景、明显虚焦作遮挡,不清晰、不抢焦、不占画面中心。"
        f"【侧位锁定·防跳轴】整段严格保持{speaker}在{speaker_side}——反打机位可以过轴,但人物左右位置绝对"
        f"不许翻到另一侧。【只动说话人】只有{speaker}在开口说话、有口型;前景的{foreground}不说话、嘴不动。"
    )


def frontal_directive(*, speaker: str) -> str:
    """君主御座裁决:正面略仰独立镜,不进反打轴,严守帝王装束。"""
    return (
        f"【本段构图·君主/裁决者独立镜】{speaker}居中端坐御座、略仰拍显威仪,正面单人成镜,"
        f"不与他人过肩、不切入反打轴线;只有{speaker}开口说话。"
        f"【身份·严守参考图】严格保持{speaker}参考图里的帝王装束(冕服/冕冠/御座)与相貌,"
        f"绝不要把{speaker}渲染成普通官员或换成便服——他是君主,装束与威仪必须区别于臣子。"
    )


def master_directive() -> str:
    """双人建立镜:同框拉开建立左右轴线(谁在哪侧由 narrative_text 给);宏伟场景叠加纵深仰拍显尺度。"""
    return (
        "【本段构图·双人建立镜(master)】把两名人物同框拉成全景,一左一右相对而立,"
        "确立此后正反打的左右轴线;这一段不要过肩、不要单人特写,只做空间建立。"
        + palace_scale_directive()
    )


def palace_scale_directive() -> str:
    """★ 宫殿纵深仰拍(治"大殿不宏伟"):尺度感的拍法约束,注入宏伟场景的建立/空景镜。"""
    return (
        "【场景尺度·宏伟空间】把空间拍出恢弘尺度:广角镜头、低机位仰拍强化层高,"
        "以夹道立柱/九级丹陛/地砖延伸线引导纵深,层高数丈、柱列合抱、御座高台数级,"
        "人物在画面里占比不大以反衬殿宇之宏大;不要平视中景把大殿拍成小屋。"
    )


def establishing_wide_directive(*, location: str = "") -> str:
    """城门/市井全景(立木已验):大全景交代地点与人流,天光下的开阔场面。"""
    loc = f"{location}的" if location else ""
    return (
        f"【本段构图·全景交代】{loc}大全景:拉开视野交代地点全貌与人物所处环境,"
        "自然天光,场面开阔;人物置于环境中而非顶满画面。"
    )


def prop_closeup_avoid_text_directive() -> str:
    """文物道具特写(避可读文字):器物质感特写,但不渲可读文字。"""
    return (
        "【本段构图·文物道具特写】聚焦器物的材质/纹饰/工艺质感;"
        "★已知坑——绝不渲染可读文字(竹简/木牍/匾额/诏版上的字会渲成乱码),"
        "文字信息靠旁白后期字幕,画面里的字只作虚焦纹样或避开。"
    )


# ── 配方卡登记(元数据;SceneScript 生成按卡名查、生成端按卡注入 directive)──────
RECIPES: dict[str, ShotRecipe] = {
    "廷议过肩反打": ShotRecipe(
        name="廷议过肩反打",
        applies_to="双人对白辩论(廷议/论辩/对峙)",
        framing="过肩镜(OTS),说话人正面/四分之三面清晰,对手肩背前景虚焦",
        movement="静态或轻微,不推近",
        composition="说话人恒在己侧(side_convention),反打过轴不翻左右位",
        pitfalls="连续性末帧会复制上一镜构图→反打翻不过去(剪切镜不传末帧);两人脸融合",
        validated=True,
    ),
    "君主御座裁决": ShotRecipe(
        name="君主御座裁决",
        applies_to="君主/裁决者在多人廷议里的裁决(独立于辩论轴)",
        framing="正面略仰单人镜,御座高台",
        movement="静态,略仰",
        composition="独立成轴,不与臣子过肩;严守帝王冕服/御座",
        pitfalls="身份漂成普通官员(需强调帝王装束+参考图)",
        validated=True,
    ),
    "宫殿纵深仰拍": ShotRecipe(
        name="宫殿纵深仰拍",
        applies_to="宫殿/朝堂/大殿/城墙/庙宇等宏伟空间的建立/空景",
        framing="广角、低机位仰拍",
        movement="缓推或静态定场",
        composition="立柱/丹陛/地砖纵深引导线,人物占比小以显空间宏大",
        pitfalls="平视中景把大殿拍成小屋(根因:场景描述没写尺度→已进 world_bible 世界卷规则)",
        validated=False,
    ),
    "城门市井全景": ShotRecipe(
        name="城门市井全景",
        applies_to="城门/市集/街市等开阔外景的地点交代",
        framing="大全景,天光",
        movement="静态或缓摇",
        composition="人物置于环境中不顶满画面,交代地点全貌",
        pitfalls="—",
        validated=True,
    ),
    "文物道具特写": ShotRecipe(
        name="文物道具特写",
        applies_to="器物/文物/道具的质感特写",
        framing="特写/微距",
        movement="缓推或静态",
        composition="聚焦材质纹饰",
        pitfalls="★可读文字渲成乱码——竹简/匾额/诏版的字避开或虚焦",
        validated=True,
    ),
}
