"""P8.1 — Runtime observation, and the fork it must not open.

P7.3 froze a boundary: ``ProviderProfile`` says what a provider *is*;
``ProviderDecision`` says what it may do. P8.1 adds a third question — is it
answering right now — and the risk is that the new answer quietly becomes a second
answer to one of the first two.

These tests exist because that is a natural mistake to make. A probe returns a
provider id and a boolean, and the path of least resistance is to attach a few
convenient attributes on the way out. Each of the five mutation tests below is the
specific way that goes wrong.

The chain, in the order it actually runs:

    ProviderCatalogue ─▶ ProviderPolicy ─▶ ProviderDecision ─▶ Runtime Probe

The probe runs last, so a provider policy already excluded is never asked about.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import pathlib

import pytest

from hevi.provider_policy.policy import ProviderDecision
from hevi.providers.facts import PROVIDER_CATALOGUE, ProviderCatalogue
from hevi.runtime.provider import (
    PROBEABLE,
    AvailabilityOutcome,
    ProviderAvailabilityDecision,
    ProviderRuntimeStatus,
    RuntimeAvailability,
    observe_policy_eligible,
    observe_provider,
    unknown_status,
)

RUNTIME_DIR = pathlib.Path("hevi/runtime")
MODELS = RUNTIME_DIR / "provider" / "models.py"
PROBE = RUNTIME_DIR / "provider" / "provider_probe.py"
RUNTIME = RUNTIME_DIR / "provider" / "provider_runtime.py"


def _probe(reachable: bool, *, latency: int | None = 7, error: str | None = None):
    async def _inner(provider_id: str) -> dict:
        return {
            "reachable": reachable,
            "latency_ms": latency,
            "error": error if not reachable else None,
            # configuration that must NOT be copied into an observation
            "required_env": ("SECRET_KEY",),
            "endpoint": "https://internal.example",
        }

    return _inner


# ══════════════════════════════════════════════════════════════════════════
# the model is an observation, not a fact
# ══════════════════════════════════════════════════════════════════════════


def test_runtime_status_has_exactly_the_permitted_fields():
    """The P8.1 contract lists five fields. No more."""
    names = {f.name for f in dataclasses.fields(ProviderRuntimeStatus)}
    assert names == {
        "provider_id", "availability", "reachable", "latency_ms",
        "checked_at", "failure_reason",
    }


def test_forbidden_fact_fields_absent_from_the_runtime_model():
    """Spec: no locality, license, capabilities, quality or ranking.

    A runtime status that carried ``locality`` would be a second fact source: a
    provider that timed out would start looking remote, and ``LOCAL_ONLY`` would
    reject it for the wrong reason.
    """
    names = {f.name for f in dataclasses.fields(ProviderRuntimeStatus)}
    for forbidden in (
        "locality", "license", "license_class", "capabilities", "capability_states",
        "quality", "quality_score", "ranking", "rank", "score", "eligible", "blocked",
    ):
        assert forbidden not in names, f"runtime observation carries fact {forbidden!r}"


def test_runtime_module_never_mentions_a_fact_field():
    for source in (MODELS, PROBE, RUNTIME):
        tree = ast.parse(source.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                assert not node.target.id.startswith(
                    ("locality", "license", "licence", "capability", "quality", "rank")
                ), f"{source.name}:{node.lineno} declares a fact field: {node.target.id}"


def test_fact_enums_are_not_imported_into_the_runtime_package():
    """The runtime layer may not even name the fact types it must not set."""
    fact_names = {"ProviderLocality", "ProviderLicenseClass", "ProviderCapabilityState",
                  "ProviderProfile", "ProviderCatalogue", "PROVIDER_CATALOGUE"}
    for source in (MODELS, PROBE, RUNTIME):
        tree = ast.parse(source.read_text())
        for node in ast.walk(tree):
            imported: set[str] = set()
            if isinstance(node, ast.ImportFrom):
                imported = {a.asname or a.name for a in node.names}
                if node.module:
                    imported.add(node.module.split(".")[-1])
            elif isinstance(node, ast.Import):
                imported = {(a.asname or a.name).split(".")[0] for a in node.names}
            for name in imported:
                assert name not in fact_names, (
                    f"{source.name}:{node.lineno} imports provider fact {name}"
                )


def test_status_never_carries_configuration():
    """The probe result holds endpoints and env var names; none may be copied."""
    status = asyncio.run(observe_provider("voicebox", probe=_probe(True)))
    dumped = status.to_dict()
    assert set(dumped) == {
        "provider_id", "availability", "reachable", "latency_ms",
        "checked_at", "failure_reason",
    }
    assert "SECRET_KEY" not in str(dumped)
    assert "internal.example" not in str(dumped)


# ══════════════════════════════════════════════════════════════════════════
# states: UNKNOWN / AVAILABLE / UNAVAILABLE — never ELIGIBLE / BLOCKED
# ══════════════════════════════════════════════════════════════════════════


def test_runtime_states_are_not_policy_vocabulary():
    values = {s.value for s in RuntimeAvailability}
    assert values == {"unknown", "available", "unavailable"}
    for policy_word in ("eligible", "blocked", "allowed", "approved"):
        assert policy_word not in values, (
            f"a probe emitting {policy_word!r} is second-guessing policy"
        )


def test_combined_outcome_keeps_the_two_questions_apart():
    values = {o.value for o in AvailabilityOutcome}
    assert values == {"usable", "unreachable", "ineligible", "unknown"}
    # "unreachable" and "ineligible" must be distinguishable: one is a network fact,
    # the other a policy decision.
    assert "unreachable" in values and "ineligible" in values


# ══════════════════════════════════════════════════════════════════════════
# fail closed
# ══════════════════════════════════════════════════════════════════════════


def test_default_status_is_unknown_and_not_usable():
    status = ProviderRuntimeStatus(provider_id="wan_local")
    assert status.availability is RuntimeAvailability.UNKNOWN
    assert status.is_usable is False
    assert status.was_probed is False


def test_unknown_observation_is_not_usable():
    status = unknown_status("wan_local", "no_probe_configuration")
    assert status.is_usable is False
    assert status.was_probed is False


def test_unknown_outcome_requires_a_reason_and_is_not_usable():
    decision = ProviderAvailabilityDecision(
        provider_id="wan_local", outcome=AvailabilityOutcome.UNKNOWN, reason="not probed"
    )
    assert decision.is_usable is False
    with pytest.raises(ValueError, match="UNKNOWN_AVAILABILITY_WITHOUT_REASON"):
        ProviderAvailabilityDecision(
            provider_id="wan_local", outcome=AvailabilityOutcome.UNKNOWN
        )


def test_unprobeable_provider_is_unknown_not_unavailable():
    """"We cannot ask" and "we asked and it failed" are different facts."""
    status = asyncio.run(observe_provider("wan_local", probe=_probe(False)))
    assert status.availability is RuntimeAvailability.UNKNOWN
    assert not status.was_probed


def test_unavailable_requires_a_reason():
    with pytest.raises(ValueError, match="UNAVAILABLE_WITHOUT_REASON"):
        ProviderRuntimeStatus(
            provider_id="voicebox",
            availability=RuntimeAvailability.UNAVAILABLE,
            reachable=False,
        )


def test_available_requires_observed_reachability():
    with pytest.raises(ValueError, match="AVAILABLE_WITHOUT_REACHABLE"):
        ProviderRuntimeStatus(
            provider_id="voicebox",
            availability=RuntimeAvailability.AVAILABLE,
            reachable=False,
        )


# ══════════════════════════════════════════════════════════════════════════
# reachable != eligible
# ══════════════════════════════════════════════════════════════════════════


def _decision(considered, eligible) -> ProviderDecision:
    return ProviderDecision(considered=list(considered), eligible=list(eligible))


def test_eligible_but_unreachable_is_not_usable():
    """Policy allowed it; the network did not. Neither fact cancels the other."""
    observation = asyncio.run(
        observe_policy_eligible(
            _decision(["voicebox"], ["voicebox"]), probe=_probe(False, error="http_503")
        )
    )
    decision = observation.decision_for("voicebox")
    assert decision.outcome is AvailabilityOutcome.UNREACHABLE
    assert decision.is_usable is False
    assert observation.usable_providers == ()


def test_eligible_and_reachable_is_usable():
    observation = asyncio.run(
        observe_policy_eligible(_decision(["voicebox"], ["voicebox"]), probe=_probe(True))
    )
    assert observation.decision_for("voicebox").outcome is AvailabilityOutcome.USABLE
    assert observation.usable_providers == ("voicebox",)


def test_ineligible_provider_is_never_probed():
    """The chain runs probe *after* policy, so excluded providers cost nothing."""
    probed: list[str] = []

    async def spy(provider_id: str) -> dict:
        probed.append(provider_id)
        return {"reachable": True, "latency_ms": 1, "error": None}

    observation = asyncio.run(
        observe_policy_eligible(
            _decision(["voicebox", "longcat"], ["voicebox"]), probe=spy
        )
    )
    assert probed == ["voicebox"], "policy excluded longcat; it must not be probed"
    assert observation.decision_for("longcat").outcome is AvailabilityOutcome.INELIGIBLE
    assert observation.status_for("longcat") is None


def test_ineligible_reports_policy_as_the_reason_not_the_network():
    observation = asyncio.run(
        observe_policy_eligible(_decision(["longcat"], []), probe=_probe(False))
    )
    decision = observation.decision_for("longcat")
    assert decision.outcome is AvailabilityOutcome.INELIGIBLE
    assert "policy" in decision.reason.lower()
    assert decision.status is None, "an unprobed provider has no runtime status"


# ══════════════════════════════════════════════════════════════════════════
# the probe is not a second fact source
# ══════════════════════════════════════════════════════════════════════════


def test_probe_does_not_mutate_the_catalogue():
    before = PROVIDER_CATALOGUE.to_dict()
    asyncio.run(observe_provider("voicebox", probe=_probe(True)))
    asyncio.run(observe_provider("wan_local", probe=_probe(False)))
    assert PROVIDER_CATALOGUE.to_dict() == before


def test_observation_of_the_whole_fleet_does_not_mutate_the_catalogue():
    before = {pid: PROVIDER_CATALOGUE.resolve(pid) for pid in PROVIDER_CATALOGUE.list_ids()}
    observation = asyncio.run(
        observe_policy_eligible(
            _decision(PROVIDER_CATALOGUE.list_ids(), PROVIDER_CATALOGUE.list_ids()),
            probe=_probe(False),
        )
    )
    assert observation.usable_providers == ()
    for pid, profile in before.items():
        assert PROVIDER_CATALOGUE.resolve(pid) is profile, f"{pid} was replaced"


def test_probe_module_never_registers_into_any_catalogue():
    for source in (MODELS, PROBE, RUNTIME):
        text = source.read_text()
        assert ".register(" not in text, f"{source.name} writes to a catalogue"
        assert "PROVIDER_CATALOGUE" not in text.replace("PROVIDER_SPECS", ""), (
            f"{source.name} references the fact catalogue"
        )


def test_runtime_state_does_not_reach_provider_decision_facts():
    """The decision's fact families are untouched by observation."""
    decision = ProviderDecision(considered=["voicebox"], eligible=["voicebox"])
    before = (dict(decision.locality), dict(decision.license_class),
              dict(decision.capability_states))
    observation = asyncio.run(
        observe_policy_eligible(decision, probe=_probe(False, error="timeout"))
    )
    assert observation.status_for("voicebox").availability is RuntimeAvailability.UNAVAILABLE
    assert (decision.locality, decision.license_class, decision.capability_states) == before


