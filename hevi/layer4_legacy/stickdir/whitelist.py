"""stickdir whitelist —— 所有枚举项的唯一真源。

设计要点(见 STICKDIR_TASK.md §(a)):

* LLM/重写输出的每一个枚举字段都必须落在这张表里;不在表内的项要么被修正
  (:func:`coerce`)要么整条回退到确定性方案。
* 动作 ``ACTION`` 的每个取值都必须在渲染器里有对应的参数化姿势
  (见 :mod:`hevi.layer4_legacy.stickdir.pose`);:func:`assert_renderable`
  在测试里守住这条不变式。
* 风格 ``STYLE`` 的键就是渲染器支持的 5 种风格(1A/1B/2A/2B/3)。
* 画幅 ``ASPECT`` / 时长 ``DURATIONS`` 与 skill 的 setup gate 对齐。
"""

from __future__ import annotations

from typing import Iterable

# ---------------------------------------------------------------------------
# 顶层枚举
# ---------------------------------------------------------------------------

#: 支持画幅(缺省必须报错, 不得静默默认)
ASPECT: tuple[str, ...] = ("9:16", "16:9")

#: 支持时长(10s 倍数)
DURATIONS: tuple[int, ...] = (30, 60, 90, 120)

#: 时长缺省值
DEFAULT_DURATION: int = 60

#: 支持风格
STYLE: tuple[str, ...] = ("1A", "1B", "2A", "2B", "3")

#: 风格中文名(proposal.md / API 回显)
STYLE_NAME: dict[str, str] = {
    "1A": "经典极简·亮(纯白底黑线)",
    "1B": "经典极简·暗(纯黑底白线)",
    "2A": "现代毛线帽·工作室科技(白高光+青蓝玻璃 UI)",
    "2B": "现代毛线帽·电影故事(全彩环境)",
    "3": "史前手绘·黑色幽默(赭棕大地+纸张纹理)",
}

#: 叙事弧(中文优先): 钩子 → 打破预期 → 机制 → 结论 → 回调
ARC_STAGES: tuple[str, ...] = ("hook", "disrupt", "mechanism", "conclusion", "callback")
ARC_NAME_ZH: dict[str, str] = {
    "hook": "钩子",
    "disrupt": "打破预期",
    "mechanism": "机制",
    "conclusion": "结论",
    "callback": "回调",
}

#: Style 3 专用弧: 铺垫 → 升级 → 反转回调
ARC_STAGES_STYLE3: tuple[str, ...] = ("setup", "escalation", "payoff")
ARC_NAME_ZH_STYLE3: dict[str, str] = {
    "setup": "铺垫",
    "escalation": "升级",
    "payoff": "反转回调",
}

# ---------------------------------------------------------------------------
# 段内三拍
# ---------------------------------------------------------------------------

#: 每个 10s 段固定三拍: [0-3s][3-7s][7-10s]
BEATS: tuple[tuple[float, float], ...] = ((0.0, 3.0), (3.0, 7.0), (7.0, 10.0))
BEAT_LABELS: tuple[str, ...] = ("establish", "escalate", "climax")

# ---------------------------------------------------------------------------
# 动作(渲染器必须全部实现)
# ---------------------------------------------------------------------------

#: 白名单动作 —— 每个都对应 pose.py 里一个参数化姿势
ACTION: tuple[str, ...] = (
    "stand",  # 站立
    "walk",  # 走
    "run",  # 跑
    "jump",  # 跳
    "point",  # 指
    "raise",  # 举物/举手
    "push_door",  # 推门
    "draw_line",  # 画线
    "sit",  # 坐
    "wave",  # 挥手
    "think",  # 思考
    "surprise",  # 惊讶
    "march",  # 原地踏步
    "kick",  # 踢
    "shuffle",  # 挪动
    "twist",  # 扭动
    "dance",  # 舞动
    "crouch",  # 蹲下
    "shrug",  # 耸肩
    "celebrate",  # 欢呼
)

#: 动作中文名
ACTION_NAME_ZH: dict[str, str] = {
    "stand": "站立",
    "walk": "行走",
    "run": "奔跑",
    "jump": "跳跃",
    "point": "指认",
    "raise": "举物",
    "push_door": "推门",
    "draw_line": "画线",
    "sit": "坐下",
    "wave": "挥手",
    "think": "思考",
    "surprise": "惊讶",
    "march": "踏步",
    "kick": "踢腿",
    "shuffle": "挪动",
    "twist": "扭身",
    "dance": "舞动",
    "crouch": "下蹲",
    "shrug": "耸肩",
    "celebrate": "欢呼",
}

#: 动作 → 是否有真实 CMU mocap 支撑(否则走参数化姿势)
ACTION_MOCAP: dict[str, str | None] = {
    "walk": "walk",
    "run": "run",
    "jump": "jump",
    "wave": "wave",
    "sit": "sit",
    "march": "march",
    "kick": "kick",
    "shuffle": "shuffle",
    "twist": "twist",
    "dance": "dance_spin",
}

