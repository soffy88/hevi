"""批A:V2 生产编排——把 G-FINAL scratchpad 里真机验证过的编排逻辑
(`gfinal_wangliulang_phase1.py`/`gfinal_phase234_v2.py`,2026-07 会话)提升成正式、
可测试、接生产 task/progress 契约的模块。是 `director_pipeline.py::
_run_director_via_tongjian` 的 V2 替身——读写同一套 `video_tasks`/`shot_states` 契约
(`task_repo.update_task`/`create_shot_state`/`delete_shots`),前端零改动就能继续用
同一套进度轮询/成片播放路径(`GET /api/tasks/{id}`→`percent`=`progress_pct`,
`GET /api/tasks/{id}/video`→`result_video_path`)。

进度上报用 `TaskService.run_task` 已经在用、SSE 也已经在读的 `progress_cb(stage, pct,
completed, total)` 形状(`task_service.py:185`),不是 V1 那种"数 *_talk.mp4 文件数量"
的伪进度——V2 每一步(抽取/渲染/QC/装配/终审)本来就是显式阶段,天然适配这个约定。

单段/单场失败优雅降级不中断整任务(照抄 V1 已经修过的教训,2026-07-17 审计:
`completed_shots` 必须是"total-failed"的真实数字,不能"全部完成"的假象)。真实成本
按每次真实调用的 `duration_s * 0.14` 累加,任务结束写的是真实花费,不是估价抄一份
(V1 现有 `actual_usd = estimated_usd` 那个坑不跟着抄)。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PRICE_PER_S = 0.14  # happyhorse_1_1_maas_ref,同 pricing_table.py 条目
_IDENTITY_THRESHOLD = 0.65
_MAX_ATTEMPTS = 2  # 每段最多 1 次重掷(共 2 次尝试),G-FINAL 既定策略
_XFADE_S = 0.3
_DIALOGUE_MATCH_THRESHOLD = 0.3


class ProduceV2Error(Exception):
    """V2 产集管线级失败(不是单段/单场失败——那些优雅降级;这是整条流水线走不下去,
    比如一场戏一个可用段都没有)。"""


def _extract_last_frame(clip: Path, out: Path) -> None:
    """`-sseof -0.3`——G-FINAL 全程验证过的稳定偏移量(不是 V1 `scene_render_avatar.py`
    的 `-0.1`,那个对这批 provider 的视频抓不到帧,踩过这个坑)。"""
    import subprocess

    subprocess.run(
        ["ffmpeg", "-y", "-sseof", "-0.3", "-i", str(clip), "-frames:v", "1", str(out)],
        check=True,
        capture_output=True,
    )


def _extract_mid_frame_sync(clip: Path, out: Path) -> None:
    import subprocess

    dur = float(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(clip),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )
    subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{dur / 2:.3f}", "-i", str(clip), "-vframes", "1", str(out)],
        check=True,
        capture_output=True,
    )


def _scene_name_for(scene_ref: int, screenplay: Any) -> str:
    """`SceneScript.scene_ref` → `Screenplay.scenes[i].location`(`DesignScene.name` 按
    这个字段关联,`pipeline_schemas.py::DesignScene.name` 的 docstring 写明"对应
    Screenplay 里的 location")。找不到对应场次 → 空字符串,调用方据此跳过空景板
    (没有场景参考图不阻断,`generate_multirole_segment` 的 `scene_plate_path` 本来
    就是 `Path | None`)。"""
    for scene in screenplay.scenes:
        if scene.scene_no == scene_ref:
            return scene.location
    return ""


async def run_v2_produce(
    *,
    task_repo: Any,
    task_id: Any,
    screenplay: Any,
    design_list: Any,
    world_bible: Any,
    scene_script_set: Any,
    subject_ref_paths: dict[str, str],
    scene_ref_paths: dict[str, str],
    voice_by_speaker: dict[str, str] | None = None,
    run_dir: Path | None = None,
    progress_cb: Any = None,
    gen_fn: Any = None,
    tts_fn: Any = None,
    transcribe_fn: Any = None,
    vlm: Any = None,
    llm: Any = None,
) -> None:
    """`_run_director_via_tongjian` 的 V2 替身。`subject_ref_paths`/`scene_ref_paths`
    是路由侧已经查过库的角色/场景参考图路径(同 `_resolve_subject_ref_paths`/
    `_resolve_scene_ref_paths` 的既有约定——orchestrator 侧不做数据库查询,只处理文件
    路径)。`gen_fn`/`tts_fn`/`transcribe_fn`/`vlm`/`llm` 显式依赖注入供测试替身,None
    时各子模块用各自的默认真实实现(同 `generate_multirole_segment`/`segment_qc` 的既定
    `tts_fn`/`gen_fn` 约定)。`llm` 同时喂给 `extract_scene_stage_from_script`(结构抽取)
    和 `generate_multirole_segment` 的 `rephrase_llm`(负面约束正面化改写)——两者都只是
    "一次文本 LLM 调用",生产环境本来也会解析到同一个默认 provider,不必分开注入。

    失败语义:单段重掷预算用尽仍不过 → 保留最后一次结果,记 `degraded`,不中断;单场
    `extract_scene_stage_from_script` 失败 → 该场跳过(不拖累其它场),记警告日志;所有
    场次加起来一个可用段都没有 → 抛 `ProduceV2Error`,由调用方(路由的 background task)
    按 `_run_director_via_tongjian` 同款 `except Exception` 写 `status="failed"`。
    """
    from hevi.assembly.assembler import ShotSegment, assemble_longvideo, probe_duration
    from hevi.assembly.color_match import frame_rgb_mean, match_color_to_reference
    from hevi.assembly.dialogue_track import (
        DialogueCue,
        build_ambient_bed,
        build_dialogue_track,
        find_cut_point_violations,
    )
    from hevi.assembly.native_dialogue import (
        CharacterVoiceRegistry,
        decide_dialogue_source,
        extract_native_dialogue_audio,
        probe_native_dialogue,
        strip_dialogue_from_track,
        verify_no_duplicate_dialogue_renders,
    )
    from hevi.audio.voice_embed import voice_embed
    from hevi.director.cut_style import classify_seam_cut_style
    from hevi.director.final_review import review_seam, synthesize_final_checklist
    from hevi.director.multirole_reference import generate_multirole_segment
    from hevi.director.pipeline_schemas import SceneScriptDialogueLine, SceneScriptSegment
    from hevi.director.scene_script import lint_camera_movement_variety
    from hevi.director.scene_stage_extract import extract_scene_stage_from_script
    from hevi.director.segment_qc import segment_qc

    voice_by_speaker = voice_by_speaker or {}
    run_dir = run_dir or Path("output/tasks") / str(task_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    async def _report(
        stage: str, pct: float, completed: int | None = None, total: int | None = None
    ) -> None:
        if progress_cb is None:
            return
        try:
            await progress_cb(stage, pct, completed, total)
        except Exception as e:  # 进度上报绝不可影响生成主链路
            logger.debug("progress_cb failed: %s", e)

    scripts = list(scene_script_set.scripts)
    total_segments = sum(len(s.segments) for s in scripts)
    if total_segments == 0:
        raise ProduceV2Error("scene_script_set 里没有任何段落,无法产集")

    # ── ① 逐场抽取 SceneStage ────────────────────────────────────────────────
    await _report("提取场事实", 2.0, 0, total_segments)
    scene_stages: dict[int, Any] = {}
    for script in scripts:
        try:
            scene_stages[script.scene_ref] = await extract_scene_stage_from_script(
                scene_script=script, design_list=design_list, llm=llm
            )
        except Exception as e:
            logger.warning("场 %s SceneStage 抽取失败,该场落位数据留空: %s", script.scene_ref, e)

    # ── ② 逐段真实生成 + QC 驱动重试 ────────────────────────────────────────
    await _report("渲染片段", 5.0, 0, total_segments)
    completed = 0
    failed_segments: list[str] = []
    total_cost_usd = 0.0
    qc_results: list[Any] = []
    ordered: list[dict[str, Any]] = []  # 每段的产出记录,按叙事顺序
    prev_frame: Path | None = None

    for script in scripts:
        stage = scene_stages.get(script.scene_ref)
        if stage is None:
            logger.warning("场 %s 没有 SceneStage,跳过该场全部段落", script.scene_ref)
            continue
        scene_name = _scene_name_for(script.scene_ref, screenplay)
        scene_plate = scene_ref_paths.get(scene_name)
        scene_plate_path = Path(scene_plate) if scene_plate else None

        for segment in script.segments:
            seg_id = f"s{script.scene_ref}_{segment.segment_id or f'sg{segment.order:03d}'}"
            character_names = [
                c for c in (script.characters_present or []) if c in subject_ref_paths
            ]
            canon_paths = {n: Path(subject_ref_paths[n]) for n in character_names}
            requested_duration = max(segment.t_end_s - segment.t_start_s, 1.0)
            seed: int | None = None
            attempt = 0
            final_clip: Path | None = None
            final_frame: Path | None = None
            qc = None

            while True:
                try_path = run_dir / f"{seg_id}_try{attempt}.mp4"
                seg_copy = segment.model_copy(
                    update={"t_start_s": 0.0, "t_end_s": requested_duration}
                )
                try:
                    await generate_multirole_segment(
                        scene_stage=stage,
                        segment=seg_copy,
                        character_names=character_names,
                        canon_paths=canon_paths,
                        scene_plate_path=scene_plate_path,
                        continuity_reference_path=prev_frame,
                        world_bible=world_bible,
                        no_cut_to=script.no_cut_to,
                        output_path=try_path,
                        seed=seed,
                        gen_fn=gen_fn,
                        rephrase_llm=llm,
                    )
                except Exception as e:
                    logger.warning("%s try%d 生成失败: %s", seg_id, attempt, e)
                    if attempt >= _MAX_ATTEMPTS - 1:
                        failed_segments.append(seg_id)
                        break
                    attempt += 1
                    continue

                actual_dur = await probe_duration(try_path)
                total_cost_usd += actual_dur * _PRICE_PER_S
                frame_path = run_dir / f"{seg_id}_try{attempt}_end.png"
                _extract_last_frame(try_path, frame_path)

                dialogue_text = segment.dialogue[0].text if segment.dialogue else None
                speaker = segment.dialogue[0].character_name if segment.dialogue else None
                seg_tts_fn = tts_fn
                if dialogue_text and seg_tts_fn is None:
                    from hevi.audio.edge_tts_custom import edge_tts_synthesize_smart

                    seg_tts_fn = edge_tts_synthesize_smart

                qc = await segment_qc(
                    try_path,
                    segment_id=seg_id,
                    character_names=character_names,
                    canon_paths=canon_paths,
                    dialogue_text=dialogue_text,
                    speaker=speaker,
                    tts_fn=seg_tts_fn if dialogue_text else None,
                    voice=voice_by_speaker.get(speaker) if speaker else None,
                    identity_threshold=_IDENTITY_THRESHOLD,
                    tmp_dir=run_dir,
                )

                if qc.retake_tier != "re_roll" or attempt >= _MAX_ATTEMPTS - 1:
                    final_clip, final_frame = try_path, frame_path
                    break
                if not qc.dialogue_fits and qc.tts_actual_s:
                    requested_duration = round(qc.tts_actual_s + 0.6, 1)
                else:
                    seed = 20000 + hash(seg_id) % 1000 + attempt + 1
                attempt += 1

            completed += 1
            await _report(
                f"渲染片段 {completed}/{total_segments}",
                5.0 + 55.0 * completed / total_segments,
                completed,
                total_segments,
            )
            if final_clip is None:
                continue
            if qc is not None:
                qc_results.append(qc)
            prev_frame = final_frame
            ordered.append(
                {
                    "segment_id": seg_id,
                    "scene_ref": script.scene_ref,
                    "clip": final_clip,
                    "character_names": character_names,
                    "canon_paths": canon_paths,
                    "dialogue_text": segment.dialogue[0].text if segment.dialogue else "",
                    "speaker": segment.dialogue[0].character_name if segment.dialogue else None,
                    "camera_movement": segment.camera_movement,
                }
            )

    if not ordered:
        raise ProduceV2Error("所有段落均生成失败,没有可装配的产物")

    # ── ③ 校色 ──────────────────────────────────────────────────────────────
    await _report("装配", 62.0, completed, total_segments)
    ref_frame = run_dir / "_color_ref.png"
    _extract_mid_frame_sync(ordered[0]["clip"], ref_frame)
    ref_mean = frame_rgb_mean(ref_frame)
    color_report = []
    for i, item in enumerate(ordered):
        out = run_dir / f"{item['segment_id']}_color.mp4"
        if i == 0:
            import shutil

            shutil.copy(item["clip"], out)
            color_report.append({"segment_id": item["segment_id"], "gain": [1.0, 1.0, 1.0]})
        else:
            info = await match_color_to_reference(item["clip"], ref_mean, out)
            color_report.append({"segment_id": item["segment_id"], "gain": list(info["gain"])})
        item["color_clip"] = out

    # ── ④ 原声/TTS 决策 + 时间轴 + 装配 ──────────────────────────────────────
    durations = [await probe_duration(item["color_clip"]) for item in ordered]
    starts: list[float] = []
    cum = 0.0
    for i, d in enumerate(durations):
        if i == 0:
            starts.append(0.0)
            cum = d
        else:
            starts.append(cum - _XFADE_S)
            cum = cum - _XFADE_S + d
    total_dur_ms = int(cum * 1000)

    script_segs_by_id = {}
    for script in scripts:
        for segment in script.segments:
            seg_id = f"s{script.scene_ref}_{segment.segment_id or f'sg{segment.order:03d}'}"
            script_segs_by_id[seg_id] = SceneScriptSegment(
                segment_id=seg_id,
                camera_movement=segment.camera_movement,
                dialogue=[SceneScriptDialogueLine(**d.model_dump()) for d in segment.dialogue],
            )

    voice_registry = CharacterVoiceRegistry()
    cues: list[Any] = []
    ambient_wavs: list[Path] = []
    expected_lines: list[tuple[str | None, str]] = []
    dialogue_decisions: list[dict[str, Any]] = []

    for i, item in enumerate(ordered):
        clip = item["color_clip"]
        expected_text = item["dialogue_text"]
        speaker = item["speaker"]
        windows: list[tuple[float, float]] = []
        hyp_text = ""
        if expected_text:
            expected_lines.append((speaker, expected_text))
            windows, hyp_text = await probe_native_dialogue(
                clip,
                tmp_wav=run_dir / f"_asr_{item['segment_id']}.wav",
                transcribe_fn=transcribe_fn,
            )

        voice_sim = None
        embedding = None
        if windows:
            probe_audio = run_dir / f"_native_probe_{item['segment_id']}.wav"
            await extract_native_dialogue_audio(clip, windows, output_path=probe_audio)
            embedding = voice_embed(probe_audio)
            voice_sim = voice_registry.similarity(speaker, embedding) if speaker else None

        decision = decide_dialogue_source(
            segment_id=item["segment_id"],
            expected_text=expected_text,
            hyp_text=hyp_text,
            native_windows_s=windows,
            voice_sim=voice_sim,
        )
        dialogue_decisions.append({"segment_id": item["segment_id"], "source": decision.source})

        amb = run_dir / f"_amb_{item['segment_id']}.wav"
        await strip_dialogue_from_track(clip, windows, output_path=amb)
        ambient_wavs.append(amb)

        if decision.source == "none":
            continue
        if decision.source == "native":
            voice_registry.register(speaker, embedding)
            dialogue_audio = run_dir / f"_dialogue_native_{item['segment_id']}.wav"
            await extract_native_dialogue_audio(clip, windows, output_path=dialogue_audio)
            window_start_s = max(0.0, min(w[0] for w in windows) - 0.15)
            start_ms = int((starts[i] + window_start_s) * 1000)
            cues.append(DialogueCue(audio_path=dialogue_audio, start_ms=max(0, start_ms)))
        else:
            from hevi.audio.edge_tts_custom import edge_tts_synthesize_smart
            from hevi.tongjian.schemas import ScriptLine

            fallback_tts_fn = tts_fn or edge_tts_synthesize_smart
            fallback_audio = run_dir / f"_dialogue_fallback_{item['segment_id']}.mp3"
            line = ScriptLine(
                line_id=f"fallback_{item['segment_id']}",
                type="dialogue",
                speaker=speaker,
                text=expected_text,
            )
            await fallback_tts_fn(
                script=[line],
                output_path=fallback_audio,
                voice=voice_by_speaker.get(speaker) if speaker else None,
                emotion=None,
            )
            natural_start_ms = int((starts[i] + _XFADE_S + 0.2) * 1000)
            offset_ms = 0
            if i > 0:
                prev_seg = script_segs_by_id.get(ordered[i - 1]["segment_id"])
                cur_seg = script_segs_by_id.get(item["segment_id"])
                if prev_seg is not None and cur_seg is not None:
                    seam = classify_seam_cut_style(prev_seg, cur_seg)
                    if seam.style == "J":
                        offset_ms = -int(seam.offset_s * 1000)
                    elif seam.style == "L":
                        offset_ms = int(seam.offset_s * 1000)
            cues.append(
                DialogueCue(
                    audio_path=fallback_audio, start_ms=max(0, natural_start_ms + offset_ms)
                )
            )

    dialogue_track = await build_dialogue_track(
        cues, output_path=run_dir / "dialogue_track.wav", total_duration_ms=total_dur_ms
    )
    cut_points_ms = [int((starts[i] + durations[i] / 2) * 1000) for i in range(1, len(ordered))]
    dialogue_windows_ms = [
        (c.start_ms, c.start_ms + int((await probe_duration(c.audio_path)) * 1000)) for c in cues
    ]
    cut_violations = find_cut_point_violations(cut_points_ms, dialogue_windows_ms)
    if cut_violations:
        logger.warning("%s: %d 处剪辑点落进对白窗口,已知晓未自动改点", task_id, len(cut_violations))

    ambient_bed = await build_ambient_bed(ambient_wavs, output_path=run_dir / "ambient_bed.wav")

    shots = [ShotSegment(video_path=item["color_clip"], target_duration=None) for item in ordered]
    final_video = run_dir / "final.mp4"
    await assemble_longvideo(
        shots=shots,
        output_path=final_video,
        narration_audio=dialogue_track,
        bgm_path=ambient_bed,
        bgm_gain_db=-9.0,
        bgm_beat_align=False,
        width=720,
        height=1280,
        fps=24,
        transition="fade",
        transition_duration=_XFADE_S,
        loudness_lufs=-14.0,
        color_normalize=False,
    )

    # ── ⑤ 出片后硬闸门:重复渲染核验 ─────────────────────────────────────────
    if expected_lines:
        violations = await verify_no_duplicate_dialogue_renders(
            final_video,
            expected_lines=expected_lines,
            tmp_wav=run_dir / "_dup_check_probe.wav",
            transcribe_fn=transcribe_fn,
            match_threshold=_DIALOGUE_MATCH_THRESHOLD,
        )
        if violations:
            logger.warning(
                "%s: 检测到 %d 处台词重复渲染,记录不阻断出片(soffy 决定是否重跑): %s",
                task_id,
                len(violations),
                [(v.speaker, v.text) for v in violations],
            )

    # ── ⑥ L5 终审 ────────────────────────────────────────────────────────────
    await _report("终审", 92.0, completed, total_segments)
    seam_reviews = []
    if vlm is None:
        from hevi.tongjian.scene_render_avatar import _resolve_vlm

        vlm = _resolve_vlm()
    if vlm is not None:
        for i in range(len(ordered) - 1):
            a, b = ordered[i], ordered[i + 1]
            frame_a = run_dir / f"_seam_{a['segment_id']}_end.png"
            frame_b = run_dir / f"_seam_{b['segment_id']}_start.png"
            _extract_last_frame(a["color_clip"], frame_a)
            _extract_mid_frame_sync(b["color_clip"], frame_b)  # 近似首帧,够用
            review = await review_seam(
                frame_a, frame_b, seam=f"{a['segment_id']}->{b['segment_id']}", vlm=vlm
            )
            seam_reviews.append(review)

    all_segments = [
        script_segs_by_id[item["segment_id"]]
        for item in ordered
        if item["segment_id"] in script_segs_by_id
    ]
    camera_lint = lint_camera_movement_variety(all_segments)
    checklist = synthesize_final_checklist(
        seam_reviews=seam_reviews,
        qc_results=qc_results,
        color_reports=color_report,
        camera_lint_findings=camera_lint,
    )

    # ── 收尾:写真实成本 + 完成状态(V1 同款 DB 契约)────────────────────────
    from datetime import UTC, datetime

    n_failed = len(failed_segments)
    await task_repo.update_task(
        task_id,
        {
            "status": "completed",
            "progress_pct": 100.0,
            "result_video_path": str(final_video),
            "total_shots": total_segments,
            "completed_shots": total_segments - n_failed,
            "error": None,
            "config_json": {
                "actual_usd": round(total_cost_usd, 3),
                "failed_segments": failed_segments,
                "dialogue_decisions": dialogue_decisions,
                "l5_checklist": checklist,
                "cut_point_violations": len(cut_violations),
            },
            "updated_at": datetime.now(UTC).replace(tzinfo=None),
        },
    )
    await task_repo.delete_shots(task_id)
    for idx, item in enumerate(ordered):
        await task_repo.create_shot_state(
            {
                "task_id": task_id,
                "shot_index": idx,
                "status": "completed",
                "output_path": str(item["color_clip"]),
                "selection_json": {
                    "provider": "happyhorse_1_1_maas_ref",
                    "segment_id": item["segment_id"],
                },
            }
        )
    logger.info(
        "V2 产集完成: task=%s 段数=%d 失败=%d 实付=$%.2f",
        task_id,
        total_segments,
        n_failed,
        total_cost_usd,
    )
