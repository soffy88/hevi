"""BGM 节拍对齐(HEVI 路线图 Phase2 #37)。

转场卡在音乐节拍点上是常见的观感提升手法,零边际成本(装配阶段的纯计算,不
额外生成任何素材)。只调每处转场的 xfade 重叠时长(在基准值 ± max_shift 内浮动
去贴最近的节拍点),不碰每个镜头的目标时长——那是音频驱动锁定的(旁白时长),
不能因为好看就打乱音画同步。

librosa 做节拍检测(已是既有依赖,不是新引入)。检测失败(非音频文件/librosa
异常)→ 空节拍列表,调用方应该据此回退到原有的统一 xfade 时长,不阻断装配。
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def detect_beat_times(audio_path: Path) -> list[float]:
    """librosa 检测音频的节拍时间点(秒)。失败(非音频/解码错误/librosa 缺失)→ []。"""
    try:
        import librosa

        y, sr = librosa.load(str(audio_path), sr=None, mono=True)
        _tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        return [float(t) for t in librosa.frames_to_time(beat_frames, sr=sr)]
    except Exception as e:
        logger.warning("beat detection failed for %s: %s", audio_path, e)
        return []


def beat_snapped_xfade_durations(
    durations: list[float],
    *,
    base_xfade_d: float,
    beats: list[float],
    max_shift: float = 0.3,
) -> list[float]:
    """给每处转场算一个贴近最近节拍点的 xfade 重叠时长。

    第 i 处转场(第 i-1 镜头与第 i 镜头之间)"自然"发生在 `merged`(前面镜头
    累计时长,还没减 xfade)那个时间点;这个点跟最近节拍点的偏移量 `shift` 直接
    转成 xfade_d 的调整量(转场提前发生 = xfade_d 增大,推后发生 = xfade_d 减小),
    夹在 `base_xfade_d ± max_shift` 内,同时不超过相邻两镜头时长的一半(与
    `assemble_longvideo` 现有的 xfade_d 上限规则一致)。

    没有节拍数据(`beats` 为空)→ 原样返回 `[base_xfade_d] * (N-1)`,退化为
    未对齐前的统一重叠时长,不报错。
    """
    n = len(durations)
    if n < 2:
        return []
    if not beats:
        return [base_xfade_d] * (n - 1)

    xfade_ds: list[float] = []
    merged = durations[0]
    for i in range(1, n):
        natural_cut = merged
        nearest = min(beats, key=lambda b: abs(b - natural_cut))
        shift = nearest - natural_cut
        d = base_xfade_d - shift
        d = max(base_xfade_d - max_shift, min(base_xfade_d + max_shift, d))
        d = max(0.05, min(d, durations[i - 1] / 2, durations[i] / 2))
        xfade_ds.append(d)
        merged = merged + durations[i] - d
    return xfade_ds
