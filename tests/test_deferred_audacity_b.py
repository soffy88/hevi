"""Tests for deferred 15-tools batch B: Audacity effect-chain
contract (B3, 3.x-only). Contract layer only; no audio processed.
"""

import pytest

from hevi.capabilities import audacity_effect_chain_contract as b3
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import contains


def _plan(**overrides):
    plan = {
        "audacity_version": "3.7.9",
        "interface": "macro",
        "project_format": "aup3",
        "input": {"source": "narration-take-1.wav", "duration_s": 30.0},
        "chain": [
            {"effect": "noise_reduction", "params": {}},
            {"effect": "normalize", "params": {}},
            {"effect": "fade_out", "params": {"duration_s": 1.5}},
        ],
        "output": {"format": "wav", "path": "narration-clean.wav"},
    }
    plan.update(overrides)
    return plan


def test_audacity_chain_positive():
    contract = b3.compile_audacity_effect_chain_contract(_plan())
    assert contract["step_count"] == 3
    assert [s["order"] for s in contract["chain"]] == [1, 2, 3]
    assert contract["project_format"] == "aup3"
    assert contract["executed_here"] is False
    assert contract["audio_rendered"] is False
    assert contract["output_file"] is None
    other = b3.compile_audacity_effect_chain_contract(
        _plan(interface="mod_script_pipe")
    )
    assert other["interface"] == "mod_script_pipe"


def test_audacity_chain_4x_fails_closed():
    for version in ("4.0.2", "4.0", "v4.1.0"):
        with pytest.raises(CapabilityError, match="3.x-only"):
            b3.compile_audacity_effect_chain_contract(
                _plan(audacity_version=version)
            )
    with pytest.raises(CapabilityError):
        b3.compile_audacity_effect_chain_contract(
            _plan(audacity_version="4.0.2", interface="macro")
        )
    with pytest.raises(CapabilityError, match="aup3"):
        b3.compile_audacity_effect_chain_contract(
            _plan(project_format="aup4")
        )
    with pytest.raises(CapabilityError):
        b3.compile_audacity_effect_chain_contract(
            _plan(interface="companion_fork")
        )


def test_audacity_chain_step_rules():
    with pytest.raises(CapabilityError):
        b3.compile_audacity_effect_chain_contract(_plan(chain=[]))
    with pytest.raises(CapabilityError):
        b3.compile_audacity_effect_chain_contract(_plan(chain=[
            {"effect": "denoise_ai", "params": {}},
        ]))
    with pytest.raises(CapabilityError):
        b3.compile_audacity_effect_chain_contract(_plan(chain=[
            {"effect": "fade_in", "params": {"duration_s": -1}},
        ]))
    with pytest.raises(CapabilityError):
        b3.compile_audacity_effect_chain_contract(_plan(chain=[
            {"effect": "gain", "params": {"db": "loud"}},
        ]))
    with pytest.raises(CapabilityError):
        b3.compile_audacity_effect_chain_contract(
            _plan(output={"format": "aup3", "path": "out.wav"})
        )


def test_batch4_registered():
    assert contains("audio.audacity_effect_chain_contract")
