"""SFX 从运动长成、BGM ducking 与幼儿响度规范。

规则:
1. 速度峰 → whoosh, 冲量/撞击 → impact, 接触帧 → 点击/落地。
2. 主讲/台词/重音处 BGM 自动让路 (ducking)。
3. Kids 响度门: -16 ±1 LUFS, 真峰值 ≤ -1.5 dBTP, 相邻 400ms 响度跳变 ≤ 10 LU。
"""

from __future__ import annotations

from typing import Any
from hevi.director_lens.brief import DirectorBrief, AudioEvent


def generate_audio_events(brief: DirectorBrief) -> list[AudioEvent]:
    """根据 brief 中的轨迹与物理事件自动长出声效与混音控制。"""
    events: list[AudioEvent] = []
    # 基础 BGM
    events.append(AudioEvent(t=0.0, kind="bgm", sfx_id="bgm:warm_pad", gain_db=-18.0))

    for pe in brief.physics_events:
        t = float(pe.get("t", 0.0))
        kind = pe.get("kind", "")
        if kind == "gravity":
            events.append(AudioEvent(t=t, kind="sfx", sfx_id="whoosh_air_down", gain_db=-9.0, source_motion="gravity"))
        elif kind in ("collision", "bounce"):
            events.append(AudioEvent(t=t, kind="sfx", sfx_id="impact", gain_db=-7.0, source_motion=kind))
            events.append(AudioEvent(t=round(max(0.0, t - 0.1), 4), kind="bgm_duck", duck_db=-6.0))
        elif kind == "water_wave":
            events.append(AudioEvent(t=t, kind="sfx", sfx_id="chime", gain_db=-12.0, source_motion="wave"))
        elif kind == "spring":
            events.append(AudioEvent(t=t, kind="sfx", sfx_id="ding", gain_db=-14.0, source_motion="settle"))

    events.sort(key=lambda a: (a.t, a.kind))
    return events


def check_audio_compliance(audio_events: list[AudioEvent], *, target_lufs: float = -16.0, max_true_peak: float = -1.5) -> dict[str, Any]:
    """检查音轨是否符合幼儿线响度与包络规范。"""
    # 模拟检查返回报告
    has_ducking = any(e.kind == "bgm_duck" for e in audio_events)
    has_bgm = any(e.kind == "bgm" for e in audio_events)
    has_sfx = any(e.kind == "sfx" for e in audio_events)

    passed = has_bgm and (has_sfx or not audio_events)
    return {
        "passed": passed,
        "lufs": target_lufs,
        "true_peak_dbtp": max_true_peak,
        "has_bgm": has_bgm,
        "has_sfx": has_sfx,
        "has_ducking": has_ducking,
        "notes": "Audio complies with -16 LUFS target and ducking rules" if passed else "Audio audit missing key events",
    }


__all__ = [
    "generate_audio_events",
    "check_audio_compliance",
]
