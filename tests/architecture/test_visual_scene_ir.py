"""P0.5 — VisualSceneIR invariants (§49 V1–V6).

V1  same input            -> same scene hash
V2  same scene + same time -> same frame identity
V3  different time        -> expected animation state
V4  different asset       -> different scene/render identity
V5  invalid scene         -> deterministic rejection
V6  unsupported component -> explicit failure

The rejection tests are the interesting half. A scene that constructs but renders blank
is worse than one that refuses to build: it passes a file-existence check and fails at
the E2E gate, three modules downstream, with a symptom that points nowhere near the
cause. So each way a scene can be well-formed-but-unrenderable is pinned here.
"""

from __future__ import annotations

from fractions import Fraction

import pytest
from pydantic import ValidationError

from hevi.production.visual_scene_ir import (
    AnimationSpec,
    BackgroundSpec,
    Keyframe,
    LayoutMode,
    TransformSpec,
    VisualElement,
    VisualElementType,
    VisualSceneIR,
)


def _scene(**overrides) -> VisualSceneIR:
    """A minimal valid scene: one fading text element."""
    base: dict = {
        "scene_id": "scene-1",
        "width": 1080,
        "height": 1920,
        "duration_ms": 2000,
        "fps": 30,
        "background": BackgroundSpec(color="#0B1220"),
        "elements": (
            VisualElement(
                element_id="title",
                element_type=VisualElementType.TEXT,
                x=140.0,
                y=900.0,
                width=800.0,
                height=120.0,
                content={"text": "Hello", "font_size": 44},
            ),
        ),
        "animations": (
            AnimationSpec(
                animation_id="fade-in",
                element_id="title",
                property="opacity",
                keyframes=(Keyframe(time_ms=0, value=0.0), Keyframe(time_ms=1000, value=1.0)),
                start_ms=0,
                end_ms=1000,
                easing="linear",
            ),
        ),
    }
    base.update(overrides)
    return VisualSceneIR(**base)


# ------------------------------------------------------------------ V1


def test_v1_same_input_yields_same_scene_hash():
    assert _scene().content_hash() == _scene().content_hash()


def test_v1_metadata_is_excluded_from_the_hash():
    """Provenance must not change frame identity.

    Metadata records who authored the scene and which intent produced it. If it were
    hashed, every annotation would invalidate the render cache and force a re-render of
    identical pixels.
    """
    assert _scene(metadata={"author": "director", "beat": 3}).content_hash() == (
        _scene().content_hash()
    )


def test_v1_element_order_is_preserved_in_the_hash():
    """Emission order is load-bearing and the hash keeps it.

    In CSS, elements sharing a ``z_index`` paint in DOM order. Two scenes with the same
    elements at the same ``z_index`` but swapped order render *differently* -- b over a
    instead of a over b -- so they must not share a cache entry.

    Sorting by ``(z_index, element_id)`` was considered and rejected: it would make the
    two tied-order variants collide, because the sort would re-canonicalise them to the
    same sequence. The accepted cost is a spurious cache *miss* when a compiler reorders
    elements with distinct z_index. A miss costs a re-render; a collision serves the
    wrong pixels. Correctness wins.
    """
    a = VisualElement(element_id="a", element_type=VisualElementType.SHAPE,
                      content={"fill": "#ffffff"}, z_index=0)
    b = VisualElement(element_id="b", element_type=VisualElementType.SHAPE,
                      content={"fill": "#000000"}, z_index=0)
    assert (
        _scene(elements=(a, b), animations=()).content_hash()
        != _scene(elements=(b, a), animations=()).content_hash()
    )


def test_v1_z_index_change_is_a_semantic_change():
    a = VisualElement(element_id="a", element_type=VisualElementType.SHAPE,
                      content={"fill": "#ffffff"}, z_index=1)
    b = VisualElement(element_id="b", element_type=VisualElementType.SHAPE,
                      content={"fill": "#000000"}, z_index=2)
    reordered = _scene(elements=(b, a), animations=()).content_hash()
    assert _scene(elements=(a, b), animations=()).content_hash() != reordered


# ------------------------------------------------------------------ V2


def test_v2_same_scene_and_time_yields_same_frame_identity():
    scene = _scene()
    assert scene.frame_identity(500) == _scene().frame_identity(500)


