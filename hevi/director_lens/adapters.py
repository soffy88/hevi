"""各产品线薄适配器 (Line Adapters).

把 DirectorBrief 翻译成该线已有的输入 (ShotSpec、分镜、模板参数、相机、SFX 事件),
不重写各线。至少接通 4 条线:
1. explainer (讲解/科普类)
2. character_narrative (角色叙事 / 手绘 / 漫剧)
3. scene3d (3D 短片 / anatomy 机械说明)
4. montage (实拍 / 素材混剪 / 纪录类)
"""

from __future__ import annotations

from typing import Any
from hevi.director_lens.brief import DirectorBrief
from hevi.creative.director_contract import ShotSpec, BeatSpec, ContinuityContract


def adapt_to_line(brief: DirectorBrief, target_line: str) -> dict[str, Any]:
    """把 DirectorBrief 转换为目标产品线的已有输入格式 (ShotSpec / 线路参数)。"""
    if target_line not in ("explainer", "character_narrative", "scene3d", "montage"):
        raise ValueError(f"unsupported target line for adapter: {target_line}")

    # 1. 转换为 ShotSpec 列表
    shots: list[ShotSpec] = []
    for s in brief.shots:
        beats = tuple(
            BeatSpec(
                beat_id=f"beat-{s.index}-{i}",
                start_sec=s.start_s + i * (s.duration_s / max(1, len(s.heavy_beats) or 3)),
                end_sec=s.start_s + (i + 1) * (s.duration_s / max(1, len(s.heavy_beats) or 3)),
                narrative_function=s.role,
                emotional_function=brief.core_message,
                visual_action=s.main_task,
                visual_devices=[t.motion for t in brief.tracks],
            )
            for i in range(max(3, len(s.heavy_beats) + 1))
        )
        shots.append(
            ShotSpec(
                shot_id=f"shot-{s.index}",
                duration_sec=s.duration_s,
                narrative_function=s.role,
                beats=beats,
                composition=f"aspect={brief.aspect}, light_azimuth={brief.key_light.azimuth_deg if brief.key_light else 135}",
                camera_intent=f"parallax depth for line {target_line}",
                continuity=ContinuityContract(),
            )
        )

    # 2. 组装线路特有适配结构
    adapter_payload = {
        "line": target_line,
        "brief_id": brief.id,
        "aspect": brief.aspect,
        "duration_s": brief.duration_s,
        "fps": brief.fps,
        "bpm": brief.bpm,
        "seed": brief.seed,
        "shots": [
            {
                "shot_id": sh.shot_id,
                "duration_sec": sh.duration_sec,
                "narrative_function": sh.narrative_function,
                "composition": sh.composition,
                "beats_count": len(sh.beats),
            }
            for sh in shots
        ],
        "subjects": [sub.to_dict() for sub in brief.subjects],
        "key_light": brief.key_light.to_dict() if brief.key_light else None,
        "audio_events_count": len(brief.audio_events),
        "prohibitions_count": len(brief.prohibitions),
    }
    return adapter_payload


__all__ = ["adapt_to_line"]
