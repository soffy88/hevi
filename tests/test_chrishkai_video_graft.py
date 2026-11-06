"""Tests for the ChrisHKAI-Video graft (A1-A9 gates, B1-B4 fake contracts)."""

import pytest

from hevi.capabilities import blender_cycles_render_schema as b4
from hevi.capabilities import creator_color_legibility_gate as a5
from hevi.capabilities import creator_intro_film_schema as b2
from hevi.capabilities import creator_intro_review_gate as a7
from hevi.capabilities import creator_pacing_gate as a4
from hevi.capabilities import creator_story_gate as a1
from hevi.capabilities import film_ledger_difference_gate as a6
from hevi.capabilities import list_capabilities
from hevi.capabilities import platform_safe_zone_schema as b3
from hevi.capabilities import story_text_probe_gate as a8
from hevi.capabilities import third_party_portrait_authorization_gate as a9
from hevi.capabilities import toy_clearance_gate as a3
from hevi.capabilities import vinyl_toy_character_schema as b1
from hevi.capabilities import vinyl_toy_identity_gate as a2
from hevi.capabilities.errors import CapabilityError

EXPECTED_NAMES = {
    "qa.creator_story_gate",
    "qa.vinyl_toy_identity_gate",
    "qa.toy_clearance_gate",
    "qa.creator_pacing_gate",
    "qa.creator_color_legibility_gate",
    "qa.film_ledger_difference_gate",
    "qa.creator_intro_review_gate",
    "qa.story_text_probe_gate",
    "qa.third_party_portrait_authorization_gate",
    "video.vinyl_toy_character_schema",
    "video.creator_intro_film_schema",
    "video.platform_safe_zone_schema",
    "video.blender_cycles_render_schema",
}


def test_all_thirteen_registered() -> None:
    names = {c.name for c in list_capabilities()}
    assert names >= EXPECTED_NAMES


# --- A1: creator story gate ---


def _a1_story(**overrides):
    story = {
        "person": {"who": "a maker", "why": "to teach", "for_whom": "beginners"},
        "directions": [
            {"hook": "a toy waves", "payoff": "the maker smiles"},
            {"hook": "a lemon rolls in", "payoff": "the toy catches it", "recommended": True},
            {"hook": "a wall of posts", "payoff": "the maker points at one"},
        ],
        "numbers": [{"value": 120, "source": "public profile", "read_at": "2026-11-06"}],
        "turning_points": [{"event": "first video", "invented": False}],
    }
    story.update(overrides)
    return story


def test_a1_pass() -> None:
    assert a1.check_creator_story(_a1_story())["verdict"] == "pass"


def test_a1_not_object() -> None:
    assert a1.check_creator_story("nope")["verdict"] == "fail"


def test_a1_person_missing() -> None:
    story = _a1_story()
    del story["person"]
    assert a1.check_creator_story(story)["issues"][0]["code"] == "person_missing"


def test_a1_person_incomplete() -> None:
    story = _a1_story()
    del story["person"]["for_whom"]
    assert a1.check_creator_story(story)["issues"][0]["code"] == "person_incomplete"


def test_a1_directions_not_three() -> None:
    story = _a1_story(directions=_a1_story()["directions"][:2])
    assert a1.check_creator_story(story)["issues"][0]["code"] == "directions_not_three"


def test_a1_direction_missing_payoff() -> None:
    story = _a1_story()
    del story["directions"][0]["payoff"]
    assert a1.check_creator_story(story)["issues"][0]["code"] == "direction_missing_axis"


def test_a1_no_recommendation() -> None:
    story = _a1_story()
    for direction in story["directions"]:
        direction.pop("recommended", None)
    assert a1.check_creator_story(story)["issues"][0]["code"] == "recommendation_not_single"


def test_a1_two_recommendations() -> None:
    story = _a1_story()
    story["directions"][0]["recommended"] = True
    assert a1.check_creator_story(story)["issues"][0]["code"] == "recommendation_not_single"


def test_a1_number_missing_source() -> None:
    story = _a1_story()
    del story["numbers"][0]["source"]
    assert a1.check_creator_story(story)["issues"][0]["code"] == "number_missing_source"


def test_a1_number_missing_read_time() -> None:
    story = _a1_story()
    del story["numbers"][0]["read_at"]
    assert a1.check_creator_story(story)["issues"][0]["code"] == "number_missing_read_time"


def test_a1_invented_turning_point() -> None:
    story = _a1_story(turning_points=[{"event": "made up", "invented": True}])
    assert a1.check_creator_story(story)["issues"][0]["code"] == "invented_turning_point"


