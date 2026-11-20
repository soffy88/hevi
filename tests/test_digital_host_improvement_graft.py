"""Tests for the digital-host improvement graft.

Every capability gets a positive case and at least one
negative case. The registration test asserts all seventeen
names are present exactly once. The schema (B) tests assert
fail-closed behaviour: ``compile_*`` returns a contract
declaring ``executed_here`` false and ``output_file`` None on
a well-formed input, and raises ``CapabilityError`` on any
shape violation. No test runs a model, loads a weight file,
reads a live danmaku feed, or starts a stream.
"""

from __future__ import annotations

import pytest

from hevi.capabilities import list_capabilities
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.talkback_edit_gate import check_talkback_edit
from hevi.capabilities.talkback_film_gate import check_talkback_film
from hevi.capabilities.talkback_film_schema import compile_talkback_film
from hevi.capabilities.talkback_model_select_gate import check_talkback_model_select
from hevi.capabilities.xiaoya_avatar_asset_gate import check_xiaoya_avatar_asset
from hevi.capabilities.xiaoya_avatar_schema import compile_xiaoya_avatar
from hevi.capabilities.xiaoya_danmaku_filter_route_gate import (
    check_xiaoya_danmaku_filter_route,
)
from hevi.capabilities.xiaoya_danmaku_queue_gift_gate import check_xiaoya_danmaku_queue_gift
from hevi.capabilities.xiaoya_danmaku_route_schema import compile_xiaoya_danmaku_route
from hevi.capabilities.xiaoya_halfbody_lipsync_gate import check_xiaoya_halfbody_lipsync
from hevi.capabilities.xiaoya_halfbody_lipsync_schema import (
    compile_xiaoya_halfbody_lipsync,
)
from hevi.capabilities.xiaoya_persona_finetune_honesty_gate import (
    check_xiaoya_persona_finetune_honesty,
)
from hevi.capabilities.xiaoya_persona_finetune_schema import (
    compile_xiaoya_persona_finetune,
)
from hevi.capabilities.xiaoya_reconnect_gate import check_xiaoya_reconnect
from hevi.capabilities.xiaoya_topic_pool_gate import check_xiaoya_topic_pool
from hevi.capabilities.xiaoya_topic_pool_schema import compile_xiaoya_topic_pool
from hevi.capabilities.xiaoya_wardrobe_hotswap_gate import check_xiaoya_wardrobe_hotswap

EXPECTED_DIGITAL_HOST_NAMES = {
    "qa.xiaoya_avatar_asset_gate",
    "qa.xiaoya_halfbody_lipsync_gate",
    "qa.xiaoya_danmaku_filter_route_gate",
    "qa.xiaoya_danmaku_queue_gift_gate",
    "qa.xiaoya_topic_pool_gate",
    "qa.xiaoya_wardrobe_hotswap_gate",
    "qa.xiaoya_reconnect_gate",
    "qa.talkback_edit_gate",
    "qa.xiaoya_persona_finetune_honesty_gate",
    "qa.talkback_film_gate",
    "qa.talkback_model_select_gate",
    "video.xiaoya_avatar_schema",
    "video.xiaoya_halfbody_lipsync_schema",
    "video.xiaoya_danmaku_route_schema",
    "video.xiaoya_topic_pool_schema",
    "video.talkback_film_schema",
    "video.xiaoya_persona_finetune_schema",
}


def test_all_digital_host_names_registered():
    found = [c.name for c in list_capabilities() if c.name in EXPECTED_DIGITAL_HOST_NAMES]
    assert sorted(found) == sorted(EXPECTED_DIGITAL_HOST_NAMES)


# ---- A1 avatar asset gate ----


def _good_asset() -> dict:
    return {
        "avatar_key": "xiaoya_e",
        "face_source": "ai_generated",
        "face_source_confirmed": True,
        "motion_source": "ai_generated",
        "is_fixed_host": True,
        "name_used": "小雅",
    }


def test_avatar_asset_pass():
    report = check_xiaoya_avatar_asset(_good_asset())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False


