"""拍点网格:BPM × fps → 帧级拍点,重动作吸附重拍(允许微偏移)。

重拍 = 强拍(每 4 拍的第 1 拍为最重,第 3 拍次重)。重动作允许的微偏移:
  - 预备动作略早(negative bias,提前若干帧起势)
  - 撞击准拍(0 bias,严格落拍)
  - 碎屑/次级响应略晚(positive bias)

纯函数,零随机,确定性:同一 (bpm, fps, duration) 永远得到同一网格。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BeatGrid:
    """帧级拍点网格。"""

    bpm: float
    fps: int
    duration_s: float
    frames: int
    frames_per_beat: float
    beat_frames: tuple[int, ...]  # 每个拍点所在帧(向下取整)
    heavy_frames: tuple[int, ...]  # 重拍所在帧(每 4 拍的第 1、3 拍)
    downbeat_frames: tuple[int, ...]  # 最重拍(每 4 拍的第 1 拍)

    def time_of_frame(self, frame: int) -> float:
        return frame / self.fps

    def frame_of_time(self, t: float) -> int:
        return int(round(t * self.fps))

    def nearest_beat(self, t: float) -> tuple[int, float]:
        """返回 (最近的拍点帧, 偏差秒数)。"""
        bf = self.beat_frames
        f = self.frame_of_time(t)
        best = min(bf, key=lambda b: abs(b - f))
        return best, (f - best) / self.fps

    def nearest_heavy(self, t: float) -> tuple[int, float]:
        """返回 (最近的重拍帧, 偏差秒数)。"""
        hf = self.heavy_frames or self.beat_frames
        f = self.frame_of_time(t)
        best = min(hf, key=lambda b: abs(b - f))
        return best, (f - best) / self.fps


# 重动作类型 → 允许的微偏移(帧)。负=略早, 0=准拍, 正=略晚。
BIAS_FRAMES: dict[str, int] = {
    "anticipation": -2,  # 预备动作略早
    "drop": -1,  # 释放略早于拍
    "impact": 0,  # 撞击准拍
    "contact": 0,  # 接触准拍
    "bounce": 1,  # 反弹略晚
    "debris": 2,  # 碎屑略晚
    "secondary": 3,  # 次级响应更晚
    "settle": 0,
    "wave": 1,
    "cohere": 1,
    "roll": 1,
    "float": 0,
    "press": 0,
}


def build_grid(bpm: float, fps: int, duration_s: float) -> BeatGrid:
    """构建帧级拍点网格。

    Args:
        bpm: 每分钟拍数, 30..240。
        fps: 帧率, >0。
        duration_s: 片长秒。

    Raises:
        ValueError: 参数越界。
    """
    if not (30.0 <= bpm <= 240.0):
        raise ValueError(f"bpm out of range: {bpm}")
    if fps <= 0 or fps > 120:
        raise ValueError(f"fps out of range: {fps}")
    if duration_s <= 0:
        raise ValueError(f"duration_s must be positive: {duration_s}")

    frames = int(round(duration_s * fps))
    frames_per_beat = fps * 60.0 / bpm
    n_beats = int(duration_s * bpm / 60.0) + 1

    beat_frames = tuple(int(round(i * frames_per_beat)) for i in range(n_beats + 1))
    beat_frames = tuple(b for b in beat_frames if b <= frames)
    heavy = tuple(b for i, b in enumerate(beat_frames) if i % 2 == 0)  # 每 2 拍一个重拍
    downbeat = tuple(b for i, b in enumerate(beat_frames) if i % 4 == 0)

    return BeatGrid(
        bpm=float(bpm),
        fps=int(fps),
        duration_s=float(duration_s),
        frames=frames,
        frames_per_beat=frames_per_beat,
        beat_frames=beat_frames,
        heavy_frames=heavy or beat_frames,
        downbeat_frames=downbeat or beat_frames,
    )


def snap_heavy_action(t: float, kind: str, grid: BeatGrid, *, heavy: bool = True) -> int:
    """把一个重动作吸附到最近的拍(重动作吸重拍),加上该类型的微偏移。

    Returns:
        吸附后的帧号(已 clamp 到 [0, grid.frames])。
    """
    ref_frame, _ = grid.nearest_heavy(t) if heavy else grid.nearest_beat(t)
    bias = BIAS_FRAMES.get(kind, 0)
    f = ref_frame + bias
    return max(0, min(grid.frames, f))


def snap_all(
    events: list[dict], grid: BeatGrid, *, heavy_kinds: set[str] | None = None
) -> list[dict]:
    """把事件列表里的重动作吸附到拍点,返回新列表(不改原对象)。

    每个事件形如 ``{"t": float, "kind": str, ...}``。非重动作保持原时间。
    """
    heavy_kinds = heavy_kinds or {"impact", "contact", "drop", "bounce", "wave", "cohere", "press"}
    out: list[dict] = []
    for e in events:
        e2 = dict(e)
        if e.get("kind") in heavy_kinds:
            f = snap_heavy_action(float(e["t"]), str(e["kind"]), grid)
            e2["t"] = round(f / grid.fps, 6)
            e2["snapped_frame"] = f
        out.append(e2)
    return out


def beat_alignment_rate(
    events: list[dict], grid: BeatGrid, *, tol_frames: float = 1.0
) -> tuple[float, list[dict]]:
    """拍点对齐率:重动作与重拍偏差 ≤ tol_frames 的比例。

    Returns:
        (对齐率 0..1, 每个重动作的 {kind, t, dev_frames, aligned})
    """
    heavy_kinds = {"impact", "contact", "drop", "bounce", "wave", "cohere", "press"}
    details: list[dict] = []
    aligned = 0
    total = 0
    for e in events:
        if e.get("kind") not in heavy_kinds:
            continue
        total += 1
        f = grid.frame_of_time(float(e["t"]))
        ref, _ = grid.nearest_heavy(float(e["t"]))
        dev = abs(f - ref)
        ok = dev <= tol_frames
        aligned += int(ok)
        details.append({"kind": e["kind"], "t": float(e["t"]), "dev_frames": dev, "aligned": ok})
    rate = (aligned / total) if total else 1.0
    return rate, details


__all__ = [
    "BeatGrid",
    "BIAS_FRAMES",
    "build_grid",
    "snap_heavy_action",
    "snap_all",
    "beat_alignment_rate",
]