# --- A2: vinyl toy identity gate ---


def _a2_toy(**overrides):
    toy = {
        "avatar_confirmed": True,
        "redraw_avatar": False,
        "body_follows_source": True,
        "on_screen_toys": 1,
        "flat_sticker_present": False,
        "fixed_features": {"bow": {"position": "on the head"}, "scar": {"position": "left cheek"}},
    }
    toy.update(overrides)
    return toy


def test_a2_pass() -> None:
    assert a2.check_vinyl_toy_identity(_a2_toy())["verdict"] == "pass"


def test_a2_not_object() -> None:
    assert a2.check_vinyl_toy_identity(None)["verdict"] == "fail"


def test_a2_avatar_not_confirmed() -> None:
    assert (
        a2.check_vinyl_toy_identity(_a2_toy(avatar_confirmed=False))["issues"][0]["code"]
        == "avatar_not_confirmed"
    )


def test_a2_avatar_redrawn() -> None:
    assert (
        a2.check_vinyl_toy_identity(_a2_toy(redraw_avatar=True))["issues"][0]["code"]
        == "avatar_redrawn"
    )


def test_a2_body_not_source() -> None:
    assert (
        a2.check_vinyl_toy_identity(_a2_toy(body_follows_source=False))["issues"][0]["code"]
        == "body_not_source"
    )


def test_a2_toy_count_wrong() -> None:
    assert (
        a2.check_vinyl_toy_identity(_a2_toy(on_screen_toys=2))["issues"][0]["code"]
        == "toy_count_wrong"
    )


def test_a2_sticker_and_toy_together() -> None:
    assert (
        a2.check_vinyl_toy_identity(_a2_toy(flat_sticker_present=True))["issues"][0]["code"]
        == "sticker_and_toy_together"
    )


def test_a2_feature_missing_position() -> None:
    assert (
        a2.check_vinyl_toy_identity(_a2_toy(fixed_features={"bow": {}}))["issues"][0]["code"]
        == "feature_missing_position"
    )


def test_a2_fixed_features_missing() -> None:
    assert (
        a2.check_vinyl_toy_identity(_a2_toy(fixed_features={}))["issues"][0]["code"]
        == "fixed_features_missing"
    )


# --- A3: toy clearance gate ---


def _a3_clearance(**overrides):
    clearance = {
        "frames_checked": True,
        "max_penetration_pct": 4.0,
        "max_height_excess_fraction": 0.1,
        "light_touch": False,
        "forced_keep": False,
    }
    clearance.update(overrides)
    return clearance


def test_a3_pass() -> None:
    assert a3.check_toy_clearance(_a3_clearance())["verdict"] == "pass"


def test_a3_light_touch_warns_not_fails() -> None:
    result = a3.check_toy_clearance(_a3_clearance(light_touch=True))
    assert result["verdict"] == "pass"
    assert result["warnings"][0]["code"] == "light_touch"


def test_a3_not_object() -> None:
    assert a3.check_toy_clearance(7)["verdict"] == "fail"


def test_a3_portrait_clearance_claim() -> None:
    assert (
        a3.check_toy_clearance(_a3_clearance(is_portrait_clearance=True))["issues"][0]["code"]
        == "portrait_clearance_claim"
    )


def test_a3_frames_not_checked() -> None:
    assert (
        a3.check_toy_clearance(_a3_clearance(frames_checked=False))["issues"][0]["code"]
        == "frames_not_checked"
    )


def test_a3_penetration_fail() -> None:
    assert (
        a3.check_toy_clearance(_a3_clearance(max_penetration_pct=15.0))["issues"][0]["code"]
        == "penetration_fail"
    )


def test_a3_penetration_below_line_passes() -> None:
    assert a3.check_toy_clearance(_a3_clearance(max_penetration_pct=14.9))["verdict"] == "pass"


def test_a3_height_excess_fail() -> None:
    assert (
        a3.check_toy_clearance(_a3_clearance(max_height_excess_fraction=0.26))["issues"][0]["code"]
        == "height_excess_fail"
    )


def test_a3_force_not_noted() -> None:
    assert (
        a3.check_toy_clearance(_a3_clearance(forced_keep=True))["issues"][0]["code"]
        == "force_not_noted"
    )


def test_a3_force_noted_passes() -> None:
    assert (
        a3.check_toy_clearance(_a3_clearance(forced_keep=True, force_noted=True))["verdict"]
        == "pass"
    )


