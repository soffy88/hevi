"""Tests for the cyber-xiaoya-live graft (A1-A6 gates, B1-B4 fake contracts)."""

import pytest

from hevi.capabilities import danmaku_route_schema as b2
from hevi.capabilities import danmaku_router_gate as a2
from hevi.capabilities import koubo_segment_discipline_gate as a6
from hevi.capabilities import list_capabilities
from hevi.capabilities import live_action_priority_gate as a4
from hevi.capabilities import live_gift_batch_schema as b3
from hevi.capabilities import live_gift_vip_gate as a3
from hevi.capabilities import live_stage_contract as b4
from hevi.capabilities import omnivoice_live_wire_note as a5
from hevi.capabilities import vidu_live_session_gate as a1
from hevi.capabilities import vidu_live_session_schema as b1
from hevi.capabilities.errors import CapabilityError

EXPECTED_NAMES = {
    "qa.vidu_live_session_gate",
    "qa.danmaku_router_gate",
    "qa.live_gift_vip_gate",
    "qa.live_action_priority_gate",
    "qa.omnivoice_live_wire_note",
    "qa.koubo_segment_discipline_gate",
    "video.vidu_live_session_schema",
    "video.danmaku_route_schema",
    "video.live_gift_batch_schema",
    "video.live_stage_contract",
}


def test_all_ten_registered() -> None:
    names = {cap.name for cap in list_capabilities()}
    assert names >= EXPECTED_NAMES
    assert len(names) == len(list_capabilities())


# --- A1: Vidu live session gate ---


def _a1_claim(**overrides):
    claim = {
        "session_kind": "component",
        "model": "vidu-s2",
        "rtc_mode": "managed",
        "declares_cloud_rendered": True,
        "declares_key_required": True,
        "avatar": {"kind": "avatar_id", "value": "avatar-001"},
    }
    claim.update(overrides)
    return claim


def test_a1_managed_component_session_passes() -> None:
    report = a1.check_vidu_live_session(_a1_claim())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False
    assert report["rtc_mode"] == "managed"


def test_a1_customer_rtc_and_image_uri_pass() -> None:
    report = a1.check_vidu_live_session(
        _a1_claim(
            rtc_mode="customer",
            avatar={"kind": "image_uri", "value": "https://example.invalid/host.png"},
        )
    )
    assert report["verdict"] == "pass"


def test_a1_async_job_masquerading_as_live_fails() -> None:
    report = a1.check_vidu_live_session(_a1_claim(session_kind="reference_to_video"))
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "session_kind_not_component"


def test_a1_local_render_and_free_run_fail() -> None:
    assert a1.check_vidu_live_session(_a1_claim(local_rendered=True))["verdict"] == "fail"
    assert a1.check_vidu_live_session(_a1_claim(claims_free=True))["verdict"] == "fail"


def test_a1_key_embedding_and_missing_key_declaration_fail() -> None:
    assert a1.check_vidu_live_session(_a1_claim(key_material_present=True))["verdict"] == "fail"
    assert a1.check_vidu_live_session(_a1_claim(declares_key_required=False))["verdict"] == "fail"


def test_a1_cost_and_balance_need_sources() -> None:
    assert a1.check_vidu_live_session(_a1_claim(cost_per_second=0.02))["verdict"] == "fail"
    assert (
        a1.check_vidu_live_session(
            _a1_claim(cost_per_second=0.02, cost_source="unverified_readme")
        )["verdict"]
        == "pass"
    )
    assert a1.check_vidu_live_session(_a1_claim(minimum_balance_credits=45))["verdict"] == "fail"
    assert (
        a1.check_vidu_live_session(
            _a1_claim(minimum_balance_credits=45, declares_balance_unverified=True)
        )["verdict"]
        == "pass"
    )


def test_a1_model_rtc_and_avatar_failures() -> None:
    assert a1.check_vidu_live_session(_a1_claim(model="vidu-q3"))["verdict"] == "fail"
    assert a1.check_vidu_live_session(_a1_claim(rtc_mode="p2p"))["verdict"] == "fail"
    assert (
        a1.check_vidu_live_session(_a1_claim(avatar={"kind": "live2d", "value": "x"}))["verdict"]
        == "fail"
    )
    assert a1.check_vidu_live_session("not a dict")["verdict"] == "fail"