def test_avatar_asset_rejects_unknown_key():
    asset = _good_asset()
    asset["avatar_key"] = "xiaoya_z"
    report = check_xiaoya_avatar_asset(asset)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "unknown_avatar_key"


def test_avatar_asset_rejects_real_person_photo():
    asset = _good_asset()
    asset["face_source"] = "real_person_photo"
    report = check_xiaoya_avatar_asset(asset)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "real_person_portrait_banned"


def test_avatar_asset_rejects_unconfirmed_e_face():
    asset = _good_asset()
    asset["face_source_confirmed"] = False
    report = check_xiaoya_avatar_asset(asset)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "face_source_unconfirmed"


def test_avatar_asset_rejects_wrong_xiaoya():
    asset = _good_asset()
    asset["origin"] = "mneme_xiaoya_practice"
    report = check_xiaoya_avatar_asset(asset)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "wrong_xiaoya"


def test_avatar_asset_rejects_pexels_fixed_host_without_release():
    asset = _good_asset()
    asset["motion_source"] = "pexels"
    asset["model_release"] = False
    report = check_xiaoya_avatar_asset(asset)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "motion_release_gap"


def test_avatar_asset_rejects_banned_name():
    asset = _good_asset()
    asset["name_used"] = "赛博小雅"
    report = check_xiaoya_avatar_asset(asset)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "banned_name"


# ---- A2 half-body lipsync gate ----


def _good_lipsync_report() -> dict:
    return {
        "engine": "wav2lip_onnx_cpu",
        "model_files": {
            "wav2lip_gan_96": True,
            "yoloface_8n": True,
            "silero_vad_v6": True,
        },
        "talk_render_fps": 20.68,
        "realtime_factor_talk": 1.034,
        "lipsync_corr": 0.278,
        "lipsync_lag_frames": -1,
        "sample_duration_s": 23.25,
    }


def test_lipsync_pass():
    report = check_xiaoya_halfbody_lipsync(_good_lipsync_report())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False


def test_lipsync_rejects_other_engine():
    data = _good_lipsync_report()
    data["engine"] = "liveportrait"
    report = check_xiaoya_halfbody_lipsync(data)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "engine_unsupported"


def test_lipsync_rejects_missing_model_file():
    data = _good_lipsync_report()
    data["model_files"]["silero_vad_v6"] = False
    report = check_xiaoya_halfbody_lipsync(data)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "model_files_missing"


def test_lipsync_rejects_placeholder_card():
    data = _good_lipsync_report()
    data["uses_placeholder_card"] = True
    report = check_xiaoya_halfbody_lipsync(data)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "placeholder_not_lipsync"


def test_lipsync_rejects_slow_render():
    data = _good_lipsync_report()
    data["talk_render_fps"] = 12.0
    report = check_xiaoya_halfbody_lipsync(data)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "render_fps_below_bar"


def test_lipsync_rejects_lag_out_of_tolerance():
    data = _good_lipsync_report()
    data["lipsync_lag_frames"] = 5
    report = check_xiaoya_halfbody_lipsync(data)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "lag_out_of_tolerance"


# ---- A3 danmaku filter and route gate ----


def _good_filter_plan() -> dict:
    return {
        "filter_categories": ["低俗擦边", "引流广告", "敏感话题", "辱骂", "收益承诺"],
        "allow_phrases": ["换裙子", "比心"],
        "max_length": 40,
        "dedupe_seconds": 60,
        "routes": ["chat", "wardrobe", "action", "restore"],
        "false_positive_check": True,
    }


def test_filter_route_pass():
    report = check_xiaoya_danmaku_filter_route(_good_filter_plan())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False