# --- A4: creator pacing gate ---


def _a4_pacing(**overrides):
    pacing = {
        "max_silence_bars": 1.5,
        "toy_height_fraction": 0.2,
        "first_hook_second": 2.0,
        "subtitles": [
            {"text": "hello", "duration_s": 2.0, "min_readable_s": 1.5},
            {"text": "world", "duration_s": 3.0, "min_readable_s": 2.0},
        ],
    }
    pacing.update(overrides)
    return pacing


def test_a4_pass() -> None:
    assert a4.check_creator_pacing(_a4_pacing())["verdict"] == "pass"


def test_a4_not_object() -> None:
    assert a4.check_creator_pacing([])["verdict"] == "fail"


def test_a4_silence_too_long() -> None:
    assert (
        a4.check_creator_pacing(_a4_pacing(max_silence_bars=2.5))["issues"][0]["code"]
        == "silence_too_long"
    )


def test_a4_silence_at_limit_passes() -> None:
    assert a4.check_creator_pacing(_a4_pacing(max_silence_bars=2.0))["verdict"] == "pass"


def test_a4_toy_too_small() -> None:
    assert (
        a4.check_creator_pacing(_a4_pacing(toy_height_fraction=0.05))["issues"][0]["code"]
        == "toy_too_small"
    )


def test_a4_no_early_hook() -> None:
    assert (
        a4.check_creator_pacing(_a4_pacing(first_hook_second=3.5))["issues"][0]["code"]
        == "no_early_hook"
    )


def test_a4_subtitle_too_short() -> None:
    pacing = _a4_pacing()
    pacing["subtitles"][0]["duration_s"] = 1.0
    assert a4.check_creator_pacing(pacing)["issues"][0]["code"] == "subtitle_too_short"


def test_a4_subtitles_missing() -> None:
    pacing = _a4_pacing()
    del pacing["subtitles"]
    assert a4.check_creator_pacing(pacing)["issues"][0]["code"] == "subtitles_missing"


# --- A5: creator color legibility gate ---


def _a5_color(**overrides):
    color = {
        "text_contrast": 4.5,
        "toy_area_contrast": 2.0,
        "palette_from_own_images": True,
        "palette_table": {"wall": "#f5e6c8", "toy": "#e4572e"},
        "bw_check_passed": True,
    }
    color.update(overrides)
    return color


def test_a5_pass() -> None:
    assert a5.check_creator_color_legibility(_a5_color())["verdict"] == "pass"


def test_a5_not_object() -> None:
    assert a5.check_creator_color_legibility("red")["verdict"] == "fail"


def test_a5_text_contrast_low() -> None:
    assert (
        a5.check_creator_color_legibility(_a5_color(text_contrast=2.5))["issues"][0]["code"]
        == "text_contrast_low"
    )


def test_a5_toy_contrast_low() -> None:
    assert (
        a5.check_creator_color_legibility(_a5_color(toy_area_contrast=1.2))["issues"][0]["code"]
        == "toy_contrast_low"
    )


def test_a5_palette_not_from_own_images() -> None:
    assert (
        a5.check_creator_color_legibility(_a5_color(palette_from_own_images=False))["issues"][0][
            "code"
        ]
        == "palette_not_from_own_images"
    )


def test_a5_palette_missing() -> None:
    assert (
        a5.check_creator_color_legibility(_a5_color(palette_table={}))["issues"][0]["code"]
        == "palette_missing"
    )


def test_a5_bw_check_failed() -> None:
    assert (
        a5.check_creator_color_legibility(_a5_color(bw_check_passed=False))["issues"][0]["code"]
        == "bw_check_failed"
    )


def test_a5_bw_failed_with_regrade_passes() -> None:
    assert (
        a5.check_creator_color_legibility(_a5_color(bw_check_passed=False, regrade_recorded=True))[
            "verdict"
        ]
        == "pass"
    )


# --- A6: film ledger difference gate ---


def _a6_ledger(**overrides):
    ledger = {
        "delivered_films": ["film-a", "film-b"],
        "new_film": {
            "opening": "toy waves from a shelf",
            "structure": "three beats",
            "signature_move": "lemon roll",
            "palette": "warm cream",
            "sound": "soft synth",
            "ending": "toy bows",
        },
        "differences": {
            "film-a": ["opening", "structure", "signature_move", "palette"],
            "film-b": ["opening", "structure", "signature_move", "palette", "sound", "ending"],
        },
    }
    ledger.update(overrides)
    return ledger