# ---------------------------------------------------------------------------
# 道具
# ---------------------------------------------------------------------------

PROP: tuple[str, ...] = (
    "none",  # 无
    "line",  # 发光线
    "panel",  # 玻璃 UI 面板
    "door",  # 门
    "box",  # 箱子
    "arrow",  # 箭头
    "clock",  # 时钟(图标化)
    "chart",  # 图表(图标化)
    "spear",  # 长矛
    "fire",  # 小火堆
    "rock",  # 石头
    "rope",  # 绳子
    "map",  # 地图
    "lantern",  # 提灯
    "book",  # 书
    "gear",  # 齿轮
    "glass",  # 玻璃天花板
)

PROP_NAME_ZH: dict[str, str] = {
    "none": "无",
    "line": "发光线条",
    "panel": "玻璃面板",
    "door": "门",
    "box": "箱子",
    "arrow": "箭头",
    "clock": "时钟",
    "chart": "图表",
    "spear": "长矛",
    "fire": "火堆",
    "rock": "石头",
    "rope": "绳子",
    "map": "地图",
    "lantern": "提灯",
    "book": "书",
    "gear": "齿轮",
    "glass": "玻璃天花板",
}

# ---------------------------------------------------------------------------
# 视觉隐喻
# ---------------------------------------------------------------------------

METAPHOR: tuple[str, ...] = (
    "none",  # 无
    "ladder",  # 阶梯
    "abyss",  # 深渊
    "mountain",  # 高山
    "treadmill",  # 跑步机
    "maze",  # 迷宫
    "iceberg",  # 冰山
    "domino",  # 多米诺
    "funnel",  # 漏斗
    "bridge",  # 桥
    "mirror",  # 镜子
    "magnet",  # 磁铁
    "cage",  # 笼子
    "horizon",  # 地平线
    "hourglass",  # 沙漏
)

METAPHOR_NAME_ZH: dict[str, str] = {
    "none": "无",
    "ladder": "阶梯",
    "abyss": "深渊",
    "mountain": "高山",
    "treadmill": "跑步机",
    "maze": "迷宫",
    "iceberg": "冰山",
    "domino": "多米诺",
    "funnel": "漏斗",
    "bridge": "桥",
    "mirror": "镜子",
    "magnet": "磁铁",
    "cage": "笼子",
    "horizon": "地平线",
    "hourglass": "沙漏",
}

# ---------------------------------------------------------------------------
# 镜头
# ---------------------------------------------------------------------------

CAMERA: tuple[str, ...] = (
    "static",  # 固定
    "push_in",  # 推
    "pull_out",  # 拉
    "pan",  # 摇
    "track",  # 跟
    "shake",  # 震
    "tilt",  # 俯仰
    "orbit",  # 环绕
)

CAMERA_NAME_ZH: dict[str, str] = {
    "static": "固定",
    "push_in": "推近",
    "pull_out": "拉远",
    "pan": "摇镜",
    "track": "跟拍",
    "shake": "震动",
    "tilt": "俯仰",
    "orbit": "环绕",
}

# ---------------------------------------------------------------------------
# 转场
# ---------------------------------------------------------------------------

TRANSITION: tuple[str, ...] = (
    "cut",  # 硬切
    "match_cut",  # 匹配剪辑
    "whip_pan",  # 甩镜
    "fade",  # 淡入淡出
    "wipe",  # 划像
    "dip_black",  # 黑场
)

TRANSITION_NAME_ZH: dict[str, str] = {
    "cut": "硬切",
    "match_cut": "匹配剪辑",
    "whip_pan": "甩镜",
    "fade": "淡入淡出",
    "wipe": "划像",
    "dip_black": "黑场",
}

# ---------------------------------------------------------------------------
# SFX(键 = feat/sfx-badclips 库里的目录名;取值可空 = 该类别可用)
# ---------------------------------------------------------------------------

SFX: tuple[str, ...] = (
    "none",
    "whoosh",
    "impact",
    "boom",
    "pop",
    "click",
    "tick",
    "chime",
    "ding",
    "swipe",
    "swoosh",
    "sparkle",
    "riser",
    "glitch",
    "shutter",
    "typewriter",
    "heartbeat",
    "bassdrop",
    "downer",
    "notification",
)

SFX_NAME_ZH: dict[str, str] = {
    "none": "无",
    "whoosh": "呼啸",
    "impact": "撞击",
    "boom": "轰鸣",
    "pop": "弹出",
    "click": "点击",
    "tick": "滴答",
    "chime": "风铃",
    "ding": "提示音",
    "swipe": "滑动",
    "swoosh": "疾掠",
    "sparkle": "闪烁",
    "riser": "上升",
    "glitch": "故障",
    "shutter": "快门",
    "typewriter": "打字机",
    "heartbeat": "心跳",
    "bassdrop": "低音下坠",
    "downer": "下坠",
    "notification": "通知",
}

