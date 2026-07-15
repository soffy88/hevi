"""非完美事件库(HEVI 路线图 Phase3 #38)。

AI 视频最大的破绽之一是"过于完美"——verité/真实感类预设(vlog/纪录片/家庭录像
一类)尤其需要一点不完美感才像真实拍摄,而不是每一帧都精准如广告片。四类事件:
摄影师失误 / 环境介入 / 主体自然行为 / 收束方式。

逐镜头挑一个、全片不重复("不重复"的范围是**一次装配/一个视频**,不是这个库
被用过一次就永久拉黑——调用方自己维护一个 `used` 集合,贯穿一次视频生成的
全部镜头调用即可,视频与视频之间应该各自新建集合)。库存量有限,用完就没有
更多可挑的(返回 None),不强行重复凑数——"平淡"好过"看得出来在硬凑"。
"""

from __future__ import annotations

import random

CAMERA_MISHAP = "摄影师失误"
ENVIRONMENTAL_INTRUSION = "环境介入"
NATURAL_BEHAVIOR = "主体自然行为"
CLOSING_STYLE = "收束方式"

IMPERFECTION_EVENTS: dict[str, list[str]] = {
    CAMERA_MISHAP: [
        "the lens racks focus briefly then snaps back",
        "a slight handheld shake as the camera repositions",
        "brief overexposure that self-corrects a moment later",
    ],
    ENVIRONMENTAL_INTRUSION: [
        "a gust of wind stirs a curtain in the background",
        "a passerby briefly crosses into frame then exits",
        "the light shifts subtly as clouds pass overhead",
    ],
    NATURAL_BEHAVIOR: [
        "an unconscious blink or hand brushing through hair",
        "a brief pause as if lost in thought",
        "an unscripted small laugh or half-smile",
    ],
    CLOSING_STYLE: [
        "the shot fades out slowly rather than cutting hard",
        "a slight lingering shake before the frame settles",
        "the final frame drifts slightly out of focus",
    ],
}


def pick_imperfection_event(*, used: set[str], rng: random.Random | None = None) -> str | None:
    """从库里挑一个还没用过的非完美事件(不分类别,只保证全局不重复)。

    全部用完(`used` 覆盖了库里所有条目)→ None,调用方据此跳过这一镜头的
    非完美感注入,不强行重复。挑中的事件会被加进 `used`(原地修改)。
    """
    r = rng or random
    all_events = [e for events in IMPERFECTION_EVENTS.values() for e in events]
    candidates = [e for e in all_events if e not in used]
    if not candidates:
        return None
    choice = r.choice(candidates)
    used.add(choice)
    return choice
