"""End-to-End test for We-Video Explainer Pipeline.

严格按 WEVIDEO_TASK.md 验收要求：
1. 一篇 800 字科普文章（《韦伯太空望远镜的宇宙探秘》）
2. 文章 → 口播稿（本地分段、口语化、时长估算、版本管理）
3. 本地 CPU 配音（Piper TTS + Faster-Whisper 真实词级时间戳对齐，禁止 mock）
4. 配音确认闸校验（未确认不能进后续，确认后流转）
5. 节奏驱动视觉规划（关键词同步高亮、配图按节奏出现、流程图逐层展开、主讲人布局切换、转场）
6. 最终纯 CPU FFmpeg MP4 视频渲染与快速预览帧生成
7. ffprobe 真实校验视频时长 ≥ 60.0 秒
8. 校验关键词高亮时间与音频词级时间戳误差严格 < 200ms
"""

import os
import subprocess
from pathlib import Path
import pytest

from hevi.capabilities import get
from hevi.explainer.render_engine import generate_preview_frames, render_storyboard_sheet
from hevi.explainer.script import create_oral_script
from hevi.explainer.state_machine import ExplainerProject, PipelineState
from hevi.explainer.visual_plan import build_visual_plan
from hevi.explainer.voice import probe_audio_duration_ms


POPULAR_SCIENCE_ARTICLE = """我们仰望璀璨星空时，你是否好奇过：宇宙究竟诞生自何处？我们又是如何看清百亿年前的宇宙第一缕曙光的？为了揭开这个终极奥秘，人类建造了有史以来最强大的太空科学仪器——詹姆斯韦伯太空望远镜。这架造价高达百亿美元的深空之眼，正带领我们穿越时空的长廊，窥探宇宙婴儿时期的真实模样。

要看清极其遥远的宇宙早期，为什么必须使用红外望远镜呢？这背后的物理原理就是著名的宇宙膨胀与红移效应。当百亿年前古老星系发出的可见光在浩瀚宇宙中穿行时，随着空间本身的膨胀，光波波长被不断拉长，原本耀眼的可见光就逐渐红移成了肉眼无法捕捉的红外光线。因此，只有极其灵敏的红外探测器，才能穿透弥漫在宇宙深处的星际尘埃，捕捉到那些跨越百亿光年的古老光子。

韦伯望远镜拥有令人惊叹的三大核心硬件构造。首先，是它标志性的主反射镜，由十八面六边形镀金金属铍镜拼接而成，总展开直径高达六点五米，集光面积是哈勃望远镜的六倍以上。其次，是面积相当于一个标准网球场的五层高分子隔热遮阳罩，能阻挡太阳、地球和月球的热辐射。最后，是它极度严苛的超低温制冷工作环境，仪器舱被冷却到接近绝对零度的零下二百三十三摄氏度，确保望远镜自身的微弱热量不会干扰对宇宙极微弱光线的探测。

整个望远镜的精密科学观测机制包含三个环环相扣的核心流程。第一步，金色巨镜精准聚焦微弱的深空红外光线；第二步，高精度近红外光谱仪将捕获的光子分解为精细的光谱指纹，精确测定百亿光年外天体的化学成分、运行速度与红移参数；第三步，高灵敏度数据阵列将深空信号数字化并经由深空网络天线传回地球实验室。

总结一下，从看见不可见的红外微光，到逆流追溯百亿年的时空起点，韦伯望远镜不仅是一件工程奇迹，更是全人类探索求知欲的最高见证。通过它传回的每一幅震撼深空场图，我们正在一步步读懂宇宙从虚无走向繁荣的生命史诗。人类探索星辰大海的浩瀚征途，现在才刚刚拉开序幕。"""