# --- A2: danmaku router gate ---


def _a2_claim(**overrides):
    claim = {
        "has_priority_queue": True,
        "batch_limit": 14,
        "has_command_confirm": True,
        "has_command_dismiss": True,
        "drop_words": ["banned-word"],
        "speaker_side_banned_words": ["smoking-word"],
        "reply_interval_ms": 3000,
        "max_replies_per_round": 2,
        "collector_source": "public_web_websocket",
    }
    claim.update(overrides)
    return claim


def test_a2_full_router_passes() -> None:
    report = a2.check_danmaku_router(_a2_claim())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False
    assert report["batch_limit"] == 14


def test_a2_missing_pieces_fail() -> None:
    assert a2.check_danmaku_router(_a2_claim(has_priority_queue=False))["verdict"] == "fail"
    assert a2.check_danmaku_router(_a2_claim(has_command_confirm=False))["verdict"] == "fail"
    assert a2.check_danmaku_router(_a2_claim(has_command_dismiss=False))["verdict"] == "fail"
    assert a2.check_danmaku_router(_a2_claim(drop_words=[]))["verdict"] == "fail"
    assert a2.check_danmaku_router(_a2_claim(speaker_side_banned_words=[]))["verdict"] == "fail"
    assert a2.check_danmaku_router(_a2_claim(reply_interval_ms=None))["verdict"] == "fail"


def test_a2_batch_and_reply_bounds_fail() -> None:
    assert a2.check_danmaku_router(_a2_claim(batch_limit=15))["verdict"] == "fail"
    assert a2.check_danmaku_router(_a2_claim(batch_limit=0))["verdict"] == "fail"
    assert a2.check_danmaku_router(_a2_claim(max_replies_per_round=3))["verdict"] == "fail"
    assert a2.check_danmaku_router(_a2_claim(max_replies_per_round=0))["verdict"] == "fail"
    assert a2.check_danmaku_router(_a2_claim(collector_source="scraper-x"))["verdict"] == "fail"


def test_a2_third_party_collector_needs_risk_declaration() -> None:
    claim = _a2_claim(collector_source="third_party_collector")
    assert a2.check_danmaku_router(claim)["verdict"] == "fail"
    claim = _a2_claim(collector_source="third_party_collector", declares_collector_risk=True)
    assert a2.check_danmaku_router(claim)["verdict"] == "pass"
    claim = _a2_claim(
        collector_source="third_party_collector",
        declares_collector_risk=True,
        declares_no_login_needed=True,
    )
    assert a2.check_danmaku_router(claim)["verdict"] == "fail"


def test_a2_non_object_fails() -> None:
    assert a2.check_danmaku_router(None)["verdict"] == "fail"


# --- A3: live gift and VIP gate ---


def _a3_claim(**overrides):
    claim = {
        "batch_window_seconds": 6,
        "trigger_people": 4,
        "trigger_diamonds": 50,
        "max_items_per_batch": 12,
        "max_batches_per_minute": 2,
        "vip_threshold_diamonds": 99,
        "vip_cooldown_seconds": 30,
    }
    claim.update(overrides)
    return claim


def test_a3_full_gift_plan_passes() -> None:
    report = a3.check_live_gift_vip(_a3_claim())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False
    assert report["vip_threshold_diamonds"] == 99


def test_a3_member_welcome_needs_both_declarations() -> None:
    assert a3.check_live_gift_vip(_a3_claim(member_welcome=True))["verdict"] == "fail"
    assert (
        a3.check_live_gift_vip(
            _a3_claim(
                member_welcome=True,
                declares_once_per_session=True,
                declares_never_interrupt_song=True,
            )
        )["verdict"]
        == "pass"
    )
    assert (
        a3.check_live_gift_vip(_a3_claim(member_welcome=True, declares_once_per_session=True))[
            "verdict"
        ]
        == "fail"
    )


