"""Word-anchored template compilation and rendering transaction (omodul layer)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.viralclone.omodul_impl._media import (
    _extract_frames,
    _mux_final_video_with_subtitles,
    _probe_video,
    _render_video_clips_concat,
    _sha256,
    _synthesize_voiceover_script,
    _transcribe_audio_with_whisper,
)
from hevi.layer4_legacy.viralclone.oprim_impl.specs import (
    ReferenceBreakdown,
    TemplateSegment,
    TemplateSpec,
    VisualAnchor,
    WordToken,
    validate_template_spec,
)
from hevi.layer4_legacy.viralclone.oskill_impl.anchoring import (
    align_segments_to_word_timestamps,
    build_ass_subtitles,
    build_timeline_from_anchors,
)
from hevi.layer4_legacy.viralclone.oskill_impl.watermark import (
    compute_watermark_spec,
    verify_implicit_watermark_metadata,
    verify_watermark_in_frame,
)
from hevi.studio.timeline import Timeline

_enabled_pillars = {"report", "cost", "decision_trail"}


def draft_template_from_breakdown(breakdown_dict: dict[str, Any]) -> TemplateSpec:
    """Draft a word-anchored TemplateSpec from a ReferenceBreakdown card."""
    b = ReferenceBreakdown.from_dict(breakdown_dict)
    segments: list[TemplateSegment] = []

    for idx, sent in enumerate(b.sentences):
        role = sent.get("role", "selling_point")
        seg_id = f"seg_{idx:02d}_{role}"
        slot_name = "hook_line" if role == "hook" else "cta" if role == "cta" else f"selling_point_{idx}"

        anchors = [
            VisualAnchor(
                event_type="cut",
                sentence_idx=idx,
                word_offset_idx=0,
                relative_delay_s=0.0,
                duration_s=round(sent.get("end_s", 2.0) - sent.get("start_s", 0.0), 2),
            )
        ]
        if role == "selling_point" and idx == 1:
            anchors.append(
                VisualAnchor(
                    event_type="product_card",
                    sentence_idx=idx,
                    word_offset_idx=0,
                    relative_delay_s=0.2,
                    duration_s=2.5,
                )
            )

        segments.append(
            TemplateSegment(
                segment_id=seg_id,
                role=role,
                narration_slot=slot_name,
                anchors=anchors,
                caption_style="karaoke",
            )
        )

    # If no segments, add standard 4-phase default
    if not segments:
        segments = [
            TemplateSegment("seg_01_hook", "hook", "hook_line", [VisualAnchor("cut", 0, 0, 0.0, 2.5)]),
            TemplateSegment("seg_02_sp1", "selling_point", "selling_point_1", [VisualAnchor("product_card", 1, 0, 0.0, 3.0)]),
            TemplateSegment("seg_03_proof", "proof", "proof_line", [VisualAnchor("cut", 2, 0, 0.0, 2.5)]),
            TemplateSegment("seg_04_cta", "cta", "cta", [VisualAnchor("cut", 3, 0, 0.0, 2.0)]),
        ]

    aspect = "9:16" if b.height > b.width else "16:9"
    w, h = (720, 1280) if aspect == "9:16" else (1280, 720)

    return TemplateSpec(
        template_id=f"tpl_{Path(b.source_video).stem}",
        aspect_ratio=aspect,
        width=w,
        height=h,
        fps=int(b.fps or 25),
        rhythm_archetype="fast_hook",
        segments=segments,
        slots_schema={
            "product": "string",
            "hook_line": "string",
            "selling_point_1": "string",
            "selling_point_2": "string",
            "proof_line": "string",
            "price": "string",
            "cta": "string",
            "host": "string",
            "lang": "string",
        },
        default_slots={
            "product": "旗舰超清真无线耳机",
            "hook_line": "你还在忍受嘈杂低劣的耳机音质吗？",
            "selling_point_1": "自适应智能深度降噪，还你沉浸听感。",
            "selling_point_2": "钛合金复合振膜，低音浑厚高音通透。",
            "proof_line": "实验室声学调校实测，好评率超98%。",
            "price": "限时¥129",
            "cta": "点击左下角小黄车立即抢购！",
            "host": "huayan",
            "lang": "zh",
        },
        visual_rules={
            "subtitle_font": "Noto Sans CJK SC",
            "subtitle_size": 40,
            "karaoke_highlight": True,
        },
    )


def compile_and_render_template(
    config: dict[str, Any],
    input_data: dict[str, Any],
    output_dir: str | Path,
    *,
    on_step: Any = None,
) -> dict[str, Any]:
    """Compile template with slot values into word-anchored Timeline JSON and render MP4."""
    t0 = time.time()
    trail: list[dict[str, Any]] = []
    dest = Path(output_dir)
    dest.mkdir(parents=True, exist_ok=True)

    # 1. Load or parse TemplateSpec
    template_raw = input_data.get("template")
    if isinstance(template_raw, dict):
        spec = TemplateSpec.from_dict(template_raw)
    elif isinstance(template_raw, str) and Path(template_raw).is_file():
        spec = TemplateSpec.from_dict(json.loads(Path(template_raw).read_text(encoding="utf-8")))
    elif input_data.get("breakdown"):
        spec = draft_template_from_breakdown(input_data["breakdown"])
    else:
        # Fallback default template
        spec = TemplateSpec.from_dict(input_data.get("spec") or {})

    # Override aspect ratio or dimensions if requested
    aspect = input_data.get("aspect_ratio") or spec.aspect_ratio
    if aspect == "9:16":
        spec.width, spec.height, spec.aspect_ratio = 720, 1280, "9:16"
    elif aspect == "16:9":
        spec.width, spec.height, spec.aspect_ratio = 1280, 720, "16:9"

    errors = validate_template_spec(spec)
    if errors:
        return {
            "status": "blocked",
            "reason": f"INVALID_TEMPLATE_SPEC: {errors}",
            "cost": {"total_usd": 0.0, "provider": "zero_local_cpu"},
            "decision_trail": [{"step": "validate_template", "errors": errors}],
            "report": {},
        }
    trail.append({"step": "validate_template", "template_id": spec.template_id})

    try:
        # 2. Merge slots with default slots
        slots = {**spec.default_slots, **(input_data.get("slots") or {})}
        lang = str(slots.get("lang") or input_data.get("lang") or "zh")

        # Extract lines to synthesize
        sentences_to_synth: list[str] = []
        for seg in spec.segments:
            text = str(slots.get(seg.narration_slot) or "").strip()
            if not text:
                text = f"{seg.role} statement"
            sentences_to_synth.append(text)
        trail.append({"step": "prepare_script", "sentences": sentences_to_synth})

        # 3. Step 1: Synthesize narration with Piper TTS
        audio_dir = dest / "audio_work"
        full_wav, sent_cues = _synthesize_voiceover_script(
            sentences_to_synth, audio_dir, lang=lang, gap_s=0.25
        )
        total_audio_dur = _probe_video(full_wav)["duration_s"]
        trail.append({"step": "tts_synthesis", "wav": str(full_wav), "duration_s": total_audio_dur})

        # 4. Step 2: Faster-Whisper alignment for exact word-level timestamps
        words_raw, aligned_sents = _transcribe_audio_with_whisper(full_wav)
        aligned_words = [
            WordToken(word=w["word"], start_s=w["start_s"], end_s=w["end_s"], score=w["score"])
            for w in words_raw
        ]
        trail.append({"step": "whisper_realignment", "words_count": len(aligned_words)})

        # 5. Step 3: Align visual segments and anchors onto the new word timestamps
        compiled_segments = align_segments_to_word_timestamps(
            spec, slots, aligned_sents or sent_cues, aligned_words
        )
        trail.append({"step": "word_anchor_alignment", "segments": compiled_segments})

        # 6. Step 4: Build Canonical Hevi Timeline JSON
        brolls = list(input_data.get("brolls") or input_data.get("broll_sources") or [])
        product_video = str(input_data.get("product_video") or "")
        tl_id = f"tl_{spec.template_id}_{int(time.time())}"
        timeline = build_timeline_from_anchors(
            timeline_id=tl_id,
            title=f"ViralClone: {slots.get('product', 'Promo')}",
            spec=spec,
            compiled_segments=compiled_segments,
            aligned_words=aligned_words,
            broll_sources=brolls,
            product_video_path=product_video,
        )

        timeline_path = dest / f"{tl_id}.json"
        timeline_path.write_text(
            json.dumps(timeline.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        trail.append({"step": "build_timeline_json", "path": str(timeline_path)})

        # 7. Step 5: Render ASS Subtitles with Karaoke & GB 45438 AI Watermark
        wm_text = str(input_data.get("watermark_text") or "AI生成")
        wm_spec = compute_watermark_spec(spec.width, spec.height, text=wm_text, duration_s=2.5)

        ass_content = build_ass_subtitles(
            words=aligned_words,
            sentences=compiled_segments,
            width=spec.width,
            height=spec.height,
            font_name="Noto Sans CJK SC",
            font_size=int(min(spec.width, spec.height) * 0.058),
            watermark_text=wm_spec.text,
            watermark_duration_s=wm_spec.duration_s,
            watermark_font_size=wm_spec.font_size_px,
        )
        ass_path = dest / "subtitles.ass"
        ass_path.write_text(ass_content, encoding="utf-8")
        trail.append({"step": "build_ass_subtitles", "path": str(ass_path)})

        # 8. Step 6: Visual cuts render
        cuts_for_render = [
            {
                "source": c.source,
                "duration_s": c.duration_s,
                "source_in_s": c.source_in_s,
            }
            for c in timeline.clips
            if c.track == "video"
        ]
        visual_mp4 = dest / "visual_cuts.mp4"
        _render_video_clips_concat(
            clips=cuts_for_render,
            total_duration_s=total_audio_dur,
            width=spec.width,
            height=spec.height,
            output_mp4=visual_mp4,
            fps=spec.fps,
        )
        trail.append({"step": "render_cuts", "path": str(visual_mp4)})

        # 9. Step 7: Final Mux with ASS Subtitles, Audio & Container Metadata
        final_mp4 = dest / f"{input_data.get('output_name', 'final')}.mp4"
        _mux_final_video_with_subtitles(
            video_path=visual_mp4,
            audio_path=full_wav,
            ass_path=ass_path,
            output_path=final_mp4,
            metadata_comment=wm_spec.implicit_comment,
        )
        trail.append({"step": "mux_final", "path": str(final_mp4)})

        # 10. QA & Verification
        probe_final = _probe_video(final_mp4)
        sha_final = _sha256(final_mp4)
        sample_frames = _extract_frames(final_mp4, dest / "qa_frames", fps=1.0, max_frames=6)

        # Watermark QA: verify pixel size and metadata
        wm_qa = verify_watermark_in_frame(sample_frames[0], spec.width, spec.height, wm_spec)
        meta_qa = verify_implicit_watermark_metadata(final_mp4)

        elapsed = time.time() - t0
        report = {
            "video_path": str(final_mp4),
            "timeline_path": str(timeline_path),
            "ass_path": str(ass_path),
            "sha256": sha_final,
            "duration_s": probe_final["duration_s"],
            "resolution": f"{probe_final['width']}x{probe_final['height']}",
            "fps": probe_final["fps"],
            "watermark_qa": wm_qa,
            "metadata_qa": meta_qa,
            "qa_frames": [str(p) for p in sample_frames],
            "elapsed_s": round(elapsed, 2),
        }

        return {
            "status": "succeeded",
            "report": report,
            "cost": {"total_usd": 0.0, "provider": "zero_local_cpu"},
            "decision_trail": trail,
        }

    except Exception as exc:
        trail.append({"step": "exception", "error": str(exc)})
        return {
            "status": "failed",
            "reason": f"COMPILER_FAILED: {exc}",
            "cost": {"total_usd": 0.0, "provider": "zero_local_cpu"},
            "decision_trail": trail,
            "report": {},
        }
