"""xfade 转场注册表 — 集中管理 ffmpeg xfade filter 支持的转场枚举与自定义表达式。

本模块被 hevi.assembly.assembler.build_xfade_chain 消费，也由 hevi.studio 的
NLE TRANSITIONS 面板读取（T1 后续对接）。每条注册项：

  - id            字符串标识符，用作 build_xfade_chain.transition 的参数值
  - name_zh       中文名称，供 UI 展示
  - kind          "builtin" | "custom"
  - ffmpeg        builtin 时 = 转场名；custom 时 = xfade expr 字符串
  - tags          描述性标签列表（soft/hard/energetic/glitch/zoom/wipe/fade 等）
  - default_duration  推荐的默认重叠时长（秒）

builtin 枚举来自 ffmpeg -hide_banner -h filter=xfade 实际输出核对，
本机 ffmpeg 7.0.2 共 58 个（0-57），全部实测可跑。
custom 转场使用 xfade=transition=custom:expr=...，表达式变量为 X,Y,W,H,P,A,B。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Transition:
    id: str
    name_zh: str
    kind: Literal["builtin", "custom"]
    ffmpeg: str  # builtin 名或 custom expr
    tags: list[str]
    default_duration: float = 0.5


# ── builtin 转场（58 个，经 ffmpeg 7.0.2 实测）─────────────────────────

_BUILTIN_TRANSITIONS: list[Transition] = [
    Transition("fade", "淡入淡出", "builtin", "fade", ["soft"], 0.5),
    Transition("fadeblack", "黑淡", "builtin", "fadeblack", ["soft"], 0.5),
    Transition("fadewhite", "白淡", "builtin", "fadewhite", ["soft"], 0.5),
    Transition("fadegrays", "灰淡", "builtin", "fadegrays", ["soft"], 0.5),
    Transition("fadefast", "快淡", "builtin", "fadefast", ["soft", "fast"], 0.3),
    Transition("fadeslow", "慢淡", "builtin", "fadeslow", ["soft", "slow"], 0.8),
    Transition("dissolve", "溶解", "builtin", "dissolve", ["soft"], 0.5),
    Transition("wipeleft", "左擦", "builtin", "wipeleft", ["hard", "wipe"], 0.5),
    Transition("wiperight", "右擦", "builtin", "wiperight", ["hard", "wipe"], 0.5),
    Transition("wipeup", "上擦", "builtin", "wipeup", ["hard", "wipe"], 0.5),
    Transition("wipedown", "下擦", "builtin", "wipedown", ["hard", "wipe"], 0.5),
    Transition("slideleft", "左滑", "builtin", "slideleft", ["hard", "slide"], 0.5),
    Transition("slideright", "右滑", "builtin", "slideright", ["hard", "slide"], 0.5),
    Transition("slideup", "上滑", "builtin", "slideup", ["hard", "slide"], 0.5),
    Transition("slidedown", "下滑", "builtin", "slidedown", ["hard", "slide"], 0.5),
    Transition("smoothleft", "平滑左", "builtin", "smoothleft", ["soft", "slide"], 0.5),
    Transition("smoothright", "平滑右", "builtin", "smoothright", ["soft", "slide"], 0.5),
    Transition("smoothup", "平滑上", "builtin", "smoothup", ["soft", "slide"], 0.5),
    Transition("smoothdown", "平滑下", "builtin", "smoothdown", ["soft", "slide"], 0.5),
    Transition("circlecrop", "圆裁", "builtin", "circlecrop", ["hard", "zoom"], 0.5),
    Transition("rectcrop", "方裁", "builtin", "rectcrop", ["hard"], 0.5),
    Transition("distance", "距离", "builtin", "distance", ["hard"], 0.5),
    Transition("radial", "径向", "builtin", "radial", ["hard", "zoom"], 0.5),
    Transition("circleopen", "圆开", "builtin", "circleopen", ["hard", "zoom"], 0.5),
    Transition("circleclose", "圆闭", "builtin", "circleclose", ["hard", "zoom"], 0.5),
    Transition("vertopen", "竖开", "builtin", "vertopen", ["hard"], 0.5),
    Transition("vertclose", "竖闭", "builtin", "vertclose", ["hard"], 0.5),
    Transition("horzopen", "横开", "builtin", "horzopen", ["hard"], 0.5),
    Transition("horzclose", "横闭", "builtin", "horzclose", ["hard"], 0.5),
    Transition("pixelize", "像素化", "builtin", "pixelize", ["hard", "glitch"], 0.5),
    Transition("diagtl", "对角左上", "builtin", "diagtl", ["hard"], 0.5),
    Transition("diagtr", "对角右上", "builtin", "diagtr", ["hard"], 0.5),
    Transition("diagbl", "对角左下", "builtin", "diagbl", ["hard"], 0.5),
    Transition("diagbr", "对角右下", "builtin", "diagbr", ["hard"], 0.5),
    Transition("hlslice", "水平左上切", "builtin", "hlslice", ["hard", "slice"], 0.5),
    Transition("hrslice", "水平右下切", "builtin", "hrslice", ["hard", "slice"], 0.5),
    Transition("vuslice", "垂直下上切", "builtin", "vuslice", ["hard", "slice"], 0.5),
    Transition("vdslice", "垂直上下载", "builtin", "vdslice", ["hard", "slice"], 0.5),
    Transition("hblur", "水平模糊", "builtin", "hblur", ["soft", "glitch"], 0.5),
    Transition("wipetl", "斜左上擦", "builtin", "wipetl", ["hard", "wipe"], 0.5),
    Transition("wipetr", "斜右上擦", "builtin", "wipetr", ["hard", "wipe"], 0.5),
    Transition("wipebl", "斜左下擦", "builtin", "wipebl", ["hard", "wipe"], 0.5),
    Transition("wipebr", "斜右下擦", "builtin", "wipebr", ["hard", "wipe"], 0.5),
    Transition("squeezeh", "水平挤压", "builtin", "squeezeh", ["hard", "energetic"], 0.5),
    Transition("squeezev", "垂直挤压", "builtin", "squeezev", ["hard", "energetic"], 0.5),
    Transition("zoomin", "缩放进入", "builtin", "zoomin", ["hard", "zoom", "energetic"], 0.5),
    Transition("hlwind", "水平旋风", "builtin", "hlwind", ["hard", "energetic"], 0.5),
    Transition("hrwind", "水平旋风右", "builtin", "hrwind", ["hard", "energetic"], 0.5),
    Transition("vuwind", "垂直旋风上", "builtin", "vuwind", ["hard", "energetic"], 0.5),
    Transition("vdwind", "垂直旋风下", "builtin", "vdwind", ["hard", "energetic"], 0.5),
    Transition("coverleft", "左覆盖", "builtin", "coverleft", ["hard", "wipe"], 0.5),
    Transition("coverright", "右覆盖", "builtin", "coverright", ["hard", "wipe"], 0.5),
    Transition("coverup", "上覆盖", "builtin", "coverup", ["hard", "wipe"], 0.5),
    Transition("coverdown", "下覆盖", "builtin", "coverdown", ["hard", "wipe"], 0.5),
    Transition("revealleft", "左揭示", "builtin", "revealleft", ["hard"], 0.5),
    Transition("revealright", "右揭示", "builtin", "revealright", ["hard"], 0.5),
    Transition("revealup", "上揭示", "builtin", "revealup", ["hard"], 0.5),
    Transition("revealdown", "下揭示", "builtin", "revealdown", ["hard"], 0.5),
]

# ── custom 转场（6 个，使用 xfade custom:expr=...）───────────────────
# 表达式变量: X,Y 像素坐标; W,H 画面宽高; P 过渡进度 [0,1]; A,B 两输入画面

_CUSTOM_EXPRESSIONS: list[Transition] = [
    Transition(
        "whip",
        "甩镜",
        "custom",
        "X+P*W*(A-B)/W",
        ["hard", "energetic", "wipe"],
        0.4,
    ),
    Transition(
        "burn",
        "灼烧",
        "custom",
        "A*(1-P*P)+(B-A)*P*P",
        ["hard", "energetic"],
        0.5,
    ),
    Transition(
        "glitch",
        "故障",
        "custom",
        "X+(B-A)*sin(P*6.28)*W/4",
        ["hard", "glitch"],
        0.4,
    ),
    Transition(
        "flash",
        "闪白",
        "custom",
        "A+(B-A)*P*P",
        ["soft", "energetic"],
        0.3,
    ),
    Transition(
        "zoom_punch",
        "推进冲击",
        "custom",
        "A*(1-P)+B*P*(1+P*0.5)",
        ["hard", "zoom", "energetic"],
        0.5,
    ),
    Transition(
        "ink",
        "墨晕",
        "custom",
        "A*(1-P)+B*P+sin(P*3.14)*0.1",
        ["soft"],
        0.6,
    ),
]

ALL_TRANSITIONS: list[Transition] = _BUILTIN_TRANSITIONS + _CUSTOM_EXPRESSIONS

# 按 id 索引
_ID_INDEX: dict[str, Transition] = {t.id: t for t in ALL_TRANSITIONS}


def list_transitions() -> list[dict]:
    """返回全部注册转场的列表（字典形式，便于 JSON 序列化）。"""
    return [
        {
            "id": t.id,
            "name_zh": t.name_zh,
            "kind": t.kind,
            "ffmpeg": t.ffmpeg,
            "tags": t.tags,
            "default_duration": t.default_duration,
        }
        for t in ALL_TRANSITIONS
    ]


def get_transition(id_: str) -> Transition:
    """按 id 查转场，未知 id 抛 ValueError。"""
    try:
        return _ID_INDEX[id_]
    except KeyError:
        available = ", ".join(sorted(_ID_INDEX.keys()))
        raise ValueError(f"Unknown transition id '{id_}'. Available: {available}") from None


def resolve(id_: str) -> str:
    """解析 id → xfade filter 中 transition= 后的值。

    builtin 直接返回 id 本身（ffmpeg 识别的转场名）。
    custom 返回 'custom:expr=...' 片段，供 build_xfade_chain 拼入 filter_complex。
    """
    t = get_transition(id_)
    if t.kind == "builtin":
        return t.ffmpeg
    else:
        return f"custom:expr={t.ffmpeg}"