# ---------------------------------------------------------------------------
# BGM(程序化合成 mood)
# ---------------------------------------------------------------------------

BGM: tuple[str, ...] = (
    "calm",
    "warm",
    "tense",
    "epic",
    "playful",
    "somber",
    "curious",
)

BGM_NAME_ZH: dict[str, str] = {
    "calm": "平静",
    "warm": "温暖",
    "tense": "紧张",
    "epic": "恢弘",
    "playful": "俏皮",
    "somber": "沉郁",
    "curious": "好奇",
}

# ---------------------------------------------------------------------------
# 强调色(Style 1 最多 3 种, 普通描述词, 禁 hex)
# ---------------------------------------------------------------------------

ACCENT: tuple[str, ...] = (
    "vivid_red",  # 鲜红
    "electric_blue",  # 电光蓝
    "warm_gold",  # 暖金
    "emerald_green",  # 翠绿
    "hot_pink",  # 亮粉
    "deep_purple",  # 深紫
)

ACCENT_NAME_ZH: dict[str, str] = {
    "vivid_red": "鲜红",
    "electric_blue": "电光蓝",
    "warm_gold": "暖金",
    "emerald_green": "翠绿",
    "hot_pink": "亮粉",
    "deep_purple": "深紫",
}

# ---------------------------------------------------------------------------
# 调度(按画幅)
# ---------------------------------------------------------------------------

#: 9:16 纵深/上下堆叠;16:9 左中右
STAGING_9_16: tuple[str, ...] = ("foreground", "midground", "background", "top", "bottom")
STAGING_16_9: tuple[str, ...] = ("left", "center", "right")

STAGING_NAME_ZH: dict[str, str] = {
    "foreground": "前景",
    "midground": "中景",
    "background": "远景",
    "top": "上部",
    "bottom": "下部",
    "left": "左侧",
    "center": "中部",
    "right": "右侧",
}


def staging_for(aspect: str) -> tuple[str, ...]:
    """该画幅允许的调度位置。"""
    if aspect == "9:16":
        return STAGING_9_16
    if aspect == "16:9":
        return STAGING_16_9
    raise ValueError(f"unknown aspect {aspect!r}; have {ASPECT}")


# ---------------------------------------------------------------------------
# 校验工具
# ---------------------------------------------------------------------------

#: 字段名 → 白名单元组
FIELDS: dict[str, tuple[str, ...]] = {
    "action": ACTION,
    "prop": PROP,
    "metaphor": METAPHOR,
    "camera": CAMERA,
    "transition": TRANSITION,
    "sfx": SFX,
    "bgm": BGM,
    "accent": ACCENT,
    "style": STYLE,
    "aspect": ASPECT,
}


def is_valid(field: str, value: str) -> bool:
    """``value`` 是否在 ``field`` 白名单内(未知字段 → False)。"""
    allowed = FIELDS.get(field)
    if allowed is None:
        return False
    return value in allowed


def coerce(field: str, value: str, default: str) -> tuple[str, bool]:
    """把 ``value`` 收敛到白名单。

    返回 ``(结果, 是否被修正)``。``default`` 必须本身在白名单内(否则抛错)。
    """
    allowed = FIELDS.get(field)
    if allowed is None:
        raise KeyError(f"unknown whitelist field {field!r}")
    if default not in allowed:
        raise ValueError(f"default {default!r} not in whitelist for {field!r}")
    if value in allowed:
        return value, False
    return default, True


def assert_renderable(actions: Iterable[str]) -> None:
    """渲染器可实现的动作不变式(测试用)。"""
    from hevi.layer4_legacy.stickdir import pose

    missing = sorted({a for a in actions if a not in pose.POSES})
    if missing:
        raise AssertionError(f"whitelist actions without a renderer pose: {missing}")


__all__ = [
    "ACCENT",
    "ACCENT_NAME_ZH",
    "ACTION",
    "ACTION_MOCAP",
    "ACTION_NAME_ZH",
    "ARC_NAME_ZH",
    "ARC_NAME_ZH_STYLE3",
    "ARC_STAGES",
    "ARC_STAGES_STYLE3",
    "ASPECT",
    "BEATS",
    "BEAT_LABELS",
    "BGM",
    "BGM_NAME_ZH",
    "CAMERA",
    "CAMERA_NAME_ZH",
    "DEFAULT_DURATION",
    "DURATIONS",
    "FIELDS",
    "METAPHOR",
    "METAPHOR_NAME_ZH",
    "PROP",
    "PROP_NAME_ZH",
    "SFX",
    "SFX_NAME_ZH",
    "STAGING_16_9",
    "STAGING_9_16",
    "STAGING_NAME_ZH",
    "STYLE",
    "STYLE_NAME",
    "TRANSITION",
    "TRANSITION_NAME_ZH",
    "assert_renderable",
    "coerce",
    "is_valid",
    "staging_for",
]