def test_a3_batch_bounds_fail() -> None:
    assert a3.check_live_gift_vip(_a3_claim(max_items_per_batch=13))["verdict"] == "fail"
    assert a3.check_live_gift_vip(_a3_claim(max_batches_per_minute=3))["verdict"] == "fail"
    assert a3.check_live_gift_vip(_a3_claim(batch_window_seconds=0))["verdict"] == "fail"
    assert a3.check_live_gift_vip(_a3_claim(trigger_people=0))["verdict"] == "fail"


def test_a3_vip_threshold_and_cooldown_required() -> None:
    assert a3.check_live_gift_vip(_a3_claim(vip_threshold_diamonds=None))["verdict"] == "fail"
    assert a3.check_live_gift_vip(_a3_claim(vip_cooldown_seconds=None))["verdict"] == "fail"


def test_a3_conversion_needs_source() -> None:
    assert a3.check_live_gift_vip(_a3_claim(diamond_to_currency=0.1))["verdict"] == "fail"
    assert (
        a3.check_live_gift_vip(
            _a3_claim(diamond_to_currency=0.1, conversion_source="platform_console")
        )["verdict"]
        == "pass"
    )
    assert a3.check_live_gift_vip("not a dict")["verdict"] == "fail"


# --- A4: live action priority gate ---


def _a4_claim(**overrides):
    claim = {
        "priority_order": ["vip", "manual", "choreo", "danmaku"],
        "same_level_fifo": True,
        "choreo_group_interval_seconds": 2,
        "choreo_gap_seconds": 15,
    }
    claim.update(overrides)
    return claim


def test_a4_four_level_order_passes() -> None:
    report = a4.check_live_action_priority(_a4_claim())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False
    assert report["priority_order"] == ["vip", "manual", "choreo", "danmaku"]


def test_a4_reversed_or_missing_level_fails() -> None:
    assert (
        a4.check_live_action_priority(
            _a4_claim(priority_order=["danmaku", "choreo", "manual", "vip"])
        )["verdict"]
        == "fail"
    )
    assert (
        a4.check_live_action_priority(_a4_claim(priority_order=["vip", "manual", "danmaku"]))[
            "verdict"
        ]
        == "fail"
    )
    assert (
        a4.check_live_action_priority(
            _a4_claim(priority_order=["vip", "manual", "choreo", "danmaku", "auto"])
        )["verdict"]
        == "fail"
    )


def test_a4_fifo_and_intervals_required() -> None:
    assert a4.check_live_action_priority(_a4_claim(same_level_fifo=False))["verdict"] == "fail"
    assert (
        a4.check_live_action_priority(_a4_claim(choreo_group_interval_seconds=None))["verdict"]
        == "fail"
    )
    assert a4.check_live_action_priority(_a4_claim(choreo_gap_seconds=None))["verdict"] == "fail"
    assert a4.check_live_action_priority(None)["verdict"] == "fail"


# --- A5: OmniVoice live wiring note ---


def _a5_claim(**overrides):
    claim = {
        "service_kind": "gradio",
        "service_port": 9877,
        "gpu_required": True,
        "hot_voice_warmup": True,
        "cache_gc": True,
        "vram_watchdog": True,
    }
    claim.update(overrides)
    return claim


def _auth(kind="own"):
    return {
        "voice_id": "host-voice",
        "authorization_kind": kind,
        "evidence_ref": "consent-record-001",
    }


def test_a5_full_wiring_passes() -> None:
    report = a5.check_omnivoice_live_wire(_a5_claim())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False
    assert report["service_port"] == 9877


def test_a5_missing_wiring_pieces_fail() -> None:
    assert a5.check_omnivoice_live_wire(_a5_claim(service_port=8080))["verdict"] == "fail"
    assert a5.check_omnivoice_live_wire(_a5_claim(gpu_required=False))["verdict"] == "fail"
    assert a5.check_omnivoice_live_wire(_a5_claim(hot_voice_warmup=False))["verdict"] == "fail"
    assert a5.check_omnivoice_live_wire(_a5_claim(cache_gc=False))["verdict"] == "fail"
    assert a5.check_omnivoice_live_wire(_a5_claim(vram_watchdog=False))["verdict"] == "fail"
    assert a5.check_omnivoice_live_wire(_a5_claim(weights_included=True))["verdict"] == "fail"
    assert a5.check_omnivoice_live_wire(_a5_claim(sample_rate_hz=16000))["verdict"] == "fail"


