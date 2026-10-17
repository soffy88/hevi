#!/usr/bin/env python3
"""HUOBAO E2E: 国风原创短剧 改写到成片 on CPU.

输入：自写原创国风小说片段（约 1500 字）。
流程：改写（语气选择 + 逐字台词保留）→ 资产表（角色/场景/道具，跨集去重 + @引用一致性）
→ 分镜（@引用解析）→ CPU keyframe（SD-Turbo guofeng_anime）→ Piper TTS（CPU 本地配音）
→ 合成 9:16 MP4。

交付：assets JSON + 参考图联系表、storyboard JSON、MP4（sha256/duration/LUFS）、
≥3 镜头抽帧证据（同一角色跨镜一致）。

说明：CosyVoice 需 GPU/大模型权重且不在本机可用 CPU 路径；按 HUOBAO_TASK 硬规则
「CPU-only 不调付费 API」，本地配音采用仓库既有的 CPU TTS（piper zh_huayan），等价替代。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from hevi.huobao.assets import AssetRegistry, normalize_name
from hevi.huobao.batch import MissingClipPrerequisiteError, estimate_batch, validate_merge_prerequisites
from hevi.huobao.keyframes import build_asset_contact_sheet, generate_asset_keyframes
from hevi.huobao.refs import UnknownAssetReferenceError, parse_references, resolve_references
from hevi.huobao.rewrite import rewrite_novel_to_screenplay
from hevi.layer4_legacy.comicnarr.oprim_impl.postprocess import apply_style_postprocess
from hevi.layer4_legacy.comicnarr.oprim_impl.contracts import ComicStyle
from hevi.layer4_legacy.keyframe.oprim_impl.registry import resolve_keyframe_engine
from hevi.layer4_legacy.keyframe.oprim_impl.style_presets import get_style_preset
from hevi.layer4_legacy.talkcraft.omodul_impl._media import FFMPEG, duration, sha256 as file_sha256
from hevi.layer4_legacy.zerolines.omodul_impl._media import mix, write_bgm

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("huobao_e2e")


# ── 自写原创国风小说片段（约 1500 字，无版权）──
NOVEL_TEXT = """第一章 灯烬

暮春的雨敲在沈府青瓦上，沈砚之在祠堂外站了许久。檐下的白灯笼被风扯得摇晃，映得他眉眼间一片凉薄。三年前那个雪夜，母亲握着他的手说：「砚之，这半枚龙纹玉玦，是你父亲当年留下的唯一念想。」话音未落，母亲便阖了眼。沈砚之将玉玦贴身收好，从此再未与人说起。

沈崇山自廊下走来，手中捏着一封密信，神色阴沉。「你可知这玉玦从何而来？」他哑声问。沈砚之抬眸：「父亲何必明知故问。」沈崇山长叹：「当年你母亲与我失散的义女，手中也有半枚。若两玦相合，便该认亲了。」沈砚之心头一震，却只淡淡道：「父亲，有些事，不提也罢。」

第二章 绣影

青州城西的绣坊里，苏晚正就着烛火描一幅寒梅。门帘一动，沈砚之挟着夜雨踏入。苏晚指尖微顿，抬眼时眸中掠过一丝惊惶，又迅速归于沉静。「你终究还是来了。」她轻声说。沈砚之取出怀中玉玦：「三年前你救我时，落下的，可是这个？」苏晚不答，只从怀中取出另一半玉玦。两玦相触，龙纹严丝合缝。

窗外风雪愈急，烛火却愈暖。苏晚垂眸：「母亲临终前说，我原是沈家流落在外的女儿。」沈砚之握信的手微微发抖——那封密信上分明写着：晚儿是你的妹妹，护她周全。他终是哑声道：「原来我们，是兄妹。」苏晚眼圈微红，却笑了：「哥哥，这一世，我等你许久了。」

第三章 归尘

回沈府那日，天光初破。沈崇山立于正堂阶前，望见两玦合璧，老泪纵横。「是我对不住你们兄妹。」他颤声道。祠堂的灯一盏盏亮起，福伯在廊下悄悄抹泪。沈砚之扶起父亲，苏晚跪在母亲牌位前，轻声说：「娘，我回来了。」