def test_filter_route_rejects_missing_category():
    plan = _good_filter_plan()
    plan["filter_categories"] = ["低俗擦边", "引流广告"]
    report = check_xiaoya_danmaku_filter_route(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "filter_category_missing"


def test_filter_route_rejects_empty_allowlist():
    plan = _good_filter_plan()
    plan["allow_phrases"] = []
    report = check_xiaoya_danmaku_filter_route(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "allowlist_missing"


def test_filter_route_rejects_long_max_length():
    plan = _good_filter_plan()
    plan["max_length"] = 200
    report = check_xiaoya_danmaku_filter_route(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "max_length_exceeds_measured"


def test_filter_route_rejects_missing_route():
    plan = _good_filter_plan()
    plan["routes"] = ["chat", "wardrobe"]
    report = check_xiaoya_danmaku_filter_route(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "route_missing"


# ---- A4 danmaku queue and gift gate ----


def _good_queue_plan() -> dict:
    return {
        "policy": "fifo",
        "gift_jumps_queue": False,
        "max_age_seconds": 180,
        "max_size": 200,
        "full_queue_drops_non_gift_first": True,
        "expiry_enabled": True,
    }


def test_queue_gift_pass():
    report = check_xiaoya_danmaku_queue_gift(_good_queue_plan())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False


def test_queue_gift_rejects_unknown_policy():
    plan = _good_queue_plan()
    plan["policy"] = "random"
    report = check_xiaoya_danmaku_queue_gift(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "unknown_policy"


def test_queue_gift_rejects_gift_jump_under_fifo():
    plan = _good_queue_plan()
    plan["gift_jumps_queue"] = True
    report = check_xiaoya_danmaku_queue_gift(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "gift_queue_jump"


def test_queue_gift_rejects_missing_expiry():
    plan = _good_queue_plan()
    plan["expiry_enabled"] = False
    report = check_xiaoya_danmaku_queue_gift(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "expiry_missing"


# ---- A5 topic pool gate ----


def _good_topic_pool() -> dict:
    return {
        "topics": [f"topic {i}" for i in range(105)],
        "repeat_rule": "no_repeat_until_exhausted",
        "survives_reconnect": True,
    }


def test_topic_pool_pass():
    report = check_xiaoya_topic_pool(_good_topic_pool())
    assert report["verdict"] == "pass"
    assert report["topic_count"] == 105


def test_topic_pool_rejects_too_small():
    pool = _good_topic_pool()
    pool["topics"] = pool["topics"][:50]
    report = check_xiaoya_topic_pool(pool)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "topic_pool_too_small"


def test_topic_pool_rejects_wrong_repeat_rule():
    pool = _good_topic_pool()
    pool["repeat_rule"] = "random"
    report = check_xiaoya_topic_pool(pool)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "repeat_rule_wrong"


def test_topic_pool_rejects_reset_on_reconnect():
    pool = _good_topic_pool()
    pool["survives_reconnect"] = False
    report = check_xiaoya_topic_pool(pool)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "pool_resets_on_reconnect"


# ---- A6 wardrobe hot-swap gate ----


def _good_wardrobe() -> dict:
    return {
        "base_avatar": "xiaoya_e",
        "items": [
            {"name": "白T", "aliases": ["白t"], "avatar": "xiaoya_d"},
            {"name": "小雅默认", "aliases": ["默认", "恢复", "复原"], "avatar": "xiaoya_e"},
        ],
        "switch": {
            "swaps_idle_talk_pair": True,
            "restores_to_base": True,
            "crossfade_frames": 8,
        },
    }


def test_wardrobe_pass():
    report = check_xiaoya_wardrobe_hotswap(_good_wardrobe())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False


def test_wardrobe_rejects_wrong_base():
    wardrobe = _good_wardrobe()
    wardrobe["base_avatar"] = "xiaoya_d"
    report = check_xiaoya_wardrobe_hotswap(wardrobe)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "base_avatar_wrong"


def test_wardrobe_rejects_missing_restore():
    wardrobe = _good_wardrobe()
    wardrobe["items"] = [wardrobe["items"][0]]
    report = check_xiaoya_wardrobe_hotswap(wardrobe)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "restore_missing"


def test_wardrobe_rejects_no_crossfade():
    wardrobe = _good_wardrobe()
    wardrobe["switch"]["crossfade_frames"] = 0
    report = check_xiaoya_wardrobe_hotswap(wardrobe)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "crossfade_missing"


# ---- A7 reconnect gate ----


def _good_reconnect_plan() -> dict:
    return {
        "delay_seconds": 3.0,
        "hourly_cap": 6,
        "window_seconds": 3600,
        "resume_speech_present": True,
        "memory_kept": True,
        "silent_after_cap": True,
    }


def test_reconnect_pass():
    report = check_xiaoya_reconnect(_good_reconnect_plan())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False


def test_reconnect_rejects_short_cooldown():
    plan = _good_reconnect_plan()
    plan["delay_seconds"] = 0.5
    report = check_xiaoya_reconnect(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "cooldown_too_short"


def test_reconnect_rejects_high_hourly_cap():
    plan = _good_reconnect_plan()
    plan["hourly_cap"] = 20
    report = check_xiaoya_reconnect(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "hourly_cap_wrong"


def test_reconnect_rejects_memory_loss():
    plan = _good_reconnect_plan()
    plan["memory_kept"] = False
    report = check_xiaoya_reconnect(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "memory_lost"


# ---- A8 talkback edit gate ----


def _good_edit_plan() -> dict:
    return {
        "removes_silence": True,
        "subtitles_aligned": True,
        "inserts_broll": True,
        "single_sentence_re_record": True,
        "full_timeline_rebuild_on_single_fix": False,
    }


def test_talkback_edit_pass():
    report = check_talkback_edit(_good_edit_plan())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False


def test_talkback_edit_rejects_silence_kept():
    plan = _good_edit_plan()
    plan["removes_silence"] = False
    report = check_talkback_edit(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "silence_not_removed"


def test_talkback_edit_rejects_full_rebuild():
    plan = _good_edit_plan()
    plan["full_timeline_rebuild_on_single_fix"] = True
    report = check_talkback_edit(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "single_fix_rebuilds_timeline"


# ---- A9 persona finetune honesty gate ----


def _good_finetune_plan() -> dict:
    return {
        "sft_data_location": "drive",
        "substitute_claimed_equal": False,
        "raw_has_tool_call_markers": True,
        "clean_text_applied": True,
        "weights_present": True,
        "weights_location": "/data/soffy/models/xiaoya",
        "violation_rate_measured": 0.0,
        "violation_rate_basis": "after_clean_text",
        "empty_reply_check": True,
        "mixed_script_check": True,
    }


def _good_substitute_plan() -> dict:
    return {
        "sft_data_location": "drive",
        "substitute_claimed_equal": False,
        "raw_has_tool_call_markers": False,
        "clean_text_applied": True,
        "weights_present": False,
        "substitute": {"model": "llama3.2:3b+persona_prompt"},
    }


def test_finetune_honesty_pass():
    report = check_xiaoya_persona_finetune_honesty(_good_finetune_plan())
    assert report["verdict"] == "pass"
    assert report["mode"] == "finetune"
    assert report["finetune_active"] is True


def test_finetune_honesty_pass_with_honest_substitute():
    report = check_xiaoya_persona_finetune_honesty(_good_substitute_plan())
    assert report["verdict"] == "pass"
    assert report["mode"] == "substitute"
    assert report["finetune_active"] is False


def test_finetune_honesty_rejects_missing_weights_without_substitute():
    plan = _good_substitute_plan()
    plan.pop("substitute")
    report = check_xiaoya_persona_finetune_honesty(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "weights_missing"


def test_finetune_honesty_rejects_substitute_claimed_equal():
    plan = _good_substitute_plan()
    plan["substitute_claimed_equal"] = True
    report = check_xiaoya_persona_finetune_honesty(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "substitute_claimed_equal"


def test_finetune_honesty_rejects_unstripped_markers():
    plan = _good_finetune_plan()
    plan["clean_text_applied"] = False
    report = check_xiaoya_persona_finetune_honesty(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "markers_unstripped"


def test_finetune_honesty_rejects_raw_violation_basis():
    plan = _good_finetune_plan()
    plan["violation_rate_basis"] = "raw"
    report = check_xiaoya_persona_finetune_honesty(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "violation_rate_basis_raw"


# ---- A10 talkback film gate ----


def _good_film_plan() -> dict:
    return {
        "steps": {
            "persona": True,
            "frames": True,
            "talkback": True,
            "edit": True,
            "polish": True,
        },
        "step_order": ["persona", "frames", "talkback", "edit", "polish"],
        "each_step_verifiable": True,
        "single_sentence_fix_rebuilds": False,
    }


def test_talkback_film_pass():
    report = check_talkback_film(_good_film_plan())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False


def test_talkback_film_rejects_missing_step():
    plan = _good_film_plan()
    plan["steps"]["polish"] = False
    report = check_talkback_film(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "step_missing"


def test_talkback_film_rejects_wrong_order():
    plan = _good_film_plan()
    plan["step_order"] = ["talkback", "persona", "frames", "edit", "polish"]
    report = check_talkback_film(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "step_order_wrong"


# ---- A11 model select gate ----


def _good_model_plan() -> dict:
    return {
        "use_case": "daily",
        "model": "wan3.0",
        "low_res_sample_first": True,
        "sample_resolution": "480p",
        "selection_basis": "daily talkback, cheapest stable driver",
    }


def test_model_select_pass():
    report = check_talkback_model_select(_good_model_plan())
    assert report["verdict"] == "pass"
    assert report["model"] == "wan3.0"


def test_model_select_rejects_mismatch():
    plan = _good_model_plan()
    plan["model"] = "seedance2.5"
    report = check_talkback_model_select(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "model_mismatch"


def test_model_select_rejects_skipped_sample():
    plan = _good_model_plan()
    plan["low_res_sample_first"] = False
    report = check_talkback_model_select(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "no_low_res_sample"


def test_model_select_rejects_missing_basis():
    plan = _good_model_plan()
    plan["selection_basis"] = ""
    report = check_talkback_model_select(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "selection_basis_missing"


# ---- B1 avatar schema ----


def _good_avatar_plan() -> dict:
    return {
        "avatar_key": "xiaoya_d",
        "face": {"source": "ai_generated", "confirmed": True},
        "motion_source": "ai_generated",
        "name": "小雅",
        "fixed_host": True,
    }


def test_avatar_schema_pass():
    contract = compile_xiaoya_avatar(_good_avatar_plan())
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["avatar_key"] == "xiaoya_d"


def test_avatar_schema_rejects_unknown_key():
    plan = _good_avatar_plan()
    plan["avatar_key"] = "xiaoya_z"
    with pytest.raises(CapabilityError):
        compile_xiaoya_avatar(plan)


def test_avatar_schema_rejects_real_person_face():
    plan = _good_avatar_plan()
    plan["face"] = {"source": "real_person_photo", "confirmed": True}
    with pytest.raises(CapabilityError):
        compile_xiaoya_avatar(plan)


def test_avatar_schema_rejects_banned_name():
    plan = _good_avatar_plan()
    plan["name"] = "赛博小雅"
    with pytest.raises(CapabilityError):
        compile_xiaoya_avatar(plan)


# ---- B2 half-body lipsync schema ----


def _good_lipsync_plan() -> dict:
    return {
        "engine": "wav2lip_onnx_cpu",
        "model_files": {
            "wav2lip_gan_96": True,
            "yoloface_8n": True,
            "silero_vad_v6": True,
        },
        "fps": 20,
        "realtime_factor": 1.034,
        "lipsync_corr": 0.278,
    }


def test_lipsync_schema_pass():
    contract = compile_xiaoya_halfbody_lipsync(_good_lipsync_plan())
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["engine"] == "wav2lip_onnx_cpu"


def test_lipsync_schema_rejects_other_engine():
    plan = _good_lipsync_plan()
    plan["engine"] = "liveportrait"
    with pytest.raises(CapabilityError):
        compile_xiaoya_halfbody_lipsync(plan)


def test_lipsync_schema_rejects_missing_model_file():
    plan = _good_lipsync_plan()
    plan["model_files"]["yoloface_8n"] = False
    with pytest.raises(CapabilityError):
        compile_xiaoya_halfbody_lipsync(plan)


# ---- B3 danmaku route schema ----


def _good_route_plan() -> dict:
    return {
        "filter_categories": ["低俗擦边", "引流广告", "敏感话题", "辱骂", "收益承诺"],
        "allow_phrases": ["换裙子", "比心"],
        "routes": ["chat", "wardrobe", "action", "restore"],
        "policy": "fifo",
    }


def test_danmaku_route_schema_pass():
    contract = compile_xiaoya_danmaku_route(_good_route_plan())
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["policy"] == "fifo"


def test_danmaku_route_schema_rejects_missing_category():
    plan = _good_route_plan()
    plan["filter_categories"] = ["低俗擦边"]
    with pytest.raises(CapabilityError):
        compile_xiaoya_danmaku_route(plan)


def test_danmaku_route_schema_rejects_unknown_policy():
    plan = _good_route_plan()
    plan["policy"] = "random"
    with pytest.raises(CapabilityError):
        compile_xiaoya_danmaku_route(plan)


# ---- B4 topic pool schema ----


def _good_pool_plan() -> dict:
    return {
        "topics": [f"topic {i}" for i in range(105)],
        "count": 105,
        "repeat_rule": "no_repeat_until_exhausted",
        "survives_reconnect": True,
    }


def test_topic_pool_schema_pass():
    contract = compile_xiaoya_topic_pool(_good_pool_plan())
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["topic_count"] == 105


def test_topic_pool_schema_rejects_count_mismatch():
    plan = _good_pool_plan()
    plan["count"] = 104
    with pytest.raises(CapabilityError):
        compile_xiaoya_topic_pool(plan)


def test_topic_pool_schema_rejects_too_small():
    plan = _good_pool_plan()
    plan["topics"] = plan["topics"][:50]
    plan["count"] = 50
    with pytest.raises(CapabilityError):
        compile_xiaoya_topic_pool(plan)


# ---- B5 talkback film schema ----


def test_talkback_film_schema_pass():
    contract = compile_talkback_film(_good_film_plan())
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["steps"] == ["persona", "frames", "talkback", "edit", "polish"]


def test_talkback_film_schema_rejects_missing_step():
    plan = _good_film_plan()
    plan["steps"]["edit"] = False
    with pytest.raises(CapabilityError):
        compile_talkback_film(plan)


def test_talkback_film_schema_rejects_rebuild():
    plan = _good_film_plan()
    plan["single_sentence_fix_rebuilds"] = True
    with pytest.raises(CapabilityError):
        compile_talkback_film(plan)


# ---- B6 persona finetune schema ----


def _good_finetune_contract_plan() -> dict:
    return {
        "weights_present": True,
        "weights_location": "/data/soffy/models/xiaoya",
        "sft_data_location": "drive",
        "clean_text": True,
    }


def _good_substitute_contract_plan() -> dict:
    return {
        "weights_present": False,
        "sft_data_location": "drive",
        "clean_text": True,
        "substitute": {"model": "llama3.2:3b+persona_prompt", "claimed_equal": False},
    }


def test_finetune_schema_pass():
    contract = compile_xiaoya_persona_finetune(_good_finetune_contract_plan())
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["mode"] == "finetune"
    assert contract["finetune_active"] is True


def test_finetune_schema_pass_with_substitute():
    contract = compile_xiaoya_persona_finetune(_good_substitute_contract_plan())
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["mode"] == "substitute"
    assert contract["finetune_active"] is False


def test_finetune_schema_rejects_weights_without_location():
    plan = _good_finetune_contract_plan()
    plan["weights_location"] = ""
    with pytest.raises(CapabilityError):
        compile_xiaoya_persona_finetune(plan)


def test_finetune_schema_rejects_substitute_claimed_equal():
    plan = _good_substitute_contract_plan()
    plan["substitute"]["claimed_equal"] = True
    with pytest.raises(CapabilityError):
        compile_xiaoya_persona_finetune(plan)
