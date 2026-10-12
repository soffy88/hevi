"""OMQUALITY 审片门禁 —— 真 ffmpeg 生成坏片的回归测试。

覆盖 OMQUALITY_FIX.md 列出的全部 11 类坏片 + 2 条正常片:
  bad1 全片随机噪点  bad3/bad3b 宏块  bad4 全绿屏  bad4b 局部绿闪
  bad5 半屏灰块  bad6 黑屏+静音  bad7 静音段  bad8 削波  bad8b 瞬态 click

夹具在 tmp_path 里用 ffmpeg 现做(低分辨率 + 短时长, 每条约 5s),
不是 mock 数据 —— 测的是真实解码后的量测路径。
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


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, timeout=300)


def _make_noise(out_dir: Path) -> Path:
    """Full-clip random noise + white-noise audio (bad1)."""
    d = out_dir / "bad_noise.mp4"
    _run([
        FF, "-nostdin", "-hide_banner", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "nullsrc=s=640x360:r=24:d=5",
        "-f", "lavfi", "-i", "anoisesrc=d=5:c=white:r=44100:a=0.5",
        "-vf", "geq=lum='random(1)*255':cb='random(2)*255':cr='random(3)*255'",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(d),
    ])
    return d


def _make_macroblock_qp51(out_dir: Path) -> Path:
    """libx264 -qp 51 real encoder macroblocks (bad3)."""
    d = out_dir / "bad_mb_qp51.mp4"
    _run([
        FF, "-nostdin", "-hide_banner", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=s=640x360:r=24:d=5",
        "-c:v", "libx264", "-preset", "ultrafast", "-qp", "51",
        "-pix_fmt", "yuv420p", "-an", str(d),
    ])
    return d


def _make_macroblock_mpeg2(out_dir: Path) -> Path:
    """mpeg2 qscale 31 low-res then upscale (bad3b)."""
    d = out_dir / "bad_mb_mpeg2.mp4"
    lq = out_dir / "tmp_lq.m2v"
    _run([
        FF, "-nostdin", "-hide_banner", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=s=160x90:r=24:d=5",
        "-c:v", "mpeg2video", "-qscale:v", "31", "-an", str(lq),
    ])
    _run([
        FF, "-nostdin", "-hide_banner", "-y", "-loglevel", "error",
        "-i", str(lq),
        "-vf", "scale=640:360:flags=neighbor",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-an", str(d),
    ])
    lq.unlink(missing_ok=True)
    return d


def _make_green(out_dir: Path) -> Path:
    """Full decoded green screen: Y=0, U=0, V=0 (bad4)."""
    d = out_dir / "bad_green.mp4"
    _run([
        FF, "-nostdin", "-hide_banner", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "nullsrc=s=640x360:r=24:d=5",
        "-vf", "geq=lum=0:cb=0:cr=0",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-an", str(d),
    ])
    return d


def _make_black_silent(out_dir: Path) -> Path:
    """Black screen + silence (bad6)."""
    d = out_dir / "bad_black_silent.mp4"
    _run([
        FF, "-nostdin", "-hide_banner", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=black:s=640x360:r=24:d=5",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo:d=5",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(d),
    ])
    return d


def _make_silence_gap(out_dir: Path) -> Path:
    """Normal clip with 3-11s silent segment (bad7)."""
    d = out_dir / "bad_silence_gap.mp4"
    _run([
        FF, "-nostdin", "-hide_banner", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=s=640x360:r=24:d=14",
        "-f", "lavfi", "-i", "aevalsrc='0.3*sin(2*PI*440*t)':s=44100:d=3",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo:d=8",
        "-f", "lavfi", "-i", "aevalsrc='0.3*sin(2*PI*440*t)':s=44100:d=3",
        "-filter_complex",
        "[1:a][2:a][3:a]concat=n=3:v=0:a=1[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(d),
    ])
    return d


def _make_audio_clip(out_dir: Path) -> Path:
    """Normal clip with 5-8s +40dB clipping (bad8)."""
    d = out_dir / "bad_audio_clip.mp4"
    _run([
        FF, "-nostdin", "-hide_banner", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=s=640x360:r=24:d=10",
        "-f", "lavfi", "-i", "aevalsrc='0.3*sin(2*PI*440*t)':s=44100:d=5",
        "-f", "lavfi", "-i", "aevalsrc='10.0*sin(2*PI*440*t)':s=44100:d=3",
        "-f", "lavfi", "-i", "aevalsrc='0.3*sin(2*PI*440*t)':s=44100:d=2",
        "-filter_complex",
        "[1:a][2:a][3:a]concat=n=3:v=0:a=1[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(d),
    ])
    return d


def _make_audio_pops(out_dir: Path) -> Path:
    """Normal clip with a full-scale click every 0.5s (bad8b)."""
    d = out_dir / "bad_audio_pops.mp4"
    _run([
        FF, "-nostdin", "-hide_banner", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=5:r=44100",
        "-f", "lavfi", "-i", "aevalsrc='0.9*(gt(mod(t,0.5),0.25)*lt(mod(t,0.5),0.26))':s=44100:d=5",
        "-f", "lavfi", "-i", "testsrc=s=640x360:r=24:d=5",
        "-filter_complex",
        "[0:a][1:a]amix=inputs=2:normalize=0[aout]",
        "-map", "2:v", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(d),
    ])
    return d


def _make_local_glitch(out_dir: Path) -> Path:
    """Normal clip with 4-7s local noise glitch (bad2)."""
    d = out_dir / "bad_local_glitch.mp4"
    _run([
        FF, "-nostdin", "-hide_banner", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=s=640x360:r=24:d=14",
        "-f", "lavfi", "-i",
        "nullsrc=s=640x360:r=24:d=3,geq=lum='random(1)*255':cb='random(2)*255':cr='random(3)*255'",
        "-filter_complex",
        "[0:v][1:v]overlay=0:0:enable='between(t,4,7)'[vout]",
        "-map", "[vout]",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-an", str(d),
    ])
    return d
def _make_local_green(out_dir: Path) -> Path:
    """Normal clip with 6-9s full green flash (bad4b)."""
    d = out_dir / "bad_local_green.mp4"
    _run([
        FF, "-nostdin", "-hide_banner", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=s=640x360:r=24:d=6",
        "-f", "lavfi", "-i", "nullsrc=s=640x360:r=24:d=3",
        "-f", "lavfi", "-i", "testsrc=s=640x360:r=24:d=5",
        "-filter_complex",
        "[1:v]geq=lum=0:cb=0:cr=0[green];"
        "[0:v][green][2:v]concat=n=3:v=1:a=0[vout]",
        "-map", "[vout]",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-an", str(d),
    ])
    return d


def _make_half_gray(out_dir: Path) -> Path:
    """Bottom half gray, top half normal (bad5)."""
    d = out_dir / "bad_half_gray.mp4"
    _run([
        FF, "-nostdin", "-hide_banner", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=s=640x360:r=24:d=5",
        "-f", "lavfi", "-i", "color=c=gray:s=640x180:r=24:d=5",
        "-filter_complex",
        "[0:v][1:v]overlay=0:180[vout]",
        "-map", "[vout]",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-an", str(d),
    ])
    return d


class TestBadClipsRed:
    """All 11 bad clips from OMQUALITY_FIX.md must be verdict=red."""

    def test_bad1_full_noise(self, tmp_path: Path) -> None:
        clip = _make_noise(tmp_path)
        r = review_finished_video_workflow(
            config={"frame_count": 4},
            input_data={"input_path": str(clip)},
            output_dir=tmp_path / "out1",
        )
        assert r["verdict"] == "red", r["violations"]
        assert r["allows_compose"] is False
        assert r["metrics"]["frames"]["noise"] >= 1

    def test_bad2_local_glitch(self, tmp_path: Path) -> None:
        clip = _make_local_glitch(tmp_path)
        r = review_finished_video_workflow(
            config={"frame_count": 4},
            input_data={"input_path": str(clip)},
            output_dir=tmp_path / "out2",
        )
        assert r["verdict"] == "red", r["violations"]
        assert r["allows_compose"] is False
        assert r["metrics"]["frames"]["noise"] >= 1

    def test_bad3_qp51_macroblocks(self, tmp_path: Path) -> None:
        clip = _make_macroblock_qp51(tmp_path)
        r = review_finished_video_workflow(
            config={"frame_count": 4},
            input_data={"input_path": str(clip)},
            output_dir=tmp_path / "out3",
        )
        assert r["verdict"] == "red", r["violations"]
        assert r["allows_compose"] is False
        assert r["metrics"]["frames"]["blocky"] >= 1

    def test_bad3b_mpeg2_macroblocks(self, tmp_path: Path) -> None:
        clip = _make_macroblock_mpeg2(tmp_path)
        r = review_finished_video_workflow(
            config={"frame_count": 4},
            input_data={"input_path": str(clip)},
            output_dir=tmp_path / "out3b",
        )
        assert r["verdict"] == "red", r["violations"]
        assert r["allows_compose"] is False
        assert r["metrics"]["frames"]["blocky"] >= 1

    def test_bad4_full_green_screen(self, tmp_path: Path) -> None:
        clip = _make_green(tmp_path)
        r = review_finished_video_workflow(
            config={"frame_count": 4},
            input_data={"input_path": str(clip)},
            output_dir=tmp_path / "out4",
        )
        assert r["verdict"] == "red", r["violations"]
        assert r["allows_compose"] is False
        joined = " ".join(r["violations"])
        assert "绿屏" in joined or "色度异常" in joined, joined

    def test_bad4b_local_green(self, tmp_path: Path) -> None:
        clip = _make_local_green(tmp_path)
        r = review_finished_video_workflow(
            config={"frame_count": 4},
            input_data={"input_path": str(clip)},
            output_dir=tmp_path / "out4b",
        )
        assert r["verdict"] == "red", r["violations"]
        assert r["allows_compose"] is False
        joined = " ".join(r["violations"])
        assert "色度异常" in joined, joined

    def test_bad5_half_gray(self, tmp_path: Path) -> None:
        clip = _make_half_gray(tmp_path)
        r = review_finished_video_workflow(
            config={"frame_count": 4},
            input_data={"input_path": str(clip)},
            output_dir=tmp_path / "out5",
        )
        assert r["verdict"] == "red", r["violations"]
        assert r["allows_compose"] is False
        joined = " ".join(r["violations"])
        assert "is_region_flat" in joined or "半屏" in joined, joined

    def test_bad6_black_silent(self, tmp_path: Path) -> None:
        clip = _make_black_silent(tmp_path)
        r = review_finished_video_workflow(
            config={"frame_count": 4},
            input_data={"input_path": str(clip)},
            output_dir=tmp_path / "out6",
        )
        assert r["verdict"] == "red", r["violations"]
        assert r["allows_compose"] is False
        joined = " ".join(r["violations"])
        assert "黑帧" in joined
        assert "白噪声" not in joined, joined

    def test_bad7_silence_gap(self, tmp_path: Path) -> None:
        clip = _make_silence_gap(tmp_path)
        r = review_finished_video_workflow(
            config={"frame_count": 4},
            input_data={"input_path": str(clip)},
            output_dir=tmp_path / "out7",
        )
        assert r["verdict"] == "red", r["violations"]
        assert r["allows_compose"] is False

    def test_bad8_audio_clip(self, tmp_path: Path) -> None:
        clip = _make_audio_clip(tmp_path)
        r = review_finished_video_workflow(
            config={"frame_count": 4},
            input_data={"input_path": str(clip)},
            output_dir=tmp_path / "out8",
        )
        assert r["verdict"] == "red", r["violations"]
        assert r["allows_compose"] is False

    def test_bad8b_audio_pops(self, tmp_path: Path) -> None:
        clip = _make_audio_pops(tmp_path)
        r = review_finished_video_workflow(
            config={"frame_count": 4},
            input_data={"input_path": str(clip)},
            output_dir=tmp_path / "out8b",
        )
        assert r["verdict"] == "red", r["violations"]
        assert r["allows_compose"] is False


GOOD_CLIP_PATHS = [
    ("/tmp/vfy_omq/base.mp4", "base"),
    ("/data/soffy/projects/hevi-omrender/output/om_render_e2e/hf_v8-chalkboard.mp4", "hf_v8-chalkboard"),
]


class TestGoodClipsPass:
    """Normal clips must NOT be red (warn/ok is acceptable)."""

    @pytest.mark.parametrize("clip_path,name", GOOD_CLIP_PATHS)
    def test_good_clip_not_red(self, clip_path: str, name: str) -> None:
        from pathlib import Path as _P
        src = _P(clip_path)
        if not src.exists():
            pytest.skip(f"good clip not available: {clip_path}")
        out = _P(f"/tmp/vfy_omq/pytest_good_{name}")
        out.mkdir(parents=True, exist_ok=True)
        r = review_finished_video_workflow(
            config={"frame_count": 4},
            input_data={"input_path": str(src)},
            output_dir=out,
        )
        assert r["verdict"] != "red", f"{name} should not be red: {r['violations']}"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