def test_no_runtime_symbol_leaks_into_the_policy_module():
    for source in (PROBE, RUNTIME, MODELS):
        tree = ast.parse(source.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    assert not isinstance(target, ast.Attribute) or target.attr not in {
                        "locality", "license_class", "capability_states",
                    }, f"{source.name}:{node.lineno} writes a provider fact"


# ══════════════════════════════════════════════════════════════════════════
# reuse, not duplication
# ══════════════════════════════════════════════════════════════════════════


def test_probeable_set_comes_from_the_existing_spec_authority():
    """P8.1 must not maintain its own list of what is probeable."""
    from hevi.provider_policy.runtime import PROVIDER_SPECS

    assert frozenset(s.provider_id for s in PROVIDER_SPECS) == PROBEABLE


def test_default_probe_delegates_to_the_existing_probe():
    source = PROBE.read_text()
    assert "probe_provider" in source, "the existing probe authority must be reused"
    assert "httpx" not in source and "aiohttp" not in source and "urllib" not in source, (
        "P8.1 must not implement its own HTTP client"
    )


def test_probeable_set_is_derived_not_declared():
    """A hand-written list of ids would not reference PROVIDER_SPECS."""
    text = PROBE.read_text()
    assert "PROVIDER_SPECS" in text
    tree = ast.parse(text)
    literals = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and node.value in set(PROVIDER_CATALOGUE.list_ids())
    ]
    assert literals == [], (
        f"probe module hard-codes provider ids {[n.value for n in literals]}; "
        "probeability is the spec authority's to declare"
    )