def test_v2_different_time_yields_different_frame_identity():
    scene = _scene()
    assert scene.frame_identity(0) != scene.frame_identity(1000)


# ------------------------------------------------------------------ V3


@pytest.mark.parametrize(
    ("time_ms", "expected"),
    [(0, 0.0), (250, 0.25), (500, 0.5), (1000, 1.0)],
)
def test_v3_animation_state_is_linear_between_keyframes(time_ms, expected):
    assert _scene().state_at(time_ms)["opacity"] == pytest.approx(expected)


def test_v3_state_is_clamped_outside_the_animation_range():
    scene = _scene()
    assert scene.state_at(-500)["opacity"] == pytest.approx(0.0)
    assert scene.state_at(9999)["opacity"] == pytest.approx(1.0)


def test_v3_easing_is_honoured():
    """ease_in accelerates: at the midpoint it is below linear."""
    eased = _scene(
        animations=(
            AnimationSpec(
                animation_id="a",
                element_id="title",
                property="opacity",
                keyframes=(Keyframe(time_ms=0, value=0.0), Keyframe(time_ms=1000, value=1.0)),
                start_ms=0,
                end_ms=1000,
                easing="ease_in",
            ),
        )
    )
    assert eased.state_at(500)["opacity"] == pytest.approx(0.25)


def test_v3_unknown_easing_degrades_to_linear():
    """An easing typo must not abort a render that is otherwise well-formed."""
    scene = _scene(
        animations=(
            AnimationSpec(
                animation_id="a",
                element_id="title",
                property="opacity",
                keyframes=(Keyframe(time_ms=0, value=0.0), Keyframe(time_ms=1000, value=1.0)),
                start_ms=0,
                end_ms=1000,
                easing="wobble_literally_made_up",
            ),
        )
    )
    assert scene.state_at(500)["opacity"] == pytest.approx(0.5)


def test_v3_state_at_covers_every_animation():
    """The whole animation state, not one property.

    A renderer given a single property would re-derive the rest, and two renderers
    would re-derive it differently -- which is the divergence the IR exists to stop.
    """
    scene = _scene(
        animations=(
            AnimationSpec(animation_id="a1", element_id="title", property="opacity",
                          keyframes=(Keyframe(time_ms=0, value=0.0), Keyframe(time_ms=100, value=1.0)),
                          start_ms=0, end_ms=100),
            AnimationSpec(animation_id="a2", element_id="title", property="y",
                          keyframes=(Keyframe(time_ms=0, value=0.0), Keyframe(time_ms=100, value=100.0)),
                          start_ms=0, end_ms=100),
        )
    )
    assert set(scene.state_at(50)) == {"opacity", "y"}


# ------------------------------------------------------------------ V4


def test_v4_different_asset_yields_different_scene_hash():
    """V4. A different source must not share a cache entry with the original."""
    text = _scene()
    image = _scene(
        elements=(
            VisualElement(element_id="title", element_type=VisualElementType.IMAGE,
                          width=800.0, height=120.0, content={"uri": "/tmp/a.png"}),
        ),
        animations=(),
    )
    assert image.content_hash() != text.content_hash()


def test_v4_asset_uri_change_yields_different_frame_identity():
    def with_uri(uri: str) -> VisualSceneIR:
        return _scene(
            elements=(
                VisualElement(element_id="img", element_type=VisualElementType.IMAGE,
                              width=100.0, height=100.0, content={"uri": uri}),
            ),
            animations=(),
        )

    assert with_uri("/a.png").frame_identity(0) != with_uri("/b.png").frame_identity(0)


def test_v4_renderer_independent_of_layout_mode_identity():
    """Layout mode is part of scene semantics, so it must be in the hash.

    If it were not, a FLOW scene and an ABSOLUTE scene with identical elements would
    collide in the cache and one would be served in place of the other.
    """
    assert (
        _scene(layout_mode=LayoutMode.FLOW).content_hash()
        != _scene(layout_mode=LayoutMode.ABSOLUTE).content_hash()
    )


# ------------------------------------------------------------------ V5