沈砚之望向堂外，晨雾散尽，一树寒梅映着初阳。他低声道：「往后，再不负任何人。」风过檐角，灯笼轻晃，像是旧年未说完的嘱托，终在这破晓里落了地。"""


def build_shot_plan_from_screenplay(screenplay, registry):
    """Derive shot plan with @reference syntax from the formatted screenplay.

    Each scene yields 2-3 shots, each carrying @角色/@场景/@道具 references.
    """
    shots = []
    idx = 0
    for sc in screenplay.scenes:
        # Determine main character and prop for this scene
        main_char = ""
        if sc.scene_no == 1:
            main_char = "沈砚之"
            scene_loc = "沈府后巷"
            scene_time = "子夜"
        elif sc.scene_no == 2:
            main_char = "苏晚"
            scene_loc = "青州绣坊内室"
            scene_time = "风雪黄昏"
        else:
            main_char = "沈崇山"
            scene_loc = "沈府正堂祠堂"
            scene_time = "破晓黎明"

        # Ensure scene is registered
        registry.register_scene(
            location=scene_loc,
            time=scene_time,
            prompt="传统中式建筑，檐下灯笼，青瓦石阶",
            lighting="暖色烛光，氛围清冷",
            episode=1,
        )

        dialogue_texts = [d.text for d in sc.dialogues]
        n_dialogues = len(dialogue_texts)

        # Shot 1: establishing + action (8s)
        shots.append({
            "shot_id": f"EP01_SC{sc.scene_no:02d}_SH01",
            "scene_no": sc.scene_no,
            "prompt": f"@沈府后巷 中景 @沈砚之 立于门廊，神情沉静" if sc.scene_no == 1 else f"@青州绣坊内室 中景 @苏晚 立于门廊，神情沉静" if sc.scene_no == 2 else f"@沈府正堂祠堂 中景 @沈崇山 立于门廊，神情沉静",
            "tts_text": sc.actions[0] if sc.actions else "",
            "duration_s": 8.0,
        })

        # Shot 2: dialogue close-up (duration scaled to text length, min 8s)
        dlg1 = dialogue_texts[0] if dialogue_texts else ""
        dur1 = max(8.0, min(12.0, len(dlg1) / 3.0 + 2.0))
        shots.append({
            "shot_id": f"EP01_SC{sc.scene_no:02d}_SH02",
            "scene_no": sc.scene_no,
            "prompt": f"@沈府后巷 近景 @沈砚之 特写，情绪内敛" if sc.scene_no == 1 else f"@青州绣坊内室 近景 @苏晚 特写，情绪内敛" if sc.scene_no == 2 else f"@沈府正堂祠堂 近景 @沈崇山 特写，情绪内敛",
            "tts_text": dlg1,
            "duration_s": dur1,
        })

        # Shot 3 (if multiple dialogues or scene 2): dialogue/prop
        if len(dialogue_texts) > 1:
            dlg2 = dialogue_texts[1]
            dur2 = max(8.0, min(12.0, len(dlg2) / 3.0 + 2.0))
            shots.append({
                "shot_id": f"EP01_SC{sc.scene_no:02d}_SH03",
                "scene_no": sc.scene_no,
                "prompt": f"@沈府后巷 侧角 @沈砚之 握紧玉玦" if sc.scene_no == 1 else f"@青州绣坊内室 侧角 @苏晚 凝视烛火" if sc.scene_no == 2 else f"@沈府正堂祠堂 侧角 @沈崇山 叹息颔首",
                "tts_text": dlg2,
                "duration_s": dur2,
            })

        # Shot 4 (scene 2 only): prop reveal (玉玦) with @道具
        if sc.scene_no == 2:
            registry.register_prop(
                name="龙纹玉玦",
                prop_type="信物",
                description="半透白玉雕龙纹玉佩，断口处龙纹可拼合",
                episode=1,
            )
            shots.append({
                "shot_id": f"EP01_SC{sc.scene_no:02d}_SH04",
                "scene_no": sc.scene_no,
                "prompt": "@青州绣坊内室 特写 @龙纹玉玦 在烛光下两半拼合，龙纹严丝合缝",
                "tts_text": "两玦相触，龙纹严丝合缝。",
                "duration_s": 8.0,
            })
    return shots


def generate_shot_keyframes(shots, registry, out_dir, engine, style, steps=2):
    """Generate per-shot keyframe images deterministically (CPU), with @reference binding."""
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    preset = get_style_preset(style)
    engine = resolve_keyframe_engine(engine)

    results = []
    for i, shot in enumerate(shots):
        try:
            resolved = resolve_references(shot["prompt"], registry, shot_index=i, style_name=style)
        except UnknownAssetReferenceError as e:
            logger.error("Unknown reference in shot %s: %s", shot["shot_id"], e)
            raise

        img_path = frames_dir / f"{shot['shot_id']}.png"
        if not img_path.is_file() or img_path.stat().st_size == 0:
            engine.generate(
                prompt_en=resolved.expanded_prompt_en,
                negative=resolved.negative_prompt,
                width=512,
                height=512,
                steps=steps,
                seed=resolved.effective_seed,
                output_path=img_path,
            )
            apply_style_postprocess(img_path, preset.postprocess)

        shot["image_path"] = str(img_path)
        shot["seed"] = resolved.effective_seed
        shot["resolved_prompt_en"] = resolved.expanded_prompt_en
        results.append(shot)
    return results


def synthesize_tts(shots, out_dir):
    """Synthesize Chinese TTS per shot (CPU piper). Returns audio path per shot."""
    from hevi.layer4_legacy.talkcraft.omodul_impl._media import piper_tts

    audio_dir = out_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    for shot in shots:
        h = hashlib.sha256(f"zh_huayan:{shot['tts_text']}".encode("utf-8")).hexdigest()[:12]
        wav = audio_dir / f"{shot['shot_id']}_{h}.wav"
        if not wav.is_file() or wav.stat().st_size == 0:
            if shot["tts_text"].strip():
                piper_tts(text=shot["tts_text"], out_wav=wav, lang="zh", length_scale=1.0)
            else:
                # silence for non-dialogue shots
                subprocess.run(
                    [FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i",
                     f"anullsrc=r=44100:cl=stereo:d={shot['duration_s']:.3f}",
                     "-ar", "44100", str(wav)],
                    check=True,
                )
        shot["audio_path"] = str(wav)
        shot["audio_duration"] = duration(wav)
    return shots


def assemble_final(shots, out_dir, width=1080, height=1920, fps=25):
    """Assemble final 9:16 MP4 from per-shot keyframe + Ken Burns + TTS + BGM."""
    clips_dir = out_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    total_dur = sum(s["duration_s"] for s in shots)
    bgm = out_dir / "audio" / "bgm.wav"
    write_bgm(bgm, total_dur + 3.0, mood="warm")

    clip_paths = []
    for i, shot in enumerate(shots):
        clip_path = clips_dir / f"{shot['shot_id']}.mp4"
        # Ken Burns zoom
        zoom = "1.04" if i % 2 == 0 else "1.06"
        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            f"zoompan=z='min(zoom+0.0008,1.06)':d={int(shot['duration_s']*fps)}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        )
        subprocess.run(
            [FFMPEG, "-y", "-v", "error", "-loop", "1", "-i", shot["image_path"],
             "-i", shot["audio_path"], "-t", f"{shot['duration_s']:.3f}",
             "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
             "-c:a", "aac", "-b:a", "192k", "-shortest", str(clip_path)],
            check=True,
        )
        clip_paths.append(clip_path)

    # Pre-merge validation (required engineering safety check)
    validate_merge_prerequisites(clip_paths, bgm)

    # Concat clips
    concat_list = out_dir / "_concat.txt"
    concat_list.write_text("\n".join(f"file '{c.resolve()}'" for c in clip_paths), encoding="utf-8")

    temp = out_dir / "_temp_concat.mp4"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", str(concat_list), "-c", "copy", str(temp)], check=True)
    concat_list.unlink(missing_ok=True)

    # Mix VO? Each clip already has its own audio. We add BGM ducking over the concat.
    mixed = out_dir / "audio" / "mixed.wav"
    # Build concat of all shot audios for ducking
    vo_concat = out_dir / "audio" / "_vo.txt"
    vo_concat.write_text("\n".join(f"file '{Path(s['audio_path']).resolve()}'" for s in shots), encoding="utf-8")
    vo_full = out_dir / "audio" / "vo_full.wav"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", str(vo_concat), "-c", "copy", str(vo_full)], check=True)
    vo_concat.unlink(missing_ok=True)
    mix(vo_full, bgm, mixed, total_dur, music_db=-22)

    final = out_dir / "final.mp4"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-i", str(temp), "-i", str(mixed),
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
                    "-b:a", "192k", "-shortest", str(final)], check=True)
    temp.unlink(missing_ok=True)
    return final


def measure_lufs(final: Path) -> float | None:
    """Measure integrated loudness (LUFS) via ffmpeg ebur128."""
    proc = subprocess.run([FFMPEG, "-i", str(final), "-af", "ebur128=framelog=verbose",
                           "-f", "null", "/dev/null"], capture_output=True, text=True)
    for line in proc.stderr.splitlines():
        if "I:" in line and "LUFS" in line:
            try:
                return float(line.split("I:")[1].split("LUFS")[0].strip())
            except ValueError:
                return None
    return None


def grab_evidence_frames(final: Path, shots, out_dir, registry) -> list[Path]:
    """Extract one frame per shot to prove cross-shot character consistency."""
    ev_dir = out_dir / "evidence"
    ev_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    cur = 0.0
    for shot in shots:
        t = cur + shot["duration_s"] / 2.0
        f = ev_dir / f"evidence_{shot['shot_id']}.jpg"
        subprocess.run([FFMPEG, "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(final),
                        "-vframes", "1", "-q:v", "2", str(f)], check=True)
        frames.append(f)
        cur += shot["duration_s"]
    return frames


def main() -> int:
    parser = argparse.ArgumentParser(description="HUOBAO E2E CPU pipeline")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "output" / "huobao_e2e")
    parser.add_argument("--tone", default="classical")
    parser.add_argument("--engine", default="sdturbo_cpu_fp16")
    parser.add_argument("--style", default="guofeng_anime")
    args = parser.parse_args()

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # 1. Rewrite
    screenplay = rewrite_novel_to_screenplay(NOVEL_TEXT, title="灯烬·归尘", tone=args.tone, target_duration_s=75.0)
    (out / "screenplay.md").write_text(screenplay.to_markdown(), encoding="utf-8")
    logger.info("1. 改写完成：%d 场，语气=%s", len(screenplay.scenes), args.tone)

    # 2. Asset registry
    registry = AssetRegistry(base_seed=42)
    # Register characters
    registry.register_character("沈砚之", role="protagonist", appearance="清冷俊逸，眉眼疏淡", styling="墨色披风，束发玉冠", episode=1)
    registry.register_character("苏晚", role="protagonist", appearance="温婉沉静，眸光清亮", styling="素白襦裙，银钗绾发", episode=1)
    registry.register_character("沈崇山", role="supporting", appearance="鬓发斑白，威严憔悴", styling="深褐常服，手持密信", episode=1)
    registry.register_character("福伯", role="supporting", appearance="苍老佝偻，忠厚", styling="灰褐仆装，提纸灯笼", episode=1)
    # Cross-episode alias merge demo (same person, different alias)
    registry.register_character("沈砚之（男主）", aliases=["砚之"], episode=2)
    registry.register_character("沈崇山（父亲）", aliases=["父亲"], episode=2)

    # 3. Build shot plan + per-scene scene registration + prop
    shots = build_shot_plan_from_screenplay(screenplay, registry)
    logger.info("2. 资产表：角色=%d 场景=%d 道具=%d 镜头=%d",
                len(registry.characters), len(registry.scenes), len(registry.props), len(shots))

    # 4. Batch estimate
    est = estimate_batch(shots, engine=args.engine, width=1080, height=1920)
    (out / "estimate.json").write_text(json.dumps(est.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("3. 预估：%s", est.note)

    # 5. Asset keyframes (CPU)
    generate_asset_keyframes(registry, out, engine_name=args.engine, steps=2)
    registry.save_json(out / "assets.json")
    # Reference image map
    ref_map = {
        "characters": {cid: c.ref_image_path for cid, c in registry.characters.items()},
        "scenes": {sid: s.ref_image_path for sid, s in registry.scenes.items()},
        "props": {pid: p.ref_image_path for pid, p in registry.props.items()},
    }
    (out / "reference_image_map.json").write_text(json.dumps(ref_map, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("4. 资产参考图生成完成")

    # 6. Shot keyframes (CPU, with @reference binding) + storyboard
    shots = generate_shot_keyframes(shots, registry, out, args.engine, args.style, steps=2)
    (out / "storyboard.json").write_text(json.dumps(shots, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("5. 分镜 + 镜头 keyframe 完成（@引用已解析绑定）")

    # 7. TTS (CPU)
    shots = synthesize_tts(shots, out)
    logger.info("6. TTS 配音完成")

    # 8. Assemble
    final = assemble_final(shots, out)
    logger.info("7. 成片合成完成：%s", final)

    # 9. Measures
    dur = duration(final)
    lufs = measure_lufs(final)
    digest = file_sha256(final)
    ev_frames = grab_evidence_frames(final, shots, out, registry)
    logger.info("8. 抽帧证据 %d 张", len(ev_frames))

    qa = {
        "sha256": digest,
        "duration_s": round(dur, 2),
        "lufs": lufs,
        "resolution": "1080x1920",
        "shot_count": len(shots),
        "asset_chars": len(registry.characters),
        "asset_scenes": len(registry.scenes),
        "asset_props": len(registry.props),
        "evidence_frames": [str(f) for f in ev_frames],
        "passed": bool(60 <= dur <= 90 and len(ev_frames) >= 3 and lufs is not None),
        "elapsed_s": round(time.time() - t0, 1),
    }
    (out / "qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(qa, ensure_ascii=False, indent=2))
    return 0 if qa["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