def test_a6_pass() -> None:
    assert a6.check_film_ledger_difference(_a6_ledger())["verdict"] == "pass"


def test_a6_not_object() -> None:
    assert a6.check_film_ledger_difference(None)["verdict"] == "fail"


def test_a6_axes_missing() -> None:
    ledger = _a6_ledger()
    del ledger["new_film"]["ending"]
    assert a6.check_film_ledger_difference(ledger)["issues"][0]["code"] == "axes_missing"


def test_a6_too_similar() -> None:
    ledger = _a6_ledger()
    ledger["differences"]["film-a"] = ["opening", "palette"]
    assert a6.check_film_ledger_difference(ledger)["issues"][0]["code"] == "too_similar"


def test_a6_three_differences_fail() -> None:
    ledger = _a6_ledger()
    ledger["differences"]["film-a"] = ["opening", "palette", "sound"]
    assert a6.check_film_ledger_difference(ledger)["issues"][0]["code"] == "too_similar"


def test_a6_unknown_axis() -> None:
    ledger = _a6_ledger()
    ledger["differences"]["film-a"] = ["opening", "structure", "signature_move", "camera"]
    assert a6.check_film_ledger_difference(ledger)["issues"][0]["code"] == "difference_axis_unknown"


def test_a6_differences_missing() -> None:
    ledger = _a6_ledger()
    del ledger["differences"]["film-b"]
    assert a6.check_film_ledger_difference(ledger)["issues"][0]["code"] == "differences_missing"


# --- A7: creator intro review gate ---


def _a7_review(**overrides):
    review = {
        "film_given": True,
        "brief_given": True,
        "conclusions_given": False,
        "rounds": [
            {"issues_fixed": ["pacing", "subtitle timing"]},
            {"issues_fixed": ["color"]},
        ],
        "verdict": "pass",
        "open_findings": [],
    }
    review.update(overrides)
    return review


def test_a7_pass() -> None:
    assert a7.check_creator_intro_review(_a7_review())["verdict"] == "pass"


def test_a7_not_object() -> None:
    assert a7.check_creator_intro_review("film")["verdict"] == "fail"


def test_a7_conclusions_given() -> None:
    assert (
        a7.check_creator_intro_review(_a7_review(conclusions_given=True))["issues"][0]["code"]
        == "conclusions_given"
    )


def test_a7_film_missing() -> None:
    assert (
        a7.check_creator_intro_review(_a7_review(film_given=False))["issues"][0]["code"]
        == "film_missing"
    )


def test_a7_too_many_rounds() -> None:
    review = _a7_review()
    review["rounds"] = [{"issues_fixed": []}] * 3
    assert a7.check_creator_intro_review(review)["issues"][0]["code"] == "too_many_rounds"


def test_a7_too_many_fixes() -> None:
    review = _a7_review(rounds=[{"issues_fixed": ["a", "b", "c", "d"]}])
    assert a7.check_creator_intro_review(review)["issues"][0]["code"] == "too_many_fixes"


def test_a7_verdict_not_pass() -> None:
    assert (
        a7.check_creator_intro_review(_a7_review(verdict="fail"))["issues"][0]["code"]
        == "review_not_passed"
    )


def test_a7_pass_with_open_findings() -> None:
    assert (
        a7.check_creator_intro_review(_a7_review(open_findings=["unfixed"]))["issues"][0]["code"]
        == "inconsistent_verdict"
    )


# --- A8: story text probe gate ---


def _a8_probe(**overrides):
    probe = {
        "memory_hook": "a lemon toy with no arms",
        "retention_reason": "the toy answers a question",
        "uniqueness": "no other intro uses this toy",
        "binding": "advisory",
    }
    probe.update(overrides)
    return probe


def test_a8_pass() -> None:
    assert a8.check_story_text_probe(_a8_probe())["verdict"] == "pass"


def test_a8_pass_with_false_binding() -> None:
    assert a8.check_story_text_probe(_a8_probe(binding=False))["verdict"] == "pass"


def test_a8_not_object() -> None:
    assert a8.check_story_text_probe(42)["verdict"] == "fail"


def test_a8_probe_incomplete() -> None:
    probe = _a8_probe()
    del probe["retention_reason"]
    assert a8.check_story_text_probe(probe)["issues"][0]["code"] == "probe_incomplete"


def test_a8_probe_claimed_binding() -> None:
    assert (
        a8.check_story_text_probe(_a8_probe(binding="blocking"))["issues"][0]["code"]
        == "probe_claimed_binding"
    )


