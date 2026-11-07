"""Tests for model.vidogrid_pricing_registration (registration only).

Free-tier facts from the VidoGrid public pages read 2026-11-02
(read-only, not signed in, no generation run). No network, no key,
no spend. Unverified items must stay 'unverified'; invented prices
and invented free models are refused; the record goes stale after
30 days.
"""

import copy

from hevi.capabilities import registry as registry_mod
from hevi.capabilities.vidogrid_pricing_registration import (
    VIDOGRID_FREE_MODELS,
    VIDOGRID_PAY_PER_USE,
    check_vidogrid_pricing_registration,
    vidogrid_pricing_record,
)


def _codes(report):
    return [issue["code"] for issue in report["issues"]]


def test_canonical_record_passes():
    record = vidogrid_pricing_record()
    report = check_vidogrid_pricing_registration(record, today="2026-11-02")
    assert report["ok"], report["issues"]
    assert report["issues"] == []


def test_free_model_table_complete():
    record = vidogrid_pricing_record()
    assert len(record["free_models"]) == len(VIDOGRID_FREE_MODELS) == 10
    keys = {(e["model"], e["variant"]) for e in record["free_models"]}
    assert ("Veo 3.1 Fast", "HD") in keys
    assert ("Veo 3.1 Fast", "Full HD") in keys
    assert ("Veo 3.1 Lite", "HD") in keys
    assert ("Veo 3.1 Lite", "Full HD") in keys
    assert ("Grok Imagine Video 1.5 Lite", "all 10 variants") in keys
    assert ("Vela AI", "image") in keys
    assert ("Nano Banana Pro", "image") in keys
    assert ("Nano Banana 2.1", "image") in keys
    assert ("Nano Banana 2 Lite", "image") in keys
    assert ("Grok Image", "image") in keys
    # Paid-only models must never appear in the free table.
    free_models = {e["model"] for e in record["free_models"]}
    assert "Omni 1.1 Flash" not in free_models
    assert "Grok Imagine Video 1.5" not in free_models
    assert "GPT Image 2.5" not in free_models
    # Vela daily free limit is recorded, not dropped.
    vela = [e for e in record["free_models"] if e["model"] == "Vela AI"][0]
    assert "10 free generations per day" in vela["note"]
    # Free-plan limits are recorded.
    assert record["free_plan"]["price_usd"] == 0
    assert "one video at a time" in record["free_plan"]["limits"]
    assert "no video extension" in record["free_plan"]["limits"]
    assert record["free_plan"]["fast_mode_logo_removal_included"] is True


def test_pay_per_use_table_complete():
    record = vidogrid_pricing_record()
    assert len(record["pay_per_use_credits"]) == len(VIDOGRID_PAY_PER_USE) == 10
    by_key = {(e["model"], e["variant"]): e for e in record["pay_per_use_credits"]}
    assert by_key[("Veo 3.1 Fast", "HD")]["credits"] == 4
    assert by_key[("Veo 2", "video")]["credits"] == 20
    assert by_key[("Veo 3.1", "Full HD")]["credits"] == 100
    assert by_key[("Omni 1.1 Flash", "all 5 variants")]["credits"] == 24
    grok = by_key[("Grok Imagine Video 1.5", "all 9 variants")]
    assert (grok["credits_min"], grok["credits_max"]) == (8, 99)
    assert by_key[("Grok Imagine Video 1.5 Lite", "most variants")]["credits_from"] == 2
    assert record["credit_rate"] == {
        "usd": 1,
        "credits": 200,
        "note": "displayed bonus rate (100 + 100%); struck-through base shown as $10 = 1,000 credits",
    }
    assert record["minimum_top_up_usd"] == 10
    assert record["credits_never_expire"] is True
    assert record["failed_renders_free"] is True


def test_paid_only_model_listed_free_is_refused():
    record = vidogrid_pricing_record()
    record["free_models"].append(
        {"model": "Omni 1.1 Flash", "variant": "HD", "note": "invented"}
    )
    report = check_vidogrid_pricing_registration(record, today="2026-11-02")
    assert not report["ok"]
    assert "paid_only_model_listed_free" in _codes(report)


def test_unknown_free_model_is_refused():
    record = vidogrid_pricing_record()
    record["free_models"].append(
        {"model": "Veo 3.1", "variant": "HD", "note": "invented free tier"}
    )
    report = check_vidogrid_pricing_registration(record, today="2026-11-02")
    assert not report["ok"]
    assert "unknown_free_model" in _codes(report)