def test_a5_clone_requests_intercepted() -> None:
    assert a5.check_omnivoice_live_wire(_a5_claim(kind="clone"))["verdict"] == "fail"
    assert a5.check_omnivoice_live_wire(_a5_claim(clone_voice=True))["verdict"] == "fail"
    assert (
        a5.check_omnivoice_live_wire(_a5_claim(voice_prompt={"source": "reference_audio"}))[
            "verdict"
        ]
        == "fail"
    )


def test_a5_authorized_own_voice_passes_clone_check() -> None:
    report = a5.check_omnivoice_live_wire(_a5_claim(kind="clone", voice_authorization=_auth()))
    assert report["verdict"] == "pass"
    report = a5.check_omnivoice_live_wire(
        _a5_claim(
            kind="clone",
            voice_authorization={"voice_id": "host-voice", "authorization_kind": "own"},
        )
    )
    assert report["verdict"] == "fail"


def test_a5_non_object_fails() -> None:
    assert a5.check_omnivoice_live_wire("not a dict")["verdict"] == "fail"


# --- A6: koubo segmentation discipline gate ---


def _a6_claim(**overrides):
    claim = {
        "protected_tokens": [
            "url",
            "email",
            "version",
            "time",
            "decimal",
            "percent",
            "english_word",
        ],
        "segments_ordered": True,
        "no_sentence_break": True,
        "per_segment_tts": True,
        "feed_order": "sequential",
        "declares_separate_output": True,
    }
    claim.update(overrides)
    return claim


def test_a6_full_discipline_passes() -> None:
    report = a6.check_koubo_segment_discipline(_a6_claim())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False
    assert len(report["protected_tokens"]) == 7


def test_a6_missing_protected_token_fails() -> None:
    assert (
        a6.check_koubo_segment_discipline(
            _a6_claim(protected_tokens=["url", "email", "version", "time", "decimal", "percent"])
        )["verdict"]
        == "fail"
    )
    assert (
        a6.check_koubo_segment_discipline(
            _a6_claim(
                protected_tokens=[
                    "url",
                    "email",
                    "version",
                    "time",
                    "decimal",
                    "percent",
                    "english_word",
                    "emoji",
                ]
            )
        )["verdict"]
        == "fail"
    )
    assert a6.check_koubo_segment_discipline(_a6_claim(protected_tokens=None))["verdict"] == "fail"


def test_a6_order_and_feed_rules_fail() -> None:
    assert a6.check_koubo_segment_discipline(_a6_claim(segments_ordered=False))["verdict"] == "fail"
    assert (
        a6.check_koubo_segment_discipline(_a6_claim(no_sentence_break=False))["verdict"] == "fail"
    )
    assert a6.check_koubo_segment_discipline(_a6_claim(per_segment_tts=False))["verdict"] == "fail"
    assert a6.check_koubo_segment_discipline(_a6_claim(feed_order="parallel"))["verdict"] == "fail"
    assert (
        a6.check_koubo_segment_discipline(_a6_claim(declares_separate_output=False))["verdict"]
        == "fail"
    )
    assert a6.check_koubo_segment_discipline([])["verdict"] == "fail"


# --- B1: Vidu live session schema ---


def _b1_plan(**overrides):
    plan = {
        "model": "vidu-s2",
        "session_kind": "component",
        "avatar": {"kind": "avatar_id", "value": "avatar-001"},
        "actions": [{"library_id": 0}, {"library_id": 3}],
        "rtc": {"mode": "managed", "recording": True},
    }
    plan.update(overrides)
    return plan


def test_b1_contract_passes() -> None:
    contract = b1.compile_vidu_live_session(_b1_plan())
    assert contract["executed_here"] is False
    assert contract["live_started"] is False
    assert contract["output_file"] is None
    assert contract["rtc_mode"] == "managed"
    assert contract["actions"] == 2


