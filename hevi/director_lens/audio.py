"""SFX 从运动长成、BGM ducking 与音频事件完整性检查。

规则:
1. 速度峰 → whoosh, 冲量/撞击 → impact, 接触帧 → 点击/落地。
2. 主讲/台词/重音处 BGM 自动让路 (ducking)。
3. 本模块只检查 brief 的音频事件是否完整（有无 BGM/SFX/ducking），
   不读取也不测量任何音频文件、不做响度测量。成片响度测量归
   earshot（audio.earshot_gate，通用档 -14±2 LUFS）与
   hevi.quality.kids_gate.check_loudness（幼儿档 -16±1 LUFS、
   真峰值 ≤ -1.5 dBTP）；-16/-1.5 在本模块仅是传给下游门禁的目标参数。
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
    """音频事件完整性检查：只看 brief 的音频事件有无 BGM/SFX/ducking。

    不测量任何音频文件，响度不在此判定：报告中的 lufs / true_peak_dbtp
    恒为 "not_measured"，target_lufs / max_true_peak 只是幼儿档目标参数
    （供下游 earshot / kids_gate 测量门禁参考）。成片响度测量见
    hevi.audio.earshot_client.measure 与 hevi.quality.kids_gate.check_loudness。
    """
    has_ducking = any(e.kind == "bgm_duck" for e in audio_events)
    has_bgm = any(e.kind == "bgm" for e in audio_events)
    has_sfx = any(e.kind == "sfx" for e in audio_events)

    passed = has_bgm and (has_sfx or not audio_events)
    return {
        "passed": passed,
        "loudness": "not_measured",
        "lufs": "not_measured",
        "true_peak_dbtp": "not_measured",
        "target_lufs": target_lufs,
        "max_true_peak_dbtp": max_true_peak,
        "has_bgm": has_bgm,
        "has_sfx": has_sfx,
        "has_ducking": has_ducking,
        "notes": "Audio events complete (BGM/SFX present); loudness not measured here — see earshot/kids_gate gates" if passed else "Audio audit missing key events",
    }


__all__ = [
    "generate_audio_events",
    "check_audio_compliance",
]