def test_missing_free_model_is_refused():
    record = vidogrid_pricing_record()
    record["free_models"] = [
        e for e in record["free_models"] if e["model"] != "Grok Image"
    ]
    report = check_vidogrid_pricing_registration(record, today="2026-11-02")
    assert not report["ok"]
    assert "free_model_missing" in _codes(report)


def test_changed_price_is_refused():
    record = vidogrid_pricing_record()
    for entry in record["pay_per_use_credits"]:
        if entry["model"] == "Veo 3.1 Fast" and entry["variant"] == "HD":
            entry["credits"] = 3
    report = check_vidogrid_pricing_registration(record, today="2026-11-02")
    assert not report["ok"]
    assert "price_value_changed" in _codes(report)


def test_unknown_price_tier_is_refused():
    record = vidogrid_pricing_record()
    record["pay_per_use_credits"].append(
        {"model": "Seedance 2.5", "variant": "1080p", "credits": 50}
    )
    report = check_vidogrid_pricing_registration(record, today="2026-11-02")
    assert not report["ok"]
    assert "unknown_price_tier" in _codes(report)


def test_changed_credit_rate_is_refused():
    record = vidogrid_pricing_record()
    record["credit_rate"]["credits"] = 100
    report = check_vidogrid_pricing_registration(record, today="2026-11-02")
    assert not report["ok"]
    assert "credit_rate_changed" in _codes(report)


def test_missing_source_is_refused():
    record = vidogrid_pricing_record()
    record["source"] = ""
    report = check_vidogrid_pricing_registration(record, today="2026-11-02")
    assert not report["ok"]
    assert "price_source_missing" in _codes(report)


def test_missing_date_is_refused():
    record = vidogrid_pricing_record()
    record["price_as_of"] = "  "
    report = check_vidogrid_pricing_registration(record, today="2026-11-02")
    assert not report["ok"]
    assert "price_date_missing" in _codes(report)


def test_credential_must_not_be_stored():
    record = vidogrid_pricing_record()
    record["api_key"] = "x-api-key-value"
    report = check_vidogrid_pricing_registration(record, today="2026-11-02")
    assert not report["ok"]
    assert "credential_must_not_be_stored" in _codes(report)


def test_unverified_fields_must_stay_unverified():
    record = vidogrid_pricing_record()
    record["unverified"]["logo_on_free_outputs"] = "no logo"
    report = check_vidogrid_pricing_registration(record, today="2026-11-02")
    assert not report["ok"]
    assert "unverified_field_overstated" in _codes(report)
    record = vidogrid_pricing_record()
    assert record["unverified"] == {
        "logo_on_free_outputs": "unverified",
        "free_queue_rules": "unverified",
        "free_tier_api_rate_limits": "unverified",
        "logged_in_daily_counters": "unverified",
    }


def test_monthly_passes_table_is_refused():
    record = vidogrid_pricing_record()
    record["monthly_passes"] = [{"pass": "Veo Max", "price_usd": 20}]
    report = check_vidogrid_pricing_registration(record, today="2026-11-02")
    assert not report["ok"]
    assert "monthly_passes_must_not_be_registered" in _codes(report)
    assert "monthly_passes_note" in record


def test_stale_after_30_days():
    record = vidogrid_pricing_record()
    report = check_vidogrid_pricing_registration(record, today="2026-12-15")
    assert not report["ok"]
    assert "price_stale_recheck" in _codes(report)
    fresh = check_vidogrid_pricing_registration(record, today="2026-12-02")
    assert fresh["ok"], fresh["issues"]


def test_non_object_record_is_refused():
    report = check_vidogrid_pricing_registration("not a record")
    assert not report["ok"]
    assert _codes(report) == ["record_not_object"]


def test_record_must_stay_unverified():
    record = vidogrid_pricing_record()
    record["verified"] = True
    report = check_vidogrid_pricing_registration(record, today="2026-11-02")
    assert not report["ok"]
    assert "record_must_stay_unverified" in _codes(report)


def test_capability_is_registered():
    import hevi.capabilities  # noqa: F401  (registers on import)

    assert registry_mod.contains("model.vidogrid_pricing_registration")
    cap = registry_mod.resolve("model.vidogrid_pricing_registration")
    assert cap.line == "model"
    assert cap.has_media_output is False


def test_check_never_raises_on_bad_input():
    for bad in (None, [], 42, {"free_models": "nope"}):
        report = check_vidogrid_pricing_registration(copy.deepcopy(bad))
        assert report["ok"] is False
        assert report["issues"]
