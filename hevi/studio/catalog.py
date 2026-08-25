"""OpenMontage 规模工具目录 —— 100+ 可调用积木,全部落到 hevi 已有模块。"""

from __future__ import annotations

from typing import Any

from hevi.studio.ops import run_op
from hevi.studio.tools import ToolSpec, get_tool, register_tool

Row = tuple[str, str, str, tuple[str, ...], tuple[str, ...], str]


def _row(
    tool_id: str,
    kind: str,
    summary: str,
    inputs: tuple[str, ...],
    outputs: tuple[str, ...],
    op: str,
) -> Row:
    return (tool_id, kind, summary, inputs, outputs, op)


# id, kind, summary, inputs, outputs, op
CATALOG: list[Row] = [
    _row(
        "ingest.fetch",
        "watch",
        "下载或直通本地视频",
        ("source",),
        ("video_path",),
        "ingest_fetch",
    ),
    _row("ingest.frames", "watch", "场景感知抽帧", ("source",), ("frames",), "ingest_frames"),
    _row(
        "ingest.transcript",
        "watch",
        "字幕/转写",
        ("source",),
        ("transcript",),
        "ingest_transcript",
    ),
    _row("ingest.contact_sheet", "watch", "联络表", ("frames",), ("sheet_path",), "ingest_contact"),
    _row("ingest.preflight", "watch", "看片环境预检", (), ("can_proceed",), "ingest_preflight"),
    _row("watch.pacing", "watch", "语速/句密度", ("transcript",), ("pacing",), "watch_pacing"),
    _row(
        "research.context",
        "research",
        "研究转剧本上下文",
        ("topic",),
        ("context",),
        "research_context",
    ),
    _row(
        "script.episode_brief",
        "script",
        "集计划压成导演 brief",
        ("episode",),
        ("brief",),
        "episode_brief",
    ),
    _row(
        "script.split_history",
        "script",
        "讲解/演绎拆分",
        ("lines",),
        ("commentary", "drama"),
        "split_history",
    ),
    _row(
        "script.from_watch",
        "script",
        "看片结果出脚本行",
        ("transcript",),
        ("script_lines",),
        "script_from_watch",
    ),
    _row("tongjian.mix", "tongjian", "通鉴=讲解+演绎", ("script",), ("mix",), "tongjian_mix"),
    _row(
        "tongjian.quotes",
        "tongjian",
        "抽出引语清单",
        ("chapter_ir",),
        ("quotes",),
        "tongjian_quotes",
    ),
    _row(
        "director.lint_stage",
        "director",
        "场面调度 lint",
        ("shot_list",),
        ("findings",),
        "lint_stage",
    ),
    _row("director.h3_cuts", "director", "H3 切点推导", ("durations",), ("starts",), "h3_cuts"),
    _row(
        "director.h3_align",
        "director",
        "H3 对齐校验",
        ("text", "durations"),
        ("errors",),
        "h3_align",
    ),
    _row("director.h3_pack", "director", "同场打包≤15s", ("shots",), ("groups",), "h3_pack"),
    _row(
        "explainer.preview_budget",
        "explainer",
        "试播 60–90s",
        ("cues",),
        ("kept",),
        "preview_budget",
    ),
    _row(
        "explainer.stock_query",
        "explainer",
        "stock 检索词",
        ("text",),
        ("query",),
        "stock_query",
    ),
    _row("audio.prosody", "tts", "重音/停顿规划", ("text",), ("prosody",), "audio_prosody"),
    _row("audio.concat", "tts", "配音段拼接", ("paths",), ("master",), "audio_concat"),
    _row("audio.probe", "tts", "ffprobe 音视频", ("path",), ("probe",), "audio_probe"),
    _row("audio.bgm_plan", "tts", "BGM 侧链计划", ("duration_s",), ("bgm",), "audio_bgm"),
    _row(
        "material.aspect_fit",
        "material",
        "画幅契合分",
        ("target", "candidate"),
        ("fit",),
        "aspect_fit",
    ),
    _row("material.pick_best", "material", "素材择优", ("query", "items"), ("best",), "pick_best"),
    _row("video.score", "score", "7 维选片商", ("candidates",), ("winner",), "score_video"),
    _row("timeline.create", "nle", "edit_plan→时间线", ("edit_plan",), ("timeline",), "tl_create"),
    _row(
        "timeline.patch",
        "nle",
        "改一镜动作",
        ("timeline_id", "clip_id"),
        ("timeline",),
        "tl_patch",
    ),
    _row("timeline.export", "nle", "时间线重导出", ("timeline_id",), ("video_path",), "tl_export"),
    _row("timeline.split", "nle", "在游标切开", ("timeline_id",), ("timeline",), "tl_split"),
    _row("timeline.ripple", "nle", "丢掉后收缝", ("timeline_id",), ("timeline",), "tl_ripple"),
    _row("nle.drop_cut", "nle", "丢掉一镜", ("cuts", "index"), ("cuts",), "nle_drop"),
    _row("nle.set_bgm", "nle", "挂 BGM", ("timeline_id", "bgm"), ("timeline",), "tl_bgm"),
    _row("publish.douyin", "publish", "抖音交接单", ("media_path",), ("status",), "pub_douyin"),
    _row("publish.kuaishou", "publish", "快手交接单", ("media_path",), ("status",), "pub_kuaishou"),
    _row("publish.xiaohongshu", "publish", "小红书交接单", ("media_path",), ("status",), "pub_xhs"),
    _row("publish.shipinhao", "publish", "视频号交接单", ("media_path",), ("status",), "pub_sph"),
    _row("publish.bilibili", "publish", "B 站交接单", ("media_path",), ("status",), "pub_bili"),
    _row("publish.list", "publish", "列出发布器", (), ("publishers",), "pub_list"),
    _row("qc.probe", "delivery", "成片 ffprobe", ("path",), ("probe",), "qc_probe"),
    _row("qc.production", "delivery", "导演交付检查", ("shots",), ("verdict",), "qc_production"),
    _row("qc.layout", "delivery", "安全区/遮挡", ("boxes",), ("ok",), "qc_layout"),
    _row("qc.motion", "delivery", "语义运动检查", ("shot",), ("ok",), "qc_motion"),
    _row(
        "delivery.promise",
        "delivery",
        "交付承诺分类",
        ("pipeline_type",),
        ("promise",),
        "delivery_promise",
    ),
    _row(
        "delivery.validate",
        "delivery",
        "切点合规校验",
        ("cuts", "promise"),
        ("valid",),
        "delivery_validate",
    ),
    _row(
        "verdict.scene_pacing",
        "delivery",
        "场景步骤节奏校验",
        ("steps",),
        ("landmarks",),
        "verdict_scene_pacing",
    ),
    _row(
        "verdict.source_review",
        "delivery",
        "完整源片审查(ffprobe+帧采样+转写)",
        ("files",),
        ("review",),
        "verdict_source_review",
    ),
    _row("clip.factory", "nle", "长片拆短", ("edit_plan",), ("clips",), "clip_factory"),
    _row("dub.translate", "script", "对白译句", ("lines", "lang"), ("lines",), "dub_translate"),
    _row(
        "montage.queries",
        "material",
        "纪录片检索词",
        ("topic",),
        ("queries",),
        "montage_queries",
    ),
    _row("character.beats", "director", "角色动作节拍", ("text",), ("beats",), "character_beats"),
    _row("batch.rank", "score", "批量择优", ("candidates",), ("best",), "batch_rank"),
    _row(
        "line.recipe_nodes",
        "canvas",
        "配方展开为画布节点",
        ("line_id",),
        ("nodes",),
        "recipe_nodes",
    ),
    _row(
        "runtime.select",
        "runtime",
        "选 Remotion/HyperFrames/Manim/ffmpeg",
        ("intent",),
        ("runtime",),
        "runtime_select",
    ),
    _row(
        "runtime.hyperframes.compile",
        "runtime",
        "编译 HyperFrames HTML 构图",
        ("topic",),
        ("html",),
        "hf_compile",
    ),
    _row(
        "runtime.hyperframes.render",
        "runtime",
        "渲 HyperFrames(CLI 或逐卡回退)",
        ("topic",),
        ("video_path",),
        "hf_render",
    ),
    _row("craft.shot_spec", "craft", "五面分镜词", ("text",), ("spec",), "craft_shot_spec"),
    _row("craft.seedance", "craft", "Seedance 八段提示", ("topic",), ("prompt",), "craft_seedance"),
    _row("craft.broll", "craft", "B-roll stock/generate", ("text",), ("mode",), "craft_broll"),
    _row("craft.taste", "craft", "口味盘+反模式", ("brief",), ("dials",), "craft_taste"),
    _row(
        "craft.slideshow_risk",
        "craft",
        "静帧幻灯风险",
        ("shots",),
        ("risky",),
        "craft_slideshow",
    ),
    _row("craft.source_review", "craft", "源片审查", ("duration_s",), ("ok",), "craft_source"),
    _row(
        "craft.variation",
        "craft",
        "相邻镜变体检查",
        ("items",),
        ("duplicates",),
        "craft_variation",
    ),
    _row("craft.grade", "craft", "调色/LUT 计划", ("look",), ("vf",), "craft_grade"),
    _row("craft.site_to_video", "craft", "网站转视频计划", ("url",), ("shots",), "craft_site"),
    _row(
        "craft.shot_prompt",
        "craft",
        "五层英文镜头提示词",
        ("scene",),
        ("prompt",),
        "craft_shot_prompt",
    ),
    _row("daily.tick", "daily", "日更排产一拍", (), ("jobs",), "daily_tick"),
    _row("veya.produce", "veya", "Veya 调成品", ("line_id",), ("job",), "veya_produce"),
]


