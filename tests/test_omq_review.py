"""OMQUALITY 审片门禁 —— 真 ffmpeg 生成坏片的回归测试。

覆盖 OMQUALITY_FIX.md 列出的全部 11 类坏片:
  bad1 全片随机噪点  bad3/bad3b 宏块  bad4 全绿屏  bad4b 局部绿闪
  bad5 半屏灰块  bad6 黑屏+静音  bad7 静音段  bad8 削波  bad8b 瞬态 click

外加 r5 复核要求的四类:
  长片(>=60s) 40s 之后噪点花屏 → red(全片扫描, 非只扫片头)
  长片(>=60s) 40s 之后绿闪     → red
  右侧 1/3 灰条(非象限对齐)    → red(行/列条带检测, 非 2x2 象限)
  正常片 + 1.5s 中段黑场       → 不 red(黑场单独门槛, 转场豁免)
  片头/片尾黑场(标题卡/淡入淡出) → 不 red(首尾豁免)

黑场判红由全片密集扫描的"连续黑场/静帧 run"决定(4 点抽帧只作参考),
因为点时间戳分不清片头黑与片中黑; 见 review_workflow.py 内注释。

"正常片" 一律用仓库内已入库的真实成片
(artifacts/real_video/20261005T160434Z/artifacts/scene_broll_720p.mp4) 现场
转码而来 —— 它是真实拍摄画面, 有真实音轨, 不会误触任何检测器; 不用
testsrc 这类合成图案(其规则几何会被 blockiness 检测器误判), 也不依赖任何
复核方临时文件(缺文件即 skip 等于没测)。坏段用真实 ffmpeg 叠加。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from hevi.layer4_legacy.review.omodul_impl.review_workflow import (
    review_finished_video_workflow,
)

HAS_FFMPEG = shutil.which("ffmpeg") is not None

FF = "ffmpeg"

#: In-repo, git-tracked real clip used as the substrate for every fixture.
REAL_BASE = (
    Path(__file__).resolve().parents[1]
    / "artifacts"
    / "real_video"
    / "20261005T160434Z"
    / "artifacts"
    / "scene_broll_720p.mp4"
)


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, timeout=600)


def _make_base(out_dir: Path, *, duration: int = 14, width: int = 640, height: int = 360) -> Path:
    """A real-looking normal base clip: real footage, real audio, scaled down.

    Sourced from the in-repo NASA b-roll clip (real camera motion + a real audio
    track), looped/trimmed to ``duration`` and re-encoded.  It does not trip any
    detector, so any red verdict on a fixture built from it must come from the
    injected defect.
    """
    d = out_dir / f"base_{duration}s.mp4"
    _run(
        [
            FF,
            "-nostdin",
            "-hide_banner",
            "-y",
            "-loglevel",
            "error",
            "-stream_loop",
            "-1",
            "-i",
            str(REAL_BASE),
            "-t",
            str(duration),
            "-vf",
            f"scale={width}:{height}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(d),
        ]
    )
    return d


def _make_noise(out_dir: Path) -> Path:
    """Full-clip random noise + white-noise audio (bad1)."""
    d = out_dir / "bad_noise.mp4"
    _run(
        [
            FF,
            "-nostdin",
            "-hide_banner",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "nullsrc=s=640x360:r=24:d=5",
            "-f",
            "lavfi",
            "-i",
            "anoisesrc=d=5:c=white:r=44100:a=0.5",
            "-vf",
            "geq=lum='random(1)*255':cb='random(2)*255':cr='random(3)*255'",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(d),
        ]
    )
    return d


def _make_macroblock_qp51(out_dir: Path) -> Path:
    """Real footage re-encoded at libx264 -qp 51 (bad3), with its audio track.

    The audio track means the red verdict cannot come from a missing-audio
    violation: it must come from the blockiness detector.
    """
    base = _make_base(out_dir, duration=5)
    d = out_dir / "bad_mb_qp51.mp4"
    _run(
        [
            FF,
            "-nostdin",
            "-hide_banner",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(base),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-qp",
            "51",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            str(d),
        ]
    )
    return d


def _make_macroblock_mpeg2(out_dir: Path) -> Path:
    """Real footage -> mpeg2 qscale 31 low-res -> neighbour upscale (bad3b)."""
    base = _make_base(out_dir, duration=5)
    d = out_dir / "bad_mb_mpeg2.mp4"
    lq = out_dir / "tmp_lq.m2v"
    _run(
        [
            FF,
            "-nostdin",
            "-hide_banner",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(base),
            "-vf",
            "scale=160:90",
            "-c:v",
            "mpeg2video",
            "-qscale:v",
            "31",
            "-an",
            str(lq),
        ]
    )
    _run(
        [
            FF,
            "-nostdin",
            "-hide_banner",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(lq),
            "-i",
            str(base),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-vf",
            "scale=640:360:flags=neighbor",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            str(d),
        ]
    )
    lq.unlink(missing_ok=True)
    return d


def _make_green(out_dir: Path) -> Path:
    """Full decoded green screen: Y=0, U=0, V=0 (bad4)."""
    d = out_dir / "bad_green.mp4"
    _run(
        [
            FF,
            "-nostdin",
            "-hide_banner",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "nullsrc=s=640x360:r=24:d=5",
            "-vf",
            "geq=lum=0:cb=0:cr=0",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(d),
        ]
    )
    return d


def _make_black_silent(out_dir: Path) -> Path:
    """Black screen + silence (bad6)."""
    d = out_dir / "bad_black_silent.mp4"
    _run(
        [
            FF,
            "-nostdin",
            "-hide_banner",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=640x360:r=24:d=5",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=stereo:d=5",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(d),
        ]
    )
    return d


def _make_silence_gap(out_dir: Path) -> Path:
    """Normal clip with a 3-11s silent segment (bad7)."""
    base = _make_base(out_dir, duration=14)
    d = out_dir / "bad_silence_gap.mp4"
    _run(
        [
            FF,
            "-nostdin",
            "-hide_banner",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(base),
            "-c:v",
            "copy",
            "-af",
            "volume=enable='between(t,3,11)':volume=0",
            "-c:a",
            "aac",
            str(d),
        ]
    )
    return d


def _make_audio_clip(out_dir: Path) -> Path:
    """Normal clip with +40dB clipping over 5-8s (bad8)."""
    base = _make_base(out_dir, duration=10)
    d = out_dir / "bad_audio_clip.mp4"
    _run(
        [
            FF,
            "-nostdin",
            "-hide_banner",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(base),
            "-c:v",
            "copy",
            "-af",
            "volume=enable='between(t,5,8)':volume=40dB,alimiter=limit=1:level=false",
            "-c:a",
            "aac",
            str(d),
        ]
    )
    return d


def _make_audio_pops(out_dir: Path) -> Path:
    """Normal clip with a full-scale click every 0.5s (bad8b)."""
    base = _make_base(out_dir, duration=5)
    d = out_dir / "bad_audio_pops.mp4"
    _run(
        [
            FF,
            "-nostdin",
            "-hide_banner",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(base),
            "-f",
            "lavfi",
            "-i",
            "aevalsrc='if(lt(mod(t,0.5),0.004),0.99*sgn(sin(2*PI*900*t)),0)':s=44100:c=stereo",
            "-filter_complex",
            "[0:a][1:a]amix=inputs=2:normalize=0[a]",
            "-map",
            "0:v",
            "-map",
            "[a]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(d),
        ]
    )
    return d


def _make_local_glitch(out_dir: Path) -> Path:
    """Normal clip with a 4-7s local noise glitch (bad2)."""
    base = _make_base(out_dir, duration=14)
    d = out_dir / "bad_local_glitch.mp4"
    _run(
        [
            FF,
            "-nostdin",
            "-hide_banner",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(base),
            "-f",
            "lavfi",
            "-i",
            "nullsrc=s=640x360:r=24:d=14,geq=lum='random(1)*255':cb='random(2)*255':cr='random(3)*255'",
            "-filter_complex",
            "[0:v][1:v]overlay=0:0:enable='between(t,4,7)'[v]",
            "-map",
            "[v]",
            "-map",
            "0:a",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            str(d),
        ]
    )
    return d


def _make_local_green(out_dir: Path) -> Path:
    """Normal clip with a 6-9s full green flash (bad4b)."""
    base = _make_base(out_dir, duration=14)
    d = out_dir / "bad_local_green.mp4"
    _run(
        [
            FF,
            "-nostdin",
            "-hide_banner",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(base),
            "-vf",
            "drawbox=x=0:y=0:w=iw:h=ih:color=0x00FF00:t=fill:enable='between(t,6,9)'",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            str(d),
        ]
    )
    return d


def _make_half_gray(out_dir: Path) -> Path:
    """Bottom half gray, top half normal (bad5), real audio kept."""
    base = _make_base(out_dir, duration=5)
    d = out_dir / "bad_half_gray.mp4"
    _run(
        [
            FF,
            "-nostdin",
            "-hide_banner",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(base),
            "-vf",
            "drawbox=x=0:y=ih/2:w=iw:h=ih/2:color=0x808080:t=fill",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            str(d),
        ]
    )
    return d


def _make_right_third_gray(out_dir: Path) -> Path:
    """Right 1/3 width gray bar over a normal clip (non-quadrant-aligned).

    The bar colour (light grey 0xB4B4B4) is chosen to contrast with the base's
    middle-third luma (≈124), so the flat run steps clearly away from its
    neighbours — a mid-grey bar would sit at the base's own luma and the
    boundary step would collapse to noise.
    """
    base = _make_base(out_dir, duration=5)
    d = out_dir / "bad_right_third_gray.mp4"
    _run(
        [
            FF,
            "-nostdin",
            "-hide_banner",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(base),
            "-vf",
            "drawbox=x=iw*2/3:y=0:w=iw/3:h=ih:color=0xB4B4B4:t=fill",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            str(d),
        ]
    )
    return d


def _make_long_glitch_after_40s(out_dir: Path) -> Path:
    """70s normal clip with a 3s noise glitch at 50-53s (blocker #1)."""
    base = _make_base(out_dir, duration=70)
    d = out_dir / "bad_long_glitch.mp4"
    _run(
        [
            FF,
            "-nostdin",
            "-hide_banner",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(base),
            "-f",
            "lavfi",
            "-i",
            "nullsrc=s=640x360:r=24:d=14,geq=lum='random(1)*255':cb='random(2)*255':cr='random(3)*255'",
            "-filter_complex",
            "[0:v][1:v]overlay=0:0:enable='between(t,50,53)'[v]",
            "-map",
            "[v]",
            "-map",
            "0:a",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            str(d),
        ]
    )
    return d


def _make_long_green_after_40s(out_dir: Path) -> Path:
    """70s normal clip with a 3s green flash at 40-43s (blocker #1)."""
    base = _make_base(out_dir, duration=70)
    d = out_dir / "bad_long_green.mp4"
    _run(
        [
            FF,
            "-nostdin",
            "-hide_banner",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(base),
            "-vf",
            "drawbox=x=0:y=0:w=iw:h=ih:color=0x00FF00:t=fill:enable='between(t,40,43)'",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            str(d),
        ]
    )
    return d


def _make_black_dip_1p5s(out_dir: Path) -> Path:
    """Normal clip with a 1.5s mid-clip black (dip-to-black transition).

    Must NOT be red: a short mid-clip black is a normal transition/chapter
    break, handled by a separate, longer black/freeze rule (>=3s).
    """
    base = _make_base(out_dir, duration=14)
    d = out_dir / "fp_black_dip.mp4"
    _run(
        [
            FF,
            "-nostdin",
            "-hide_banner",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(base),
            "-vf",
            "drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='between(t,6,7.5)'",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            str(d),
        ]
    )
    return d


def _make_black_edges(out_dir: Path) -> Path:
    """Normal clip with black at the head (0-2s) and tail (12-14s).

    Must NOT be red: head/tail black (fade-in/out, title hold) is exempt.
    """
    base = _make_base(out_dir, duration=14)
    d = out_dir / "fp_black_edges.mp4"
    _run(
        [
            FF,
            "-nostdin",
            "-hide_banner",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(base),
            "-vf",
            "drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='lt(t,2)+gt(t,12)'",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            str(d),
        ]
    )
    return d


def _review(clip: Path, out_dir: Path) -> dict:
    return review_finished_video_workflow(
        config={"frame_count": 4, "require_audio": True},
        input_data={"input_path": str(clip)},
        output_dir=out_dir,
    )


pytestmark = pytest.mark.skipif(
    not HAS_FFMPEG or not REAL_BASE.is_file(),
    reason="ffmpeg or in-repo real base clip not available",
)


class TestBadClipsRed:
    """All 11 bad clips from OMQUALITY_FIX.md must be verdict=red."""

    def test_bad1_full_noise(self, tmp_path: Path) -> None:
        r = _review(_make_noise(tmp_path), tmp_path / "out1")
        assert r["verdict"] == "red", r["violations"]
        assert r["allows_compose"] is False
        assert r["metrics"]["frames"]["noise"] >= 1
        assert "噪点" in " ".join(r["violations"])

    def test_bad2_local_glitch(self, tmp_path: Path) -> None:
        r = _review(_make_local_glitch(tmp_path), tmp_path / "out2")
        assert r["verdict"] == "red", r["violations"]
        assert r["allows_compose"] is False
        assert r["metrics"]["frames"]["noise"] >= 1

    def test_bad3_qp51_macroblocks(self, tmp_path: Path) -> None:
        r = _review(_make_macroblock_qp51(tmp_path), tmp_path / "out3")
        assert r["verdict"] == "red", r["violations"]
        assert r["allows_compose"] is False
        assert r["metrics"]["frames"]["blocky"] >= 1
        assert "宏块" in " ".join(r["violations"])

    def test_bad3b_mpeg2_macroblocks(self, tmp_path: Path) -> None:
        r = _review(_make_macroblock_mpeg2(tmp_path), tmp_path / "out3b")
        assert r["verdict"] == "red", r["violations"]
        assert r["allows_compose"] is False
        assert r["metrics"]["frames"]["blocky"] >= 1
        assert "宏块" in " ".join(r["violations"])

    def test_bad4_full_green_screen(self, tmp_path: Path) -> None:
        r = _review(_make_green(tmp_path), tmp_path / "out4")
        assert r["verdict"] == "red", r["violations"]
        assert r["allows_compose"] is False
        joined = " ".join(r["violations"])
        assert "绿屏" in joined or "色度异常" in joined, joined

    def test_bad4b_local_green(self, tmp_path: Path) -> None:
        r = _review(_make_local_green(tmp_path), tmp_path / "out4b")
        assert r["verdict"] == "red", r["violations"]
        assert r["allows_compose"] is False
        assert "色度异常" in " ".join(r["violations"])

    def test_bad5_half_gray(self, tmp_path: Path) -> None:
        r = _review(_make_half_gray(tmp_path), tmp_path / "out5")
        assert r["verdict"] == "red", r["violations"]
        assert r["allows_compose"] is False
        assert "is_region_flat" in " ".join(r["violations"]), r["violations"]

    def test_bad6_black_silent(self, tmp_path: Path) -> None:
        r = _review(_make_black_silent(tmp_path), tmp_path / "out6")
        assert r["verdict"] == "red", r["violations"]
        assert r["allows_compose"] is False
        joined = " ".join(r["violations"])
        # an all-black clip is a whole-clip black/freeze run, caught by the dense
        # scan (the 4-point black spot is now only a reference warning)
        assert "黑场" in joined, joined
        assert "白噪声" not in joined, joined

    def test_bad7_silence_gap(self, tmp_path: Path) -> None:
        r = _review(_make_silence_gap(tmp_path), tmp_path / "out7")
        assert r["verdict"] == "red", r["violations"]
        assert r["allows_compose"] is False
        assert "连续静音段" in " ".join(r["violations"])

    def test_bad8_audio_clip(self, tmp_path: Path) -> None:
        r = _review(_make_audio_clip(tmp_path), tmp_path / "out8")
        assert r["verdict"] == "red", r["violations"]
        assert r["allows_compose"] is False
        assert "削波" in " ".join(r["violations"])

    def test_bad8b_audio_pops(self, tmp_path: Path) -> None:
        r = _review(_make_audio_pops(tmp_path), tmp_path / "out8b")
        assert r["verdict"] == "red", r["violations"]
        assert r["allows_compose"] is False
        assert "瞬态爆音" in " ".join(r["violations"])


class TestLongAndNonQuadrantDefects:
    """r5 blockers: whole-clip scan, non-quadrant region, black/freeze split."""

    def test_long_noise_glitch_after_40s_is_red(self, tmp_path: Path) -> None:
        r = _review(_make_long_glitch_after_40s(tmp_path), tmp_path / "long_glitch")
        assert r["verdict"] == "red", r["violations"]
        assert r["allows_compose"] is False
        # the reported defect must be in the 50-53s window, not the head
        hits = r["metrics"]["local_defect_scan"]["defect_hits"]
        assert hits, r["metrics"]["local_defect_scan"]
        assert any(45.0 <= h["start_s"] <= 55.0 for h in hits), hits

    def test_long_green_flash_after_40s_is_red(self, tmp_path: Path) -> None:
        r = _review(_make_long_green_after_40s(tmp_path), tmp_path / "long_green")
        assert r["verdict"] == "red", r["violations"]
        assert r["allows_compose"] is False
        hits = r["metrics"]["local_defect_scan"]["defect_hits"]
        assert any(35.0 <= h["start_s"] <= 45.0 for h in hits), hits

    def test_right_third_gray_bar_is_red(self, tmp_path: Path) -> None:
        r = _review(_make_right_third_gray(tmp_path), tmp_path / "third")
        assert r["verdict"] == "red", r["violations"]
        assert r["allows_compose"] is False
        assert "is_region_flat" in " ".join(r["violations"]), r["violations"]

    def test_mid_clip_black_1p5s_not_red(self, tmp_path: Path) -> None:
        r = _review(_make_black_dip_1p5s(tmp_path), tmp_path / "black_dip")
        assert r["verdict"] != "red", r["violations"]
        assert r["allows_compose"] is True

    def test_head_tail_black_not_red(self, tmp_path: Path) -> None:
        r = _review(_make_black_edges(tmp_path), tmp_path / "black_edges")
        assert r["verdict"] != "red", r["violations"]
        assert r["allows_compose"] is True


class TestNormalClipsNotRed:
    """Real normal clips generated inside the test must NOT be red."""

    def test_plain_base_not_red(self, tmp_path: Path) -> None:
        r = _review(_make_base(tmp_path, duration=8), tmp_path / "base_out")
        assert r["verdict"] != "red", r["violations"]

    def test_long_base_not_red(self, tmp_path: Path) -> None:
        r = _review(_make_base(tmp_path, duration=70), tmp_path / "longbase_out")
        assert r["verdict"] != "red", r["violations"]


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
