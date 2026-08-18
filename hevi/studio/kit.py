"""三条管线共享能力 —— 通鉴 / 短剧 / 解说互借,失败降级不 raise。

通鉴按设计 = 解说(讲解) + 演绎(对白)。本模块是互调入口,不复制实现。
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _ok(**payload: Any) -> dict[str, Any]:
    return {"status": "ok", **payload}


def _fail(reason: str, **payload: Any) -> dict[str, Any]:
    return {"status": "failed", "reason": reason, **payload}


async def watch_video_tool(payload: dict[str, Any]) -> dict[str, Any]:
    """claude-video /watch:任意产线先看片。"""
    from hevi.ingest.reference_concepts import derive_reference_concepts
    from hevi.ingest.video_watch import WatchResult

    source = str(payload.get("source") or payload.get("reference_url") or "").strip()
    transcript = str(payload.get("transcript") or "")
    work_dir = Path(str(payload.get("work_dir") or "data/workspace/watch"))
    if source and not transcript:
        try:
            from hevi.ingest.video_watch import watch_video

            result = watch_video(source, work_dir, detail=payload.get("detail") or "transcript")
        except Exception as exc:
            logger.warning("watch_video failed: %s", exc)
            result = WatchResult(source=source, duration_s=float(payload.get("duration_s") or 0))
    else:
        duration = float(payload.get("duration_s") or 0)
        result = WatchResult(source=source or "inline", duration_s=duration)
        if transcript:
            from hevi.ingest.video_transcript import TranscriptSegment

            result.transcript.append(
                TranscriptSegment(start=0.0, end=result.duration_s, text=transcript)
            )
    concepts = await derive_reference_concepts(result, llm=payload.get("llm"))
    return _ok(
        source=result.source,
        duration_s=result.duration_s,
        transcript=result.transcript_text,
        frame_count=result.frame_count,
        concepts=concepts,
        notes=list(result.notes),
    )


async def tongjian_l0(payload: dict[str, Any]) -> dict[str, Any]:
    """史料闸:短剧/解说也可借。无 LLM 返回空 IR,不阻断。"""
    from hevi.tongjian.chapter_ir import extract_chapter_ir

    raw = str(payload.get("raw_text") or payload.get("source_text") or "").strip()
    if not raw:
        return _fail("raw_text required")
    name = str(payload.get("source_name") or "source")
    ir = await extract_chapter_ir(source_name=name, raw_text=raw, llm=payload.get("llm"))
    dump = ir.model_dump() if hasattr(ir, "model_dump") else {}
    return _ok(chapter_ir=dump, quote_count=len(getattr(ir, "quotes", []) or []))


def tongjian_provenance(payload: dict[str, Any]) -> dict[str, Any]:
    """CG2.5:对白必须有 quote_id 或 dramatized。短剧/解说借此守史实。"""
    lines = payload.get("lines") or []
    errors: list[str] = []
    for i, line in enumerate(lines):
        if not isinstance(line, dict):
            continue
        kind = str(line.get("type") or "")
        if kind != "dialogue":
            continue
        if line.get("quote_id") or line.get("dramatized"):
            continue
        errors.append(f"line[{i}] dialogue missing quote_id and dramatized")
    return _ok(passed=not errors, errors=errors)


async def storygraph_extract(payload: dict[str, Any]) -> dict[str, Any]:
    """短剧 B0:通鉴/解说改编小说时也可借。"""
    from hevi.storygraph.extract import extract_story_graph

    raw = str(payload.get("raw_text") or payload.get("manuscript") or "").strip()
    if not raw:
        return _fail("raw_text required")
    graph = await extract_story_graph(
        source_name=str(payload.get("source_name") or "story"),
        raw_text=raw,
        llm=payload.get("llm"),
    )
    dump = graph.model_dump(mode="json") if hasattr(graph, "model_dump") else {}
    return _ok(
        story_graph=dump,
        characters=len(getattr(graph, "characters", []) or []),
        events=len(getattr(graph, "events", []) or []),
    )


async def explainer_manim(payload: dict[str, Any]) -> dict[str, Any]:
    """代码即画面:导演/通鉴讲解段可借,缺 CLI 走 ffmpeg 回退。"""
    from hevi.providers.manim.provider import manim_generate

    dest = Path(str(payload.get("output_path") or "output/manim/scene.mp4"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    prompt = payload.get("prompt") or payload.get("text") or "list_reveal"
    path = await manim_generate(
        prompt=prompt,
        output_path=dest,
        duration_s=float(payload.get("duration_s") or 4.0),
        width=int(payload.get("width") or 1280),
        height=int(payload.get("height") or 720),
    )
    return _ok(asset_path=str(path), exists=Path(path).exists())


async def explainer_cues_from_text(payload: dict[str, Any]) -> dict[str, Any]:
    """把讲解文本编成解说 cue,通鉴讲解段走这条,不另写一套。"""
    from hevi.explainer.contracts import ExplainerCue

    texts = payload.get("texts") or []
    if payload.get("text") and not texts:
        texts = [payload["text"]]
    cues = []
    for text in texts:
        line = str(text).strip()
        if not line:
            continue
        visual = str(payload.get("visual_type") or "voiceover")
        cue = ExplainerCue(text=line[:2000], visual_type=visual)  # type: ignore[arg-type]
        cues.append(cue.model_dump())
    return _ok(cues=cues)


async def avatar_compose(payload: dict[str, Any]) -> dict[str, Any]:
    """口型叠片:三条线统一入口。缺素材 skipped;引擎失败 failed。"""
    image = payload.get("image_path")
    audio = payload.get("audio_path")
    dest = payload.get("output_path")
    if not image or not audio or not dest:
        return _fail("image_path, audio_path, output_path required")
    image_p, audio_p, dest_p = Path(str(image)), Path(str(audio)), Path(str(dest))
    if not image_p.exists() or not audio_p.exists():
        return {"status": "skipped", "reason": "presenter or audio missing"}
    dest_p.parent.mkdir(parents=True, exist_ok=True)
    try:
        from hevi.digital_human.talking_face import generate_talking_face

        out = await generate_talking_face(
            image_path=image_p,
            audio_path=audio_p,
            output_path=dest_p,
            reference_video=payload.get("reference_video"),
        )
        return _ok(avatar_path=str(out))
    except Exception as exc:
        logger.warning("avatar.compose failed: %s", exc)
        return _fail(str(exc))


async def tts_synth(payload: dict[str, Any]) -> dict[str, Any]:
    """可替换 TTS:lux / edge / auto。三条线不要再各写一条分支。"""
    text = str(payload.get("text") or "").strip()
    dest = Path(str(payload.get("output_path") or "output/tts/line.wav"))
    if not text:
        return _fail("text required")
    dest.parent.mkdir(parents=True, exist_ok=True)
    provider = str(payload.get("provider") or "auto").lower()
    if provider in {"auto", "lux"}:
        try:
            from hevi.audio.lux_tts_service import lux_tts_available, synth_with_luxvoice

            if lux_tts_available():
                await synth_with_luxvoice(
                    text,
                    dest,
                    reference_audio=payload.get("reference_audio"),
                )
                return _ok(audio_path=str(dest), provider="lux")
            if provider == "lux":
                return _fail("luxvoice unavailable")
        except Exception as exc:
            if provider == "lux":
                return _fail(str(exc))
            logger.info("lux tts skipped: %s", exc)
    try:
        import edge_tts

        voice = str(payload.get("voice") or "zh-CN-YunxiNeural")
        await edge_tts.Communicate(text, voice).save(str(dest))
        return _ok(audio_path=str(dest), provider="edge_tts")
    except Exception as exc:
        return _fail(str(exc))


async def director_scene_stage(payload: dict[str, Any]) -> dict[str, Any]:
    """场面调度:通鉴场/解说多角色段可借。"""
    from hevi.director.pipeline_schemas import DesignList, ScreenplayScene
    from hevi.director.scene_stage import generate_scene_stage_draft

    scene_raw = payload.get("scene") or {}
    design_raw = payload.get("design_list") or {}
    if not scene_raw:
        return _fail("scene required")
    scene = ScreenplayScene.model_validate(scene_raw)
    design = DesignList.model_validate(design_raw) if design_raw else DesignList()
    stage = await generate_scene_stage_draft(
        scene=scene, design_list=design, llm=payload.get("llm")
    )
    dump = stage.model_dump() if hasattr(stage, "model_dump") else {}
    return _ok(scene_stage=dump)


def shot_export(payload: dict[str, Any]) -> dict[str, Any]:
    """Jellyfish:把一镜登记为跨线资产,解说/通鉴可引用。"""
    from hevi.studio.assets import bind_asset

    shot_id = str(payload.get("shot_id") or payload.get("label") or "").strip()
    if not shot_id:
        return _fail("shot_id required")
    ref = bind_asset(
        "shot",
        line_id=str(payload.get("line_id") or "director_pipeline"),
        label=shot_id,
        payload={
            "shot_id": shot_id,
            "video_path": payload.get("video_path"),
            "prompt": payload.get("prompt"),
            "duration_s": payload.get("duration_s"),
            "scene_no": payload.get("scene_no"),
        },
        asset_id=payload.get("asset_id"),
    )
    return _ok(asset=ref.to_dict())


def freeze_profile(payload: dict[str, Any]) -> dict[str, Any]:
    """AVP:workspace + project 合并后冻结 SHA,配置失效即停。"""
    workspace = payload.get("workspace") or {}
    project = payload.get("project") or {}
    if not isinstance(workspace, dict) or not isinstance(project, dict):
        return _fail("workspace and project must be mappings")
    resolved = {**workspace, **project, "frozen": True}
    dest = Path(str(payload.get("dest") or "data/workspace/.pipeline/resolved-profile.json"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(resolved, ensure_ascii=False, sort_keys=True, indent=2)
    dest.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    sha_path = dest.with_suffix(".sha256")
    sha_path.write_text(digest, encoding="utf-8")
    return _ok(resolved_path=str(dest), sha256=digest, sha_path=str(sha_path))


def verify_profile(payload: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(payload.get("resolved_path") or ""))
    if not path.exists():
        return _fail("resolved profile missing")
    text = path.read_text(encoding="utf-8")
    actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
    expected = str(payload.get("sha256") or "").strip()
    sha_file = path.with_suffix(".sha256")
    if not expected and sha_file.exists():
        expected = sha_file.read_text(encoding="utf-8").strip()
    passed = bool(expected) and actual == expected
    return _ok(passed=passed, actual=actual, expected=expected)


def nle_recut(payload: dict[str, Any]) -> dict[str, Any]:
    """ChatCut:按时间线重导出,不是再跑一条管线。"""
    clips = [Path(str(p)) for p in (payload.get("clips") or []) if str(p)]
    dest = Path(str(payload.get("output_path") or "output/nle/recut.mp4"))
    existing = [p for p in clips if p.exists() and p.stat().st_size > 0]
    if not existing:
        return _fail("no clip files")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if len(existing) == 1:
        if existing[0].resolve() != dest.resolve():
            shutil.copyfile(existing[0], dest)
        return _ok(video_path=str(dest), clips=1)
    if not shutil.which("ffmpeg"):
        return _fail("ffmpeg not on PATH")
    listing = dest.with_suffix(".txt")
    listing.write_text(
        "".join(f"file '{p.resolve()}'\n" for p in existing),
        encoding="utf-8",
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(listing),
        "-c",
        "copy",
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not dest.exists():
        return _fail((proc.stderr or "ffmpeg concat failed")[-400:])
    return _ok(video_path=str(dest), clips=len(existing))


KIT_HANDLERS: dict[str, Any] = {
    "watch.video": watch_video_tool,
    "tongjian.l0": tongjian_l0,
    "tongjian.provenance": tongjian_provenance,
    "storygraph.extract": storygraph_extract,
    "explainer.manim": explainer_manim,
    "explainer.cues": explainer_cues_from_text,
    "avatar.compose": avatar_compose,
    "tts.synth": tts_synth,
    "director.scene_stage": director_scene_stage,
    "shot.export": shot_export,
    "profile.freeze": freeze_profile,
    "profile.verify": verify_profile,
    "nle.recut": nle_recut,
}

KIT_SPECS: list[tuple[str, str, str, tuple[str, ...], tuple[str, ...]]] = [
    ("watch.video", "watch", "看片+概念,三条线都能先看", ("source",), ("concepts", "transcript")),
    ("tongjian.l0", "tongjian", "史料闸,短剧/解说可借", ("raw_text",), ("chapter_ir",)),
    ("tongjian.provenance", "tongjian", "对白必须有出处或戏剧化标记", ("lines",), ("passed",)),
    ("storygraph.extract", "shortdrama", "手稿抽故事图", ("raw_text",), ("story_graph",)),
    ("explainer.manim", "explainer", "代码即画面", ("prompt",), ("asset_path",)),
    ("explainer.cues", "explainer", "讲解文本→解说 cue", ("texts",), ("cues",)),
    (
        "avatar.compose",
        "avatar",
        "基础片过检后再叠口型",
        ("image_path", "audio_path"),
        ("avatar_path",),
    ),
    ("tts.synth", "tts", "lux/edge/auto 统一配音", ("text",), ("audio_path", "provider")),
    ("director.scene_stage", "director", "场面调度草案", ("scene",), ("scene_stage",)),
    ("shot.export", "shot", "一镜登记为跨线资产", ("shot_id",), ("asset",)),
    ("profile.freeze", "profile", "配置冻结+SHA", ("workspace", "project"), ("sha256",)),
    ("profile.verify", "profile", "校验冻结配置", ("resolved_path",), ("passed",)),
    ("nle.recut", "nle", "按时间线 ffmpeg 重导出", ("clips",), ("video_path",)),
]
