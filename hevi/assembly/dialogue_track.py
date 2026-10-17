"""SPEC-007 批1 ③:对白主轨 + 环境床——产物喂给既有 `assembler.py::assemble_longvideo`。

手法照抄 `hevi/tongjian/assemble.py` 里已经验证过的两个 ffmpeg 写法(`mix_bgm_master` 的
acrossfade 拼接链、`mix_sfx_master` 的 adelay+amix),但那两个函数跟 `MusicPlan`/
`cue.act`/`cue.t_start_ms` 强绑定,不能直接调用——这里收纯 `(Path, start_ms)` 输入,不
依赖 tongjian 的 cue 数据类型。

J-cut(下一段对白提前进入)/L-cut(上一段对白话音延续)这类**场景相关的时间偏移怎么算**
不在这个模块里——那是调用方按 handoff/剪辑点数据决定的编排逻辑,这个模块只管"给一组
(音频,起始毫秒)配对混出一条轨道"这个机制本身,机制和场景决策分开,不要耦合。

两个产物按这样接进已有装配函数,不要在这里重新拼视频/duck/loudnorm(那些
`assemble_longvideo` 已经做了):
    dialogue_track = await build_dialogue_track(cues, output_path=..., total_duration_ms=...)
    ambient_bed = await build_ambient_bed(segment_audio_paths, output_path=...)
    await assemble_longvideo(shots=..., narration_audio=dialogue_track, bgm_path=ambient_bed, ...)
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from obase.ffmpeg import run as ffmpeg_run

_DEFAULT_CROSSFADE_S = 0.3


@dataclass(frozen=True)
class DialogueCue:
    audio_path: Path
    start_ms: int


async def build_ambient_bed(
    segment_audio_paths: list[Path], *, output_path: Path, crossfade_s: float = _DEFAULT_CROSSFADE_S
) -> Path | None:
    """把各段的环境音 acrossfade 拼成一条连续环境床(手法抄 `mix_bgm_master`,
    `hevi/tongjian/assemble.py:221-256`)。

    **硬约束:`segment_audio_paths` 必须是已经不含台词的纯环境音**——这个函数只管混轨,
    不检查/剥离内容。2026-07-20 G-FINAL 真机撞见过把原始整条 AAC(带着 provider 烧进去
    的原声台词)直接当"环境音"喂进来的用法,造成台词在成片里被念了两遍(还叠了一份独立
    TTS)。调用方要先过 `hevi.assembly.native_dialogue.strip_dialogue_from_track`(把 ASR
    测到的开口窗口静音掉)或者本来就是独立生成的环境音,不能直接传 provider 原始输出的
    整条音轨。"""
    paths = [p for p in segment_audio_paths if p.exists()]
    if not paths:
        return None
    if len(paths) == 1:
        shutil.copy(paths[0], output_path)
        return output_path

    inputs: list[str] = []
    for p in paths:
        inputs += ["-i", str(p)]
    parts: list[str] = []
    prev = "[0:a]"
    for i in range(1, len(paths)):
        out_label = f"[ax{i}]" if i < len(paths) - 1 else "[aout]"
        parts.append(f"{prev}[{i}:a]acrossfade=d={crossfade_s}:c1=tri:c2=tri{out_label}")
        prev = out_label
    await ffmpeg_run(
        args=[*inputs, "-filter_complex", ";".join(parts), "-map", "[aout]", str(output_path)],
        expected_output=output_path,
    )
    return output_path


_DEFAULT_MIN_GAP_MS = 200
_DEFAULT_MAX_SEARCH_MS = 3000  # 硬约束不能让剪辑点漫无边际地漂移——找不到近处安全间隙就该
# 报错,不是把剪辑点推到天涯海角去"凑合安全"(那已经不是原来那个剪辑点了)。


@dataclass(frozen=True)
class CutPointViolation:
    cut_time_ms: int
    window: tuple[int, int]  # 落进的(含 min_gap 安全边距扩张后的)dialogue 窗口
    resolved_time_ms: int  # 纠正后建议使用的时间点


def _merge_windows(windows: list[tuple[int, int]], *, min_gap_ms: int) -> list[tuple[int, int]]:
    """按 min_gap_ms 扩张各窗口再合并重叠/相邻区间——合并后间隙之间的空白才是真正安全的。"""
    if not windows:
        return []
    expanded = sorted((max(0, s - min_gap_ms), e + min_gap_ms) for s, e in windows)
    merged = [expanded[0]]
    for s, e in expanded[1:]:
        last_s, last_e = merged[-1]
        if s <= last_e:
            merged[-1] = (last_s, max(last_e, e))
        else:
            merged.append((s, e))
    return merged


def find_cut_point_violations(
    cut_times_ms: list[int],
    dialogue_windows_ms: list[tuple[int, int]],
    *,
    min_gap_ms: int = _DEFAULT_MIN_GAP_MS,
    max_search_ms: int = _DEFAULT_MAX_SEARCH_MS,
) -> list[CutPointViolation]:
    """纯函数,零成本——检查每个剪辑点是否落进任一 dialogue 窗口(含 `min_gap_ms` 安全
    边距)。落进了就在 `max_search_ms` 范围内找最近的安全间隙,回报 violation(不静默
    纠正,调用方决定要不要采纳 `resolved_time_ms`)。找不到安全间隙的剪辑点,
    `resolved_time_ms` 落在超出 `max_search_ms` 范围之外的第一个安全点(仍然给出一个值
    供参考),但会与找到范围内安全点的情况在 `resolve_cut_points` 里区别对待(前者报错,
    后者采纳)。"""
    merged = _merge_windows(dialogue_windows_ms, min_gap_ms=min_gap_ms)
    violations: list[CutPointViolation] = []
    for t in cut_times_ms:
        hit = next((w for w in merged if w[0] <= t <= w[1]), None)
        if hit is None:
            continue
        left = hit[0] - 1
        right = hit[1] + 1
        # 左右两个候选点本身也可能落进相邻窗口(窗口间距小于 min_gap_ms 时不会发生,因为
        # 已经合并过;但左候选可能是负数,右候选理论上无上界,这里只比较距离原剪辑点的远近)。
        resolved = left if (left >= 0 and t - left <= right - t) else right
        violations.append(CutPointViolation(cut_time_ms=t, window=hit, resolved_time_ms=resolved))
    return violations


def resolve_cut_points(
    cut_times_ms: list[int],
    dialogue_windows_ms: list[tuple[int, int]],
    *,
    min_gap_ms: int = _DEFAULT_MIN_GAP_MS,
    max_search_ms: int = _DEFAULT_MAX_SEARCH_MS,
) -> list[int]:
    """`find_cut_point_violations` 的纠偏版——直接返回一份纠正后的剪辑点列表(有违规的
    换成最近安全间隙)。任何一个剪辑点的最近安全间隙超出 `max_search_ms` 范围(比如台词
    几乎连续说满全场,附近根本没有真正的间隙)→ 抛 `ValueError`,不能悄悄把剪辑点挪到
    很远的地方去"凑合安全"——那已经不是同一个剪辑决策了。"""
    violations = {
        v.cut_time_ms: v
        for v in find_cut_point_violations(
            cut_times_ms, dialogue_windows_ms, min_gap_ms=min_gap_ms, max_search_ms=max_search_ms
        )
    }
    resolved: list[int] = []
    for t in cut_times_ms:
        v = violations.get(t)
        if v is None:
            resolved.append(t)
            continue
        if abs(v.resolved_time_ms - t) > max_search_ms:
            raise ValueError(
                f"剪辑点 {t}ms 落进对白窗口 {v.window},{max_search_ms}ms 范围内找不到"
                f"安全间隙(最近的在 {v.resolved_time_ms}ms 处,超出范围)"
            )
        resolved.append(v.resolved_time_ms)
    return resolved


async def build_dialogue_track(
    cues: list[DialogueCue], *, output_path: Path, total_duration_ms: int
) -> Path | None:
    """按各自 `start_ms` 定时叠加对白线索,`amix` 成一条覆盖全片时长的对白主轨(手法抄
    `mix_sfx_master`,`hevi/tongjian/assemble.py:259-295`)。`start_ms` 已经包含调用方算好
    的 J/L-cut 偏移,这里只管照着摆。"""
    valid = [c for c in cues if c.audio_path.exists()]
    if not valid:
        return None

    inputs: list[str] = []
    parts: list[str] = []
    labels: list[str] = []
    for i, cue in enumerate(valid):
        inputs += ["-i", str(cue.audio_path)]
        parts.append(f"[{i}:a]adelay={max(cue.start_ms, 0)}:all=1[d{i}]")
        labels.append(f"[d{i}]")

    total_s = max(total_duration_ms, 1) / 1000.0
    n = len(labels)
    parts.append("".join(labels) + f"amix=inputs={n}:duration=longest:dropout_transition=0[mixed]")
    parts.append(f"[mixed]apad=whole_dur={total_s:.3f}[aout]")
    await ffmpeg_run(
        args=[
            *inputs,
            "-filter_complex",
            ";".join(parts),
            "-map",
            "[aout]",
            "-t",
            f"{total_s:.3f}",
            str(output_path),
        ],
        expected_output=output_path,
    )
    return output_path