def test_b1_key_material_refused() -> None:
    with pytest.raises(CapabilityError):
        b1.compile_vidu_live_session(_b1_plan(api_key="sk-secret"))
    with pytest.raises(CapabilityError):
        b1.compile_vidu_live_session(_b1_plan(rtc={"mode": "managed", "token": "tok-secret"}))


def test_b1_shape_and_execution_failures() -> None:
    with pytest.raises(CapabilityError):
        b1.compile_vidu_live_session(_b1_plan(model="vidu-q3"))
    with pytest.raises(CapabilityError):
        b1.compile_vidu_live_session(_b1_plan(session_kind="reference_to_video"))
    with pytest.raises(CapabilityError):
        b1.compile_vidu_live_session(_b1_plan(executed_here=True))
    with pytest.raises(CapabilityError):
        b1.compile_vidu_live_session(_b1_plan(live_started=True))
    with pytest.raises(CapabilityError):
        b1.compile_vidu_live_session(_b1_plan(avatar={"kind": "live2d", "value": "x"}))
    with pytest.raises(CapabilityError):
        b1.compile_vidu_live_session(_b1_plan(actions=[{"library_id": -1}]))
    with pytest.raises(CapabilityError):
        b1.compile_vidu_live_session(_b1_plan(rtc={"mode": "p2p"}))
    with pytest.raises(CapabilityError):
        b1.compile_vidu_live_session("not a dict")


# --- B2: danmaku route schema ---


def _b2_plan(**overrides):
    plan = {
        "batch": {"max": 14, "read_per_batch": 1},
        "priority_queue": True,
        "commands": {"confirm": True, "dismiss": True},
        "filters": {
            "drop_words": ["banned-word"],
            "speaker_side_banned_words": ["smoking-word"],
        },
        "collector": {"source": "public_web_websocket"},
        "reply": {"interval_ms": 3000, "max_replies_per_round": 2},
    }
    plan.update(overrides)
    return plan


def test_b2_contract_passes() -> None:
    contract = b2.compile_danmaku_route(_b2_plan())
    assert contract["executed_here"] is False
    assert contract["routing_ran"] is False
    assert contract["output_file"] is None
    assert contract["batch_max"] == 14


def test_b2_third_party_collector_needs_risk() -> None:
    with pytest.raises(CapabilityError):
        b2.compile_danmaku_route(_b2_plan(collector={"source": "third_party_collector"}))
    contract = b2.compile_danmaku_route(
        _b2_plan(collector={"source": "third_party_collector", "declares_risk": True})
    )
    assert contract["collector_source"] == "third_party_collector"


def test_b2_shape_and_execution_failures() -> None:
    with pytest.raises(CapabilityError):
        b2.compile_danmaku_route(_b2_plan(batch={"max": 15, "read_per_batch": 1}))
    with pytest.raises(CapabilityError):
        b2.compile_danmaku_route(_b2_plan(priority_queue=False))
    with pytest.raises(CapabilityError):
        b2.compile_danmaku_route(_b2_plan(commands={"confirm": True, "dismiss": False}))
    with pytest.raises(CapabilityError):
        b2.compile_danmaku_route(
            _b2_plan(filters={"drop_words": [], "speaker_side_banned_words": ["x"]})
        )
    with pytest.raises(CapabilityError):
        b2.compile_danmaku_route(_b2_plan(reply={"interval_ms": 3000, "max_replies_per_round": 3}))
    with pytest.raises(CapabilityError):
        b2.compile_danmaku_route(_b2_plan(executed_here=True))
    with pytest.raises(CapabilityError):
        b2.compile_danmaku_route(_b2_plan(collector={"source": "unknown"}))
    with pytest.raises(CapabilityError):
        b2.compile_danmaku_route(None)


# --- B3: live gift batch schema ---


def _b3_plan(**overrides):
    plan = {
        "batch": {
            "window_seconds": 6,
            "trigger_people": 4,
            "trigger_diamonds": 50,
            "max_items": 12,
            "max_per_minute": 2,
        },
        "vip": {"threshold_diamonds": 99, "cooldown_seconds": 30, "face_display": True},
        "member_welcome": {
            "enabled": True,
            "once_per_session": True,
            "never_interrupt_song": True,
        },
        "stats": {"panels": ["gift_diamonds", "vidu_credits"]},
    }
    plan.update(overrides)
    return plan


