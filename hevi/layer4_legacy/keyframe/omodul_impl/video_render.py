"""Video render pipeline omodul: keyframe generation, camera motion, TTS, subtitles, and video assembly.

3O Pillar: omodul.video_render
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from hevi.layer4_legacy.keyframe.oprim_impl.character_card import CharacterCard
from hevi.layer4_legacy.keyframe.oprim_impl.contracts import KeyframeEngine, KeyframeResult
from hevi.layer4_legacy.keyframe.oprim_impl.face_gate import (
    compute_face_cosine,
    detect_faces,
    extract_face_embedding,
    verify_character_face,
)
from hevi.layer4_legacy.keyframe.oprim_impl.image_score import (
    compute_clip_similarity,
    score_keyframe,
)
from hevi.layer4_legacy.keyframe.oprim_impl.registry import get_engine, resolve_keyframe_engine
from hevi.layer4_legacy.keyframe.oskill_impl.prompt_translator import (
    DEFAULT_NEGATIVE,
    zh_shot_to_sd_prompt,
)
from hevi.layer4_legacy.talkcraft.omodul_impl._media import (
    FFMPEG,
    FFPROBE,
    duration,
    piper_tts,
    probe,
    sha256,
)

logger = logging.getLogger(__name__)

CAMERA_MOVES = ("push", "pan_r", "pull", "pan_l")


@dataclass
class RenderConfig:
    engine: str = "sdturbo_cpu"
    target_width: int = 1080
    target_height: int = 1920
    fps: int = 25
    kf_width: int = 512
    kf_height: int = 512
    steps: int = 2
    face_threshold: float = 0.35
    enable_tts: bool = True
    enable_subtitles: bool = True
    base_seed: int = 42


def _format_srt_time(seconds: float) -> str:
    millis = int(round((seconds - int(seconds)) * 1000))
    s = int(seconds) % 60
    m = (int(seconds) // 60) % 60
    h = int(seconds) // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{millis:03d}"


def _camera_filter_str(move: str, d: float, w: int, h: int, fps: int = 25) -> str:
    """Generate ffmpeg -vf filter string for Ken Burns camera motion."""
    if move == "push":
        # Slow zoom in: scale factor from 1.0 to 1.15
        k = f"(1.0+0.15*t/{d})"
        return (
            f"fps={fps},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
            f"scale=w='trunc({w}*{k}/2)*2':h='trunc({h}*{k}/2)*2':eval=frame,"
            f"crop={w}:{h}:x='(iw-{w})/2':y='(ih-{h})/2',setsar=1,format=yuv420p"
        )
    elif move == "pull":
        # Slow zoom out: scale factor from 1.15 down to 1.0
        k = f"(1.15-0.15*t/{d})"
        return (
            f"fps={fps},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
            f"scale=w='trunc({w}*{k}/2)*2':h='trunc({h}*{k}/2)*2':eval=frame,"
            f"crop={w}:{h}:x='(iw-{w})/2':y='(ih-{h})/2',setsar=1,format=yuv420p"
        )
    elif move == "pan_l":
        # Pan from right to left
        sw, sh = int(w * 1.15) // 2 * 2, int(h * 1.15) // 2 * 2
        return (
            f"fps={fps},scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},"
            f"crop={w}:{h}:x='(iw-{w})*(1-t/{d})':y='(ih-{h})/2',setsar=1,format=yuv420p"
        )
    else:  # pan_r
        # Pan from left to right
        sw, sh = int(w * 1.15) // 2 * 2, int(h * 1.15) // 2 * 2
        return (
            f"fps={fps},scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},"
            f"crop={w}:{h}:x='(iw-{w})*t/{d}':y='(ih-{h})/2',setsar=1,format=yuv420p"
        )


def generate_character_portraits(
    cards: list[CharacterCard],
    *,
    engine: KeyframeEngine,
    output_dir: Path,
    kf_width: int = 512,
    kf_height: int = 512,
    seeds: tuple[int, int, int] = (101, 102, 103),
) -> list[CharacterCard]:
    """Generate 3 seed candidates per character card, pick best face as reference portrait."""
    portraits_dir = output_dir / "portraits"
    portraits_dir.mkdir(parents=True, exist_ok=True)

    for card in cards:
        if card.ref_image and card.ref_face_embedding:
            continue

        best_emb = None
        best_path = None
        best_score = -1.0

        prompt = f"{card.name}, {card.appearance_en_tokens}, close-up portrait, clean background, sharp focus"

        for s in seeds:
            cand_path = portraits_dir / f"{card.id}_cand_seed_{s}.png"
            if not cand_path.is_file():
                engine.generate(
                    prompt_en=prompt,
                    width=kf_width,
                    height=kf_height,
                    steps=2,
                    seed=s,
                    output_path=cand_path,
                )

            emb = extract_face_embedding(cand_path)
            score_data = score_keyframe(cand_path, prompt_en=prompt)
            composite = score_data.get("composite_score", 0.0)

            # Prioritize candidate having a valid detected face embedding
            effective_score = composite + (1.0 if emb is not None else -1.0)
            if effective_score > best_score:
                best_score = effective_score
                best_path = cand_path
                best_emb = emb

        if best_path is not None:
            final_ref = portraits_dir / f"{card.id}_ref.png"
            shutil.copy2(best_path, final_ref)
            card.ref_image = str(final_ref)
            if best_emb is not None:
                card.ref_face_embedding = [round(float(x), 5) for x in best_emb.tolist()]

    return cards


def render_dramakey_pipeline(
    *,
    shots: list[dict[str, Any]],
    output_dir: Path | str,
    character_cards: list[CharacterCard] | None = None,
    config: RenderConfig | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Execute the end-to-end DRAMAKEY rendering workflow.

    Generates:
      - characters.json (character dossiers with reference face embeddings)
      - keyframes/ (winner keyframes and discarded candidates)
      - subtitles.srt (timed subtitles)
      - final.mp4 (1080x1920 video with motion, voiceover, and burned subtitles)
      - contact_sheet.jpg (6-frame contact sheet)
      - qa.json (measured QA report)
      - record.json (performance and configuration metrics)
    """
    _enabled_pillars = {"report", "cost", "decision_trail"}
    cfg = config or RenderConfig()
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    kf_dir = out_dir / "keyframes"
    kf_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = out_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    clips_dir = out_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    engine = get_engine(cfg.engine)
    if not engine.available():
        raise RuntimeError(f"Engine '{cfg.engine}' is unavailable on this system.")

    start_time = time.time()
    total_kf_gen_sec = 0.0

    # 1. Setup Character Dossiers & Reference Portraits
    if character_cards is None:
        from hevi.layer4_legacy.script2video.oprim_impl.character_fuse import (
            fuse_characters_to_cards,
        )

        all_chars = []
        for s in shots:
            for c in s.get("visible_chars") or []:
                all_chars.append({"name": c, "description": ""})
        character_cards = fuse_characters_to_cards(all_chars)

    character_cards = generate_character_portraits(
        character_cards,
        engine=engine,
        output_dir=out_dir,
        kf_width=cfg.kf_width,
        kf_height=cfg.kf_height,
    )

    # Save characters.json
    chars_json_path = out_dir / "characters.json"
    chars_payload = [c.to_dict() for c in character_cards]
    chars_json_path.write_text(
        json.dumps(chars_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    card_lookup = {c.name: c for c in character_cards}
    for c in character_cards:
        for a in c.aliases:
            card_lookup[a] = c

    # 2. Render each shot (Audio + Dual Candidates + Face Gate + Ken Burns clip)
    shot_clips: list[Path] = []
    shot_durations: list[float] = []
    srt_cues: list[tuple[float, float, str]] = []
    shot_records: list[dict[str, Any]] = []
    current_timeline_s = 0.0

    for idx, shot in enumerate(shots):
        shot_idx = int(shot.get("idx", idx))
        text = str(
            shot.get("text")
            or shot.get("narration")
            or shot.get("script")
            or shot.get("visual_desc")
            or ""
        ).strip()
        visual_desc = str(shot.get("visual_desc") or text).strip()
        visible_chars = [str(c) for c in (shot.get("visible_chars") or [])]
        cam_move = str(shot.get("camera_move") or CAMERA_MOVES[idx % len(CAMERA_MOVES)])

        if on_progress:
            on_progress({"stage": "render_shot", "shot": idx, "total": len(shots)})

        # A. Voiceover Audio
        shot_audio_path = audio_dir / f"shot_{shot_idx:02d}.wav"
        if not shot_audio_path.is_file() and text:
            # Check if speaking character matches a specific card
            speaker_card = None
            for vc in visible_chars:
                if vc in card_lookup:
                    speaker_card = card_lookup[vc]
                    break
            v_speed = speaker_card.voice_speed if speaker_card else 1.0
            piper_tts(text=text, out_wav=shot_audio_path, lang="zh", length_scale=v_speed)

        if shot_audio_path.is_file():
            audio_len = duration(shot_audio_path)
            shot_dur = max(3.0, round(audio_len + 0.35, 3))
        else:
            # Fallback silence wav
            shot_dur = 3.5
            subprocess.run(
                [
                    FFMPEG,
                    "-y",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=r=48000:cl=stereo",
                    "-t",
                    f"{shot_dur}",
                    str(shot_audio_path),
                ],
                check=True,
            )

        # B. Prompt Translation
        prompt_en, neg = zh_shot_to_sd_prompt(
            shot,
            character_cards=character_cards,
        )

        # C. Dual Candidate Keyframe Generation (ViMax strategy)
        seed_1 = cfg.base_seed + shot_idx * 17
        seed_2 = cfg.base_seed + shot_idx * 17 + 1000

        cand1_path = kf_dir / f"shot_{shot_idx:02d}_cand1_s{seed_1}.png"
        cand2_path = kf_dir / f"shot_{shot_idx:02d}_cand2_s{seed_2}.png"

        t_gen_0 = time.time()
        res1 = engine.generate(
            prompt_en=prompt_en,
            negative=neg,
            width=cfg.kf_width,
            height=cfg.kf_height,
            steps=cfg.steps,
            seed=seed_1,
            output_path=cand1_path,
        )
        res2 = engine.generate(
            prompt_en=prompt_en,
            negative=neg,
            width=cfg.kf_width,
            height=cfg.kf_height,
            steps=cfg.steps,
            seed=seed_2,
            output_path=cand2_path,
        )
        total_kf_gen_sec += time.time() - t_gen_0

        score1 = score_keyframe(cand1_path, prompt_en=prompt_en)
        score2 = score_keyframe(cand2_path, prompt_en=prompt_en)

        if score1["composite_score"] >= score2["composite_score"]:
            winner_path, winner_res, winner_score = cand1_path, res1, score1
            loser_path, loser_res, loser_score = cand2_path, res2, score2
        else:
            winner_path, winner_res, winner_score = cand2_path, res2, score2
            loser_path, loser_res, loser_score = cand1_path, res1, score1

        # Keep loser candidate in keyframes folder as required
        loser_dst = kf_dir / f"shot_{shot_idx:02d}_loser_seed_{loser_res.seed}.png"
        if not loser_dst.is_file():
            shutil.copy2(loser_path, loser_dst)

        # D. Face Consistency Gate with Reference Portrait
        ref_card = None
        for char_name in visible_chars:
            c = card_lookup.get(char_name)
            if c and c.ref_face_embedding:
                ref_card = c
                break

        face_passed = True
        face_sim = 1.0
        face_detected = False
        retry_count = 0
        identity_weak = False

        if ref_card is not None and ref_card.ref_face_embedding:
            face_passed, face_sim, face_detected = verify_character_face(
                winner_path,
                ref_embedding=ref_card.ref_face_embedding,
                threshold=cfg.face_threshold,
            )

            # Retry up to 2 times if face detected but below similarity threshold
            while face_detected and (not face_passed) and retry_count < 2:
                retry_count += 1
                retry_seed = cfg.base_seed + shot_idx * 17 + 2000 * retry_count
                retry_path = kf_dir / f"shot_{shot_idx:02d}_retry{retry_count}_s{retry_seed}.png"

                t_retry = time.time()
                engine.generate(
                    prompt_en=prompt_en,
                    negative=neg,
                    width=cfg.kf_width,
                    height=cfg.kf_height,
                    steps=cfg.steps,
                    seed=retry_seed,
                    output_path=retry_path,
                )
                total_kf_gen_sec += time.time() - t_retry

                retry_score = score_keyframe(retry_path, prompt_en=prompt_en)
                p_retry, sim_retry, det_retry = verify_character_face(
                    retry_path,
                    ref_embedding=ref_card.ref_face_embedding,
                    threshold=cfg.face_threshold,
                )
                if det_retry and sim_retry > face_sim:
                    winner_path = retry_path
                    winner_score = retry_score
                    face_sim = sim_retry
                    face_passed = p_retry
                    face_detected = True

            if face_detected and not face_passed:
                identity_weak = True

        final_kf_path = kf_dir / f"shot_{shot_idx:02d}_kf.png"
        shutil.copy2(winner_path, final_kf_path)

        # Record shot metadata
        shot_records.append(
            {
                "shot_idx": shot_idx,
                "text": text,
                "prompt_en": prompt_en,
                "camera_move": cam_move,
                "duration_s": shot_dur,
                "selected_seed": winner_res.seed,
                "candidate1_score": score1,
                "candidate2_score": score2,
                "winner_score": winner_score,
                "ref_character": ref_card.name if ref_card else None,
                "face_detected": face_detected,
                "face_similarity": round(face_sim, 4),
                "face_passed": face_passed,
                "retry_count": retry_count,
                "identity_weak": identity_weak,
                "keyframe_sha256": sha256(final_kf_path),
            }
        )

        # E. Video Clip with Ken Burns Motion and Audio
        shot_clip_path = clips_dir / f"shot_{shot_idx:02d}.mp4"
        vf = _camera_filter_str(
            cam_move,
            d=shot_dur,
            w=cfg.target_width,
            h=cfg.target_height,
            fps=cfg.fps,
        )

        clip_cmd = [
            FFMPEG,
            "-y",
            "-v",
            "error",
            "-loop",
            "1",
            "-i",
            str(final_kf_path),
            "-i",
            str(shot_audio_path),
            "-t",
            f"{shot_dur:.3f}",
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-af",
            f"apad=pad_dur={shot_dur}",
            "-shortest",
            str(shot_clip_path),
        ]
        subprocess.run(clip_cmd, check=True)

        shot_clips.append(shot_clip_path)
        shot_durations.append(shot_dur)

        # Subtitle cue
        if text:
            srt_cues.append((current_timeline_s, current_timeline_s + shot_dur, text))
        current_timeline_s += shot_dur

    # 3. Subtitles Generation (.srt)
    srt_path = out_dir / "subtitles.srt"
    srt_lines = []
    for cue_idx, (st, et, cue_text) in enumerate(srt_cues, start=1):
        srt_lines.append(f"{cue_idx}")
        srt_lines.append(f"{_format_srt_time(st)} --> {_format_srt_time(et)}")
        srt_lines.append(f"{cue_text}\n")
    srt_path.write_text("\n".join(srt_lines), encoding="utf-8")

    # 4. Final Video Assembly (Concat + Subtitle Burn-In)
    concat_list_path = out_dir / "_concat_list.txt"
    concat_lines = [f"file '{clip.resolve()}'" for clip in shot_clips]
    concat_list_path.write_text("\n".join(concat_lines), encoding="utf-8")

    final_mp4_path = out_dir / "final.mp4"
    temp_concat_mp4 = out_dir / "_temp_concat.mp4"

    # Fast stream concatenation
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
            str(concat_list_path),
            "-c",
            "copy",
            str(temp_concat_mp4),
        ],
        check=True,
    )

    # Subtitle burn-in with clear font style
    if cfg.enable_subtitles and srt_path.stat().st_size > 0:
        sub_filter = (
            f"subtitles='{srt_path}':force_style="
            f"'FontSize=22,FontName=WenQuanYi Zen Hei,PrimaryColour=&H00FFFFFF,"
            f"OutlineColour=&H00000000,BorderStyle=3,MarginV=80'"
        )
        subprocess.run(
            [
                FFMPEG,
                "-y",
                "-v",
                "error",
                "-i",
                str(temp_concat_mp4),
                "-vf",
                sub_filter,
                "-c:v",
                "libx264",
                "-c:a",
                "copy",
                str(final_mp4_path),
            ],
            check=True,
        )
    else:
        shutil.move(str(temp_concat_mp4), str(final_mp4_path))

    temp_concat_mp4.unlink(missing_ok=True)
    concat_list_path.unlink(missing_ok=True)

    total_wall_sec = time.time() - start_time
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0

    # 5. QA Verification & Metrics Calculation
    probe_info = probe(final_mp4_path)
    measured_dur = duration(final_mp4_path)
    video_stream = next((s for s in probe_info["streams"] if s["codec_type"] == "video"), {})
    audio_stream = next((s for s in probe_info["streams"] if s["codec_type"] == "audio"), {})

    # Volume detect
    vol_proc = subprocess.run(
        [FFMPEG, "-i", str(final_mp4_path), "-af", "volumedetect", "-f", "null", "/dev/null"],
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

    # 6 Sample frames across duration for contact sheet & dynamic motion test
    sample_timestamps = [
        measured_dur * 0.10,
        measured_dur * 0.25,
        measured_dur * 0.50,
        measured_dur * 0.65,
        measured_dur * 0.80,
        measured_dur * 0.95,
    ]
    sampled_frames = []
    frame_diffs = []

    for t_s in sample_timestamps:
        frame_tmp = out_dir / f"_frame_{int(t_s * 100)}.jpg"
        subprocess.run(
            [
                FFMPEG,
                "-y",
                "-v",
                "error",
                "-ss",
                f"{t_s:.2f}",
                "-i",
                str(final_mp4_path),
                "-vframes",
                "1",
                "-q:v",
                "2",
                str(frame_tmp),
            ],
            check=True,
        )
        if frame_tmp.is_file():
            arr = cv2.imread(str(frame_tmp))
            sampled_frames.append(arr)
            frame_tmp.unlink(missing_ok=True)

    for i in range(1, len(sampled_frames)):
        diff = float(np.mean(np.abs(sampled_frames[i] - sampled_frames[i - 1])))
        frame_diffs.append(round(diff, 2))

    mean_frame_diff = float(np.mean(frame_diffs)) if frame_diffs else 0.0

    # Build Contact Sheet (2 rows x 3 columns)
    contact_sheet_path = out_dir / "contact_sheet.jpg"
    if len(sampled_frames) == 6:
        # Resize thumbnails to 360x640
        thumbs = [cv2.resize(f, (360, 640)) for f in sampled_frames]
        row1 = np.hstack(thumbs[:3])
        row2 = np.hstack(thumbs[3:])
        sheet = np.vstack([row1, row2])
        cv2.imwrite(str(contact_sheet_path), sheet)

    # Keyframe SHA256 mapping
    kf_hashes = {}
    for p in sorted(kf_dir.glob("*.png")):
        kf_hashes[p.name] = sha256(p)

    final_mp4_sha256 = sha256(final_mp4_path)

    qa_passed = (
        measured_dur >= 30.0
        and bool(audio_stream)
        and mean_vol > -45.0
        and mean_frame_diff > 5.0
        and len(shot_records) == len(shots)
    )

    qa_report = {
        "passed": qa_passed,
        "video": {
            "duration": round(measured_dur, 2),
            "width": int(video_stream.get("width", 0)),
            "height": int(video_stream.get("height", 0)),
            "codec": video_stream.get("codec_name"),
            "fps": round(
                eval(video_stream.get("r_frame_rate", "25/1")), 2
            ),
            "sha256": final_mp4_sha256,
        },
        "audio": {
            "codec": audio_stream.get("codec_name"),
            "sample_rate": int(audio_stream.get("sample_rate", 0)),
            "channels": int(audio_stream.get("channels", 0)),
            "mean_volume_db": round(mean_vol, 2),
            "max_volume_db": round(max_vol, 2),
        },
        "motion": {
            "sample_count": len(sampled_frames),
            "frame_differences": frame_diffs,
            "mean_frame_difference": round(mean_frame_diff, 2),
            "is_dynamic": bool(mean_frame_diff > 5.0),
        },
        "shots_evaluated": len(shot_records),
        "keyframes_generated": len(kf_hashes),
        "keyframe_hashes": kf_hashes,
        "shot_records": shot_records,
    }

    qa_path = out_dir / "qa.json"
    qa_path.write_text(json.dumps(qa_report, ensure_ascii=False, indent=2), encoding="utf-8")

    record_report = {
        "engine": engine.name,
        "model": "sd-turbo",
        "total_wall_sec": round(total_wall_sec, 2),
        "keyframe_gen_sec": round(total_kf_gen_sec, 2),
        "peak_rss_mb": round(rss_mb, 1),
        "shot_count": len(shots),
        "video_duration_s": round(measured_dur, 2),
        "tts_engine": "piper_zh_huayan",
        "subtitles_burned": cfg.enable_subtitles,
        "resolution": f"{cfg.target_width}x{cfg.target_height}",
        "pillars": sorted(_enabled_pillars),
    }

    record_path = out_dir / "record.json"
    record_path.write_text(json.dumps(record_report, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "status": "completed" if qa_passed else "qa_failed",
        "final_mp4": str(final_mp4_path),
        "qa_report": qa_report,
        "record_report": record_report,
        "qa_path": str(qa_path),
        "record_path": str(record_path),
        "contact_sheet": str(contact_sheet_path),
        "characters_path": str(chars_json_path),
    }