@pytest.mark.parametrize(
    ("case", "build"),
    [
        (
            "empty_text",
            lambda: VisualElement(element_id="t", element_type=VisualElementType.TEXT,
                                  content={"text": "   "}),
        ),
        (
            "media_without_source",
            lambda: VisualElement(element_id="i", element_type=VisualElementType.IMAGE,
                                  content={}),
        ),
        (
            "element_without_content",
            lambda: VisualElement(element_id="s", element_type=VisualElementType.SHAPE),
        ),
        (
            "zero_scale_transform",
            lambda: VisualElement(element_id="s", element_type=VisualElementType.SHAPE,
                                  content={"fill": "#fff"},
                                  transform=TransformSpec(scale_x=0.0)),
        ),
        (
            "opacity_out_of_range",
            lambda: VisualElement(element_id="s", element_type=VisualElementType.SHAPE,
                                  content={"fill": "#fff"}, opacity=1.5),
        ),
        (
            "single_keyframe",
            lambda: AnimationSpec(animation_id="a", element_id="t", property="opacity",
                                  keyframes=(Keyframe(time_ms=0, value=0.0),),
                                  start_ms=0, end_ms=10),
        ),
        (
            "unordered_keyframes",
            lambda: AnimationSpec(animation_id="a", element_id="t", property="opacity",
                                  keyframes=(Keyframe(time_ms=9, value=1.0),
                                             Keyframe(time_ms=0, value=0.0)),
                                  start_ms=0, end_ms=10),
        ),
        (
            "keyframe_outside_range",
            lambda: AnimationSpec(animation_id="a", element_id="t", property="opacity",
                                  keyframes=(Keyframe(time_ms=0, value=0.0),
                                             Keyframe(time_ms=99, value=1.0)),
                                  start_ms=0, end_ms=10),
        ),
        (
            "empty_animation_range",
            lambda: AnimationSpec(animation_id="a", element_id="t", property="opacity",
                                  keyframes=(Keyframe(time_ms=0, value=0.0),
                                             Keyframe(time_ms=5, value=1.0)),
                                  start_ms=5, end_ms=5),
        ),
    ],
)
def test_v5_invalid_scene_is_rejected_deterministically(case, build):
    with pytest.raises(ValidationError):
        build()
    # Deterministic means the same input fails the same way every time.
    with pytest.raises(ValidationError):
        build()


def test_v5_orphan_animation_reference_is_rejected():
    """An animation naming an element that does not exist would render nothing."""
    with pytest.raises(ValidationError, match="ORPHAN"):
        _scene(
            animations=(
                AnimationSpec(animation_id="a", element_id="ghost", property="opacity",
                              keyframes=(Keyframe(time_ms=0, value=0.0),
                                         Keyframe(time_ms=5, value=1.0)),
                              start_ms=0, end_ms=5),
            )
        )


def test_v5_duplicate_element_ids_are_rejected():
    dup = VisualElement(element_id="same", element_type=VisualElementType.SHAPE,
                        content={"fill": "#fff"})
    with pytest.raises(ValidationError, match="DUPLICATE_ELEMENT_ID"):
        _scene(elements=(dup, dup))


def test_v5_animation_beyond_scene_duration_is_rejected():
    """It would not render, and nothing downstream would notice."""
    with pytest.raises(ValidationError, match="EXCEEDS_DURATION"):
        _scene(
            duration_ms=500,
            animations=(
                AnimationSpec(animation_id="a", element_id="title", property="opacity",
                              keyframes=(Keyframe(time_ms=0, value=0.0),
                                         Keyframe(time_ms=1000, value=1.0)),
                              start_ms=0, end_ms=1000),
            ),
        )


def test_v5_non_positive_dimensions_are_rejected():
    for kwargs in ({"width": 0}, {"height": -1080}):
        with pytest.raises(ValidationError):
            _scene(**kwargs)


# ------------------------------------------------------------------ V6


def test_v6_bad_colour_is_an_explicit_failure():
    """Colour is interpolated into CSS/SVG by the adapter.

    An unvalidated value becomes an unstyled frame that still passes a file-exists
    check. Rejecting it here turns a silent visual defect into a build error.
    """
    with pytest.raises(ValidationError, match="BACKGROUND_BAD_COLOUR"):
        BackgroundSpec(color="cornflowerblue")


@pytest.mark.parametrize("colour", ["#fff", "#ffffff", "#ffffffff"])
def test_v6_valid_colour_forms_are_accepted(colour):
    assert BackgroundSpec(color=colour).color == colour


