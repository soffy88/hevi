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
from urllib.parse import urlsplit

import httpx

from hevi.explainer.contracts import ExplainerCue
from hevi.explainer.echo_avatar import PRESENTER_IMAGE_KEY, PRESENTER_VIDEO_KEY
from hevi.explainer.manim_scene import attach_manim_scenes
from hevi.explainer.production import NarratedRenderResult, render_narrated_storyboard
from hevi.explainer.props import normalise_visual_config, process_cues_for_remotion
from hevi.explainer.schemas import SceneType, Storyboard, StoryboardSegment, validate_props
from hevi.explainer.whiteboard import attach_whiteboard_scenes
from hevi.production.delivery_gate import (
    PREVIEW_MAX_SECONDS,
    PREVIEW_MIN_SECONDS,
    PREVIEW_TARGET_SECONDS,
    evaluate_preview_delivery,
    probe_video,
    write_preview_report,
)

logger = logging.getLogger(__name__)


def _freeze_stock_url(
    url: str,
    *,
    media_type: str,
    intent: str,
    output_dir: Path,
    source_metadata: dict[str, Any],
) -> Path:
    """Download a stock URL through the HEVI media-use ledger contract."""

    from hevi.sourcing.media_providers import _download_cached, _write_source_manifest
    from hevi.sourcing.media_use import MediaLedger, resolve_media

    parsed = urlsplit(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix not in {".mp4", ".webm", ".mov", ".m4v", ".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".mp4" if media_type == "video" else ".jpg"
    cache_dir = output_dir / "stock_media"
    ledger_path = output_dir / "media_ledger.json"
    ledger = MediaLedger.load(ledger_path)

    def stock_provider(_intent: str) -> Path | None:
        if not url.startswith(("http://", "https://")):
            local = Path(url)
            return local if local.is_file() else None
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            path = _download_cached(url, cache_dir, suffix, client)
        if path is not None:
            _write_source_manifest(path, source_metadata)
        return path

    resolution = resolve_media(
        media_type,
        intent,
        providers={media_type: {"stock": stock_provider}},
        ledger=ledger,
        out_dir=cache_dir,
        verify_paths=True,
    )
    ledger.save(ledger_path)
    return resolution.path


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
    cues: list[ExplainerCue],
    stock_svc: Any,
    output_dir: Path,
    *,
    user_id: str = "explainer_session",
) -> None:
    import json
    import os
    import shutil
    from collections import Counter

    from hevi.sourcing.corpus import Corpus

    corpus_dir = Path(os.environ.get("HEVI_CORPUS_DIR", "data/corpus"))
    corpus = Corpus.load(corpus_dir)
    api_key = os.environ.get("PEXELS_API_KEY", "")
    if not api_key:
        for env_path in [Path(".env"), Path("/data/soffy/projects/hevi/.env")]:
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    if line.startswith("PEXELS_API_KEY="):
                        api_key = line.split("=", 1)[1].strip()
                        os.environ["PEXELS_API_KEY"] = api_key
                        break
            if api_key:
                break

    # 跟踪素材使用次数与来源分布，严格去重 (每素材至多使用 1 次，多源均衡)
    usage_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    MAX_REUSE = 1
    output_dir.mkdir(parents=True, exist_ok=True)
    prov = output_dir / "provenance.jsonl"
    if prov.exists():
        prov.unlink()

    for idx, cue in enumerate(cues):
        if cue.visual_type != "stock_broll":
            continue
        if cue.visual_config.get("assetUrl"):
            continue
        query = getattr(cue, "visual_search_query", "") or getattr(cue, "text", "")
        if not query.strip():
            cue.visual_type = "voiceover"
            continue

        import asyncio

        # 真实素材检索：优先覆盖 NASA, Wikimedia Commons, Archive.org
        tasks = [
            corpus.add_nasa_api(query=query, count=2),
            corpus.add_wikimedia_commons(query=query, count=2),
            corpus.add_archive_org(query=query, count=2),
        ]
        if api_key:
            tasks.append(corpus.add_pexels(query=query, count=2, api_key=api_key))

        await asyncio.gather(*tasks, return_exceptions=True)
        corpus.save()

        # 排除已用满上限的素材
        excluded = {cid for cid, count in usage_counts.items() if count >= MAX_REUSE}
        hits = corpus.rank_for_slot(query, top_k=max(len(corpus.records), 50))

        hit = None
        # 1. 优先选满足阈值且来源不过度集中的候选
        for cand in hits:
            cid = cand.get("clip_id")
            src = cand.get("source")
            if cid in excluded:
                continue
            if float(cand.get("score", 0.0)) < 0.15:
                continue
            # 若某单一来源已超过 4 个槽位，优先让渡给其他合格来源
            if source_counts[src] >= 4 and any(
                c.get("clip_id") not in excluded
                and float(c.get("score", 0.0)) >= 0.15
                and source_counts[c.get("source")] < 4
                for c in hits
            ):
                continue
            local = Path(corpus.root) / cand["local_path"]
            if local.exists() and local.stat().st_size > 0:
                hit = dict(cand)
                hit["local_abs_path"] = str(local)
                break

        # 2. 若无命中，选取未被排除且满足安全底线(0.11)的最高分候选
        if hit is None:
            for cand in hits:
                cid = cand.get("clip_id")
                if cid in excluded:
                    continue
                if float(cand.get("score", 0.0)) < 0.11:
                    continue
                local = Path(corpus.root) / cand["local_path"]
                if local.exists() and local.stat().st_size > 0:
                    hit = dict(cand)
                    hit["local_abs_path"] = str(local)
                    break

        if hit and "local_abs_path" in hit:
            clip_id = hit.get("clip_id", "")
            usage_counts[clip_id] += 1
            source_counts[hit.get("source")] += 1

            remotion_public = Path(__file__).resolve().parent.parent.parent / "hevi-remotion" / "public"
            dest = remotion_public / "stock" / Path(hit["local_abs_path"]).name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(hit["local_abs_path"], dest)
            cue.visual_config["assetUrl"] = f"stock/{dest.name}"
            cue.visual_config["clip_id"] = hit.get("clip_id")
            cue.visual_config["clip_score"] = hit.get("score")
            cue.visual_config["clip_mode"] = "degraded" if hit.get("degraded") else "open_clip_vit_b_32_cpu"

            # Write provenance log with clip score, source, and query
            prov = output_dir / "provenance.jsonl"
            with open(prov, "a") as f:
                prov_record = {
                    "cue_index": idx,
                    "slot_query": query,
                    "clip_id": hit.get("clip_id"),
                    "source": hit.get("source"),
                    "score": hit.get("score"),
                    "title": hit.get("title"),
                    "asset_url": f"stock/{dest.name}",
                    "license": hit.get("license"),
                    "degraded": hit.get("degraded", False),
                    "clip_mode": "degraded" if hit.get("degraded") else "open_clip_vit_b_32_cpu",
                }
                f.write(json.dumps(prov_record, ensure_ascii=False) + "\n")
        else:
            cue.visual_type = "voiceover"


PREVIEW_SECONDS = PREVIEW_TARGET_SECONDS


def _truncate_to_preview(
    cues: list[ExplainerCue],
    *,
    min_s: float = PREVIEW_MIN_SECONDS,
    max_s: float = PREVIEW_MAX_SECONDS,
    target_s: float = PREVIEW_TARGET_SECONDS,
) -> list[ExplainerCue]:
    """截取 60–90 秒试播。先凑满 60s,到 75s 停,加下一条会超过 90s 则不加。"""
    if not cues:
        return cues
    kept: list[ExplainerCue] = []
    acc = 0.0
    for cue in cues:
        dur = float(cue.time_estimate_s or 5.0)
        if kept and acc >= min_s and acc + dur > max_s:
            break
        kept.append(cue)
        acc += dur
        if acc >= target_s and acc >= min_s:
            break
    return kept


def _stamp_presenter_image(
    cues: list[ExplainerCue],
    packager: dict[str, Any] | None,
    presenter_image_url: str | None,
    presenter_reference_video: str | None = None,
) -> None:
    """Park presenter still/video on cue 0. Remotion avatar flag is set only after lipsync."""
    if not cues:
        return
    image = None
    video = presenter_reference_video
    if packager:
        image = packager.get("presenter_image_url")
        video = video or packager.get("presenter_reference_video")
    image = image or presenter_image_url
    if not image and not video:
        return
    cfg = cues[0].visual_config
    if not isinstance(cfg, dict):
        cues[0].visual_config = {}
        cfg = cues[0].visual_config
    if image:
        cfg[PRESENTER_IMAGE_KEY] = str(image)
    if video:
        cfg[PRESENTER_VIDEO_KEY] = str(video)
    packaging = dict(cfg.get("packaging") or (packager or {}))
    packaging.pop("presenter_image_url", None)
    if packaging:
        cfg["packaging"] = packaging


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
    enable_manim_render: bool = True,
    enable_whiteboard_render: bool = True,
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
    stock_user_id: str = "explainer_session",
    presenter_image_url: str | None = None,
    presenter_reference_video: str | None = None,
    preview_mode: bool = False,
    source_text: str = "",
    reference_url: str = "",
    tts_provider: str | None = None,
) -> NarratedRenderResult:
    """Compile edited cues and run the standard injected Remotion transaction.

    ``preview_mode=True`` 时只取 60–90 秒的 cue/音频/画面(试播闸),
    写 qc-report 后停,未经确认不渲全片。试播不叠数字人。
    """
    if aspect_ratio not in {"9:16", "16:9"}:
        raise ValueError("aspect_ratio 仅支持 9:16 或 16:9")
    if source_text.strip():
        from hevi.studio.kit import tongjian_l0, tongjian_provenance
        from hevi.studio.mix import plan_history_mix

        borrowed = await tongjian_l0({"source_name": topic, "raw_text": source_text, "llm": None})
        logger.info("explainer borrowed tongjian.l0: %s", borrowed.get("status"))
        mix = await plan_history_mix(
            {"lines": [{"type": "narration", "text": source_text[:2000], "speaker": "NARRATOR"}]}
        )
        extra = [
            ExplainerCue.model_validate(item)
            for item in mix.commentary_cues
            if isinstance(item, dict)
        ]
        if extra:
            cues = [*extra, *cues]
        tongjian_provenance({"lines": mix.drama_lines})
    if reference_url.strip():
        from hevi.studio.kit import watch_video_tool

        watched = await watch_video_tool(
            {
                "source": reference_url.strip(),
                "work_dir": str(output_dir / "watch"),
                "detail": "transcript",
            }
        )
        logger.info("explainer borrowed watch.video: %s", watched.get("status"))
    if preview_mode:
        prepared_for_preview = _truncate_to_preview(cues)
        if len(prepared_for_preview) < len(cues):
            logger.info(
                "preview_mode: %d 条 cue 截断为 60–90 秒试播的 %d 条",
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
    if enable_stock_broll:
        await _fulfill_stock_visuals(
            prepared_cues, stock_service, output_dir, user_id=stock_user_id
        )

    # 解说员照片先记在 cue 上;基础片过检后再叠数字人(见 render._overlay_talking_face)。
    # 不在这里写 packaging.presenter_image_url——Remotion 见到它就会找
    # public/continuous_avatar/*.mp4,那时片子还不存在。
    _stamp_presenter_image(
        prepared_cues,
        packager,
        presenter_image_url,
        presenter_reference_video,
    )

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
    manim_w, manim_h = (1080, 1920) if aspect_ratio == "9:16" else (1920, 1080)
    remotion_public = Path(__file__).resolve().parent.parent.parent / "hevi-remotion" / "public"
    await attach_manim_scenes(
        prepared_cues,
        output_dir,
        enabled=enable_manim_render,
        remotion_public=remotion_public if remotion_public.is_dir() else None,
        width=manim_w,
        height=manim_h,
    )
    await attach_whiteboard_scenes(
        prepared_cues,
        output_dir,
        enabled=enable_whiteboard_render,
        remotion_public=remotion_public if remotion_public.is_dir() else None,
        width=manim_w,
        height=manim_h,
    )
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
    result = await render_narrated_storyboard(
        storyboard, render_target, voice=voice, tts_provider=tts_provider
    )
    if preview_mode:
        budget = sum(float(cue.time_estimate_s or 5.0) for cue in prepared_cues)
        cover = render_target / "cover.jpg"
        report = evaluate_preview_delivery(
            probe_video(result.portrait_path),
            cue_budget_s=budget,
            cover_path=cover if cover.exists() else None,
        )
        report["landscape_path"] = str(result.landscape_path)
        report["cue_count"] = len(prepared_cues)
        dest = write_preview_report(render_target, report)
        logger.info("preview qc-report: %s ok=%s", dest, report.get("ok"))
        if not report["ok"]:
            from hevi.production.delivery_gate import ComposeGateError

            raise ComposeGateError("试播未通过: " + "; ".join(report.get("blockers") or []))
    return result
