"""3O conformance tests (HELIOS_3O_SPEC_v3_0, registry scope).

Layer attribution, ``__manifest__`` coverage, and layer validity.
Guard tests for single-source convergence and the spend gate live in
``test_3o_single_source.py`` and ``test_3o_spend_gate.py``.
"""

from __future__ import annotations

import pytest

from hevi.capabilities import __manifest__ as MANIFEST
from hevi.capabilities import list_capabilities
from hevi.capabilities.layer_attribution import LAYER_ATTRIBUTION
from hevi.capabilities.registry import (
    LAYERS,
    Capability,
    CapabilityError,
    layer_of,
    register,
)

EXPECTED_COUNT = 397


def _dummy_capability(name: str, layer: str) -> Capability:
    return Capability(
        name=name,
        kind="line",
        aspects=["16:9"],
        params_schema={"type": "object"},
        cpu_cost_hint=0.0,
        render=lambda params, out_dir, **kw: None,
        layer=layer,
    )


def test_layer_attribution_full_coverage() -> None:
    caps = list_capabilities()
    assert len(caps) == EXPECTED_COUNT
    assert len({c.name for c in caps}) == EXPECTED_COUNT
    assert set(LAYER_ATTRIBUTION) == {c.name for c in caps}
    for cap in caps:
        assert cap.layer in LAYERS, f"{cap.name}: unattributed layer {cap.layer!r}"
        assert cap.layer == LAYER_ATTRIBUTION[cap.name]["layer"]
        assert LAYER_ATTRIBUTION[cap.name]["reason"].strip()
        assert LAYER_ATTRIBUTION[cap.name]["file"].strip()


def test_layer_counts_match_attribution() -> None:
    from collections import Counter

    counted = Counter(c.layer for c in list_capabilities())
    tabled = Counter(e["layer"] for e in LAYER_ATTRIBUTION.values())
    assert counted == tabled
    assert counted["oservi"] == 0  # no registry capability passes SPEC §7 red lines
    assert sum(counted.values()) == EXPECTED_COUNT


def test_manifest_full_coverage() -> None:
    assert MANIFEST["spec"] == "HELIOS_3O_SPEC_v3_0"
    elements = MANIFEST["elements"]
    assert len(elements) == EXPECTED_COUNT
    assert {e["name"] for e in elements} == {c.name for c in list_capabilities()}
    for element in elements:
        assert element["layer"] in LAYERS
        assert element["kind"]
        assert element["line"] is not None
        assert element["signature"]
        assert element["version"]


def test_invalid_layer_rejected() -> None:
    with pytest.raises(CapabilityError, match="unknown 3O layer"):
        register(_dummy_capability("qa.__3o_probe_bad_layer__", "bogus"))
    # The rejected registration must not leak into the registry.
    assert "qa.__3o_probe_bad_layer__" not in {c.name for c in list_capabilities()}


def test_explicit_layer_wins_over_table() -> None:
    import hevi.capabilities.registry as registry_mod

    cap = _dummy_capability("qa.__3o_probe_explicit__", "obase")
    try:
        register(cap)
        assert cap.layer == "obase"
    finally:
        registry_mod._REGISTRY.pop("qa.__3o_probe_explicit__", None)


def test_unattributed_name_resolves_empty() -> None:
    assert layer_of("qa.__definitely_not_a_capability__") == ""
