"""produce_v2 J/L-cut 偏移纯函数测试 — native 分支与 fallback 共用同一套语义。

seam_offset_ms / native_start_ms 住在 hevi.director.cut_style (produce_v2
两分支运行时懒导入这两个函数; 直接 import produce_v2 在 HEAD 上有既存的
TransitionStrategy 导入断裂, 与本测试无关):
fallback 原先内联的 J=-400ms / L=+400ms / 无风格=0 必须保持不变;
native 分支在此基础上把偏移叠加在 ASR 窗口起点之后,且 clamp >= 0。
"""
from __future__ import annotations

from hevi.director.cut_style import native_start_ms as _native_start_ms
from hevi.director.cut_style import seam_offset_ms as _seam_offset_ms
from hevi.director.pipeline_schemas import SceneScriptDialogueLine, SceneScriptSegment


def _seg(*, camera_movement: str = "", speaker: str = "") -> SceneScriptSegment:
    dialogue = (
        [SceneScriptDialogueLine(character_name=speaker, text="台词")] if speaker else []
    )
    return SceneScriptSegment(camera_movement=camera_movement, dialogue=dialogue)


def test_seam_offset_j_cut_is_negative():
    prev = _seg(camera_movement="静态对话", speaker="王生")
    cur = _seg(camera_movement="峰值轻推", speaker="王生")
    assert _seam_offset_ms(prev, cur) == -400


def test_seam_offset_l_cut_is_positive():
    prev = _seg(camera_movement="静态对话", speaker="王生")
    cur = _seg(camera_movement="反应插入", speaker="")
    assert _seam_offset_ms(prev, cur) == 400


def test_seam_offset_no_style_is_zero():
    prev = _seg(camera_movement="静态对话", speaker="王生")
    cur = _seg(camera_movement="横移", speaker="老道士")
    assert _seam_offset_ms(prev, cur) == 0


def test_seam_offset_missing_segment_is_zero():
    cur = _seg(camera_movement="峰值轻推", speaker="王生")
    assert _seam_offset_ms(None, cur) == 0
    assert _seam_offset_ms(cur, None) == 0
    assert _seam_offset_ms(None, None) == 0


def test_native_start_ms_without_offset_preserves_window():
    # shot starts at 10s, ASR window starts 1.85s into the clip -> 11850ms
    assert _native_start_ms(shot_start_s=10.0, window_start_s=1.85) == 11850


def test_native_start_ms_applies_offset_after_window():
    assert (
        _native_start_ms(shot_start_s=10.0, window_start_s=1.85, seam_offset_ms=-400)
        == 11450
    )
    assert (
        _native_start_ms(shot_start_s=10.0, window_start_s=1.85, seam_offset_ms=400)
        == 12250
    )


def test_native_start_ms_clamps_to_zero():
    # J-cut on the first seconds must not push the cue before t=0.
    assert _native_start_ms(shot_start_s=0.0, window_start_s=0.1, seam_offset_ms=-400) == 0
