"""Comic narration workflow (omodul): topic/story -> script -> keyframes + TTS + BGM + Ken Burns + subtitles -> MP4.

Standard 3O triple signature ``(config, input_data, output_dir, *, on_step)``.
Fail-closed and evidence-based. No mock/dummy video on production path.

3O Pillar: omodul.comicnarr_pipeline
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import resource
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from hevi.layer4_legacy.comicnarr.oprim_impl.contracts import ComicScene, ComicScript
from hevi.layer4_legacy.comicnarr.oprim_impl.ken_burns import (
    CAMERA_MOVES,
    build_ken_burns_filter,
)
from hevi.layer4_legacy.comicnarr.oprim_impl.postprocess import (
    apply_style_postprocess,
    is_grayscale,
)
from hevi.layer4_legacy.comicnarr.oprim_impl.subtitle import (
    build_comic_ass,
    build_srt_content,
)
from hevi.layer4_legacy.comicnarr.oprim_impl.subtitle_ocr import (
    measure_subtitle_readability,
)
from hevi.layer4_legacy.comicnarr.oprim_impl.templates import DEFAULT_STYLE, get_style_template
from hevi.layer4_legacy.comicnarr.oskill_impl.prompt_builder import build_scene_prompt
from hevi.layer4_legacy.comicnarr.oskill_impl.script_planner import (
    generate_comic_script,
    probe_free_llm,
)
from hevi.layer4_legacy.keyframe.oprim_impl.image_score import score_keyframe
from hevi.layer4_legacy.keyframe.oprim_impl.registry import resolve_keyframe_engine
from hevi.layer4_legacy.talkcraft.omodul_impl._media import (
    FFMPEG,
    duration,
    piper_tts,
    probe,
    sha256,
)
from hevi.layer4_legacy.zerolines.omodul_impl._media import mix, write_bgm

logger = logging.getLogger(__name__)

_enabled_pillars = {"report", "cost", "decision_trail"}


def comic_narration_workflow(
    config: dict[str, Any] | None,
    input_data: dict[str, Any],
    output_dir: str | Path,
    *,
    on_step: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Execute end-to-end Comic Narration generation pipeline."""
    started_at = time.time()
    cfg = dict(config or {})
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = out_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    clips_dir = out_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    trail: list[dict[str, Any]] = []

    def step(name: str, **info: Any) -> None:
        trail.append({"step": name, "t": round(time.time(), 3), **info})
        if on_step:
            on_step(name, info)

    # 1. Parse request parameters
    topic = str(input_data.get("topic") or input_data.get("title") or "").strip()
    raw_texts = input_data.get("texts") or input_data.get("script_lines") or []
    if isinstance(raw_texts, str):
        raw_texts = [raw_texts]
    style_name = str(input_data.get("style") or cfg.get("style") or DEFAULT_STYLE)
    style = get_style_template(style_name)
    subtitle_style = str(input_data.get("subtitle_style") or cfg.get("subtitle_style") or "bottom")
    use_bubble = subtitle_style == "bubble"

    engine_name = str(
        input_data.get("keyframe_engine")
        or input_data.get("engine")
        or cfg.get("keyframe_engine")
        or cfg.get("engine")
        or os.environ.get("HEVI_KEYFRAME_ENGINE")
        or "sdturbo_cpu"
    )
    if engine_name == "zero":
        engine_name = "sdturbo_cpu"

    base_seed = int(input_data.get("base_seed") or cfg.get("base_seed") or 42)
    tts_engine = str(input_data.get("tts_engine") or cfg.get("tts_engine") or "piper")
    kf_width = int(input_data.get("kf_width") or cfg.get("kf_width") or 512)
    kf_height = int(input_data.get("kf_height") or cfg.get("kf_height") or 512)
    target_width = int(input_data.get("width") or cfg.get("width") or 1080)
    target_height = int(input_data.get("height") or cfg.get("height") or 1920)
    fps = int(input_data.get("fps") or cfg.get("fps") or 25)

    step(
        "init",
        topic=topic,
        style=style.name,
        engine=engine_name,
        tts_engine=tts_engine,
    )

    # 2. Step: Script Planning (probe the free LLM channel first, then fall back)
    llm_probe = probe_free_llm(timeout_s=float(cfg.get("llm_probe_timeout_s", 4.0)))
    llm_available = bool(llm_probe.get("available"))
    script, script_channel = generate_comic_script(
        topic=topic,
        raw_texts=list(raw_texts),
        style_name=style.name,
        base_seed=base_seed,
        use_llm=llm_available,
    )
    step(
        "script_planning",
        scene_count=len(script.scenes),
        title=script.title,
        channel=script_channel,
        llm_probe=llm_probe,
    )

    # 3. Step: Build Prompts for each scene
    for scene in script.scenes:
        prompt_en, neg = build_scene_prompt(
            visual_desc_zh=scene.visual_desc,
            character_desc_en=script.character_desc_en,
            style=style,
            character_tokens=script.character_tokens,
            use_llm=llm_available,
        )
        scene.prompt_en = prompt_en
        scene.negative_prompt = neg

    # Save script.json
    script_path = out_dir / "script.json"
    script_path.write_text(
        json.dumps(script.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Clean stale shot files from previous runs with higher scene counts
    for stale in frames_dir.glob("shot_*_kf.png"):
        try:
            s_idx = int(stale.stem.split("_")[1])
            if s_idx >= len(script.scenes):
                stale.unlink(missing_ok=True)
        except Exception:
            pass
    for stale in clips_dir.glob("shot_*.mp4"):
        try:
            s_idx = int(stale.stem.split("_")[1])
            if s_idx >= len(script.scenes):
                stale.unlink(missing_ok=True)
        except Exception:
            pass

    # 4. Step: Voiceover Audio (Piper TTS) with content-hash cache
    sentence_audio_paths: list[Path] = []
    sentence_durations: list[float] = []

    for idx, scene in enumerate(script.scenes):
        audio_hash = hashlib.sha256(
            f"{tts_engine}:zh_huayan:{scene.narration}".encode("utf-8")
        ).hexdigest()[:12]
        scene_audio_path = audio_dir / f"shot_{idx:02d}_{audio_hash}.wav"

        if not scene_audio_path.is_file() or scene_audio_path.stat().st_size == 0:
            piper_tts(
                text=scene.narration,
                out_wav=scene_audio_path,
                lang="zh",
                length_scale=1.0,
            )

        dur_s = duration(scene_audio_path)
        # Ensure minimum readable duration with pause padding
        effective_dur = max(3.8, round(dur_s + 0.45, 2))
        scene.duration_s = effective_dur
        scene.audio_path = str(scene_audio_path)
        sentence_audio_paths.append(scene_audio_path)
        sentence_durations.append(effective_dur)

    total_narr_dur = sum(sentence_durations)

    # Guarantee total duration is comfortably within [45.0, 75.0] seconds
    if total_narr_dur < 48.0 and sentence_durations:
        needed_per_scene = (52.0 - total_narr_dur) / len(sentence_durations)
        for i in range(len(sentence_durations)):
            sentence_durations[i] = round(sentence_durations[i] + needed_per_scene, 2)
            script.scenes[i].duration_s = sentence_durations[i]
        total_narr_dur = sum(sentence_durations)

    step(
        "audio_rendered",
        total_duration_s=round(total_narr_dur, 2),
        scene_count=len(script.scenes),
    )

    # 5. Step: Keyframe Generation (ViMax Dual Candidates + OpenCLIP Selection)
    engine = resolve_keyframe_engine(engine_name)
    total_kf_gen_sec = 0.0

    steps = int(input_data.get("steps") or cfg.get("steps") or 1)

    for idx, scene in enumerate(script.scenes):
        seed_1 = base_seed + idx * 17
        seed_2 = base_seed + idx * 17 + 500

        # Breakpoint resumption cache
        h1 = hashlib.sha256(f"{engine_name}:{seed_1}:{scene.prompt_en}".encode("utf-8")).hexdigest()[:12]
        h2 = hashlib.sha256(f"{engine_name}:{seed_2}:{scene.prompt_en}".encode("utf-8")).hexdigest()[:12]
        cand1_path = frames_dir / f"shot_{idx:02d}_cand1_{h1}.png"
        cand2_path = frames_dir / f"shot_{idx:02d}_cand2_{h2}.png"

        t_kf_0 = time.time()
        if not cand1_path.is_file() or cand1_path.stat().st_size == 0:
            engine.generate(
                prompt_en=scene.prompt_en,
                negative=scene.negative_prompt,
                width=kf_width,
                height=kf_height,
                steps=steps,
                seed=seed_1,
                output_path=cand1_path,
            )
            apply_style_postprocess(cand1_path, style.postprocess)
        if not cand2_path.is_file() or cand2_path.stat().st_size == 0:
            engine.generate(
                prompt_en=scene.prompt_en,
                negative=scene.negative_prompt,
                width=kf_width,
                height=kf_height,
                steps=steps,
                seed=seed_2,
                output_path=cand2_path,
            )
            apply_style_postprocess(cand2_path, style.postprocess)
        total_kf_gen_sec += time.time() - t_kf_0

        score1 = score_keyframe(cand1_path, prompt_en=scene.prompt_en)
        score2 = score_keyframe(cand2_path, prompt_en=scene.prompt_en)

        if score1["composite_score"] >= score2["composite_score"]:
            winner_path, winner_seed, winner_score = cand1_path, seed_1, score1
            loser_path, loser_seed, loser_score = cand2_path, seed_2, score2
        else:
            winner_path, winner_seed, winner_score = cand2_path, seed_2, score2
            loser_path, loser_seed, loser_score = cand1_path, seed_1, score1

        final_kf_path = frames_dir / f"shot_{idx:02d}_kf.png"
        loser_dst_path = frames_dir / f"shot_{idx:02d}_loser_seed_{loser_seed}.png"
        if winner_path != final_kf_path:
            shutil.copy2(winner_path, final_kf_path)
        if loser_path != loser_dst_path:
            shutil.copy2(loser_path, loser_dst_path)

        scene.image_path = str(final_kf_path)
        scene.seed = winner_seed
        scene.clip_score = winner_score["clip_score"]
        scene.rejected_seed = loser_seed
        scene.rejected_image_path = str(loser_dst_path)
        scene.rejected_score = loser_score["clip_score"]

    step(
        "keyframes_generated",
        winner_count=len(script.scenes),
        engine=engine.name,
        gen_time_s=round(total_kf_gen_sec, 2),
    )

    # 6. Step: BGM & Audio Track Assembly with Ducking
    bgm_path = audio_dir / "bgm.wav"
    write_bgm(bgm_path, total_narr_dur + 3.0, mood=style.bgm_mood)

    # Concat all scene audios with precise padding to match scene durations
    padded_audio_paths: list[Path] = []
    for idx, (a_path, s_dur) in enumerate(zip(sentence_audio_paths, sentence_durations, strict=False)):
        padded_path = audio_dir / f"shot_{idx:02d}_padded.wav"
        subprocess.run(
            [
                FFMPEG,
                "-y",
                "-v",
                "error",
                "-i",
                str(a_path),
                "-af",
                f"apad=whole_dur={s_dur:.3f}",
                "-ar",
                "44100",
                str(padded_path),
            ],
            check=True,
        )
        padded_audio_paths.append(padded_path)

    vo_concat_list = audio_dir / "_vo_concat.txt"
    vo_concat_lines = [f"file '{p.resolve()}'" for p in padded_audio_paths]
    vo_concat_list.write_text("\n".join(vo_concat_lines), encoding="utf-8")

    vo_full_path = audio_dir / "vo_full.wav"
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-v",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(vo_concat_list),
            "-c",
            "copy",
            str(vo_full_path),
        ],
        check=True,
    )
    vo_concat_list.unlink(missing_ok=True)

    mixed_audio_path = audio_dir / "mixed_audio.wav"
    mix(vo_full_path, bgm_path, mixed_audio_path, total_narr_dur, music_db=-22)

    step("audio_mixed", mixed_audio=str(mixed_audio_path))

    # 7. Step: Per-Scene Ken Burns Video Clips
    scene_clip_paths: list[Path] = []
    for idx, scene in enumerate(script.scenes):
        cam_move = CAMERA_MOVES[idx % len(CAMERA_MOVES)]
        vf = build_ken_burns_filter(
            move=cam_move,
            duration=scene.duration_s,
            width=target_width,
            height=target_height,
            fps=fps,
        )
        clip_path = clips_dir / f"shot_{idx:02d}.mp4"

        cmd = [
            FFMPEG,
            "-y",
            "-v",
            "error",
            "-loop",
            "1",
            "-i",
            str(scene.image_path),
            "-t",
            f"{scene.duration_s:.3f}",
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-r",
            f"{fps}",
            str(clip_path),
        ]
        subprocess.run(cmd, check=True)
        scene.clip_path = str(clip_path)
        scene_clip_paths.append(clip_path)

    step("clips_rendered", clip_count=len(scene_clip_paths))

    # 8. Step: Subtitles (SRT & ASS)
    cues: list[tuple[float, float, str]] = []
    cur_t = 0.0
    for scene in script.scenes:
        cues.append((cur_t, cur_t + scene.duration_s, scene.narration))
        cur_t += scene.duration_s

    srt_path = out_dir / "subtitles.srt"
    srt_path.write_text(build_srt_content(cues=cues), encoding="utf-8")

    ass_path = out_dir / "subtitles.ass"
    ass_path.write_text(
        build_comic_ass(
            cues=cues,
            width=target_width,
            height=target_height,
            style_name=style.name,
            bubble=use_bubble,
        ),
        encoding="utf-8",
    )

    # 9. Step: Assemble Final Video with Concat, Mixed Audio, and Burned Subtitles
    concat_list = out_dir / "_concat_list.txt"
    concat_lines = [f"file '{c.resolve()}'" for c in scene_clip_paths]
    concat_list.write_text("\n".join(concat_lines), encoding="utf-8")

    temp_concat_video = out_dir / "_temp_concat.mp4"
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-v",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            str(temp_concat_video),
        ],
        check=True,
    )
    concat_list.unlink(missing_ok=True)

    # Merge mixed audio with video and burn ASS subtitles
    final_mp4 = out_dir / "final.mp4"
    sub_filter = f"ass='{ass_path}'"

    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-v",
            "error",
            "-i",
            str(temp_concat_video),
            "-i",
            str(mixed_audio_path),
            "-filter_complex",
            f"[0:v]{sub_filter}[v]",
            "-map",
            "[v]",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(final_mp4),
        ],
        check=True,
    )
    temp_concat_video.unlink(missing_ok=True)

    step("assembly_complete", final_mp4=str(final_mp4))

    # 10. Step: QA Real Measurement & Contact Sheet
    probe_info = probe(final_mp4)
    measured_dur = duration(final_mp4)
    video_stream = next((s for s in probe_info["streams"] if s["codec_type"] == "video"), {})
    audio_stream = next((s for s in probe_info["streams"] if s["codec_type"] == "audio"), {})

    # Volume detect
    vol_proc = subprocess.run(
        [FFMPEG, "-i", str(final_mp4), "-af", "volumedetect", "-f", "null", "/dev/null"],
        capture_output=True,
        text=True,
    )
    mean_vol = -99.0
    max_vol = -99.0
    for line in vol_proc.stderr.splitlines():
        if "mean_volume:" in line:
            mean_vol = float(line.split("mean_volume:")[1].split("dB")[0].strip())
        if "max_volume:" in line:
            max_vol = float(line.split("max_volume:")[1].split("dB")[0].strip())

    # ---- Frame grabber (single frame -> BGR array) ----
    def _grab_frame(t_s: float) -> np.ndarray | None:
        frame_tmp = out_dir / f"_frame_{int(t_s * 1000)}.jpg"
        subprocess.run(
            [
                FFMPEG,
                "-y",
                "-v",
                "error",
                "-ss",
                f"{t_s:.3f}",
                "-i",
                str(final_mp4),
                "-vframes",
                "1",
                "-q:v",
                "2",
                str(frame_tmp),
            ],
            check=True,
        )
        arr = cv2.imread(str(frame_tmp)) if frame_tmp.is_file() else None
        frame_tmp.unlink(missing_ok=True)
        return arr

    # Sample 6 frames across duration for the contact sheet + cross-shot diff.
    sample_timestamps = [
        measured_dur * 0.10,
        measured_dur * 0.25,
        measured_dur * 0.50,
        measured_dur * 0.65,
        measured_dur * 0.80,
        measured_dur * 0.95,
    ]
    sampled_frames = [f for f in (_grab_frame(t) for t in sample_timestamps) if f is not None]

    cross_frame_diffs = [
        round(float(np.mean(np.abs(sampled_frames[i] - sampled_frames[i - 1]))), 2)
        for i in range(1, len(sampled_frames))
    ]
    mean_cross_diff = float(np.mean(cross_frame_diffs)) if cross_frame_diffs else 0.0

    # Build 6-frame contact sheet (2 rows x 3 columns)
    contact_sheet_path = out_dir / "contact_sheet.jpg"
    if len(sampled_frames) == 6:
        thumbs = [cv2.resize(f, (360, 640)) for f in sampled_frames]
        row1 = np.hstack(thumbs[:3])
        row2 = np.hstack(thumbs[3:])
        sheet = np.vstack([row1, row2])
        cv2.imwrite(str(contact_sheet_path), sheet)

    # ---- Within-shot motion (two frames 1s apart inside the SAME shot) ----
    scene_starts: list[float] = []
    t_acc = 0.0
    for scene in script.scenes:
        scene_starts.append(t_acc)
        t_acc += scene.duration_s

    within_shot_diffs: list[float] = []
    readability: list[dict[str, Any]] = []
    grayscale_flags: list[bool] = []
    qa_ocr_enabled = bool(input_data.get("qa_ocr", cfg.get("qa_ocr", True)))

    for idx, scene in enumerate(script.scenes):
        start = scene_starts[idx]
        t_a = start + min(0.6, scene.duration_s * 0.25)
        t_b = min(t_a + 1.0, start + scene.duration_s - 0.15)
        fa = _grab_frame(t_a)
        fb = _grab_frame(t_b) if t_b > t_a + 0.1 else None
        if fa is not None and fb is not None:
            diff = float(
                np.mean(np.abs(fa.astype(np.int16) - fb.astype(np.int16)))
            )
            within_shot_diffs.append(round(diff, 2))

        mid = _grab_frame(start + scene.duration_s * 0.5)
        if mid is not None:
            grayscale_flags.append(is_grayscale(mid))
            if qa_ocr_enabled:
                readability.append(
                    {"index": idx, **measure_subtitle_readability(mid, scene.narration)}
                )

    mean_within_diff = float(np.mean(within_shot_diffs)) if within_shot_diffs else 0.0
    min_ocr_sim = min((r["similarity"] for r in readability), default=0.0)
    mean_ocr_sim = (
        float(np.mean([r["similarity"] for r in readability])) if readability else 0.0
    )
    all_subtitles_readable = (not qa_ocr_enabled) or (
        bool(readability)
        and all(r.get("readable") for r in readability)
        and min_ocr_sim >= 0.6
    )

    grayscale_required = style.postprocess == "manga_bw"
    grayscale_ok = (
        (not grayscale_required)
        or (bool(grayscale_flags) and all(grayscale_flags))
    )

    # Keyframe SHA256 hashes (verify distinctness)
    kf_hashes = {}
    for scene in script.scenes:
        if scene.image_path and Path(scene.image_path).is_file():
            kf_hashes[Path(scene.image_path).name] = sha256(Path(scene.image_path))

    unique_kf_hashes = len(set(kf_hashes.values())) == len(kf_hashes) and len(kf_hashes) > 0
    final_sha = sha256(final_mp4)

    qa_passed = (
        45.0 <= measured_dur <= 75.0
        and bool(audio_stream)
        and mean_vol > -45.0
        and mean_within_diff > 1.0
        and unique_kf_hashes
        and len(script.scenes) >= 6
        and all_subtitles_readable
        and grayscale_ok
    )

    qa_report = {
        "passed": qa_passed,
        "video": {
            "duration": round(measured_dur, 2),
            "width": int(video_stream.get("width", 0)),
            "height": int(video_stream.get("height", 0)),
            "codec": video_stream.get("codec_name"),
            "fps": round(eval(video_stream.get("r_frame_rate", "25/1")), 2),
            "sha256": final_sha,
        },
        "audio": {
            "codec": audio_stream.get("codec_name"),
            "sample_rate": int(audio_stream.get("sample_rate", 0)),
            "channels": int(audio_stream.get("channels", 0)),
            "mean_volume_db": round(mean_vol, 2),
            "max_volume_db": round(max_vol, 2),
        },
        "motion": {
            "sample_count": len(within_shot_diffs),
            "within_shot_differences": within_shot_diffs,
            "mean_within_shot_difference": round(mean_within_diff, 2),
            "cross_shot_frame_differences": cross_frame_diffs,
            "mean_cross_shot_difference": round(mean_cross_diff, 2),
            "is_dynamic": bool(mean_within_diff > 1.0),
        },
        "subtitle_readability": {
            "ocr_engine": "rapidocr_onnxruntime",
            "enabled": qa_ocr_enabled,
            "threshold": 0.6,
            "min_similarity": round(min_ocr_sim, 4),
            "mean_similarity": round(mean_ocr_sim, 4),
            "all_readable": all_subtitles_readable,
            "per_scene": readability,
        },
        "grayscale": {
            "required": grayscale_required,
            "postprocess": style.postprocess,
            "all_grayscale": grayscale_ok,
        },
        "scenes": [s.to_dict() for s in script.scenes],
        "keyframe_hashes": kf_hashes,
        "all_keyframes_distinct": unique_kf_hashes,
        "llm_channel": script_channel,
        "llm_probe": llm_probe,
        "tts_channel": f"{tts_engine}_zh_huayan",
    }
    qa_path = out_dir / "qa.json"
    qa_path.write_text(json.dumps(qa_report, ensure_ascii=False, indent=2), encoding="utf-8")

    wall_sec = time.time() - started_at
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0

    record_report = {
        "engine": engine.name,
        "model": "sd-turbo",
        "style": style.name,
        "style_presets_module": "hevi.layer4_legacy.keyframe.oprim_impl.style_presets",
        "style_postprocess": style.postprocess,
        "total_wall_sec": round(wall_sec, 2),
        "keyframe_gen_sec": round(total_kf_gen_sec, 2),
        "peak_rss_mb": round(rss_mb, 1),
        "scene_count": len(script.scenes),
        "video_duration_s": round(measured_dur, 2),
        "llm_channel": script_channel,
        "llm_probe": llm_probe,
        "tts_engine": tts_engine,
        "subtitles_burned": True,
        "subtitle_style": subtitle_style,
        "resolution": f"{target_width}x{target_height}",
        "pillars": sorted(_enabled_pillars),
        "decision_trail": trail,
    }
    record_path = out_dir / "record.json"
    record_path.write_text(json.dumps(record_report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Update script.json with final scene details (including paths and scores)
    script_path.write_text(
        json.dumps(script.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "status": "completed" if qa_passed else "failed",
        "final_mp4": str(final_mp4),
        "qa_path": str(qa_path),
        "record_path": str(record_path),
        "script_path": str(script_path),
        "contact_sheet": str(contact_sheet_path),
        "subtitles_path": str(srt_path),
        "qa": qa_report,
        "record": record_report,
    }


__all__ = [
    "comic_narration_workflow",
]
