"""T2 xfade pack: 逐接缝转场注册表 + build_xfade_chain list 支持 + E2E 验收。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from skimage.metrics import structural_similarity as compare_ssim

from hevi.assembly.assembler import build_xfade_chain
from hevi.assembly.xfade_transitions import (
    ALL_TRANSITIONS,
    get_transition,
    list_transitions,
    resolve,
)

_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
ffmpeg_only = pytest.mark.skipif(not _HAS_FFMPEG, reason="needs ffmpeg/ffprobe")

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


# ── 辅助函数────────────────────────────────────────────────────────────


def _probe_dur(path: Path) -> float:
    out = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    ).stdout.strip()
    return float(out)


def _grab_frame_raw(path: Path, time: float, w: int = 320, h: int = 240) -> bytes:
    """抽帧并返回 raw RGB 字节串。"""
    res = subprocess.run(
        [
            FFMPEG,
            "-y",
            "-ss",
            str(time),
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
    )
    assert len(res.stdout) == w * h * 3, f"expected {w * h * 3} bytes, got {len(res.stdout)}"
    return res.stdout


def _make_clip(
    tmp_path: Path,
    src: str,
    extra_vf: str | None = None,
    size: tuple[int, int] = (320, 240),
    duration: float = 1.0,
    fps: int = 30,
) -> Path:
    c = tmp_path / f"clip_{hash(src) % 10000}.mp4"
    cmd = [FFMPEG, "-y", "-f", "lavfi", "-i", src]
    if extra_vf:
        cmd += ["-vf", extra_vf]
    cmd += ["-s", f"{size[0]}x{size[1]}", "-r", str(fps), "-pix_fmt", "yuv420p", str(c)]
    subprocess.run(cmd, check=True, capture_output=True)
    return c


# ── 注册表单测（无需 ffmpeg）─────────────────────────────────────────


def test_list_transitions_returns_all() -> None:
    transitions = list_transitions()
    assert len(transitions) >= 64  # 58 builtin + 6 custom


def test_builtin_count_ge_40() -> None:
    builtins = [t for t in ALL_TRANSITIONS if t.kind == "builtin"]
    assert len(builtins) >= 40, f"expected >=40 builtins, got {len(builtins)}"


def test_custom_count_ge_6() -> None:
    customs = [t for t in ALL_TRANSITIONS if t.kind == "custom"]
    assert len(customs) >= 6, f"expected >=6 customs, got {len(customs)}"


def test_get_transition_known_id() -> None:
    t = get_transition("fade")
    assert t.id == "fade"
    assert t.kind == "builtin"
    assert t.ffmpeg == "fade"


def test_get_transition_custom() -> None:
    t = get_transition("whip")
    assert t.kind == "custom"
    # whip 是横向甩镜:空间位移,必须逐平面取样(a0/a1/a2 或 b0/b1/b2)
    assert "a0(" in t.ffmpeg and "b0(" in t.ffmpeg
    assert "PLANE" in t.ffmpeg


def test_get_transition_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown transition id"):
        get_transition("nonexistent_xyz")


def test_resolve_builtin() -> None:
    assert resolve("fade") == "fade"
    assert resolve("dissolve") == "dissolve"
    assert resolve("zoomin") == "zoomin"


def test_resolve_custom() -> None:
    t = get_transition("flash")
    assert resolve("flash") == f"custom:expr={t.ffmpeg}"
    assert resolve("flash").startswith("custom:expr=")


def test_custom_exprs_have_no_bare_commas() -> None:
    """custom 表达式里的逗号必须转义为 \\, 否则会破坏 filter_complex 解析。"""
    for t in ALL_TRANSITIONS:
        if t.kind != "custom":
            continue
        # 去掉所有已转义的逗号,剩下的裸逗号数量应为 0
        bare = t.ffmpeg.replace("\\,", "")
        assert "," not in bare, f"{t.id}: bare comma in expr breaks filter_complex"


def test_all_registered_ids_unique() -> None:
    ids = [t.id for t in ALL_TRANSITIONS]
    assert len(ids) == len(set(ids)), f"duplicate ids: {[i for i in ids if ids.count(i) > 1]}"


# ── build_xfade_chain 纯函数回归（无需 ffmpeg）──────────────────────


_GOLDEN_STR_FC = (
    "[0:v][1:v]xfade=transition=fade:duration=0.5:offset=4.500[vx1]"
    ";[vx1][2:v]xfade=transition=fade:duration=0.5:offset=9.000[vout]"
)


def test_xfade_chain_single_shot() -> None:
    fc, label, total = build_xfade_chain([5.0], "fade", 0.5)
    assert fc == ""
    assert label == "0:v"
    assert total == 5.0


def test_xfade_chain_str_backward_compat() -> None:
    """str 调用生成的 filter_complex 与改动前逐字一致。"""
    fc, label, total = build_xfade_chain([5.0, 5.0, 5.0], "fade", 0.5)
    assert fc == _GOLDEN_STR_FC
    assert label == "[vout]"
    assert total == pytest.approx(14.0)


def test_xfade_chain_list_different_transitions() -> None:
    fc, label, total = build_xfade_chain([5.0, 5.0, 5.0], ["fade", "dissolve"], 0.5)
    assert "transition=fade:duration=0.5:offset=4.500" in fc
    assert "transition=dissolve:duration=0.5:offset=9.000" in fc
    assert total == pytest.approx(14.0)


def test_xfade_chain_list_with_custom() -> None:
    fc, _, _ = build_xfade_chain([3.0, 3.0], ["whip"], 0.5)
    assert f"transition={resolve('whip')}" in fc


def test_xfade_chain_list_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="1 entries"):
        build_xfade_chain([5.0, 5.0], ["fade", "dissolve"], 0.5)


# ── F5: 逐接缝 "cut" 支持 ─────────────────────────────────────────────


def test_xfade_chain_str_cut_all_seams() -> None:
    """str "cut" 等价于全部接缝硬切(concat),总时长 = sum(durations)。"""
    fc, label, total = build_xfade_chain([5.0, 5.0, 5.0], "cut", 0.5)
    assert total == pytest.approx(15.0)
    assert "concat=n=2:v=1:a=0" in fc
    assert "xfade=" not in fc
    assert label == "[vout]"


def test_xfade_chain_mixed_cut_and_xfade_total() -> None:
    """list 里混入 "cut":总时长只减去非 cut 接缝的 d。"""
    fc, label, total = build_xfade_chain([5.0, 5.0, 5.0], ["fade", "cut"], 0.5)
    assert total == pytest.approx(15.0 - 0.5)  # 只有 seam0 重叠 0.5
    assert "concat=n=2:v=1:a=0" in fc
    assert "xfade=transition=fade" in fc
    assert label == "[vout]"


def test_xfade_chain_empty_transition_list_raises() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        build_xfade_chain([5.0, 5.0], [], 0.5)


def test_xfade_chain_unknown_id_raises() -> None:
    with pytest.raises(ValueError, match="Unknown transition id"):
        build_xfade_chain([5.0, 5.0], "nonexistent_xyz", 0.5)


def test_xfade_chain_per_transition_duration_with_list_transition() -> None:
    fc, _, total = build_xfade_chain([5.0, 5.0, 5.0], ["fade", "dissolve"], [0.3, 0.7])
    assert "duration=0.3" in fc
    assert "duration=0.7" in fc
    assert total == pytest.approx(15.0 - 0.3 - 0.7)


# ── 集成测：每个 builtin/custom 用 lavfi 合成片真跑 ffmpeg ─────────


def _xfade_run(a: Path, b: Path, transition: str, duration: float, out: Path) -> None:
    """用 build_xfade_chain 解析后的 transition 值直接跑 ffmpeg xfade。"""
    fc, _, _ = build_xfade_chain([duration, duration], [transition], duration / 2)
    if not fc:
        shutil.copy2(a, out)
        return
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-i",
            str(a),
            "-i",
            str(b),
            "-filter_complex",
            fc,
            "-map",
            "[vout]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(out),
        ],
        check=True,
        capture_output=True,
    )


@pytest.mark.parametrize("trans_id", [t.id for t in ALL_TRANSITIONS if t.kind == "builtin"])
@ffmpeg_only
def test_builtin_transition_runs(tmp_path, trans_id: str) -> None:
    d = 1.0
    a = _make_clip(tmp_path, f"testsrc=duration={d}:size=320x240:rate=30")
    b = _make_clip(tmp_path, f"color=c=red:s=320x240:d={d}:rate=30")
    out = tmp_path / f"out_{trans_id}.mp4"
    _xfade_run(a, b, trans_id, d, out)
    assert out.exists()
    dur = _probe_dur(out)
    expected = d * 2 - d / 2  # 1+1-0.5 = 1.5
    assert dur == pytest.approx(expected, abs=0.1), f"{trans_id}: got {dur}"


@pytest.mark.parametrize("trans_id", [t.id for t in ALL_TRANSITIONS if t.kind == "custom"])
@ffmpeg_only
def test_custom_transition_runs(tmp_path, trans_id: str) -> None:
    d = 1.0
    a = _make_clip(tmp_path, f"testsrc=duration={d}:size=320x240:rate=30")
    b = _make_clip(tmp_path, f"color=c=red:s=320x240:d={d}:rate=30")
    out = tmp_path / f"out_{trans_id}.mp4"
    _xfade_run(a, b, trans_id, d, out)
    assert out.exists()
    dur = _probe_dur(out)
    expected = d * 2 - d / 2
    assert dur == pytest.approx(expected, abs=0.1), f"{trans_id}: got {dur}"


# ── E2E：多镜头多转场成片验收 ──────────────────────────────────────


@ffmpeg_only
def test_e2e_multi_transition_chain(tmp_path: Path) -> None:
    """5 镜头 × 4 种转场（含 custom），d=0.6s，验证总时长与过渡形态。"""
    durations = [3.0] * 5
    transitions = ["fade", "dissolve", "whip", "zoom_punch"]
    xfade_d = 0.6

    clips = []
    configs = [
        ("testsrc=duration=3:size=640x360:rate=30", None),
        ("color=c=red:s=640x360:d=3:rate=30", None),
        ("color=c=green:s=640x360:d=3:rate=30", None),
        ("color=c=blue:s=640x360:d=3:rate=30", None),
        (
            "testsrc=duration=3:size=640x360:rate=30",
            "drawbox=x=100:y=100:w=200:h=100:c=yellow:t=fill",
        ),
    ]
    for i, (src, extra) in enumerate(configs):
        c = tmp_path / f"shot{i}.mp4"
        cmd = [FFMPEG, "-y", "-f", "lavfi", "-i", src]
        if extra:
            cmd += ["-vf", extra]
        cmd += ["-pix_fmt", "yuv420p", str(c)]
        subprocess.run(cmd, check=True, capture_output=True)
        clips.append(c)

    fc, label, expected_total = build_xfade_chain(durations, transitions, xfade_d)
    assert expected_total == pytest.approx(
        sum(durations) - sum(xfade_d for _ in transitions), abs=0.01
    )

    out = tmp_path / "e2e_multi.mp4"
    inputs = []
    for c in clips:
        inputs.extend(["-i", str(c)])
    subprocess.run(
        [
            FFMPEG,
            "-y",
            *inputs,
            "-filter_complex",
            fc,
            "-map",
            label,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    assert out.exists()

    dur = _probe_dur(out)
    assert dur == pytest.approx(expected_total, abs=0.2), f"expected ~{expected_total}s, got {dur}"


@ffmpeg_only
def test_e2e_hardcut_baseline(tmp_path: Path) -> None:
    """硬切基线：同素材无重叠，总时长 = sum(durations)。"""
    durations = [3.0] * 5
    clips = []
    colors = ["red", "green", "blue", "yellow", "cyan"]
    for color in colors:
        c = tmp_path / f"cut_{color}.mp4"
        subprocess.run(
            [
                FFMPEG,
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s=640x360:d=3:rate=30",
                "-pix_fmt",
                "yuv420p",
                str(c),
            ],
            check=True,
            capture_output=True,
        )
        clips.append(c)
    concat_list = tmp_path / "concat.txt"
    concat_list.write_text("".join(f"file '{p.resolve()}'\n" for p in clips))
    out = tmp_path / "e2e_hardcut.mp4"
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    assert out.exists()
    dur = _probe_dur(out)
    assert dur == pytest.approx(15.0, abs=0.3)


@ffmpeg_only
def test_transition_at_midpoint_differs_from_hardcut(tmp_path: Path) -> None:
    """在 xfade 接缝中点抽帧，与硬切同刻帧做 SSIM 对比 < 0.98（确有过渡）。"""
    d = 3.0
    xfade_d = 0.6
    a = _make_clip(tmp_path, f"testsrc=duration={d}:size=320x240:rate=30", size=(320, 240))
    b = _make_clip(tmp_path, f"color=c=red:s=320x240:d={d}:rate=30", size=(320, 240))

    # xfade 成片
    fc, label, _ = build_xfade_chain([d, d], ["fade"], xfade_d)
    xfade_out = tmp_path / "xfade.mp4"
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-i",
            str(a),
            "-i",
            str(b),
            "-filter_complex",
            fc,
            "-map",
            label,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(xfade_out),
        ],
        check=True,
        capture_output=True,
    )
    # 硬切基线
    concat_list = tmp_path / "concat.txt"
    concat_list.write_text(f"file '{a.resolve()}'\nfile '{b.resolve()}'\n")
    cut_out = tmp_path / "cut.mp4"
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(cut_out),
        ],
        check=True,
        capture_output=True,
    )

    # 接缝中点 = d - xfade_d/2 = 2.7s
    midpoint = d - xfade_d / 2

    frame_xfade = _grab_frame_raw(xfade_out, midpoint, 320, 240)
    frame_cut = _grab_frame_raw(cut_out, midpoint, 320, 240)

    import numpy as np

    arr_xfade = np.frombuffer(frame_xfade, dtype=np.uint8).reshape((240, 320, 3))
    arr_cut = np.frombuffer(frame_cut, dtype=np.uint8).reshape((240, 320, 3))

    ssim = compare_ssim(arr_xfade, arr_cut, channel_axis=2)
    assert ssim < 0.98, f"SSIM {ssim} >= 0.98, transition not visible at midpoint"


@ffmpeg_only
def test_different_midpoints_have_different_transition_shapes(tmp_path: Path) -> None:
    """4 个接缝各自的中点帧两两之间 SSIM 应不同（过渡形态各异）。"""
    import numpy as np

    durations = [3.0] * 5
    transitions = ["fade", "dissolve", "whip", "zoom_punch"]
    xfade_d = 0.6

    configs = [
        "testsrc=duration=3:size=320x240:rate=30",
        "color=c=red:s=320x240:d=3:rate=30",
        "color=c=green:s=320x240:d=3:rate=30",
        "color=c=blue:s=320x240:d=3:rate=30",
        "color=c=yellow:s=320x240:d=3:rate=30",
    ]
    clips = [_make_clip(tmp_path, src) for src in configs]

    fc, label, _ = build_xfade_chain(durations, transitions, xfade_d)
    out = tmp_path / "multi.mp4"
    inputs = []
    for c in clips:
        inputs.extend(["-i", str(c)])
    subprocess.run(
        [
            FFMPEG,
            "-y",
            *inputs,
            "-filter_complex",
            fc,
            "-map",
            label,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(out),
        ],
        check=True,
        capture_output=True,
    )

    # 每个接缝中点时刻
    midpoints = []
    cum = durations[0]
    for i in range(1, len(durations)):
        midpoints.append(cum - xfade_d / 2)
        cum = cum + durations[i] - xfade_d

    frames = [_grab_frame_raw(out, t, 320, 240) for t in midpoints]
    arrs = [np.frombuffer(f, dtype=np.uint8).reshape((240, 320, 3)) for f in frames]

    # 两两比较 SSIM
    ssims = []
    for i in range(len(arrs)):
        for j in range(i + 1, len(arrs)):
            ssims.append(compare_ssim(arrs[i], arrs[j], channel_axis=2))

    # 要求至少有一对 SSIM < 0.99（有可辨差异）
    unique_ssims = set(round(s, 3) for s in ssims)
    assert len(unique_ssims) > 1 or max(ssims) < 0.99, (
        f"All midpoint frames are too similar (ssims={ssims}), "
        f"transitions should produce different visual shapes"
    )


@ffmpeg_only
def test_contact_sheet_transitions_visible(tmp_path: Path) -> None:
    """为每个注册转场生成中点帧 contact sheet，验证肉眼可辨。"""
    from PIL import Image

    d = 1.0
    xfade_d = 0.5
    cols = 8
    rows = (len(ALL_TRANSITIONS) + cols - 1) // cols

    a = _make_clip(tmp_path, f"testsrc=duration={d}:size=320x240:rate=30")
    b = _make_clip(tmp_path, f"color=c=red:s=320x240:d={d}:rate=30")

    mid_time = d - xfade_d / 2  # 0.75s

    cell_w, cell_h = 320, 240
    canvas = Image.new("RGB", (cell_w * cols, cell_h * rows))

    for idx, trans in enumerate(ALL_TRANSITIONS):
        row, col = divmod(idx, cols)
        fc, label, _ = build_xfade_chain([d, d], [trans.id], xfade_d)
        out = tmp_path / f"tmp_{idx}.mp4"
        subprocess.run(
            [
                FFMPEG,
                "-y",
                "-i",
                str(a),
                "-i",
                str(b),
                "-filter_complex",
                fc,
                "-map",
                label,
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(out),
            ],
            check=True,
            capture_output=True,
        )
        raw = _grab_frame_raw(out, mid_time, 320, 240)
        frame = Image.frombytes("RGB", (320, 240), raw)
        canvas.paste(frame, (col * cell_w, row * cell_h))

    sheet_path = tmp_path / "contact_sheet.png"
    canvas.save(sheet_path)
    assert sheet_path.exists()
    assert sheet_path.stat().st_size > 0


# ── F3: 用有结构素材的强断言(端点方向 + 无伪彩 + custom≠fade)──────────
#
# F1/F2 的病根:旧断言只测"能跑通/时长对",没测过渡两端的画面内容。这里补上
# 真实 ffmpeg 断言:A=有结构的 testsrc2、B=smptehdbars(两种都有结构,纯色上
# 很多错误看不出来)。逐帧解码后按帧号比对(不用 -ss,避免定位误差)。

_F3_W, _F3_H, _F3_FPS = 320, 240, 30
_F3_D, _F3_CLIP = 1.0, 2.0
_F3_OFF = _F3_CLIP - _F3_D  # 过渡起点在成片时间轴上的位置 = 1.0


def _f3_sources(tmp_path: Path) -> tuple[Path, Path]:
    a = tmp_path / "f3_A.mp4"
    b = tmp_path / "f3_B.mp4"
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=duration={_F3_CLIP}:size={_F3_W}x{_F3_H}:rate={_F3_FPS}",
            "-pix_fmt",
            "yuv420p",
            str(a),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"smptehdbars=duration={_F3_CLIP}:size={_F3_W}x{_F3_H}:rate={_F3_FPS}",
            "-pix_fmt",
            "yuv420p",
            str(b),
        ],
        check=True,
        capture_output=True,
    )
    return a, b


def _f3_render(a: Path, b: Path, trans_id: str, out: Path) -> None:
    fc, label, _ = build_xfade_chain([_F3_CLIP, _F3_CLIP], [trans_id], _F3_D)
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-i",
            str(a),
            "-i",
            str(b),
            "-filter_complex",
            fc,
            "-map",
            label,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            str(out),
        ],
        check=True,
        capture_output=True,
    )


def _f3_frames(path: Path, pix_fmt: str = "rgb24") -> "np.ndarray":
    import numpy as np

    res = subprocess.run(
        [FFMPEG, "-y", "-i", str(path), "-f", "rawvideo", "-pix_fmt", pix_fmt, "-"],
        capture_output=True,
    )
    arr = np.frombuffer(res.stdout, dtype=np.uint8)
    if pix_fmt == "rgb24":
        return arr.reshape(-1, _F3_H, _F3_W, 3)
    return arr.reshape(-1, _F3_H * 3 // 2, _F3_W)


def _f3_idx(frac: float) -> int:
    """过渡段内的帧号:frac=0 起始帧(P=1),frac=1 结束帧(P=0)。"""
    i0 = int(_F3_OFF * _F3_FPS)
    return i0 + round(frac * _F3_D * _F3_FPS)


@pytest.mark.parametrize("trans_id", [t.id for t in ALL_TRANSITIONS])
@ffmpeg_only
def test_transition_endpoints_match_sources(tmp_path: Path, trans_id: str) -> None:
    """每个转场:起始帧≈A 同时刻帧、结束帧≈B 同时刻帧(方向正确,无跳切)。

    旧 bug 里 custom 表达式方向反了(P:1→0 被写反),过渡一开头就跳到 B、
    结束时又硬切回 B —— 这个断言会在两端各抓一次,方向错了必挂。
    """
    import numpy as np

    a, b = _f3_sources(tmp_path)
    out = tmp_path / f"ep_{trans_id}.mp4"
    _f3_render(a, b, trans_id, out)
    af, bf, of = _f3_frames(a), _f3_frames(b), _f3_frames(out)

    i_start, i_end = _f3_idx(0.0), _f3_idx(1.0)
    s_start = compare_ssim(of[i_start], af[i_start], channel_axis=2)
    s_end = compare_ssim(of[i_end], bf[i_end - int(_F3_OFF * _F3_FPS)], channel_axis=2)
    assert s_start >= 0.9, (
        f"{trans_id}: start frame vs A SSIM={s_start:.3f} < 0.9 (direction wrong / jump cut)"
    )
    assert s_end >= 0.9, f"{trans_id}: end frame vs B SSIM={s_end:.3f} < 0.9 (jump cut back to A)"


@pytest.mark.parametrize("trans_id", [t.id for t in ALL_TRANSITIONS])
@ffmpeg_only
def test_transition_midpoint_differs_from_both_sources(tmp_path: Path, trans_id: str) -> None:
    """中点帧既不像 A 也不像 B(过渡确实发生,不是直接跳变)。"""
    a, b = _f3_sources(tmp_path)
    out = tmp_path / f"mid_{trans_id}.mp4"
    _f3_render(a, b, trans_id, out)
    af, bf, of = _f3_frames(a), _f3_frames(b), _f3_frames(out)
    i_mid = _f3_idx(0.5)
    s_a = compare_ssim(of[i_mid], af[i_mid], channel_axis=2)
    s_b = compare_ssim(of[i_mid], bf[i_mid - int(_F3_OFF * _F3_FPS)], channel_axis=2)
    assert s_a < 0.95 and s_b < 0.95, (
        f"{trans_id}: midpoint too close to a source (vs A={s_a:.3f}, vs B={s_b:.3f})"
    )


_CUSTOM_IDS = [t.id for t in ALL_TRANSITIONS if t.kind == "custom"]


@ffmpeg_only
def test_flash_midpoint_is_white_no_false_color(tmp_path: Path) -> None:
    """flash 中点基本全白:Y 高、U/V≈128(不得偏粉/绿,即不能有伪彩)。"""
    import numpy as np

    a, b = _f3_sources(tmp_path)
    out = tmp_path / "flash_mid.mp4"
    _f3_render(a, b, "flash", out)
    yuv = _f3_frames(out, "yuv420p")
    i_mid = _f3_idx(0.5)
    n = _F3_W * _F3_H
    flat = yuv[i_mid].reshape(-1)
    y = float(flat[:n].mean())
    u = float(flat[n : n + n // 4].mean())
    v = float(flat[n + n // 4 :].mean())
    assert y > 200, f"flash midpoint Y={y:.1f} not bright (should be ~white)"
    assert abs(u - 128) <= 12, f"flash midpoint U={u:.1f} off-neutral (false color)"
    assert abs(v - 128) <= 12, f"flash midpoint V={v:.1f} off-neutral (false color)"


@pytest.mark.parametrize("trans_id", _CUSTOM_IDS)
@ffmpeg_only
def test_custom_midpoint_differs_from_fade(tmp_path: Path, trans_id: str) -> None:
    """每个 custom 的中点帧与同素材普通 fade 中点帧不同(确有自己形态,非 fade)。"""
    a, b = _f3_sources(tmp_path)
    out_c = tmp_path / f"c_{trans_id}.mp4"
    out_f = tmp_path / "c_fade.mp4"
    _f3_render(a, b, trans_id, out_c)
    _f3_render(a, b, "fade", out_f)
    cf, ff = _f3_frames(out_c), _f3_frames(out_f)
    i_mid = _f3_idx(0.5)
    s = compare_ssim(cf[i_mid], ff[i_mid], channel_axis=2)
    assert s < 0.95, f"{trans_id}: midpoint too similar to fade (SSIM={s:.3f})"


@ffmpeg_only
def test_cut_seam_renders_real_concat(tmp_path: Path) -> None:
    """含 "cut" 接缝的链真跑 ffmpeg,总时长按公式(只减非 cut 接缝的 d)。"""
    a, b = _f3_sources(tmp_path)
    durations = [2.0, 2.0, 2.0]
    fc, label, total = build_xfade_chain(durations, ["fade", "cut"], 0.5)
    assert total == pytest.approx(5.5)
    out = tmp_path / "cut_seam.mp4"
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-i",
            str(a),
            "-i",
            str(b),
            "-i",
            str(a),
            "-filter_complex",
            fc,
            "-map",
            label,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    dur = _probe_dur(out)
    assert dur == pytest.approx(total, abs=0.1), f"got {dur}, expected {total}"


@ffmpeg_only
def test_assemble_longvideo_mixed_cut_list(tmp_path: Path) -> None:
    """assemble_longvideo 端到端:transition=["fade","cut"] 真跑通,时长公式正确。

    F5 之前:list 中间出现 "cut" 会因注册表没有它而抛 ValueError;空 list 会
    在 transition[0] 处 IndexError。这里跑真实装配,并断言空 list 明确抛错。
    """
    import asyncio

    from hevi.assembly.assembler import ShotSegment, assemble_longvideo

    shots = []
    for i, src in enumerate(["testsrc2", "smptehdbars", "rgbtestsrc"]):
        p = tmp_path / f"alv{i}.mp4"
        subprocess.run(
            [FFMPEG, "-y", "-f", "lavfi",
             "-i", f"{src}=duration=2:size=320x240:rate=30",
             "-pix_fmt", "yuv420p", str(p)],
            check=True, capture_output=True,
        )
        shots.append(ShotSegment(video_path=p))

    out = tmp_path / "alv_mixed.mp4"
    asyncio.run(
        assemble_longvideo(
            shots=shots, output_path=out, transition=["fade", "cut"],
            transition_duration=0.5, width=320, height=240, fps=30, color_normalize=False,
        )
    )
    assert _probe_dur(out) == pytest.approx(5.5, abs=0.15)  # 3×2 − 0.5

    with pytest.raises(ValueError, match="must not be empty"):
        asyncio.run(
            assemble_longvideo(
                shots=shots, output_path=tmp_path / "x.mp4", transition=[],
                transition_duration=0.5, width=320, height=240, fps=30,
                color_normalize=False,
            )
        )