def _extra_domain_tools() -> list[Row]:
    """把各域细能力展开,凑齐 OpenMontage 级工具面。"""
    extras: list[Row] = []
    extras.extend(
        _row(
            f"explainer.card.{name}",
            "explainer",
            summary,
            ("text",),
            ("cue",),
            "explainer_card",
        )
        for name, summary in (
            ("hook", "开场钩子"),
            ("definition", "定义卡"),
            ("list_reveal", "列表揭示"),
            ("equation", "公式变换"),
            ("compare", "对比卡"),
            ("timeline", "时间轴卡"),
            ("map", "地图卡"),
            ("quote", "金句卡"),
        )
    )
    extras.extend(
        _row(
            f"profile.out.{platform}",
            "profile",
            f"{platform} 输出规格",
            (),
            ("profile",),
            "out_profile",
        )
        for platform in ("youtube", "tiktok", "reels", "linkedin", "shorts")
    )
    extras.extend(
        _row(
            f"audio.mood.{kind}",
            "tts",
            f"{kind} 配乐情绪",
            ("duration_s",),
            ("bgm",),
            "audio_bgm",
        )
        for kind in ("warm", "tense", "epic", "mystery", "upbeat")
    )
    extras.extend(
        _row(f"qc.gate.{gate}", "delivery", f"{gate} 闸", ("shots",), ("ok",), "qc_gate")
        for gate in ("black", "identity", "wardrobe", "lip", "canon")
    )
    extras.extend(
        _row(
            f"material.src.{src}",
            "material",
            f"{src} 素材源计划",
            ("query",),
            ("plan",),
            "material_src",
        )
        for src in ("pexels", "pixabay", "coverr", "archive", "nasa", "wikimedia")
    )
    extras.extend(
        _row(
            f"tongjian.layer.{layer}",
            "tongjian",
            f"通鉴 {layer} 能力票",
            ("topic",),
            ("ticket",),
            "layer_ticket",
        )
        for layer in ("L0", "L1", "L2", "L3", "L4", "L6", "L8")
    )
    extras.extend(
        _row(
            f"director.step.{step}",
            "director",
            f"导演 {step} 能力票",
            ("topic",),
            ("ticket",),
            "layer_ticket",
        )
        for step in ("concept", "screenplay", "design", "stage", "shots", "produce")
    )
    extras.extend(
        _row(
            f"nle.transition.{name}",
            "nle",
            summary,
            ("timeline_id",),
            ("plan",),
            "nle_transition",
        )
        for name, summary in (
            ("cut", "硬切"),
            ("dissolve", "叠化"),
            ("wipe", "划像"),
            ("smash", "闪切"),
        )
    )
    extras.extend(
        _row(
            f"director.camera.{name}",
            "director",
            summary,
            ("scene",),
            ("plan",),
            "camera_plan",
        )
        for name, summary in (
            ("wide", "全景"),
            ("medium", "中景"),
            ("close", "近景"),
            ("insert", "插入特写"),
        )
    )
    return extras


ALL_CATALOG = CATALOG + _extra_domain_tools()


def register_catalog() -> int:
    added = 0
    for tool_id, kind, summary, inputs, outputs, op in ALL_CATALOG:
        if get_tool(tool_id) is not None:
            continue

        async def _run(
            payload: dict[str, Any],
            _op: str = op,
            _id: str = tool_id,
        ) -> dict[str, Any]:
            body = dict(payload)
            body.setdefault("_tool_id", _id)
            return await run_op(_op, body)

        register_tool(ToolSpec(tool_id, kind, summary, inputs, outputs), _run)
        added += 1
    return added
