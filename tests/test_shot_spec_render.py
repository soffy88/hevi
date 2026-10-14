"""ShotSpec 渲染真实 ffmpeg 验收(GAP_PLAN §2 W1 step 5)。不 mock。

覆盖:
  1. ``shot_start_times`` 与 ``build_xfade_chain`` 的 offset 公式逐接缝一致;
  2. 音效位置:成片音轨(底音静音)的 onset = 镜头起点(扣重叠)+ offset,±0.1s;
  3. 特效:mono 镜中段帧 U/V 相对 128 偏差 < 2;warm 镜 R/B 比相对基线上升;
  4. 转场:spec 接缝中点帧与硬切基线同刻帧 SSIM < 0.98;spec 指定 cut 的接缝为硬切
     (与硬切基线近似);不同接缝转场形态不同;
  5. 成片时长 = Σ时长 − Σd(±1 帧)。

全部走真实 ``assemble_longvideo`` + ffmpeg/ffprobe,素材用 lavfi 合成片。
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from skimage.metrics import structural_similarity as compare_ssim

from hevi.assembly.assembler import ShotSegment, assemble_longvideo, build_xfade_chain
from hevi.production.shot_spec import (
    VALID_STYLES,
    ShotSpec,
    rejected,
    template_render_supported,
    valid_template_ids,
)
from hevi.production.shot_spec_render import (
    effect_filter,
    seam_transitions,
    shot_start_times,
    spec_sfx_cues,
)

_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
ffmpeg_only = pytest.mark.skipif(not _HAS_FFMPEG, reason="needs ffmpeg/ffprobe")

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

_W, _H, _FPS = 640, 360, 30


# ── 素材 / 渲染 / 探测辅助 ────────────────────────────────────────────


def _make_clip(tmp_path: Path, name: str, src: str, dur: float) -> Path:
    p = tmp_path / f"{name}.mp4"
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"{src}=s={_W}x{_H}:d={dur}:rate={_FPS}",
            "-t",
            str(dur),
            "-pix_fmt",
            "yuv420p",
            str(p),
        ],
        check=True,
        capture_output=True,
    )
    return p


def _clips(tmp_path: Path, dur: float, n: int = 3) -> list[Path]:
    # 全部用随帧变化的图案(testsrc2 家族),硬切帧比对才有区分度;
    # 静态色条(smptehdbars)在中段帧会与硬切基线假性相似。
    srcs = ["testsrc2", "testsrc", "yuvtestsrc", "testsrc2", "testsrc"]
    return [_make_clip(tmp_path, f"c{i}", srcs[i % len(srcs)], dur) for i in range(n)]


def _render(
    clips: list[Path],
    out: Path,
    specs: list[ShotSpec | None] | None,
    transition="fade",
    xfade_d=0.5,
) -> Path:
    asyncio.run(
        assemble_longvideo(
            shots=[ShotSegment(video_path=c) for c in clips],
            output_path=out,
            shot_specs=specs,
            transition=transition,
            transition_duration=xfade_d,
            width=_W,
            height=_H,
            fps=_FPS,
            color_normalize=False,
        )
    )
    return out


def _probe_dur(path: Path) -> float:
    return float(
        subprocess.run(
            [
                FFPROBE,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(path),
            ],
            capture_output=True,
            text=True,
        ).stdout.strip()
    )


def _frame_rgb(path: Path, t: float) -> np.ndarray:
    res = subprocess.run(
        [
            FFMPEG,
            "-y",
            "-ss",
            f"{t:.4f}",
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
    arr = np.frombuffer(res.stdout, dtype=np.uint8)
    assert arr.size == _W * _H * 3, f"frame at {t}: got {arr.size} bytes"
    return arr.reshape(_H, _W, 3)


def _frame_yuv(path: Path, t: float) -> tuple[float, float, float]:
    res = subprocess.run(
        [
            FFMPEG,
            "-y",
            "-ss",
            f"{t:.4f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "yuv420p",
            "-",
        ],
        capture_output=True,
    )
    raw = np.frombuffer(res.stdout, dtype=np.uint8)
    n = _W * _H
    y = float(raw[:n].mean())
    u = float(raw[n : n + n // 4].mean())
    v = float(raw[n + n // 4 :].mean())
    return y, u, v


def _audio_mono(path: Path, sr: int = 44100) -> np.ndarray:
    res = subprocess.run(
        [FFMPEG, "-y", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(sr), "-"],
        capture_output=True,
    )
    return np.frombuffer(res.stdout, dtype=np.float32)


def _onsets(x: np.ndarray, sr: int = 44100, hop_s: float = 0.005) -> list[float]:
    """短时 RMS 包络的起振点(从静音越过阈值的那一刻)。"""
    hop = max(1, int(sr * hop_s))
    n = len(x) // hop
    if n == 0:
        return []
    env = np.array([float(np.sqrt((x[i * hop : (i + 1) * hop] ** 2).mean())) for i in range(n)])
    peak = float(env.max())
    if peak <= 0:
        return []
    thresh = max(1e-5, 0.05 * peak)
    above = env > thresh
    out: list[float] = []
    for i in range(len(above)):
        if above[i] and (i == 0 or not above[i - 1]):
            out.append(i * hop / sr)
    return out


# ── 1. 起点公式与 build_xfade_chain 一致(纯函数)────────────────────


def test_shot_start_times_matches_build_xfade_chain_offsets() -> None:
    durations = [3.0, 3.0, 3.0, 3.0]
    seam = ["dissolve", "cut", "whip"]
    d = 0.5
    fc, _, total = build_xfade_chain(durations, seam, d)
    starts = shot_start_times(durations, d, seam)
    # 每条非 cut 接缝的 xfade offset 就是下一镜的起点。
    assert f"offset={starts[1]:.3f}" in fc  # seam0 dissolve
    assert f"offset={starts[3]:.3f}" in fc  # seam2 whip (seam1 是 cut,无 xfade)
    assert "concat=n=2:v=1:a=0" in fc  # seam1 硬切
    # 总时长 = Σd − Σ(非 cut 接缝的 d) = 12 − 1.0
    assert total == pytest.approx(sum(durations) - 2 * d)
    assert starts[0] == 0.0


def test_seam_transitions_ignores_first_shot() -> None:
    specs = [
        ShotSpec(transition_in="whip"),  # 第 1 镜 → 忽略
        ShotSpec(transition_in="dissolve"),
        None,
    ]
    assert seam_transitions(specs, 3, "fade") == ["dissolve", "fade"]
    # 全 None / 全等于默认 → 回落成 str(向后兼容路径)
    assert seam_transitions([None, None, None], 3, "fade") == "fade"


def test_effect_filter_maps() -> None:
    assert effect_filter(ShotSpec(effect="mono")) == "hue=s=0"
    assert "colortemperature" in effect_filter(ShotSpec(effect="warm"))
    assert "colortemperature" in effect_filter(ShotSpec(effect="cool"))
    assert effect_filter(ShotSpec()) == ""
    assert effect_filter(None) == ""


# ── 2. 音效位置 ──────────────────────────────────────────────────────


@ffmpeg_only
def test_sfx_onsets_match_shot_start_plus_offset(tmp_path: Path) -> None:
    dur, xfade_d = 2.0, 0.5
    clips = _clips(tmp_path, dur, n=3)
    specs: list[ShotSpec | None] = [
        ShotSpec(effect="warm", duration=dur, sfx=[{"id": "impact_hard", "offset": 0.5}]),
        ShotSpec(
            transition_in="dissolve",
            duration=dur,
            sfx=[{"id": "ding_bell", "offset": 0.3}, {"id": "pop_dry", "offset": 1.8}],
        ),
        ShotSpec(
            transition_in="whip",
            duration=dur,
            sfx=[{"id": "boom_short", "offset": 1.0}],
        ),
    ]
    out = _render(clips, tmp_path / "sfx.mp4", specs, transition="fade", xfade_d=xfade_d)

    # 期望:起点(扣重叠)+ offset。starts=[0, 1.5, 3.0]
    seam = seam_transitions(specs, 3, "fade")
    starts = shot_start_times([dur, dur, dur], xfade_d, seam)
    assert starts == pytest.approx([0.0, 1.5, 3.0])
    expected = [t for _, t in spec_sfx_cues(specs, starts)]
    assert expected == pytest.approx([0.5, 1.8, 3.3, 4.0])

    x = _audio_mono(out)
    onsets = _onsets(x)
    assert onsets, "no audio onsets detected (base should be silent)"
    for t_exp in expected:
        nearest = min(onsets, key=lambda o: abs(o - t_exp))
        assert abs(nearest - t_exp) <= 0.1, (
            f"sfx onset mismatch: expected {t_exp}s, nearest {nearest:.3f}s "
            f"(all onsets={[round(o, 3) for o in onsets]})"
        )


def _audio_stream_count(path: Path) -> int:
    out = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
    ).stdout.strip()
    return len([line for line in out.splitlines() if line])


@ffmpeg_only
def test_sfx_absent_without_spec(tmp_path: Path) -> None:
    """无 spec 时不产生 spec sfx 音轨(装配器不新增音频输入)。"""
    clips = _clips(tmp_path, 2.0, n=2)
    out = _render(clips, tmp_path / "nospec.mp4", None)
    assert _audio_stream_count(out) == 0, "no-spec render should have no audio track"


@ffmpeg_only
def test_sfx_present_with_spec(tmp_path: Path) -> None:
    """有 spec sfx 时成片带音轨(对照组)。"""
    clips = _clips(tmp_path, 2.0, n=2)
    specs: list[ShotSpec | None] = [
        ShotSpec(duration=2.0, sfx=[{"id": "ding_bell", "offset": 0.5}]),
        ShotSpec(transition_in="dissolve", duration=2.0),
    ]
    out = _render(clips, tmp_path / "withspec.mp4", specs)
    assert _audio_stream_count(out) == 1


# ── 3. 特效 ──────────────────────────────────────────────────────────


@ffmpeg_only
def test_mono_effect_zero_chroma(tmp_path: Path) -> None:
    clips = _clips(tmp_path, 2.0, n=2)
    specs: list[ShotSpec | None] = [ShotSpec(effect="mono", duration=2.0)] * 2
    out = _render(clips, tmp_path / "mono.mp4", specs)
    _, u, v = _frame_yuv(out, 1.0)  # 镜0 中段
    assert abs(u - 128) < 2, f"mono U={u:.2f} not neutral"
    assert abs(v - 128) < 2, f"mono V={v:.2f} not neutral"


@ffmpeg_only
def test_warm_effect_raises_rb_ratio(tmp_path: Path) -> None:
    clips = _clips(tmp_path, 2.0, n=2)
    base = _render(clips, tmp_path / "base.mp4", None)
    specs: list[ShotSpec | None] = [ShotSpec(effect="warm", duration=2.0)] * 2
    warm = _render(clips, tmp_path / "warm.mp4", specs)

    def rb(p: Path) -> float:
        f = _frame_rgb(p, 1.0).astype(float)
        return f[:, :, 0].mean() / max(f[:, :, 2].mean(), 1.0)

    rb_base, rb_warm = rb(base), rb(warm)
    assert rb_warm > rb_base + 0.05, f"warm R/B {rb_warm:.3f} not above baseline {rb_base:.3f}"


# ── 4. 转场 ──────────────────────────────────────────────────────────


def _seam_midpoints(durations, seam, d):
    starts = shot_start_times(durations, d, seam)
    mids = []
    for i in range(1, len(durations)):
        tok = seam[i - 1]
        di = 0.0 if tok == "cut" else d
        mids.append(starts[i] + di / 2)
    return mids


@ffmpeg_only
def test_transitions_vs_hardcut(tmp_path: Path) -> None:
    """spec 接缝(dissolve/whip)中点帧与全硬切基线同刻帧 SSIM < 0.98;两接缝形态不同。"""
    dur, xfade_d = 2.0, 0.5
    clips = _clips(tmp_path, dur, n=3)
    seam = ["dissolve", "whip"]
    specs: list[ShotSpec | None] = [
        ShotSpec(duration=dur),  # 第 1 镜 transition_in 忽略
        ShotSpec(transition_in="dissolve", duration=dur),
        ShotSpec(transition_in="whip", duration=dur),
    ]
    spec_out = _render(clips, tmp_path / "spec.mp4", specs, transition="fade", xfade_d=xfade_d)
    # 全硬切基线(同素材,总时长与 spec 版一致:2 条接缝,都 d=0.5 vs 都 d=0)
    base_out = _render(clips, tmp_path / "cut.mp4", None, transition="cut", xfade_d=xfade_d)

    mids = _seam_midpoints([dur] * 3, seam, xfade_d)
    for idx in (0, 1):
        f_spec = _frame_rgb(spec_out, mids[idx])
        f_base = _frame_rgb(base_out, mids[idx])
        s = compare_ssim(f_spec, f_base, channel_axis=2)
        assert s < 0.98, f"seam{idx} midpoint SSIM {s:.3f} >= 0.98 (no visible transition)"

    # 不同接缝转场形态不同(dissolve 中点 ≠ whip 中点)
    s_diff = compare_ssim(
        _frame_rgb(spec_out, mids[0]), _frame_rgb(spec_out, mids[1]), channel_axis=2
    )
    assert s_diff < 0.98, f"dissolve vs whip midpoints too similar (SSIM {s_diff:.3f})"


@ffmpeg_only
def test_cut_seam_is_hardcut(tmp_path: Path) -> None:
    """spec 指定 transition_in='cut' 的接缝确为硬切:该镜以原始画面直接进入。

    spec 版 seam0=fade(d=0.5)、seam1=cut(d=0),第 3 镜起点 = 2.0+2.0−0.5 = 3.5。
    硬切不混合 → 第 3 镜起点之后的画面应等于该镜素材自身对应帧;若 cut 未生效
    (仍走 xfade),起点会前移 0.5s 且画面是混合帧,SSIM 会明显掉。
    """
    dur, xfade_d = 2.0, 0.5
    clips = _clips(tmp_path, dur, n=3)
    specs: list[ShotSpec | None] = [
        ShotSpec(duration=dur),
        ShotSpec(transition_in="fade", duration=dur),
        ShotSpec(transition_in="cut", duration=dur),
    ]
    out = _render(clips, tmp_path / "withcut.mp4", specs, transition="fade", xfade_d=xfade_d)

    starts = shot_start_times([dur] * 3, xfade_d, seam_transitions(specs, 3, "fade"))
    assert starts == pytest.approx([0.0, 1.5, 3.5])  # seam1 cut → 不重叠

    t = dur / 2
    f_spec = _frame_rgb(out, starts[2] + t)
    f_clip2 = _frame_rgb(clips[2], t)
    s = compare_ssim(f_spec, f_clip2, channel_axis=2)
    assert s > 0.95, f"cut seam frame SSIM {s:.3f} — 第3镜未以原始画面硬切进入"


# ── 5. 时长 ──────────────────────────────────────────────────────────


@ffmpeg_only
def test_duration_equals_sum_minus_overlaps(tmp_path: Path) -> None:
    dur, xfade_d = 3.0, 0.5
    clips = _clips(tmp_path, dur, n=4)
    specs: list[ShotSpec | None] = [
        ShotSpec(duration=dur),
        ShotSpec(transition_in="dissolve", duration=dur),
        ShotSpec(transition_in="cut", duration=dur),
        ShotSpec(transition_in="whip", duration=dur),
    ]
    out = _render(clips, tmp_path / "dur.mp4", specs, transition="fade", xfade_d=xfade_d)
    # 4×3 − (0.5 + 0 + 0.5) = 11.0
    expected = sum([dur] * 4) - 2 * xfade_d
    got = _probe_dur(out)
    assert got == pytest.approx(expected, abs=1.0 / _FPS + 0.02), f"got {got}, expected {expected}"


def _framemd5(path: Path) -> list[str]:
    """提取视频每帧的 framemd5 列表 (每行去注保留帧 md5 字符串)。"""
    res = subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:v",
            "-f",
            "framemd5",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    lines = [line.strip() for line in res.stdout.splitlines() if not line.startswith("#")]
    # framemd5 输出格式: stream, dts, pts, duration, size, hash
    return [l.split(",")[-1].strip() for l in lines if l]


# ── 6. R2 FIX: Template 真实 ffmpeg 验收 (按 category) ──────────────


def test_template_all_valid_supported_or_rejected() -> None:
    """R2 验收 1 单测: valid_template_ids() 中所有 ID 均需满足 supported 或 rejected。"""
    all_ids = valid_template_ids()
    assert len(all_ids) >= 100
    assert all(template_render_supported(t) or rejected(t) for t in all_ids)


@ffmpeg_only
@pytest.mark.parametrize(
    ("category", "tpl_id"),
    [
        ("style", "tc:pencil-sketch-draw"),
        ("overlay", "tc:crash-zoom-punch"),
        ("transition", "tc:black-slam-transition"),
    ],
)
def test_template_render_framemd5_differs(tmp_path: Path, category: str, tpl_id: str) -> None:
    """每个可渲染 category 抽 1 个 id 真实渲染:

    - 该镜时间段 framemd5 与无 template 渲染不同;
    - 其它镜纯段逐帧相同 (framemd5 一致)。
    """
    dur, xfade_d = 3.0, 0.5
    clips = _clips(tmp_path, dur, n=3)
    base_out = _render(clips, tmp_path / f"base_{category}.mp4", None, transition="fade", xfade_d=xfade_d)
    tpl_specs: list[ShotSpec | None] = [
        None,
        ShotSpec(template=tpl_id, duration=dur),
        None,
    ]
    tpl_out = _render(clips, tmp_path / f"tpl_{category}.mp4", tpl_specs, transition="fade", xfade_d=xfade_d)

    md5_base = _framemd5(base_out)
    md5_tpl = _framemd5(tpl_out)
    assert len(md5_base) == len(md5_tpl), f"frame count mismatch {len(md5_base)} vs {len(md5_tpl)}"

    # 3 镜 (各 3.0s, xfade_d=0.5, 总长 8.0s = 240 帧):
    # 镜0 纯画面范围: 0.0s..2.0s (0..59 帧, 共 60 帧, 绝不沾接缝0)
    # 镜1 中段画面范围: 2.67s..4.67s (80..139 帧, 共 60 帧, 绝在镜1内部)
    # 镜2 纯画面范围: 5.67s..8.0s (170..239 帧, 共 70 帧, 绝在接缝1之后)
    pure_shot0 = slice(0, 60)
    shot1_range = slice(80, 140)
    pure_shot2 = slice(170, len(md5_base))

    # 1. 镜0 纯画面段逐帧一致
    assert md5_tpl[pure_shot0] == md5_base[pure_shot0], (
        f"category {category} affected shot 0: first mismatch at "
        f"{next(i for i, (a, b) in enumerate(zip(md5_tpl[pure_shot0], md5_base[pure_shot0], strict=True)) if a != b)}"
    )

    # 2. 镜1 时间段 framemd5 显著不同
    assert md5_tpl[shot1_range] != md5_base[shot1_range], (
        f"category {category} ({tpl_id}) had no visual difference on shot 1"
    )

    # 3. 镜2 纯画面段逐帧一致
    assert md5_tpl[pure_shot2] == md5_base[pure_shot2], (
        f"category {category} affected shot 2: first mismatch at "
        f"{next(i for i, (a, b) in enumerate(zip(md5_tpl[pure_shot2], md5_base[pure_shot2], strict=True)) if a != b)}"
    )


# ── 7. R2 FIX: Style 枚举逐值真实 ffmpeg 验收 ──────────────────────────


@ffmpeg_only
@pytest.mark.parametrize("style_name", sorted(VALID_STYLES))
def test_style_enum_real_ffmpeg(tmp_path: Path, style_name: str) -> None:
    """每个合法 style 枚举值真实渲染: 该镜中段帧与无 style 基线 SSIM < 0.98 或通道均值有可测偏移。"""
    clips = _clips(tmp_path, 2.0, n=2)
    base_out = _render(clips, tmp_path / f"base_style_{style_name}.mp4", None)
    specs: list[ShotSpec | None] = [ShotSpec(style=style_name, duration=2.0), None]
    style_out = _render(clips, tmp_path / f"styled_{style_name}.mp4", specs)

    # 取镜0中段 (1.0s) 比较画面
    f_base = _frame_rgb(base_out, 1.0)
    f_style = _frame_rgb(style_out, 1.0)
    s = compare_ssim(f_style, f_base, channel_axis=2)

    if style_name == "warm":
        rb_base = f_base[:, :, 0].mean() / max(f_base[:, :, 2].mean(), 1.0)
        rb_style = f_style[:, :, 0].mean() / max(f_style[:, :, 2].mean(), 1.0)
        assert rb_style > rb_base + 0.04 or s < 0.98
    elif style_name == "cool":
        rb_base = f_base[:, :, 0].mean() / max(f_base[:, :, 2].mean(), 1.0)
        rb_style = f_style[:, :, 0].mean() / max(f_style[:, :, 2].mean(), 1.0)
        assert rb_style < rb_base - 0.04 or s < 0.98
    elif style_name in ("mono", "noir"):
        _, u, v = _frame_yuv(style_out, 1.0)
        assert (abs(u - 128) < 2 and abs(v - 128) < 2) or s < 0.98
    else:
        assert s < 0.98, f"style '{style_name}' SSIM {s:.4f} >= 0.98 vs baseline"


# ── 8. R2 FIX: Duration 真实裁切/补帧与 SFX 对齐验收 ───────────────────


@ffmpeg_only
def test_duration_clip_pad_and_sfx_alignment(tmp_path: Path) -> None:
    """R2 验收 3: spec.duration 裁剪(3.0->1.5)与补帧(3.0->4.0);

    - ffprobe 成片时长 = Σ(spec.duration 或素材时长) − Σ(非 cut 接缝 d) ±1 帧;
    - sfx 起点公式随之正确,误差 ≤0.1s。
    """
    native_dur = 3.0
    clips = _clips(tmp_path, native_dur, n=3)
    specs: list[ShotSpec | None] = [
        ShotSpec(duration=1.5, sfx=[{"id": "impact_hard", "offset": 0.4}]),
        ShotSpec(transition_in="dissolve", duration=4.0, sfx=[{"id": "ding_bell", "offset": 1.0}]),
        ShotSpec(transition_in="cut"),  # 未给 duration -> 回落素材原时长 3.0s
    ]
    out = _render(clips, tmp_path / "dur_clip_pad.mp4", specs, transition="fade", xfade_d=0.5)

    # 时长理论值: 1.5 + 4.0 + 3.0 - 0.5(dissolve) - 0.0(cut) = 8.0s
    expected_dur = 1.5 + 4.0 + native_dur - 0.5
    measured_dur = _probe_dur(out)
    assert measured_dur == pytest.approx(expected_dur, abs=1.0 / _FPS + 0.02)

    # SFX 期望起点:
    # 镜0 起点 0.0, offset 0.4 -> 0.4s
    # 镜1 起点 1.5 - 0.5 = 1.0, offset 1.0 -> 2.0s
    seam = seam_transitions(specs, 3, "fade")
    starts = shot_start_times([1.5, 4.0, native_dur], 0.5, seam)
    assert starts == pytest.approx([0.0, 1.0, 5.0])
    expected_cues = [t for _, t in spec_sfx_cues(specs, starts)]
    assert expected_cues == pytest.approx([0.4, 2.0])

    x = _audio_mono(out)
    onset_list = _onsets(x)
    assert onset_list, "no onsets found"
    for t_exp in expected_cues:
        nearest = min(onset_list, key=lambda o: abs(o - t_exp))
        assert abs(nearest - t_exp) <= 0.1, (
            f"sfx onset mismatch: expected {t_exp}s, nearest {nearest:.3f}s"
        )


# ── 9. R2 FIX: 出片入口存储读取与集成测试 ──────────────────────────────


@ffmpeg_only
def test_ingress_reads_task_specs_and_renders_mono(tmp_path: Path) -> None:
    """R2 验收 4: 经由 API PATCH 单镜 spec (effect=mono),

    出片入口 (director/graph_render) 从任务存储读 spec 传给 assemble_longvideo,
    该镜中段 |U-128| < 2。
    """
    from uuid import uuid4

    from fastapi.testclient import TestClient

    from hevi.api.main import app
    from hevi.api.routers.tasks import get_repository
    from hevi.auth.dependencies import get_current_user
    from hevi.director.graph_render import render_graph_episode_artifact

    task_id = uuid4()
    user = {"id": "spec-ingress-test"}
    clips = _clips(tmp_path, 2.0, n=2)

    # 模拟真实任务存储 (shot_states 行)
    shots_data = [
        {
            "id": uuid4(),
            "task_id": str(task_id),
            "shot_index": i,
            "status": "pending",
            "selection_json": {},
        }
        for i in range(2)
    ]

    class FakeTaskRepo:
        async def get_task(self, tid):
            return {"id": str(task_id), "user_id": user["id"]}

        async def get_shots(self, tid):
            return shots_data

        async def save_shot(self, row):
            for i, s in enumerate(shots_data):
                if s["id"] == row["id"]:
                    shots_data[i] = row

    fake_repo = FakeTaskRepo()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_repository] = lambda: fake_repo

    client = TestClient(app)
    try:
        # ① 通过真实 API PATCH 镜0 effect=mono
        r = client.patch(
            f"/api/tasks/{task_id}/shots/0/spec",
            json={"effect": "mono"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["spec"]["effect"] == "mono"
    finally:
        client.close()
        app.dependency_overrides.clear()

    # ② 模拟现有出片入口所调用的 executor 服务
    class FakeExecutor:
        async def execute_graph(self, graph_id: str):
            return {
                "results": {
                    "shot_0000": {"node_type": "video", "success": True, "output": {"output": str(clips[0])}},
                    "shot_0001": {"node_type": "video", "success": True, "output": {"output": str(clips[1])}},
                }
            }

    class FakeTaskService:
        repository = fake_repo

    # ③ 走现有的出片入口执行装配 (内部自动从 repository.get_shots(task_id) 读 spec)
    out_dir = tmp_path / "task_out"
    rendered = asyncio.run(
        render_graph_episode_artifact(
            graph_id="test_graph",
            output_dir=out_dir,
            executor_service=FakeExecutor(),
            width=_W,
            height=_H,
            fps=_FPS,
            transition="cut",
            task_id=task_id,
            task_service=FakeTaskService(),
        )
    )

    final_video = Path(rendered["video_path"])
    assert final_video.exists()

    # ④ 镜0 (带 mono spec) 中段 |U-128| < 2, |V-128| < 2
    _, u0, v0 = _frame_yuv(final_video, 1.0)
    assert abs(u0 - 128) < 2, f"Shot 0 mid U={u0:.2f} not neutral"
    assert abs(v0 - 128) < 2, f"Shot 0 mid V={v0:.2f} not neutral"