def test_a8_probe_binding_unclear() -> None:
    probe = _a8_probe()
    del probe["binding"]
    assert a8.check_story_text_probe(probe)["issues"][0]["code"] == "probe_binding_unclear"


# --- A9: third-party portrait authorization gate ---


def test_a9_self_pass() -> None:
    assert (
        a9.check_third_party_portrait_authorization({"creator_is_requester": True})["verdict"]
        == "pass"
    )


def test_a9_third_party_with_evidence_pass() -> None:
    assert (
        a9.check_third_party_portrait_authorization(
            {"creator_is_requester": False, "authorization_evidence": "signed note 2026-11-06"}
        )["verdict"]
        == "pass"
    )


def test_a9_not_object() -> None:
    assert a9.check_third_party_portrait_authorization("me")["verdict"] == "fail"


def test_a9_missing_authorization() -> None:
    assert (
        a9.check_third_party_portrait_authorization({"creator_is_requester": False})["issues"][0][
            "code"
        ]
        == "missing_authorization"
    )


def test_a9_minor_blocked() -> None:
    assert (
        a9.check_third_party_portrait_authorization(
            {"creator_is_requester": True, "creator_is_minor": True}
        )["issues"][0]["code"]
        == "minor_blocked"
    )


def test_a9_minor_blocked_even_with_evidence() -> None:
    assert (
        a9.check_third_party_portrait_authorization(
            {
                "creator_is_requester": False,
                "creator_is_minor": True,
                "authorization_evidence": "signed note",
            }
        )["issues"][0]["code"]
        == "minor_blocked"
    )


# --- B1: vinyl toy character schema ---


def _b1_plan(**overrides):
    plan = {
        "kit": "parts",
        "parts": ["head", "body", "bow"],
        "colors": ["#e4572e", "#f5e6c8"],
        "size": {"height_cm": 12},
    }
    plan.update(overrides)
    return plan


def test_b1_pass() -> None:
    contract = b1.compile_vinyl_toy_character(_b1_plan())
    assert contract["executed_here"] is False
    assert contract["rendered_here"] is False
    assert contract["output_file"] is None
    assert contract["kit"] == "parts"


def test_b1_kits() -> None:
    for kit in ("parts", "pet", "sdf"):
        assert b1.compile_vinyl_toy_character(_b1_plan(kit=kit))["kit"] == kit


def test_b1_not_object() -> None:
    with pytest.raises(CapabilityError):
        b1.compile_vinyl_toy_character("toy")


def test_b1_unknown_kit() -> None:
    with pytest.raises(CapabilityError):
        b1.compile_vinyl_toy_character(_b1_plan(kit="clay"))


def test_b1_asset_field() -> None:
    with pytest.raises(CapabilityError):
        b1.compile_vinyl_toy_character(_b1_plan(toy_json="toy.json"))


def test_b1_avatar_image_field() -> None:
    with pytest.raises(CapabilityError):
        b1.compile_vinyl_toy_character(_b1_plan(avatar_image="avatar.png"))


def test_b1_rendered_claim() -> None:
    with pytest.raises(CapabilityError):
        b1.compile_vinyl_toy_character(_b1_plan(rendered_here=True))


def test_b1_empty_parts() -> None:
    with pytest.raises(CapabilityError):
        b1.compile_vinyl_toy_character(_b1_plan(parts=[]))


# --- B2: creator intro film schema ---


def _b2_plan(**overrides):
    plan = {
        "template": "creator-intro",
        "theme": "x-desktop",
        "story": "a maker introduces himself",
        "segments": ["opening", "toy", "wall", "ending"],
        "sound": "soft synth",
        "duration_s": 30,
        "aspect": "16:9",
        "steps": [
            "environment_check",
            "link_and_framing",
            "research_and_story",
            "toy",
            "storyboard",
            "render",
        ],
    }
    plan.update(overrides)
    return plan


def test_b2_pass() -> None:
    contract = b2.compile_creator_intro_film(_b2_plan())
    assert contract["executed_here"] is False
    assert contract["rendered_here"] is False
    assert contract["output_file"] is None
    assert contract["duration_s"] == 30


def test_b2_vertical_aspect() -> None:
    assert b2.compile_creator_intro_film(_b2_plan(aspect="9:16"))["aspect"] == "9:16"


def test_b2_not_object() -> None:
    with pytest.raises(CapabilityError):
        b2.compile_creator_intro_film(None)


