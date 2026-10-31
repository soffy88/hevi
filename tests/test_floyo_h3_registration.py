"""Tests for the Floyo H3 registration (registration only, no account,
no payment, no promo code, no network, both records unverified)."""

from __future__ import annotations

from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.floyo_h3_registration import (
    FLOYO_MODEL_ID,
    FLOYO_WORKFLOW_ID,
    LOCAL_H3_MODEL_ID,
    floyo_h3_config,
    local_h3_config,
    record_in_directory,
    validate_floyo_config,
)
from hevi.capabilities.model_directory import call_model, get_record


def test_capability_registered() -> None:
    assert caps.get("model.floyo_h3_registration").name == "model.floyo_h3_registration"


def test_floyo_config_records_workflow_inputs_and_billing() -> None:
    config = floyo_h3_config()
    assert config["workflow"] == FLOYO_WORKFLOW_ID
    assert config["workflow"] == "Minimax_H3_Image_to_Video_OpenWeight"
    assert config["inputs"] == ["start_frame", "aspect_ratio", "duration", "prompt"]
    assert config["billing"]["api_wallet_consumed"] is False
    assert config["billing"]["unit"] == "FloTime (GPU time)"
    assert config["billing"]["plans"]["Explorer"] == "2 hours per month"
    assert config["billing"]["plans"]["Flex"] == "$9/hour"
    assert "pricing page" in config["billing"]["source"]


def test_floyo_claims_all_unverified() -> None:
    claims = floyo_h3_config()["claims"]
    assert claims == {
        "no_censorship": "unverified",
        "lora": "unverified",
        "adult_performance": "unverified",
        "h100_speed": "unverified",
    }


def test_floyo_config_no_account_no_payment_no_promo() -> None:
    config = floyo_h3_config()
    assert config["account_registered"] is False
    assert config["payment_method_on_file"] is False
    assert config["promo_code_used"] is False
    assert config["status"] == "unverified"
    assert config["verified"] is False


def test_local_h3_record_is_a_different_record() -> None:
    local = local_h3_config()
    assert LOCAL_H3_MODEL_ID != FLOYO_MODEL_ID
    assert local["capability"] == "video.fasth3_local"
    assert local["provider"] == "local"
    assert local["workflow"] is None
    assert local["billing"]["floyo_workflow"] is False
    assert local["claims"]["h100_speed"] == "unverified"


def test_validate_accepts_registered_config() -> None:
    assert validate_floyo_config(floyo_h3_config()) == floyo_h3_config()


def test_validate_refuses_claim_stated_as_guarantee() -> None:
    config = floyo_h3_config()
    config["claims"]["no_censorship"] = True
    with pytest.raises(CapabilityError, match="must stay 'unverified'"):
        validate_floyo_config(config)
    config = floyo_h3_config()
    config["claims"]["h100_speed"] = "guaranteed"
    with pytest.raises(CapabilityError, match="must stay 'unverified'"):
        validate_floyo_config(config)


def test_validate_refuses_wrong_workflow_and_missing_input() -> None:
    config = floyo_h3_config()
    config["workflow"] = "Minimax_H3_Other"
    with pytest.raises(CapabilityError, match="workflow must be"):
        validate_floyo_config(config)
    config = floyo_h3_config()
    config["inputs"] = ["start_frame", "prompt"]
    with pytest.raises(CapabilityError, match="inputs must be exactly"):
        validate_floyo_config(config)


def test_validate_refuses_wallet_account_payment_promo() -> None:
    config = floyo_h3_config()
    config["billing"]["api_wallet_consumed"] = True
    with pytest.raises(CapabilityError, match="api_wallet_consumed"):
        validate_floyo_config(config)
    for flag in ("account_registered", "payment_method_on_file", "promo_code_used"):
        config = floyo_h3_config()
        config[flag] = True
        with pytest.raises(CapabilityError, match=flag):
            validate_floyo_config(config)


def test_record_in_directory_leaves_both_unverified_and_call_refused(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "model_directory.json"
    records = record_in_directory(directory)
    assert set(records) == {FLOYO_MODEL_ID, LOCAL_H3_MODEL_ID}
    for model_id, record in records.items():
        assert record["status"] == "unverified"
        assert record["verified_at"] is None
        stored = get_record(directory, model_id)
        assert stored["config_hash"] == record["config_hash"]
        with pytest.raises(CapabilityError, match="not verified"):
            call_model(directory, model_id=model_id, config=record["config"])


def test_describe_action_writes_no_directory_file(tmp_path: Path) -> None:
    cap = caps.get("model.floyo_h3_registration")
    out = tmp_path / "out"
    result = cap.render_safe({"action": "describe"}, out, duration=0.0,
                             aspect="16:9", seed=1)
    assert result.qa["result"]["floyo"]["workflow"] == FLOYO_WORKFLOW_ID
    assert not (tmp_path / "model_directory.json").exists()


def test_record_action_writes_both_records(tmp_path: Path) -> None:
    cap = caps.get("model.floyo_h3_registration")
    directory = tmp_path / "model_directory.json"
    out = tmp_path / "out"
    result = cap.render_safe(
        {"action": "record", "directory_path": str(directory)},
        out, duration=0.0, aspect="16:9", seed=1,
    )
    assert directory.is_file()
    assert get_record(directory, FLOYO_MODEL_ID)["status"] == "unverified"
    assert get_record(directory, LOCAL_H3_MODEL_ID)["status"] == "unverified"
    assert result.qa["result"]["records"][FLOYO_MODEL_ID]["status"] == "unverified"


def test_module_makes_no_network_calls() -> None:
    import hevi.capabilities.floyo_h3_registration as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    for token in ("import requests", "import httpx", "urllib", "socket",
                  "urlopen", "aiohttp"):
        assert token not in source
