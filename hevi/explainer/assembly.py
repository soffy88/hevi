"""Cue-aware explainer assembly boundary.

The installed ``omodul`` release currently exposes
``narrated_video_produce`` rather than the newer
``video_assemble_workflow`` name.  This module resolves the public operation
at runtime and keeps the input/output contract stable for the eventual 3O
package upgrade.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast

from hevi.explainer.contracts import ExplainerCue
from hevi.explainer.production import NarratedRenderResult, render_narrated_storyboard
from hevi.explainer.props import normalise_visual_config, process_cues_for_remotion
from hevi.explainer.schemas import SceneType, Storyboard, StoryboardSegment, validate_props

logger = logging.getLogger(__name__)


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
                "points": [{"num": "1", "title": text[:24], "sub": "核对来源与时间"}],
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
            ("visual_search_query", getattr(cue, "visual_search_query", "") or ""),
            ("layout_mode", getattr(cue, "layout_mode", "fullscreen") or "fullscreen"),
            ("audio_style", getattr(cue, "audio_style", "formal") or "formal"),
        ):
            if value is not None and str(value).strip():
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


async def _fulfill_stock_visuals(
    cues: list[ExplainerCue], stock_svc: Any, output_dir: Path
) -> None:
    """🚨 v9.0: 视觉素材装填 —— 为 stock_broll cues 检索真实画面。
    
    遍历所有 cues，对 visual_type==stock_broll 且没有 mediaUrl 的条目：
    1. 从 cue.visual_search_query 提取关键词
    2. 调用 StockSearchService.search() 检索 Pexels
    3. 将最佳匹配的 preview_url 写入 cue.visual_config[assetUrl]
    4. 如果检索失败，降级为 browser_broll fallback（用 search query 搜图）
    """
    
    for idx, cue in enumerate(cues):
        if cue.visual_type != "stock_broll":
            continue
        
        # Skip if already has a media URL
        if cue.visual_config.get("assetUrl"):
            continue
        
        query = getattr(cue, "visual_search_query", "") or ""
        if not query.strip():
            logger.warning(f"stock_broll cue {idx} missing visual_search_query; skipping")
            cue.visual_type = "voiceover"  # degrade gracefully
            continue
        
        try:
            results = await stock_svc.search(
                user_id="explainer_session",
                query=query,
                media_type="video",
                count=3,
            )
            if results:
                best = results[0] if isinstance(results, list) else results.get("results", [{}])[0]
                preview = best.get("preview_url") or best.get("video_url")
                if preview:
                    cue.visual_config["assetUrl"] = preview
                    logger.info(f"stock_broll cue {idx}: fetched {preview[:80]}...")
                    continue
        except Exception as exc:
            logger.warning(f"Pexels search failed for cue {idx}: {exc}")
        
        # Fallback: use image instead of video
        try:
            img_results = await stock_svc.search(
                user_id="explainer_session",
                query=query,
                media_type="image",
                count=1,
            )
            if img_results:
                best = (
                    img_results[0]
                    if isinstance(img_results, list)
                    else img_results.get("results", [{}])[0]
                )
                img_url = best.get("thumbnail_url") or best.get("preview_url")
                if img_url:
                    cue.visual_config["assetUrl"] = img_url
                    logger.info(f"stock_broll cue {idx}: fallback image {img_url[:80]}...")
        except Exception as img_exc:
            logger.error(f"All stock fallbacks failed for cue {idx}: {img_exc}")
            cue.visual_type = "voiceover"  # last resort: no visual


PREVIEW_SECONDS = 15.0


def _truncate_to_preview(cues: list[ExplainerCue]) -> list[ExplainerCue]:
    """截取前 15 秒的 cue(15s Preview Gate)。

    按 time_estimate_s 累加,刚好跨过 15s 边界的那条保留(保证能听到半句话),
    至少保留 1 条;空列表原样返回。
    """
    if not cues:
        return cues
    kept: list[ExplainerCue] = []
    acc = 0.0
    for cue in cues:
        kept.append(cue)
        acc += float(cue.time_estimate_s or 5.0)
        if acc >= PREVIEW_SECONDS:
            break
    return kept


def _preview_output_dir(output_dir: Path) -> Path:
    """先导样片输出目录:与全量成片同一沙盒下的 preview 子目录。"""
    return output_dir / "preview"


async def assemble_explainer_cues(
    topic: str,
    cues: list[ExplainerCue],
    output_dir: Path,
    *,
    voice: str,
    enable_circle_avatar_mask: bool = True,
    enable_remotion_code_render: bool = True,
    enable_browser_broll: bool = True,
    enable_stock_broll: bool = True,
    aspect_ratio: str = "9:16",
    heygen_presenter_id: str | None = None,
    presenter_provider: str = "remotion",
    presenter_name: str = "HEVI 默认解说数字人",
    heygen_provider: Any = None,
    broll_recorder: Any = None,
    packager: dict[str, Any] | None = None,
    stock_service: Any = None,
    presenter_image_url: str | None = None,
    preview_mode: bool = False,
) -> NarratedRenderResult:
    """Compile edited cues and run the standard injected Remotion transaction.

    ``preview_mode=True`` 时只取前 15 秒的 cue/音频/画面 —— 15s 先导样片
    (Preview Gate),用约 1/10 的算力在确稿前先看质感,不合格不浪费全量渲染。
    """
    if aspect_ratio not in {"9:16", "16:9"}:
        raise ValueError("aspect_ratio 仅支持 9:16 或 16:9")
    # 🚨 v9.1: 15 秒先导样片 —— 在一切算力消耗之前截断 cue 列表。
    if preview_mode:
        prepared_for_preview = _truncate_to_preview(cues)
        if len(prepared_for_preview) < len(cues):
            logger.info(
                "preview_mode: %d 条 cue 截断为前 15 秒的 %d 条",
                len(cues),
                len(prepared_for_preview),
            )
        cues = prepared_for_preview
    # 装配入参防御解析:确稿台/旧客户端可能把 cue 或嵌套字段(visual_config /
    # chart_data)序列化成 JSON 字符串;这里统一规整成安全形状,脏条目直接丢弃。
    prepared_cues = process_cues_for_remotion(cues)
    if not prepared_cues:
        raise ValueError("装配入参没有可用的视觉脚手架 cue")
    # browser_broll 缺 target_url 时不再报错阻断装配:自动降级为 voiceover
    # (Remotion 端 visualType==voiceover 时不渲染任何叠加层,见
    # ExplainerVideo.tsx 的 VisualOverlay)——旁白 + props 主视觉照常呈现,
    # 只是少一个网页截图叠加。highlight_selector 一并清空,它是针对原网页
    # 写的,没有 URL 也无意义。
    for cue in prepared_cues:
        if cue.visual_type == "browser_broll" and not cue.target_url:
            cue.visual_type = "voiceover"
            cue.highlight_selector = None
    # 🚨 v9.0: 视觉素材装填 —— stock_broll 检索真实画面（在 HeyGen 之前）
    if enable_stock_broll and stock_service is not None:
        await _fulfill_stock_visuals(prepared_cues, stock_service, output_dir)

    # 🚨 v9.0: 全时段 Talking Face 底轨生成
    continuous_avatar_path: Path | None = None
    if presenter_provider == "remotion" and packager:
        presenter_img = packager.get("presenter_image_url") or presenter_image_url
        if presenter_img:
            try:
                from hevi.digital_human.talking_face import (
                    generate_continuous_avatar_track as _talking_face,
                )
                avatar_output = output_dir / "continuous_avatar"
                continuous_avatar_path = await _talking_face(
                    image_path=presenter_img,
                    master_audio_path=output_dir / "master_placeholder.wav",  # 由 voiceover 后填
                    output_dir=avatar_output,
                    aspect_ratio=aspect_ratio,
                    preset_name=presenter_name,
                )
                logger.info("Continuous avatar track: %s", continuous_avatar_path)
            except Exception as tf_exc:
                logger.warning("Talking Face generation skipped: %s", tf_exc)

    avatar_indices = [
        index for index, cue in enumerate(prepared_cues) if cue.visual_type == "heygen_avatar"
    ]
    if avatar_indices:
        if presenter_provider == "remotion":
            # 本地可渲染数字人:不调 HeyGen,标记 local_presenter 让 Remotion
            # 用本地 Talking Face / 静态底图方案出镜(v9.0 全时段底轨在下方)。
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
    render_target = _preview_output_dir(output_dir) if preview_mode else output_dir
    return await render_narrated_storyboard(storyboard, render_target, voice=voice)