def test_b2_wrong_steps() -> None:
    with pytest.raises(CapabilityError):
        b2.compile_creator_intro_film(_b2_plan(steps=["toy", "render"]))


def test_b2_bad_aspect() -> None:
    with pytest.raises(CapabilityError):
        b2.compile_creator_intro_film(_b2_plan(aspect="1:1"))


def test_b2_duration_out_of_range() -> None:
    with pytest.raises(CapabilityError):
        b2.compile_creator_intro_film(_b2_plan(duration_s=90))


def test_b2_rendered_claim() -> None:
    with pytest.raises(CapabilityError):
        b2.compile_creator_intro_film(_b2_plan(rendered_here=True))


def test_b2_key_field() -> None:
    with pytest.raises(CapabilityError):
        b2.compile_creator_intro_film(_b2_plan(api_key="secret"))


# --- B3: platform safe zone schema ---


def _b3_plan(**overrides):
    plan = {
        "platform": "douyin-mobile",
        "safe_zone": {"top": 120, "bottom": 160, "left": 24, "right": 24},
    }
    plan.update(overrides)
    return plan


def test_b3_pass() -> None:
    contract = b3.compile_platform_safe_zone(_b3_plan())
    assert contract["executed_here"] is False
    assert contract["verified_here"] is False
    assert contract["output_file"] is None


def test_b3_all_platforms() -> None:
    for platform in (
        "x-desktop",
        "x-mobile",
        "douyin-mobile",
        "xhs-mobile",
        "channels-mobile",
        "ig-mobile",
    ):
        assert b3.compile_platform_safe_zone(_b3_plan(platform=platform))["platform"] == platform


def test_b3_not_object() -> None:
    with pytest.raises(CapabilityError):
        b3.compile_platform_safe_zone("zone")


def test_b3_unknown_platform() -> None:
    with pytest.raises(CapabilityError):
        b3.compile_platform_safe_zone(_b3_plan(platform="tiktok-web"))


def test_b3_negative_margin() -> None:
    plan = _b3_plan()
    plan["safe_zone"]["top"] = -10
    with pytest.raises(CapabilityError):
        b3.compile_platform_safe_zone(plan)


def test_b3_missing_margin() -> None:
    plan = _b3_plan()
    del plan["safe_zone"]["bottom"]
    with pytest.raises(CapabilityError):
        b3.compile_platform_safe_zone(plan)


def test_b3_verified_claim() -> None:
    with pytest.raises(CapabilityError):
        b3.compile_platform_safe_zone(_b3_plan(verified_here=True))


# --- B4: Blender Cycles render schema ---


def _b4_plan(**overrides):
    plan = {
        "blender": "5.2",
        "node": "22",
        "python": "3.9",
        "ffmpeg": True,
        "headless_chrome": True,
        "gpu_required": True,
        "device": "CUDA",
        "samples": 128,
        "scale": 1.0,
    }
    plan.update(overrides)
    return plan


def test_b4_pass() -> None:
    contract = b4.compile_blender_cycles_render(_b4_plan())
    assert contract["executed_here"] is False
    assert contract["rendered_here"] is False
    assert contract["output_file"] is None
    assert contract["device"] == "CUDA"


def test_b4_devices() -> None:
    for device in ("OptiX", "CUDA", "HIP", "oneAPI", "Metal"):
        assert b4.compile_blender_cycles_render(_b4_plan(device=device))["device"] == device


def test_b4_not_object() -> None:
    with pytest.raises(CapabilityError):
        b4.compile_blender_cycles_render([])


def test_b4_gpu_not_required() -> None:
    with pytest.raises(CapabilityError):
        b4.compile_blender_cycles_render(_b4_plan(gpu_required=False))


def test_b4_unknown_device() -> None:
    with pytest.raises(CapabilityError):
        b4.compile_blender_cycles_render(_b4_plan(device="CPU"))


def test_b4_missing_ffmpeg() -> None:
    with pytest.raises(CapabilityError):
        b4.compile_blender_cycles_render(_b4_plan(ffmpeg=False))


def test_b4_bad_samples() -> None:
    with pytest.raises(CapabilityError):
        b4.compile_blender_cycles_render(_b4_plan(samples=0))


def test_b4_bad_scale() -> None:
    with pytest.raises(CapabilityError):
        b4.compile_blender_cycles_render(_b4_plan(scale=1.5))


def test_b4_rendered_claim() -> None:
    with pytest.raises(CapabilityError):
        b4.compile_blender_cycles_render(_b4_plan(rendered_here=True))
