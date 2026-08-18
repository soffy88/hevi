"""production_checks —— 生产侧确定性质量检查(3O oskill 风格, 差距 B4)。

对标 agent-video-pipeline 的 validate 面(prosody/voice_stability/av_alignment/
scene_pacing/semantic_motion/layout_boxes/episode_independence/audio_boundaries),
补 hevi 差距: verdict 目前强于图像身份/返工, 缺语速节奏/音频边界/集独立性等
**确定性**检查。

本模块全部为纯函数(输入 JSON 化事实, 输出 CheckResult), 零媒体解码依赖:
  - check_scene_pacing(scenes): 场景时长分布(过短/过长/方差)
  - check_audio_boundaries(segments): 静音间隙/重叠/爆音提示(基于分段时间轴)
  - check_episode_independence(episode_meta): 集独立性(开场 recap 缺失/结尾悬念/自包含引用)
  - check_voice_stability(voice_stats): 同一配音者各段 RMS/语速/基频稳定性
  - run_production_checks(checks): 汇总执行, 输出逐项 + 总 verdict

与 hevi/verdict/scorecard.py 的关系: 那是**图像身份**打分(需解码抽帧); 这里是
**时间轴/元数据**级确定性检查(便宜、可在合成前跑)。将来回迁 oskill 时可并入
同一校验族。
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

# 场景时长经验阈值(秒)。
SCENE_MIN_S = 1.5
SCENE_MAX_S = 45.0

# 音频边界: 段间最小静音间隙(秒)与最大允许重叠(秒)。
GAP_MIN_S = 0.05
OVERLAP_MAX_S = 0.05

# 声音稳定性: 允许的相对偏差(分段 RMS/语速/基频的标准差上限)。
RMS_REL_STD_MAX = 0.35
PITCH_REL_STD_MAX = 0.20


@dataclass
class CheckResult:
    name: str
    passed: bool
    details: list[str] = field(default_factory=list)
    severity: str = "warning"  # warning / error

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "details": self.details, "severity": self.severity}


# ---------------------------------------------------------------------------
# 1. 场景节奏
# ---------------------------------------------------------------------------


def check_scene_pacing(
    scenes: Sequence[dict[str, Any]],
    *,
    min_s: float = SCENE_MIN_S,
    max_s: float = SCENE_MAX_S,
) -> CheckResult:
    """场景时长分布检查: 过短(< min_s)视为剪辑碎; 过长(> max_s)视为拖沓。

    scenes: [{"id", "duration_s"}]。缺 duration_s 的项忽略并记 note。
    """
    res = CheckResult(name="scene_pacing", passed=True)
    durations = [float(s["duration_s"]) for s in scenes if s.get("duration_s")]
    missing = len(scenes) - len(durations)
    if missing:
        res.details.append(f"缺时长的场景 {missing} 个(已跳过)")
    if not durations:
        res.passed = False
        res.details.append("无场景时长数据")
        return res
    too_short = [d for d in durations if d < min_s]
    too_long = [d for d in durations if d > max_s]
    if too_short:
        res.passed = False
        res.details.append(f"{len(too_short)} 个场景过短(<{min_s}s): {[round(d,1) for d in too_short][:5]}")
    if too_long:
        res.passed = False
        res.details.append(f"{len(too_long)} 个场景过长(>{max_s}s): {[round(d,1) for d in too_long][:5]}")
    if len(durations) >= 3:
        cv = statistics.pstdev(durations) / (statistics.mean(durations) or 1.0)
        if cv > 0.9:
            res.details.append(f"时长离散度过高(CV={cv:.2f} > 0.9), 节奏不匀")
    return res


# ---------------------------------------------------------------------------
# 2. 音频边界
# ---------------------------------------------------------------------------


def check_audio_boundaries(
    segments: Sequence[dict[str, Any]],
    *,
    gap_min_s: float = GAP_MIN_S,
    overlap_max_s: float = OVERLAP_MAX_S,
) -> CheckResult:
    """音频段边界检查: 段间静音间隙不足 / 重叠 / 时间轴倒挂。

    segments: [{"start", "end"}] 秒。按 start 排序后逐对检查。
    """
    res = CheckResult(name="audio_boundaries", passed=True)
    segs = sorted(
        (s for s in segments if s.get("start") is not None and s.get("end") is not None),
        key=lambda s: float(s["start"]),
    )
    if not segs:
        res.passed = False
        res.details.append("无音频段数据")
        return res
    for prev, cur in zip(segs, segs[1:]):
        p_end, c_start = float(prev["end"]), float(cur["start"])
        if c_start < p_end:
            overlap = p_end - c_start
            if overlap > overlap_max_s:
                res.passed = False
                res.details.append(f"段重叠 {overlap:.2f}s(>{overlap_max_s}s)")
        elif c_start - p_end < gap_min_s:
            res.details.append(f"段间静音间隙不足({c_start - p_end:.3f}s < {gap_min_s}s)")
    return res


# ---------------------------------------------------------------------------
# 3. 集独立性
# ---------------------------------------------------------------------------


def check_episode_independence(episode: dict[str, Any]) -> CheckResult:
    """集独立性检查: 集作为可独立观看的单元所需的结构件。

    episode: {"title", "recap_present", "cliffhanger_present", "self_contained_refs": bool,
              "cold_open": bool, "episode_number", "series_name"}
    """
    res = CheckResult(name="episode_independence", passed=True)
    if not episode.get("recap_present") and not episode.get("cold_open"):
        res.passed = False
        res.details.append("无开场 recap 且无 cold open: 新观众缺乏上下文锚点")
    if not episode.get("cliffhanger_present"):
        res.details.append("无结尾悬念(系列连续观看钩子弱)")
    if episode.get("self_contained_refs") is False:
        res.passed = False
        res.details.append("存在对前集未解释的引用(需在台词内自包含)")
    if not episode.get("title"):
        res.details.append("缺集标题")
    return res


# ---------------------------------------------------------------------------
# 4. 声音稳定性
# ---------------------------------------------------------------------------


def check_voice_stability(
    voice_stats: Sequence[dict[str, Any]],
    *,
    rms_rel_std_max: float = RMS_REL_STD_MAX,
    pitch_rel_std_max: float = PITCH_REL_STD_MAX,
) -> CheckResult:
    """同一配音者各段声学稳定性: RMS(响度)与基频(音高)的相对标准差。

    voice_stats: [{"rms": float, "pitch_hz": float|None, "wpm": float|None, "label": str|None}]
    仅用 RMS/基频(两者可离线测得, 不依赖 ASR); 语速(wpm)有则附注。
    """
    res = CheckResult(name="voice_stability", passed=True)
    if not voice_stats:
        res.passed = False
        res.details.append("无配音段声学数据")
        return res
    rms = [float(v["rms"]) for v in voice_stats if v.get("rms") is not None]
    pitches = [float(v["pitch_hz"]) for v in voice_stats if v.get("pitch_hz")]
    if len(rms) >= 2:
        mean_rms = statistics.mean(rms) or 1.0
        rel_std = statistics.pstdev(rms) / mean_rms
        if rel_std > rms_rel_std_max:
            res.passed = False
            res.details.append(f"响度不稳定(rel_std={rel_std:.2f} > {rms_rel_std_max})")
    if len(pitches) >= 2:
        mean_p = statistics.mean(pitches) or 1.0
        rel_std = statistics.pstdev(pitches) / mean_p
        if rel_std > pitch_rel_std_max:
            res.passed = False
            res.details.append(f"基频漂移(rel_std={rel_std:.2f} > {pitch_rel_std_max})")
    if len(rms) < 2 and len(pitches) < 2:
        res.details.append("样本不足(单段), 稳定性判定从宽")
    return res


# ---------------------------------------------------------------------------
# 汇总执行
# ---------------------------------------------------------------------------

CheckFn = Callable[[], CheckResult]


def run_production_checks(
    checks: dict[str, CheckFn] | Sequence[tuple[str, CheckFn]],
) -> dict[str, Any]:
    """批量执行检查, 汇总: 逐项结果 + 总 verdict(failed 数 + 明细)。

    3O omodul 风格: 调用方按阶段注册检查项, 本函数串行执行并聚合。
    """
    items = list(checks.items()) if isinstance(checks, dict) else list(checks)
    results: list[CheckResult] = []
    for name, fn in items:
        try:
            res = fn()
            res.name = name  # 以注册名为准(检查器内部 name 仅作默认)
            results.append(res)
        except Exception as exc:  # 检查器自身异常不阻断其他项
            results.append(
                CheckResult(name=name, passed=False, details=[f"检查器异常: {exc}"], severity="error")
            )
    failed = [r for r in results if not r.passed]
    return {
        "passed": not failed,
        "failed_count": len(failed),
        "checks": [r.to_dict() for r in results],
    }


__all__ = [
    "CheckResult",
    "check_audio_boundaries",
    "check_episode_independence",
    "check_scene_pacing",
    "check_voice_stability",
    "run_production_checks",
]