def test_wevideo_end_to_end_pipeline(tmp_path: Path):
    # ── 1. 文章字数校验（~800 字科普文章）──────────────────────────────
    clean_article = POPULAR_SCIENCE_ARTICLE.replace("\n", "").replace(" ", "")
    char_len = len(clean_article)
    assert 700 <= char_len <= 900, f"Article length should be ~800 chars, got {char_len}"

    # ── 2. 文稿：文章 → 口播稿（本地分段、口语化、时长估算）─────────────
    script = create_oral_script(
        POPULAR_SCIENCE_ARTICLE,
        title="韦伯太空望远镜的宇宙探秘",
        script_id="wevid_e2e_01",
    )
    assert script.revision == 1
    assert len(script.sections) == 5
    assert script.total_estimated_duration_s >= 60.0
    for s in script.sections:
        assert s.char_count > 0
        assert s.estimated_duration_s > 0
        assert len(s.key_terms) > 0

    # ── 3. 状态机与配音确认闸 ──────────────────────────────────────────
    proj = ExplainerProject(project_id="proj_wevid_01", script=script)
    assert proj.state == PipelineState.SCRIPT
    assert proj.voice_approved is False

    # 真实本地 CPU 配音合成与词级对齐 (Piper + Faster-Whisper, 禁止 mock)
    work_dir = tmp_path / "e2e_workdir"
    work_dir.mkdir(parents=True, exist_ok=True)
    voiceover = proj.synthesize_voice(out_dir=work_dir)

    assert Path(voiceover.full_audio_path).is_file()
    assert voiceover.total_duration_ms >= 60_000, f"Audio duration {voiceover.total_duration_ms}ms < 60s"
    assert len(voiceover.timeline_words) > 100

    # 闸门拦截验证
    with pytest.raises(Exception):
        proj.advance_to_plan({})

    # 用户/闸门确认配音
    proj.approve_voice()
    assert proj.state == PipelineState.VOICE_APPROVED
    assert proj.voice_approved is True

    # ── 4. 节奏驱动视觉规划 ──────────────────────────────────────────
    plan = build_visual_plan(
        script=script,
        voiceover=voiceover,
        out_dir=work_dir / "plan",
        aspect="16:9",
    )
    assert len(plan.scenes) == 5
    assert len(plan.all_highlights) >= 5

    # 核心指标验证：关键词高亮时间与词时间戳误差严格 < 200ms
    max_err_ms = 0
    for hl in plan.all_highlights:
        assert hl.diff_from_audio_ms < 200, f"Highlight timing error {hl.diff_from_audio_ms}ms >= 200ms!"
        max_err_ms = max(max_err_ms, hl.diff_from_audio_ms)
        assert hl.start_ms >= 0
        assert hl.end_ms > hl.start_ms

    print(f"\n[E2E Verification] All {len(plan.all_highlights)} keyword highlights verified. Max timing error = {max_err_ms}ms (< 200ms)")

    # 推进状态
    proj.advance_to_plan(plan.to_dict())
    assert proj.state == PipelineState.PLAN

    # ── 5. 快速预览帧与分镜图 ────────────────────────────────────────
    preview_frames = generate_preview_frames(plan, work_dir, preview_w=480, preview_h=270)
    assert len(preview_frames) >= 5
    sheet_p = render_storyboard_sheet(plan, work_dir, preview_frames=preview_frames)
    assert sheet_p.is_file()
    assert sheet_p.stat().st_size > 5000

    # ── 6. 最终 MP4 纯 CPU 本地渲染 ────────────────────────────────────
    cap_render = get("explainer.render")
    res_render = cap_render.render(
        params={
            "plan": plan.to_dict(),
            "voiceover": voiceover.to_dict(),
            "fast_preview_only": False,
        },
        out_dir=work_dir / "render",
        duration=round(voiceover.total_duration_ms / 1000.0, 2),
        aspect="16:9",
        seed=1001,
    )

    final_mp4 = Path(res_render.mp4)
    assert final_mp4.is_file(), f"Output MP4 {final_mp4} must exist"

    # 拷贝一份至标准产物交付目录 audit/wevideo/e2e_science_explainer.mp4
    e2e_target = Path("audit/wevideo/e2e_science_explainer.mp4")
    e2e_target.parent.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copyfile(final_mp4, e2e_target)
    shutil.copyfile(sheet_p, Path("audit/wevideo/e2e_preview_storyboard.png"))

    # ── 7. ffprobe 严格校验最终视频时长 ≥ 60 秒 ────────────────────────
    proc_dur = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(e2e_target),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    final_duration_s = float(proc_dur.stdout.strip())
    print(f"[E2E Verification] Final MP4 Duration: {final_duration_s:.2f}s (required >= 60.0s)")
    assert final_duration_s >= 60.0, f"Final MP4 duration {final_duration_s}s is less than 60.0s!"

    # 校验音视频轨编码
    proc_streams = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name",
            "-of",
            "csv=p=0",
            str(e2e_target),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    stream_info = proc_streams.stdout.strip()
    assert "h264" in stream_info and "video" in stream_info
    assert "aac" in stream_info and "audio" in stream_info

    proj.advance_to_render({"mp4_path": str(e2e_target), "duration_s": final_duration_s})
    assert proj.state == PipelineState.RENDER
    assert e2e_target.stat().st_size > 100_000, "MP4 file size should be substantial (>100KB)"
