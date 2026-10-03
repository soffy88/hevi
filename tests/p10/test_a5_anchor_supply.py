"""A5 production: anchor supply composition (R-P10-01 made structural)."""

import pytest

from hevi.audio.tts_alignment import AudioAlignment, PhraseTiming, WordTiming
from hevi.studio.anchor_resolver import (
    Anchor,
    AnchorOrphaned,
    compose_film_anchor,
    dialogue_end_map,
    resolve_anchor,
)

# 两句:line1 尾静音到 1800ms(词 100-1800),line2 从 2496 开始
ALIGNMENT = AudioAlignment(
    "voice", 4728,
    (WordTiming("For", 100, 400), WordTiming("a", 450, 900),
     WordTiming("century", 950, 1800), WordTiming("It", 2500, 2800),
     WordTiming("bends", 2850, 3300), WordTiming("light", 3350, 3800)),
    (PhraseTiming("scene1.line001", 0, 2496), PhraseTiming("scene1.line002", 2496, 4728)),
)


def test_a5_dialogue_end_map_uses_last_word_not_audio_end():
    ends = dialogue_end_map(ALIGNMENT)
    # 末词结束,不是 2496/4728 的音频段尾
    assert ends == {"scene1.line001": 1800, "scene1.line002": 3800}
    assert dialogue_end_map(AudioAlignment("x", 100)) == {}


def test_a5_line_local_then_film_global():
    anchor = Anchor("AFTER_DIALOGUE", "scene1.line001", offset_ms=500)
    local = resolve_anchor(anchor, dialogue_end_ms=dialogue_end_map(ALIGNMENT), fps=30)
    assert local.time_ms == 2300

    film = compose_film_anchor(anchor, alignment=ALIGNMENT, segment_offset_ms=6464, fps=30,
                               alignment_hash="align:r1", timeline_hash="tl:1")
    assert film.time_ms == 6464 + 2300 == 8764
    assert film.frame == round(8764 * 30 / 1000)
    assert film.evidence == ("align:r1", "tl:1")  # evidence 透传,可审计


def test_a5_film_anchor_differs_from_local_by_offset():
    anchor = Anchor("AFTER_DIALOGUE", "scene1.line002", offset_ms=500)
    local = resolve_anchor(anchor, dialogue_end_ms=dialogue_end_map(ALIGNMENT), fps=25)
    film = compose_film_anchor(anchor, alignment=ALIGNMENT, segment_offset_ms=1000, fps=25)
    assert film.time_ms - local.time_ms == 1000


def test_a5_orphan_target_still_fails_loud():
    anchor = Anchor("AFTER_DIALOGUE", "scene1.missing", offset_ms=0)
    with pytest.raises(AnchorOrphaned):
        compose_film_anchor(anchor, alignment=ALIGNMENT, segment_offset_ms=0, fps=30)


def test_a5_supply_change_moves_film_anchor_only():
    """R-P10-01:换 TTS/语速 → film 锚点移动,而非把 local 值当 film 值用。"""
    anchor = Anchor("AFTER_DIALOGUE", "scene1.line001", offset_ms=500)
    first = compose_film_anchor(anchor, alignment=ALIGNMENT, segment_offset_ms=6464, fps=30)
    faster = AudioAlignment(
        "voice", 3600,
        (WordTiming("For", 100, 320), WordTiming("a", 340, 700), WordTiming("century", 720, 1500)),
        (PhraseTiming("scene1.line001", 0, 2000),),
    )
    second = compose_film_anchor(anchor, alignment=faster, segment_offset_ms=6464, fps=30)
    assert second.time_ms < first.time_ms
    assert second.time_ms == 6464 + 2000