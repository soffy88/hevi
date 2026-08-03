"""Cue-aware explainer assembly boundary.

The installed ``omodul`` release currently exposes
``narrated_video_produce`` rather than the newer
``video_assemble_workflow`` name.  This module resolves the public operation
at runtime and keeps the input/output contract stable for the eventual 3O
package upgrade.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from hevi.explainer.contracts import ExplainerCue
from hevi.explainer.production import NarratedRenderResult, render_narrated_storyboard
from hevi.explainer.props import normalise_visual_config, process_cues_for_remotion
from hevi.explainer.schemas import SceneType, Storyboard, StoryboardSegment, validate_props


def _props_for(index: int, text: str) -> tuple[str, dict[str, Any]]:
    """Create valid legacy scene props for a free-form v6 cue."""
    options = [
        (
            "hook",
            {
                "title": text[:12],
                "subtitle": "深度解说",
                "items": [{"emoji": "🎙️", "label": "重点"}],
            },
        ),
        (
            "definition",
            {
                "question": text[:30],
                "formulaHead": "核心概念",
                "formulaLines": ["= 事实与证据", "= 可验证结论"],
                "sinkEmojis": ["📌", "🔎"],
                "splitLeft": {"emoji": "📚", "title": "材料", "sub": "来源与背景"},
                "splitRight": {"emoji": "🧭", "title": "结论", "sub": "行动方向"},
            },
        ),
        (
            "cards",
            {"header": "关键画面", "cards": [{"emoji": "📰", "title": "证据", "desc": text[:40]}]},
        ),
        (
            "reason",
            {
                "question": "为什么重要？",
                "brainLine": text[:40],
                "bubbleText": "把证据放回上下文。",
                "leftLabel": {"title": "只看表面", "sub": "容易误判"},
                "rightLabel": {"title": "看清机制", "sub": "做出判断"},
            },
        ),
        (
            "method",
            {
                "header": "三个检查动作",
                "points": [
                    {"num": "1", "title": text[:24], "sub": "核对来源与时间"}
                ],
            },
        ),
        (
            "outro",
            {
                "setupLine1": "把复杂问题讲清楚。",
                "setupLine2": "下一次做决定前，记住这句话。",
                "quoteLine1": text[:20],
                "quoteLine2": "证据决定判断。",
                "ctaEmojis": ["👍", "⭐", "🔔"],
                "ctaText": "点赞 · 收藏 · 关注",
                "byline": "我们下期见",
            },
        ),
    ]
    scene_type, raw_props = options[index % len(options)]
    scene_type = cast(SceneType, scene_type)
    raw_props = cast(dict[str, Any], raw_props)
    return scene_type, validate_props(scene_type, raw_props)


def cues_to_storyboard(topic: str, cues: list[ExplainerCue]) -> Storyboard:
    segments: list[StoryboardSegment] = []
    for index, cue in enumerate(cues):
        scene_type, props = _props_for(index, cue.text)
        # 防御解析:visual_config 里的嵌套对象(如 chart_data)若被序列化成 JSON
        # 字符串,先还原成 dict 再进 manifest——下游 Remotion 模板对这些字段做
        # 对象链式访问,字符串会直接 TypeError 炸掉渲染。
        visual_config = normalise_visual_config(cue.visual_config)
        # 顶层字段只覆盖非 None 值:视觉配置里已有的 chart_data 不应被顶层的
        # None 冲掉(legacy LLM 直出常把 chart_data 塞在 visual_config 里)。
        for key, value in (
            ("time_range", cue.time_range),
            ("target_url", cue.target_url),
            ("highlight_selector", cue.highlight_selector),
            ("chart_data", cue.chart_data),
            ("code_text", cue.code_text),
            ("language", cue.language),
        ):
            if value is not None:
                visual_config[key] = value
        segments.append(
            StoryboardSegment(
                id=f"cue-{index + 1}",
                scene_type=scene_type,  # type: ignore[arg-type]
                narration=cue.text,
                keywords=[word for word in cue.text.split() if word][:2],
                props=props,
                visual_type=cue.visual_type,
                visual_config=visual_config,
            )
        )
    return Storyboard(topic=topic, segments=segments)


async def assemble_explainer_cues(
    topic: str,
    cues: list[ExplainerCue],
    output_dir: Path,
    *,
    voice: str,
    enable_circle_avatar_mask: bool = True,
    enable_remotion_code_render: bool = True,
    enable_browser_broll: bool = True,
    aspect_ratio: str = "9:16",
    heygen_presenter_id: str | None = None,
    presenter_provider: str = "heygen",
    presenter_name: str = "HEVI 数字人",
    heygen_provider: Any = None,
    broll_recorder: Any = None,
) -> NarratedRenderResult:
    """Compile edited cues and run the standard injected Remotion transaction."""
    if aspect_ratio not in {"9:16", "16:9"}:
        raise ValueError("aspect_ratio 仅支持 9:16 或 16:9")
    # 装配入参防御解析:确稿台/旧客户端可能把 cue 或嵌套字段(visual_config /
    # chart_data)序列化成 JSON 字符串;这里统一规整成安全形状,脏条目直接丢弃。
    prepared_cues = process_cues_for_remotion(cues)
    if not prepared_cues:
        raise ValueError("装配入参没有可用的视觉脚手架 cue")
    avatar_indices = [
        index for index, cue in enumerate(prepared_cues) if cue.visual_type == "heygen_avatar"
    ]
    if avatar_indices:
        if presenter_provider == "remotion":
            for index in avatar_indices:
                prepared_cues[index].visual_config.update(
                    {
                        "local_presenter": True,
                        "presenter_name": presenter_name,
                    }
                )
        else:
            if not heygen_presenter_id:
                raise ValueError("HeyGen 数字人缺少供应商 presenter ID")
            if heygen_provider is None:
                from hevi.explainer.heygen import heygen_avatar_generate

                heygen_provider = heygen_avatar_generate

            avatar_dir = output_dir / "heygen"
            for index in avatar_indices:
                avatar_path = avatar_dir / f"cue-{index + 1}.mp4"
                generated = await heygen_provider(
                    text=prepared_cues[index].text,
                    presenter_id=heygen_presenter_id,
                    output_path=avatar_path,
                )
                prepared_cues[index].visual_config["assetUrl"] = str(generated)
    if any(cue.visual_type == "browser_broll" for cue in prepared_cues):
        if not enable_browser_broll:
            raise ValueError("browser B-roll is disabled for this task")
        if broll_recorder is None:
            from hevi.sourcing.browser_broll import browser_broll_recorder

            broll_recorder = browser_broll_recorder

        broll_dir = output_dir / "browser_broll"
        for index, cue in enumerate(prepared_cues):
            if cue.visual_type != "browser_broll":
                continue
            if not cue.target_url:
                raise ValueError(f"cue {index + 1} 缺少 target_url")
            broll_path = broll_dir / f"cue-{index + 1}.webm"
            await broll_recorder(
                cue.target_url,
                highlight_selector=cue.highlight_selector,
                duration_s=cue.time_estimate_s or 5.0,
                aspect_ratio=aspect_ratio,
                output_path=broll_path,
            )
            cue.visual_config["assetUrl"] = str(broll_path)
    storyboard = cues_to_storyboard(topic, prepared_cues)
    for cue in prepared_cues:
        if cue.visual_type == "remotion_code" and not enable_remotion_code_render:
            raise ValueError("remotion code rendering is disabled for this task")
    # The renderer reads visual_type/config from each manifest segment.  The
    # current Remotion template supports the same contract and ignores a
    # missing optional asset gracefully.
    if not enable_circle_avatar_mask:
        for segment in storyboard.segments:
            if segment.visual_type == "heygen_avatar":
                segment.visual_config["circle_avatar_mask"] = False
    return await render_narrated_storyboard(storyboard, output_dir, voice=voice)
