"""SPEC-003 ⑤ 成片逐镜头裁决(hevi/director/verdict_checks.py)。用真 ffmpeg 生成
黑/彩 clip 验证黑帧检测 + 五档决策;VLM 传 None 跳过 hand safety(无模型依赖)。"""

from __future__ import annotations

import subprocess

import pytest

from hevi.api.routers import director_pipeline as dp
from hevi.director.verdict_checks import detect_black_ratio, verdict_shot


def _make_clip(path, color: str, dur: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=320x240:d={dur}:r=24",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def test_derive_shot_id():
    assert dp._derive_shot_id("/x/SH003_02_clip.mp4") == "SH003_02"
    assert dp._derive_shot_id("/x/SH001_04_talk.mp4") == "SH001_04"
    assert dp._derive_shot_id(None) == ""


def test_detect_black_ratio_black_vs_color(tmp_path):
    black = tmp_path / "black.mp4"
    color = tmp_path / "color.mp4"
    _make_clip(black, "black")
    _make_clip(color, "red")
    assert detect_black_ratio(black) >= 0.9  # 近全黑(blackdetect d=0.05 会漏掉首尾一点)
    assert detect_black_ratio(color) == 0.0  # 纯红不是黑


@pytest.mark.asyncio
async def test_verdict_black_frame_re_roll(tmp_path):
    clip = tmp_path / "SH001_01_clip.mp4"
    _make_clip(clip, "black")
    v = await verdict_shot(
        shot_index=0, shot_id="SH001_01", clip_path=clip, identity_score=0.9, vlm=None
    )
    assert v.passed is False
    assert v.retake_tier == "re_roll"
    assert v.black_ratio >= 0.9


@pytest.mark.asyncio
async def test_verdict_identity_drift_rewrite(tmp_path):
    clip = tmp_path / "SH001_02_clip.mp4"
    _make_clip(clip, "red")  # 非黑
    v = await verdict_shot(
        shot_index=1,
        shot_id="SH001_02",
        clip_path=clip,
        identity_score=0.4,
        vlm=None,
        consistency_floor=0.75,
    )
    assert v.passed is False
    assert v.diagnosis_category == "参考图角色错配"
    assert v.retake_tier == "rewrite"


@pytest.mark.asyncio
async def test_verdict_pass_keep(tmp_path):
    clip = tmp_path / "SH001_03_clip.mp4"
    _make_clip(clip, "green")
    v = await verdict_shot(
        shot_index=2, shot_id="SH001_03", clip_path=clip, identity_score=0.9, vlm=None
    )
    assert v.passed is True
    assert v.retake_tier == "keep"


@pytest.mark.asyncio
async def test_run_verdict_honors_upstream_degraded_shot(tmp_path):
    """2026-07-17 审计实证的静默交付路径:关键帧降级成 canon 定妆照时,clip 本身**完好**——
    画面不黑(verdict 第一项过)、身份分满分(第二项过,因为它就是那张 canon 本人)。于是 20 镜
    里 14 镜这样的成片被判全过、当成功交付。verdict 靠自己查不出这种镜,必须尊重渲染层给出的
    degraded 结论,并给 rewrite(hard purge 连 kf 一起删,逼重出关键帧;re_roll 保 kf 会把同一
    张定妆照再拼一遍,纯烧钱)。"""
    clip = tmp_path / "SH001_01_clip.mp4"
    _make_clip(clip, "green")  # 画面完好,不黑
    shots = [
        {
            "index": 0,
            "path": str(clip),
            "passed": False,
            "consistency_score": 1.0,  # 身份满分:它就是 canon 本人
            "diagnosis_category": "构图:关键帧降级为定妆照",
            "degraded": True,
        }
    ]
    verdicts = await dp._run_verdict(shots, vlm=None)
    assert verdicts[0].passed is False
    assert verdicts[0].retake_tier == "rewrite"
    assert verdicts[0].checks["upstream_degraded"] is True


@pytest.mark.asyncio
async def test_run_verdict_still_checks_non_degraded_shot(tmp_path):
    """上一条不能变成"凡上游说话就照单全收":没标 degraded 的镜仍要真跑三项检查。"""
    clip = tmp_path / "SH001_02_clip.mp4"
    _make_clip(clip, "black")
    shots = [{"index": 0, "path": str(clip), "consistency_score": 0.9, "degraded": False}]
    verdicts = await dp._run_verdict(shots, vlm=None)
    assert verdicts[0].passed is False
    assert verdicts[0].retake_tier == "re_roll"  # 黑帧,不是 rewrite


def test_purge_shot_artifacts(tmp_path):
    for suf in ("_clip.mp4", "_talk.mp4", "_kf.png", "_vis.mp4"):
        (tmp_path / f"SH001_01{suf}").write_bytes(b"x")
    (tmp_path / "SH002_01_clip.mp4").write_bytes(b"y")  # 别的镜头,不该被删
    # re_roll(hard=False):删动画产物,保留 kf
    dp._purge_shot_artifacts(tmp_path, "SH001_01", hard=False)
    assert not (tmp_path / "SH001_01_clip.mp4").exists()
    assert not (tmp_path / "SH001_01_talk.mp4").exists()
    assert (tmp_path / "SH001_01_kf.png").exists()  # kf 保留
    assert (tmp_path / "SH002_01_clip.mp4").exists()  # 别的镜头没动
    # rewrite(hard=True):连 kf 一起删
    dp._purge_shot_artifacts(tmp_path, "SH001_01", hard=True)
    assert not (tmp_path / "SH001_01_kf.png").exists()