# ══════════════════════════════════════════════════════════════════════════
# the model is strict
# ══════════════════════════════════════════════════════════════════════════


def test_status_requires_a_provider_id():
    with pytest.raises(ValueError, match="RUNTIME_STATUS_WITHOUT_ID"):
        ProviderRuntimeStatus(provider_id="")


def test_negative_latency_is_refused():
    with pytest.raises(ValueError, match="NEGATIVE_LATENCY"):
        ProviderRuntimeStatus(provider_id="voicebox", latency_ms=-1)


def test_probe_errors_become_observations_not_exceptions():
    async def explode(provider_id: str) -> dict:
        raise ConnectionResetError("connection reset by peer")

    status = asyncio.run(observe_provider("voicebox", probe=explode))
    assert status.availability is RuntimeAvailability.UNAVAILABLE
    assert "ConnectionResetError" in status.failure_reason
    assert status.is_usable is False


def test_latency_is_recorded_when_observed():
    status = asyncio.run(observe_provider("voicebox", probe=_probe(True, latency=320)))
    assert status.latency_ms == 320
    assert status.is_usable


def test_observation_serialises_for_audit():
    observation = asyncio.run(
        observe_policy_eligible(_decision(["voicebox"], ["voicebox"]), probe=_probe(True))
    )
    payload = observation.to_dict()
    assert payload["decisions"][0]["outcome"] == "usable"
    assert payload["statuses"][0]["provider_id"] == "voicebox"
    assert payload["checked_at"]


def test_catalogue_is_unaffected_by_runtime_construction():
    """Constructing statuses must not register anything."""
    fresh = ProviderCatalogue()
    before = fresh.to_dict()
    for pid in ("a", "b"):
        ProviderRuntimeStatus(provider_id=pid, availability=RuntimeAvailability.AVAILABLE,
                              reachable=True)
    assert fresh.to_dict() == before