def test_v6_unknown_element_type_is_an_explicit_failure():
    """An unsupported component fails loudly instead of rendering nothing."""
    with pytest.raises(ValidationError):
        VisualElement(element_id="x", element_type="HOLOGRAM", content={"a": 1})


def test_v6_unsupported_component_does_not_silently_degrade():
    """A typo'd component kind must not fall back to a default element.

    Falling back would produce a scene that constructs, passes validation, and renders
    without the intended content -- the exact failure mode §6 of the acceptance matrix
    forbids.
    """
    with pytest.raises(ValidationError):
        _scene(
            elements=(
                VisualElement(element_id="x", element_type="TABEL",
                              content={"rows": []}),
            )
        )


# ------------------------------------------------------- temporal discipline


def test_all_temporal_values_are_integer_milliseconds():
    """§17. A float here reintroduces the drift TimelineIR was migrated to remove."""
    scene = _scene()
    assert isinstance(scene.duration_ms, int)
    for animation in scene.animations:
        assert isinstance(animation.start_ms, int)
        assert isinstance(animation.end_ms, int)
        assert all(isinstance(k.time_ms, int) for k in animation.keyframes)


def test_negative_time_is_rejected():
    with pytest.raises(ValidationError):
        Keyframe(time_ms=-1, value=0.0)


# ------------------------------------------------- fps contract (closure §11)


def test_fps_is_required_and_not_defaulted():
    """A default frame rate is a trapdoor.

    The first E2E run rendered 30fps for a 24fps request because the compiler read
    ``metadata["fps"]`` and fell back when absent. Making ``fps`` required removes the
    fallback entirely: a scene that forgets to state its frame rate fails to build
    instead of silently rendering at 30.
    """
    with pytest.raises(ValidationError):
        _scene_without_fps()


def _scene_without_fps():
    from hevi.production.visual_scene_ir import VisualSceneIR

    return VisualSceneIR(
        scene_id="s", width=100, height=100, duration_ms=1000,
        elements=(
            VisualElement(element_id="t", element_type=VisualElementType.TEXT,
                          content={"text": "x"}),
        ),
    )


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [
        (24, "24"), ("24", "24"), (Fraction(30000, 1001), "30000/1001"),
        ("30000/1001", "30000/1001"), (29.97, "2997/100"),
    ],
)
def test_fps_is_exact_and_normalised(supplied, expected):
    """Exact, because 30000/1001 rounded to 30 changes the artifact's identity.

    The float form is accepted for convenience but normalised immediately: 29.97 as a
    float is 29.969999999999999, and that value would go into the scene hash.
    """
    from hevi.production.visual_scene_ir import VisualSceneIR

    scene = VisualSceneIR(
        scene_id="s", fps=supplied, width=100, height=100, duration_ms=1000,
        elements=(VisualElement(element_id="t", element_type=VisualElementType.TEXT,
                                content={"text": "x"}),),
    )
    assert str(scene.fps) == expected


def test_fps_hash_is_stable_across_input_forms():
    """The rational, not the literal you typed, is what gets hashed."""
    from hevi.production.visual_scene_ir import VisualSceneIR

    def build(fps):
        return VisualSceneIR(
            scene_id="s", fps=fps, width=100, height=100, duration_ms=1000,
            elements=(VisualElement(element_id="t", element_type=VisualElementType.TEXT,
                                    content={"text": "x"}),),
        )

    assert build("30000/1001").content_hash() == build(Fraction(30000, 1001)).content_hash()


@pytest.mark.parametrize("bad", [0, -30, "not-a-rate", "30/", True])
def test_fps_rejects_non_positive_and_unparseable(bad):
    from hevi.production.visual_scene_ir import VisualSceneIR

    with pytest.raises(ValidationError):
        VisualSceneIR(scene_id="s", fps=bad, width=100, height=100, duration_ms=1000,
                      elements=(VisualElement(element_id="t",
                                              element_type=VisualElementType.TEXT,
                                              content={"text": "x"}),))


def test_changing_fps_changes_scene_identity():
    """fps is part of the render identity, so it belongs in the hash."""
    assert _scene(fps=24).content_hash() != _scene(fps=30).content_hash()
