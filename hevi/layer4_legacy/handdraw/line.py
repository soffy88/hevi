"""Hevi Handdraw Line: production entry point for line=handdraw.

Provides standard line fulfillment interface:
`render_handdraw_line(order, output_dir)`
Supports topics, scripts, landscape (1920x1080) and portrait (1080x1920),
and the 4 required styles: 1, 8, 10, 17.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.handdraw.pipeline import render_handdraw_pipeline

logger = logging.getLogger(__name__)

# Pre-designed high-fidelity storyboards for the two qualification topics
# Sized specifically to yield 45-65 seconds of high-density spoken narration
STANDARD_TOPIC_STORYBOARDS: dict[str, dict[str, Any]] = {
    "anger_decision": {
        "title": "为什么越生气越容易做错决定",
        "style_id": "8",  # 水墨写意
        "hand_preset": "navy",  # 深蓝袖马克笔
        "pages": [
            {
                "title": "一、情绪风暴的神经机制",
                "scene_key": "anger_brain",
                "note": "杏仁核劫持理性大脑",
                "beats": [
                    {
                        "text": "在生活中，你是否曾因一时愤怒，做出了让自己后悔莫及的糟糕决定？",
                        "note": "生活常见错误反思",
                    },
                    {
                        "text": "脑科学研究表明，愤怒会瞬间激活深层的情绪中枢杏仁核，使前额叶理性皮层短暂离线。",
                        "note": "神经生物学因果机制",
                    },
                ],
            },
            {
                "title": "二、理智与情绪的天平失衡",
                "scene_key": "balance_scale",
                "note": "决策天平严重偏向冲动",
                "beats": [
                    {
                        "text": "在远古进化本能的驱动下，大脑误以为面对生死威胁，强行压制了长远的得失权衡。",
                        "note": "远古应激反应机制",
                    },
                    {
                        "text": "此时的认知天平被冲动彻底霸占，微小的口角被无限放大，最终演变成不可挽回的毁灭行为。",
                        "note": "非理性决策的连锁代价",
                    },
                ],
            },
            {
                "title": "三、十二秒黄金冷静法则",
                "scene_key": "calm_decision",
                "note": "深呼吸让前额叶重新接管",
                "beats": [
                    {
                        "text": "神经科学家指出，情绪化学物质在体内的代谢峰值，往往只有关键的十二秒。",
                        "note": "生理代谢时间窗口",
                    },
                    {
                        "text": "深呼吸三次，为前额叶争取重新接管的时间，在情绪冷却后再做决定，才是成人的顶级智慧。",
                        "note": "收束与长远决策复盘",
                    },
                ],
            },
        ],
    },
    "compound_interest": {
        "title": "复利效应：普通人逆袭的数学杠杆",
        "style_id": "1",  # 极简黑白线条
        "hand_preset": "pen-only",  # 仅画笔 · 无手臂
        "pages": [
            {
                "title": "一、长坡厚雪的滚雪球思维",
                "scene_key": "snowball_effect",
                "note": "起点虽小但坡道足够长",
                "beats": [
                    {
                        "text": "巴菲特曾将一生的财富积累总结为：人生就像滚雪球，最重要的是发现很湿的雪和很长的坡。",
                        "note": "核心隐喻概念引入",
                    },
                    {
                        "text": "在起步阶段，雪球的微弱增长几乎肉眼难辨，九成以上的人在这一漫长的平庸期选择了放弃。",
                        "note": "常见认知盲区揭示",
                    },
                ],
            },
            {
                "title": "二、跨越冰点后的爆发奇迹",
                "scene_key": "growth_curves",
                "note": "指数曲线超越线性积累",
                "beats": [
                    {
                        "text": "普通人习惯线性思维，误以为努力与回报成正比，而复利是典型的大后期指数级爆发曲线。",
                        "note": "线性与指数数学对比",
                    },
                    {
                        "text": "只要保持每年哪怕微弱的正向迭代，越过拐点之后，累积资产将呈现几何级数的垂直跃升。",
                        "note": "拐点飞跃机制剖析",
                    },
                ],
            },
            {
                "title": "三、时间给长期主义者的奖赏",
                "scene_key": "coin_pyramid",
                "note": "微小习惯铸就复利金字塔",
                "beats": [
                    {
                        "text": "不仅金钱遵循复利，知识储备、技能磨练和健康习惯同样受这一底层宇宙法则支配。",
                        "note": "普适认知迁移与应用",
                    },
                    {
                        "text": "保持耐心，拒绝短期暴利诱惑，把时间当成最坚定的盟友，平凡坚持终将汇聚成不可撼动的奇迹。",
                        "note": "长期主义行动收束",
                    },
                ],
            },
        ],
    },
}


def _match_topic_spec(topic: str) -> dict[str, Any]:
    """Route every Studio handdraw topic to a preschool-safe storyboard template."""
    from hevi.layer4_legacy.handdraw.kids_storyboards import select_kids_storyboard

    spec = select_kids_storyboard(topic)
    return {
        "title": spec["title"],
        "style_id": "17",
        "hand_preset": "navy",
        "theme": spec["theme"],
        "stages": spec["stages"],
        "pages": spec["pages"],
    }

async def render_handdraw_line(
    order: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    """Fulfills line=handdraw requests from Hevi Studio."""
    topic = str(order.get("topic") or order.get("title") or "小狐狸学会轮流").strip()
    canvas_w = int(order.get("width") or order.get("canvas_width") or 1920)
    canvas_h = int(order.get("height") or order.get("canvas_height") or 1080)
    style_id = str(order.get("style_id") or order.get("style") or "17").strip()
    hand_preset = str(order.get("hand_preset") or order.get("hand") or "navy").strip()
    spec = _match_topic_spec(topic)
    if style_id not in {"1", "8", "10", "17"}:
        raise ValueError(f"unsupported style_id: {style_id}")
    if hand_preset not in {"navy", "pen-only"}:
        raise ValueError(f"unsupported hand_preset: {hand_preset}")
    final_style_id = style_id
    final_hand = hand_preset

    job_id = str(order.get("job_id") or order.get("slate_id") or "handdraw_job")

    from hevi.layer4_legacy.handdraw.kids_storyboards import validate_kids_script
    from hevi.layer4_legacy.handdraw.layout import compute_canvas_layout

    if (canvas_w, canvas_h) not in {(1920, 1080), (1080, 1920)}:
        raise ValueError("handdraw canvas must be 1920x1080 or 1080x1920")
    layout = compute_canvas_layout(canvas_w, canvas_h)
    safety = validate_kids_script(
        topic,
        spec["pages"],
        aspect="16:9" if canvas_w >= canvas_h else "9:16",
        caption_font_size=layout.caption_font_size,
    )
    if not safety["passed"]:
        raise ValueError(f"KIDS_ANIME_DIRECTION gate failed before rendering: {safety['checks']}")

    result = render_handdraw_pipeline(
        job_id=job_id,
        title=spec["title"],
        pages_spec=spec["pages"],
        output_dir=output_dir,
        canvas_size=(canvas_w, canvas_h),
        style_id=final_style_id,
        hand_preset=final_hand,
        seed=int(order.get("seed") or 0),
    )

    return {
        "status": "completed",
        "target": "handdraw",
        "line_id": "handdraw",
        "video_path": result["video_path"],
        "cover_path": result["cover_path"],
        "srt_path": result["srt_path"],
        "script_path": result["script_path"],
        "verification_path": result["verification_path"],
        "sha256": result["sha256"],
        "duration": result["duration"],
        "lufs": result["lufs"],
        "canvas": f"{canvas_w}x{canvas_h}",
        "style_id": final_style_id,
        "hand_preset": final_hand,
        "kids_safety_path": result.get("kids_safety_path"),
        "human_review": "pending",
    }
