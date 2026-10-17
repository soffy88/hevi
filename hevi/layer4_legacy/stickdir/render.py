"""CPU 渲染器 —— 把提案渲染成真实 mp4。

流水线:

1. 时间线:每 10s 段 → 段内三拍 → 每帧 (action, phase, staging, camera, prop, metaphor)。
2. 画面:PIL 逐帧绘制参数化火柴人(见 :mod:`pose` / :mod:`paint`), 背景/隐喻按段缓存,
   raw RGB 帧经 stdin 直接喂给 ffmpeg(不落中间帧, 省磁盘)。
3. 声音:piper/CosyVoice 旁白(按段对齐) + 程序化 BGM + SFX 库, 混音 loudnorm 到 −16 LUFS。
4. 字幕:按词/标点切分对齐 TTS 时长, 烧录 + 输出 .srt。
5. 封装:视频 + 混音 → mp4。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw

from hevi.layer4_legacy.stickdir import paint, pose, styles, subtitles, tts
from hevi.layer4_legacy.stickdir.paint import Canvas

logger = logging.getLogger(__name__)

FFMPEG = shutil.which("ffmpeg") or "/home/soffy/.local/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/home/soffy/.local/bin/ffprobe"

#: 画幅 → 像素尺寸
SIZE = {"9:16": (1080, 1920), "16:9": (1920, 1080)}

#: 旁白起始偏移(段内)
VO_LEAD = 0.30

#: BGM mood 白名单 → 程序化 BGM 预设
BGM_MOOD = {
    "calm": "calm",
    "warm": "warm",
    "tense": "tense",
    "epic": "epic",
    "playful": "bright",
    "somber": "calm",
    "curious": "bright",
}

#: 画幅 → 调度位置 → (anchor_x_frac, anchor_y_frac, scale_frac)
STAGING_GEOM = {
    "9:16": {
        "foreground": (0.50, 0.90, 0.30),
        "midground": (0.50, 0.82, 0.26),
        "background": (0.50, 0.72, 0.21),
        "top": (0.50, 0.74, 0.24),
        "bottom": (0.50, 0.91, 0.28),
    },
    "16:9": {
        "left": (0.30, 0.88, 0.40),
        "center": (0.50, 0.88, 0.40),
        "right": (0.70, 0.88, 0.40),
    },
}

#: 镜头 → 段内(zoom, dx_frac, dy_frac) 起点/终点
CAMERA_MOVE = {
    "static": ((1.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
    "push_in": ((1.0, 0.0, 0.0), (1.14, 0.0, 0.0)),
    "pull_out": ((1.14, 0.0, 0.0), (1.0, 0.0, 0.0)),
    "pan": ((1.0, -0.05, 0.0), (1.0, 0.05, 0.0)),
    "track": ((1.0, -0.03, 0.0), (1.0, 0.03, 0.0)),
    "shake": ((1.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
    "tilt": ((1.0, 0.0, -0.03), (1.0, 0.0, 0.03)),
    "orbit": ((1.0, -0.04, 0.0), (1.0, 0.04, 0.0)),
}


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


@dataclass
class FrameState:
    t: float
    seg: int
    beat: int
    action: str
    phase: float
    prop: str
    metaphor: str
    camera: str
    staging: str
    blink: bool


@dataclass
class RenderPlan:
    aspect: str
    duration: int
    style: str
    fps: int
    segments: list[dict]
    narration_offsets: list[float] = field(default_factory=list)
    narration_lines: list[str] = field(default_factory=list)

    @property
    def n_frames(self) -> int:
        return int(round(self.duration * self.fps))


def _segment_narration_lines(segments: list[dict]) -> tuple[list[str], list[float]]:
    lines: list[str] = []
    offsets: list[float] = []
    for seg in segments:
        text = (seg.get("narration") or "").strip()
        lines.append(text)
        offsets.append(seg["start"] + VO_LEAD)
    return lines, offsets


def build_plan(data: dict, *, fps: int) -> RenderPlan:
    """从提案数据构造渲染计划。"""
    segments = data["storyboard"]["segments"]
    lines, offsets = _segment_narration_lines(segments)
    return RenderPlan(
        aspect=data["aspect"],
        duration=data["duration"],
        style=data["style"],
        fps=fps,
        segments=segments,
        narration_offsets=offsets,
        narration_lines=lines,
    )


def _beat_at(seg: dict, local: float) -> tuple[int, float]:
    """段内局部时间 → (拍索引, 拍内进度 0..1)。"""
    for i, b in enumerate(seg["beats"]):
        if local < b["t1"] or i == len(seg["beats"]) - 1:
            span = max(b["t1"] - b["t0"], 0.001)
            return i, max(0.0, min(1.0, (local - b["t0"]) / span))
    return 0, 0.0


def _camera_state(camera: str, prog: float, local: float) -> tuple[float, float, float]:
    a, b = CAMERA_MOVE.get(camera, CAMERA_MOVE["static"])
    e = _ease(prog)
    zoom = a[0] + (b[0] - a[0]) * e
    dx = a[1] + (b[1] - a[1]) * e
    dy = a[2] + (b[2] - a[2]) * e
    if camera == "shake":
        dy = 0.006 * _shakesign(local)
        dx = 0.004 * _shakesign(local * 1.7)
    return zoom, dx, dy


def _shakesign(x: float) -> float:
    import math

    return math.sin(x * 2 * math.pi * 7.0)


def frame_state(plan: RenderPlan, t: float) -> FrameState:
    """给定时刻, 求该帧的绘制状态。"""
    idx = min(int(t // 10), len(plan.segments) - 1)
    seg = plan.segments[idx]
    local = t - seg["start"]
    bi, prog = _beat_at(seg, local)
    beat = seg["beats"][bi]
    action = beat["action"]
    # 相位: 循环动作按 2.5s 周期;一次性动作按拍时长(每拍重放)
    if action in pose.ONESHOT:
        phase = prog
    else:
        phase = (local % 2.5) / 2.5
    # 眨眼: 每 ~3.2s 一帧(确定性)
    blink = (int(t * plan.fps) % int(3.2 * plan.fps)) == 0
    return FrameState(
        t=t,
        seg=idx,
        beat=bi,
        action=action,
        phase=phase,
        prop=beat["prop"],
        metaphor=beat["metaphor"],
        camera=beat["camera"],
        staging=beat["staging"],
        blink=blink,
    )


def _staging_geom(plan: RenderPlan, staging: str) -> tuple[float, float, float]:
    table = STAGING_GEOM[plan.aspect]
    return table.get(staging, table[list(table)[0]])


def _metaphor_for(seg: dict) -> str:
    """段内取"最丰富"的隐喻(非 none 的第一个), 作为段级场景元素。"""
    for b in seg["beats"]:
        if b["metaphor"] != "none":
            return b["metaphor"]
    return "none"


class FrameRenderer:
    """按风格缓存背景+段级隐喻, 逐帧只画角色与道具。"""

    def __init__(self, plan: RenderPlan):
        self.plan = plan
        self.w, self.h = SIZE[plan.aspect]
        self.canvas = Canvas(self.w, self.h)
        self.dna = styles.get(plan.style)
        self._bg_cache: dict[tuple[int, str], Image.Image] = {}
        self.line_w = max(4, int(self.h * 0.006))

    def _bg(self, seg_idx: int, metaphor: str) -> Image.Image:
        key = (seg_idx, metaphor)
        cached = self._bg_cache.get(key)
        if cached is not None:
            return cached
        img = Image.new("RGB", (self.w, self.h), self.dna.bg)
        paint.draw_background(img, self.dna)
        d = ImageDraw.Draw(img)
        ground_y = self.h * 0.92
        paint.draw_metaphor(d, self.dna, metaphor, self.canvas, ground_y=ground_y)
        self._bg_cache[key] = img
        return img

    def render(self, fs: FrameState) -> Image.Image:
        seg = self.plan.segments[fs.seg]
        img = self._bg(fs.seg, _metaphor_for(seg)).copy()
        d = ImageDraw.Draw(img)

        ax, ay, sf = _staging_geom(self.plan, fs.staging)
        zoom, dxf, dyf = _camera_state(
            fs.camera, _beat_at(seg, fs.t - seg["start"])[1], fs.t - seg["start"]
        )
        scale = self.h * sf * zoom
        origin = (self.w * ax + self.w * dxf, self.h * ay + self.h * dyf)

        joints = pose.solve(pose.angles_at(fs.action, fs.phase))
        paint.draw_prop(d, self.dna, fs.prop, anchor=origin, scale=scale, line_w=self.line_w)
        paint.draw_character(
            d, self.dna, joints, scale=scale, origin=origin, line_w=self.line_w, blink=fs.blink
        )
        return img


def _render_video(plan: RenderPlan, out_silent: Path, work_dir: Path) -> None:
    """把全部帧经 stdin 喂给 ffmpeg, 写出无声视频。"""
    w, h = SIZE[plan.aspect]
    fr = FrameRenderer(plan)
    cmd = [
        FFMPEG,
        "-y",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{w}x{h}",
        "-r",
        str(plan.fps),
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        str(out_silent),
    ]
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    assert proc.stdin is not None
    try:
        for i in range(plan.n_frames):
            t = i / plan.fps
            img = fr.render(frame_state(plan, t))
            proc.stdin.write(img.tobytes())
    finally:
        proc.stdin.close()
        err = proc.stderr.read() if proc.stderr else b""
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg video encode failed: {err[-500:]!r}")
    if not out_silent.is_file() or out_silent.stat().st_size == 0:
        raise RuntimeError("ffmpeg wrote no video")


def _generate_bgm(plan: RenderPlan, work_dir: Path) -> Path:
    """按段 mood 生成程序化 BGM 并拼接。"""
    from hevi.audio.procedural_bgm import BgmConfig, generate_bgm_file

    parts: list[Path] = []
    for i, seg in enumerate(plan.segments):
        mood = BGM_MOOD.get(seg["bgm"], "calm")
        part = work_dir / f"bgm_{i:02d}.wav"
        generate_bgm_file(BgmConfig(mood=mood, duration_s=10.0, gain=0.30, seed=i + 1), part)
        parts.append(part)
    listfile = work_dir / "bgm.txt"
    listfile.write_text("".join(f"file '{p.resolve()}'\n" for p in parts), encoding="utf-8")
    out = work_dir / "bgm.wav"
    proc = subprocess.run(
        [
            FFMPEG,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listfile),
            "-c",
            "copy",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"bgm concat failed: {proc.stderr[-300:]}")
    return out


#: 段级 SFX 白名单类别 → 库内首选文件(相对 assets/audio/sfx/library/)
SFX_PICK = {
    "riser": "riser/riser_tech.wav",
    "glitch": "glitch/glitch_digital.wav",
    "click": "click/click_soft.wav",
    "chime": "chime/chime_soft.wav",
    "ding": "ding/ding_bell.wav",
    "impact": "impact/impact_soft.wav",
    "boom": "boom/boom_short.wav",
    "downer": "downer/downer_resolve.wav",
    "whoosh": "whoosh/whoosh_tight.wav",
    "pop": "pop/pop_snap.wav",
    "sparkle": "sparkle/sparkle_crystal.wav",
    "swipe": "swipe/swipe_right.wav",
    "swoosh": "swoosh/swoosh_snappy.wav",
    "tick": "tick/tick_dry.wav",
    "heartbeat": "heartbeat/heartbeat_single.wav",
    "bassdrop": "bassdrop/bassdrop_short.wav",
    "notification": "notification/notification_ping.wav",
    "shutter": "shutter/shutter_single.wav",
    "typewriter": "typewriter/typewriter_single.wav",
}

#: SFX 库根(本分支自己的目录, 由 feat/sfx-badclips 只读取用)
SFX_ROOT = Path(__file__).resolve().parents[3] / "assets" / "audio" / "sfx" / "library"


def _sfx_track(plan: RenderPlan, total: float, work_dir: Path) -> Path | None:
    """把每段的段级 SFX 放在该段高潮拍起点。"""
    events: list[tuple[float, Path]] = []
    for seg in plan.segments:
        cat = None
        for b in seg["beats"]:
            if b["sfx"] and b["sfx"] != "none":
                cat = b["sfx"]
                break
        if not cat:
            continue
        rel = SFX_PICK.get(cat)
        if not rel:
            continue
        wav = SFX_ROOT / rel
        if not wav.is_file():
            continue
        at = seg["start"] + 7.0  # 高潮拍 [7-10s] 起点
        events.append((at, wav))
    if not events:
        return None
    cmd = [
        FFMPEG,
        "-y",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-t",
        f"{total:.3f}",
        "-i",
        "anullsrc=r=44100:cl=mono",
    ]
    for _at, wav in events:
        cmd += ["-i", str(wav)]
    filters, labels = [], ["[0:a]"]
    for i, (at, _wav) in enumerate(events):
        ms = int(round(at * 1000))
        filters.append(f"[{i + 1}:a]adelay={ms}|{ms}[s{i}]")
        labels.append(f"[s{i}]")
    filters.append(
        "".join(labels) + f"amix=inputs={len(labels)}:normalize=0:dropout_transition=0[mix]"
    )
    filters.append("[mix]volume=0.55[out]")
    cmd += [
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[out]",
        "-ar",
        "44100",
        "-ac",
        "1",
        str(work_dir / "sfx.wav"),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        logger.warning("sfx track failed: %s", proc.stderr[-200:])
        return None
    return work_dir / "sfx.wav"


def _mix_audio(narration: Path, bgm: Path, sfx: Path | None, total: float, out: Path) -> None:
    """旁白 + BGM + SFX → loudnorm −16 LUFS / TP −1.5。"""
    inputs = ["-i", str(narration), "-i", str(bgm)]
    if sfx is not None:
        inputs += ["-i", str(sfx)]
    fc = "[0:a]volume=1.0[n];[1:a]volume=0.16[b]"
    labels = "[n][b]"
    if sfx is not None:
        fc += ";[2:a]volume=0.55[s]"
        labels += "[s]"
    fc += f";{labels}amix=inputs={3 if sfx else 2}:normalize=0:dropout_transition=0[m]"
    fc += ";[m]highpass=f=60,loudnorm=I=-16:TP=-1.5:LRA=11[out]"
    cmd = [
        FFMPEG,
        "-y",
        "-loglevel",
        "error",
        *inputs,
        "-filter_complex",
        fc,
        "-map",
        "[out]",
        "-t",
        f"{total:.3f}",
        "-ar",
        "44100",
        "-ac",
        "1",
        str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"audio mix failed: {proc.stderr[-400:]}")


def _build_srt(plan: RenderPlan, cues: list[tuple[float, float]], out: Path) -> list[subtitles.Cue]:
    all_cues: list[subtitles.Cue] = []
    for seg, (start, end) in zip(plan.segments, cues):
        text = (seg.get("narration") or "").strip()
        if not text:
            continue
        # 字幕不越段:结束时间夹到本段窗口内(音频仍按真实时长播放)
        seg_end = float(seg["end"]) - 0.05
        capped_end = max(min(end, seg_end), start + 0.5)
        all_cues.extend(subtitles.split_cues(text, start, capped_end))
    out.write_text(subtitles.to_srt(all_cues), encoding="utf-8")
    return all_cues


def _burn_and_mux(video: Path, audio: Path, ass: Path, out: Path, *, burn: bool) -> None:
    """烧字幕 + 封装音视频。"""
    cmd = [FFMPEG, "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio)]
    if burn:
        cmd += ["-vf", f"ass={ass.name}"]
    cmd += [
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ass.parent))
    if proc.returncode != 0:
        raise RuntimeError(f"mux failed: {proc.stderr[-500:]}")


def render_proposal(
    data: dict,
    out_path: Path,
    *,
    fps: int = 30,
    work_dir: Path | None = None,
    burn_subtitles: bool = True,
    tts_engine: str | None = None,
) -> Path:
    """把一份提案数据渲染成 mp4。"""
    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plan = build_plan(data, fps=fps)
    wd = (work_dir or (out_path.parent / f".{out_path.stem}_work")).resolve()
    wd.mkdir(parents=True, exist_ok=True)

    total = float(plan.duration)

    # 1) 旁白(按段对齐)
    nar = tts.synthesize_timed(
        plan.narration_lines, plan.narration_offsets, total, wd / "tts", engine=tts_engine
    )
    logger.info("narration engine=%s cues=%d", nar.engine, len(nar.cues))

    # 2) BGM + SFX
    bgm = _generate_bgm(plan, wd)
    sfx = _sfx_track(plan, total, wd)

    # 3) 混音
    mixed = wd / "mixed.wav"
    _mix_audio(nar.wav, bgm, sfx, total, mixed)

    # 4) 视频
    silent = wd / "video_silent.mp4"
    _render_video(plan, silent, wd)

    # 5) 字幕 + 封装
    srt = out_path.with_suffix(".srt")
    cues = _build_srt(plan, nar.cues, srt)
    w, h = SIZE[plan.aspect]
    ass = out_path.with_suffix(".ass")
    ass.write_text(subtitles.to_ass(cues, w, h), encoding="utf-8")
    _burn_and_mux(silent, mixed, ass, out_path, burn=burn_subtitles)
    if not out_path.is_file() or out_path.stat().st_size == 0:
        raise RuntimeError("render produced no output")
    return out_path


__all__ = ["FrameRenderer", "RenderPlan", "SIZE", "build_plan", "frame_state", "render_proposal"]
