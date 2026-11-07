"""Tests for oskill.llm.prompt_fingerprint.prompt_fingerprint."""

import subprocess
import sys

import pytest

from oskill.llm.prompt_fingerprint import prompt_fingerprint

# ── Happy path ──────────────────────────────────────────────────────────────


def test_prompt_fingerprint_returns_three_keys():
    """Result has exactly the three required keys."""
    result = prompt_fingerprint("Hello {name}", {"name": "World"})
    assert set(result.keys()) == {"fingerprint", "template_fingerprint", "full_payload_canonical"}


def test_prompt_fingerprint_returns_64_char_hex():
    """Both fingerprint and template_fingerprint are 64-char lowercase hex."""
    result = prompt_fingerprint("test template")
    for key in ("fingerprint", "template_fingerprint"):
        fp = result[key]
        assert len(fp) == 64, f"{key} length should be 64, got {len(fp)}"
        assert all(c in "0123456789abcdef" for c in fp), f"{key} not valid hex"


def test_prompt_fingerprint_deterministic_across_calls():
    """Same input twice → identical fingerprint."""
    r1 = prompt_fingerprint("Say {x}", {"x": "hello"}, model="claude-haiku-4-5", seed=7)
    r2 = prompt_fingerprint("Say {x}", {"x": "hello"}, model="claude-haiku-4-5", seed=7)
    assert r1["fingerprint"] == r2["fingerprint"]
    assert r1["template_fingerprint"] == r2["template_fingerprint"]


def test_prompt_fingerprint_different_templates_different_fp():
    """Different templates → different fingerprints."""
    r1 = prompt_fingerprint("Template A", {})
    r2 = prompt_fingerprint("Template B", {})
    assert r1["fingerprint"] != r2["fingerprint"]
    assert r1["template_fingerprint"] != r2["template_fingerprint"]


def test_prompt_fingerprint_different_variables_different_fingerprint():
    """Different variables → different full fingerprint but same template_fingerprint."""
    r1 = prompt_fingerprint("Say {x}", {"x": "a"})
    r2 = prompt_fingerprint("Say {x}", {"x": "b"})
    assert r1["fingerprint"] != r2["fingerprint"]
    assert r1["template_fingerprint"] == r2["template_fingerprint"]


def test_prompt_fingerprint_different_seed_different_fingerprint():
    """Different seed → different fingerprint."""
    r1 = prompt_fingerprint("T", seed=1)
    r2 = prompt_fingerprint("T", seed=2)
    assert r1["fingerprint"] != r2["fingerprint"]


def test_prompt_fingerprint_different_temperature_different_fingerprint():
    """Different temperature → different fingerprint."""
    r1 = prompt_fingerprint("T", temperature=0.0)
    r2 = prompt_fingerprint("T", temperature=0.5)
    assert r1["fingerprint"] != r2["fingerprint"]


def test_prompt_fingerprint_empty_variables_vs_none_equivalent():
    """None and {} for variables produce the same fingerprint."""
    r1 = prompt_fingerprint("T", None)
    r2 = prompt_fingerprint("T", {})
    assert r1["fingerprint"] == r2["fingerprint"]


def test_prompt_fingerprint_template_only():
    """Works with only template (no other args)."""
    result = prompt_fingerprint("Hello World")
    assert len(result["fingerprint"]) == 64


def test_prompt_fingerprint_canonical_string_is_json():
    """full_payload_canonical is valid JSON containing the template."""
    import json

    result = prompt_fingerprint("My {template}", {"k": "v"}, model="m")
    payload = json.loads(result["full_payload_canonical"])
    assert payload["template"] == "My {template}"
    assert payload["variables"] == {"k": "v"}
    assert payload["model"] == "m"


# ── Academic reference ────────────────────────────────────────────────────────


@pytest.mark.academic_reference
def test_prompt_fingerprint_cross_process_determinism():
    """Same fingerprint produced in a subprocess (cross-process determinism).

    Reference: arxiv 2601.15322 (Replayable Financial Agents, 2026).
    The fingerprint must be identical across different Python processes,
    not just within a single process — this ensures true reproducibility
    for audit trails and replay verification.
    """
    template = "Analyze market for {ticker}"
    variables = {"ticker": "AAPL"}
    model = "claude-opus-4-7"
    seed = 42

    # Compute fingerprint in this process
    result = prompt_fingerprint(template, variables, model=model, temperature=0.0, seed=seed)
    expected_fp = result["fingerprint"]

    # Compute fingerprint in a subprocess
    code = (
        "from oskill.llm.prompt_fingerprint import prompt_fingerprint; "
        "r = prompt_fingerprint("
        f"'{template}', {{'ticker': 'AAPL'}}, "
        f"model='{model}', temperature=0.0, seed={seed}"
        "); print(r['fingerprint'])"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"Subprocess failed: {proc.stderr}"
    subprocess_fp = proc.stdout.strip()
    assert subprocess_fp == expected_fp, (
        f"Cross-process fingerprint mismatch: {subprocess_fp!r} != {expected_fp!r}"
    )