def test_b3_contract_passes() -> None:
    contract = b3.compile_live_gift_batch(_b3_plan())
    assert contract["executed_here"] is False
    assert contract["gifts_received"] is False
    assert contract["output_file"] is None
    assert contract["vip_threshold_diamonds"] == 99
    assert contract["stat_panels"] == ["gift_diamonds", "vidu_credits"]


def test_b3_bounds_and_welcome_failures() -> None:
    with pytest.raises(CapabilityError):
        b3.compile_live_gift_batch(
            _b3_plan(
                batch={
                    "window_seconds": 6,
                    "trigger_people": 4,
                    "trigger_diamonds": 50,
                    "max_items": 13,
                    "max_per_minute": 2,
                }
            )
        )
    with pytest.raises(CapabilityError):
        b3.compile_live_gift_batch(
            _b3_plan(
                batch={
                    "window_seconds": 6,
                    "trigger_people": 4,
                    "trigger_diamonds": 50,
                    "max_items": 12,
                    "max_per_minute": 3,
                }
            )
        )
    with pytest.raises(CapabilityError):
        b3.compile_live_gift_batch(
            _b3_plan(
                member_welcome={
                    "enabled": True,
                    "once_per_session": False,
                    "never_interrupt_song": True,
                }
            )
        )
    with pytest.raises(CapabilityError):
        b3.compile_live_gift_batch(_b3_plan(stats={"panels": ["gift_diamonds", "revenue"]}))
    with pytest.raises(CapabilityError):
        b3.compile_live_gift_batch(_b3_plan(diamond_to_currency=0.1))
    with pytest.raises(CapabilityError):
        b3.compile_live_gift_batch(_b3_plan(executed_here=True))
    with pytest.raises(CapabilityError):
        b3.compile_live_gift_batch(
            _b3_plan(vip={"threshold_diamonds": 0, "cooldown_seconds": 30, "face_display": True})
        )


# --- B4: live stage contract ---


def _b4_plan(**overrides):
    plan = {
        "zones": ["quick_commands", "song_queue", "reference_images", "recording", "stats_panel"],
        "quick_commands": [{"label": "wave", "action": "wave_hand"}],
        "song_queue": {"enabled": True},
        "reference_images": {"enabled": True, "declares_identity_unchanged": True},
        "recording": {"server_side": True, "manual_fetch": True},
        "stats_panel": {"draggable": True, "reset_on_double_click": True},
    }
    plan.update(overrides)
    return plan


def test_b4_contract_passes() -> None:
    contract = b4.compile_live_stage_contract(_b4_plan())
    assert contract["executed_here"] is False
    assert contract["page_built"] is False
    assert contract["output_file"] is None
    assert contract["zones"] == sorted(
        ["quick_commands", "song_queue", "reference_images", "recording", "stats_panel"]
    )
    assert contract["quick_commands"] == 1


def test_b4_zones_and_identity_failures() -> None:
    with pytest.raises(CapabilityError):
        b4.compile_live_stage_contract(
            _b4_plan(zones=["quick_commands", "song_queue", "reference_images", "recording"])
        )
    with pytest.raises(CapabilityError):
        b4.compile_live_stage_contract(
            _b4_plan(
                zones=[
                    "quick_commands",
                    "song_queue",
                    "reference_images",
                    "recording",
                    "stats_panel",
                    "chat",
                ]
            )
        )
    with pytest.raises(CapabilityError):
        b4.compile_live_stage_contract(
            _b4_plan(reference_images={"enabled": True, "declares_identity_unchanged": False})
        )
    with pytest.raises(CapabilityError):
        b4.compile_live_stage_contract(_b4_plan(quick_commands=[]))
    with pytest.raises(CapabilityError):
        b4.compile_live_stage_contract(_b4_plan(page_built=True))
    with pytest.raises(CapabilityError):
        b4.compile_live_stage_contract(_b4_plan(executed_here=True))
    with pytest.raises(CapabilityError):
        b4.compile_live_stage_contract("not a dict")
