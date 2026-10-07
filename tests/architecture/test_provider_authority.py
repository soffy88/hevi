"""P0-4.2.0 — provider authority invariants.

`docs/architecture/provider_authority.md` records the classification. These tests
pin the four defects that were live at the time of writing, because each one is
silent: none of them raises, they just produce a confidently wrong answer about a
provider.

A passing suite here means the double-source problem is *detected*. The gate
`PROVIDER_REGISTRY_SINGLE_SOURCE` stays BLOCKED until these are inverted to assert
convergence rather than divergence.
"""

from __future__ import annotations

import dataclasses as d

import pytest

from hevi.providers.facts import PROVIDER_CATALOGUE, ProviderCapabilityState
from hevi.providers.runtime_specs import RUNTIME_SPECS
from hevi.video.capability_guard import PROVIDER_LIMITS


def _shared_catalogue_and_limits() -> list[str]:
    return sorted(set(PROVIDER_CATALOGUE.list_ids()) & set(PROVIDER_LIMITS))


# ------------------------------------------- defect 1: capability divergence


def test_catalogue_and_limits_disagree_for_nine_providers():
    """The headline finding: 9 of 14 shared providers have two capability answers.

    Pinned as a divergence count rather than a list of names so that fixing one
    provider moves the number and the test tells the truth about progress, instead
    of being edited into silence.
    """
    divergent = [
        provider_id
        for provider_id in _shared_catalogue_and_limits()
        if set(PROVIDER_CATALOGUE.get(provider_id).capabilities)
        != set(PROVIDER_LIMITS[provider_id].modes)
    ]
    assert len(divergent) == 9, f"expected 9 divergent, got {divergent}"


@pytest.mark.parametrize(
    "provider_id",
    [
        # catalogue claims i2v; the t2v callable takes no reference image and i2v
        # is registered as a separate provider id (`happyhorse_1_1_ref`,
        # `wan22_kf2v_maas` under image_to_video).
        "hailuo", "happyhorse_1_1", "happyhorse_1_1_maas", "kling_v2", "veo3",
        "wan_2_7", "wan_2_7_maas",
    ],
)
def test_catalogue_over_claims_i2v(provider_id: str):
    """Fail-open direction: the catalogue advertises a capability that cannot run."""
    profile = PROVIDER_CATALOGUE.get(provider_id)
    assert "i2v" in profile.capabilities, (
        f"{provider_id} no longer over-claims i2v in the catalogue — "
        "the divergence for this provider may be fixed; move it out of this list"
    )
    assert "i2v" not in PROVIDER_LIMITS[provider_id].modes


def test_limits_agree_with_the_providers_own_capability_row():
    """A third copy of the same fact must not exist.

    `H3_LOCAL_CAPABILITY` is cited by `capability_guard.py:60` and `registry.py:304`
    as the evidence for the limits. If the row and the limits drift apart, the
    comment becomes a lie.
    """
    from hevi.providers.h3_local.provider import H3_LOCAL_CAPABILITY

    limits_modes = set(PROVIDER_LIMITS["h3_local"].modes)
    declared_modes = set(H3_LOCAL_CAPABILITY["capabilities"]) & {"i2v", "t2v"}
    assert limits_modes == declared_modes
    # and the native_audio flag agrees too
    assert PROVIDER_LIMITS["h3_local"].native_audio is (
        "native_audio" in H3_LOCAL_CAPABILITY["capabilities"]
    )


def test_manim_capability_neither_source_is_complete():
    """Neither the catalogue nor the limits holds manim's true capability set.

    Recorded because "pick one source and delete the other" is the wrong fix for
    this row: the union is the truth, so the migration has to add information
    rather than only move it.
    """
    from hevi.providers.manim.provider import MANIM_CAPABILITY

    catalogue = set(PROVIDER_CATALOGUE.get("manim").capabilities)
    limits = set(PROVIDER_LIMITS["manim"].modes)
    truth = set(MANIM_CAPABILITY["capabilities"]) & {"t2v", "code_scene"}
    assert catalogue != truth
    assert limits != truth
    assert catalogue | limits == truth


# ------------------------------------- defect 2: the policy capability gate


def test_required_capability_gate_cannot_see_modes():
    """`policy.py` reads capabilities as boolean attributes that do not exist.

    `ProviderLimits` stores modes in a frozenset, so `getattr(limits, "t2v", False)`
    is False for every provider and every t2v/i2v request is rejected. This asserts
    the *shape* mismatch rather than the rejection, because the rejection depends on
    policy configuration and the mismatch does not.
    """
    limits = PROVIDER_LIMITS["ltx2_cloud"]
    assert not hasattr(limits, "t2v")
    assert not hasattr(limits, "i2v")
    assert "t2v" in limits.modes
    # The only capability-shaped attributes that actually resolve are the two
    # genuine booleans, which is why the bug went unnoticed.
    assert limits.native_audio is True
    assert limits.lip_sync is False


def test_obase_capability_tags_are_mostly_absent():
    """`validate_request` prefers obase tags, which are empty almost everywhere.

    This is why `PROVIDER_LIMITS` is the de facto production authority despite
    `PROVIDER_CATALOGUE` claiming to be canonical: nothing reads the catalogue's
    capabilities at all.
    """
    from obase.provider_registry import ProviderRegistry

    with_tags = [
        provider_id
        for provider_id in PROVIDER_LIMITS
        if (ProviderRegistry.get().capabilities(provider_id) or {}).get("modes")
    ]
    assert len(with_tags) <= 1, (
        f"more providers now declare obase capability tags: {with_tags}"
    )


# --------------------------------------- defect 3: availability stated and ignored


def test_mainline_provider_is_not_mislabelled_unadopted():
    """`happyhorse_1_1_maas_lock` was NOT_ADOPTED while being the mainline path.

    It is referenced by `longvideo_orchestrator`, `director`, `shortdrama` and
    `director_pipeline`, and `registry.py` names it the mainline provider. The
    declared adoption state contradicted all of that. Now that adoption state
    gates selection, this would have denied the mainline provider outright.
    """
    profile = PROVIDER_CATALOGUE.get("happyhorse_1_1_maas_lock")
    assert profile.capability_state.value == "AVAILABLE"
    assert "happyhorse_1_1_maas_lock" in PROVIDER_LIMITS
    assert "happyhorse_1_1_maas_lock" in RUNTIME_SPECS.list_ids()


def test_capability_state_is_enforced_not_merely_recorded():
    """Adoption state must gate selection.

    `policy.py` used to populate `decision.capability_states` and never read it, so
    a provider the catalogue declared NOT_ADOPTED was selectable exactly like any
    other. An unenforced field drifts straight back into being a comment, which is
    how `NOT_ADOPTED` survived on the mainline provider in the first place.
    """
    import inspect

    from hevi.provider_policy.policy import (
        _SELECTABLE_STATES,
        evaluate_provider_policy,
    )

    assert frozenset({"AVAILABLE"}) == _SELECTABLE_STATES, (
        "more states became selectable; re-check that each one is genuinely "
        "permission to run rather than a reporting label"
    )

    src = inspect.getsource(evaluate_provider_policy)
    assert "capability_state_blocks_selection" in src, (
        "the adoption-state gate disappeared; capability_states is being recorded "
        "and ignored again"
    )

    # And it actually refuses: a provider with no selectable state is rejected even
    # when it is otherwise perfect.
    import asyncio

    from hevi.provider_policy.policy import ProviderPolicy

    decision = asyncio.run(
        evaluate_provider_policy(
            ProviderPolicy(mode="t2v", candidates=["manim"]),
            catalogue=_OneBlockedCatalogue(),
        )
    )
    rejected = {r.provider_id: r.reasons for r in decision.rejected}
    assert "capability_state_blocks_selection:BLOCKED" in rejected.get("manim", []), (
        f"expected an adoption-state refusal, got {rejected}"
    )


class _OneBlockedCatalogue:
    """A catalogue that reports BLOCKED for every provider, to exercise the gate.

    Wraps the real catalogue rather than mutating it, so a test cannot leak state
    into the next one. Reports a *uniform* state on purpose: the gate has to refuse
    regardless of which provider it is asked about, and a per-provider stand-in
    would only prove the gate reads one row.
    """

    def __init__(self):
        self._inner = PROVIDER_CATALOGUE

    def get(self, provider_id):
        profile = self._inner.get(provider_id)
        if profile is None:
            return None
        import dataclasses

        return dataclasses.replace(
            profile, capability_state=ProviderCapabilityState.BLOCKED
        )

    def has(self, provider_id):
        return self._inner.has(provider_id)

    def facts_for(self, provider_id):
        return self._inner.facts_for(provider_id)


# ------------------------------------------------------ classification facts


def test_production_adapter_registry_is_not_a_provider_registry():
    """Its key space is `production_source`, not a provider id.

    The "six registries" count included it. Merging a task-shape registry into a
    provider authority would be a category error, so this pins the distinction.
    """
    from hevi.production.adapters import default_production_adapters

    sources = default_production_adapters().sources()
    assert sources, "expected registered production sources"
    assert not set(sources) & set(PROVIDER_CATALOGUE.list_ids()), (
        "a production_source now collides with a provider id; re-check whether "
        "this registry has drifted into the provider key space"
    )


def test_providers_are_executable_but_have_no_facts():
    """20 providers are registered and describable by nothing."""
    from obase.provider_registry import ProviderRegistry

    from hevi.providers.registry import register_all_providers

    register_all_providers()
    described = (
        set(PROVIDER_CATALOGUE.list_ids())
        | set(PROVIDER_LIMITS)
        | set(RUNTIME_SPECS.list_ids())
    )
    undocumented = {name for _cat, name in ProviderRegistry.list_providers()} - described
    assert len(undocumented) >= 15, (
        f"only {len(undocumented)} registry-only providers remain; the catalogue "
        "backfill is progressing and this floor should be raised"
    )


def test_providers_are_documented_but_not_executable():
    """5 providers exist as setup prose with nothing behind them."""
    from obase.provider_registry import ProviderRegistry

    from hevi.provider_policy.runtime import PROVIDER_SPECS
    from hevi.providers.registry import register_all_providers

    register_all_providers()
    registered = {name for _cat, name in ProviderRegistry.list_providers()}
    spec_only = {s.provider_id for s in PROVIDER_SPECS} - registered
    assert len(spec_only) >= 4, f"spec-only providers shrank to {spec_only}"


# ------------------------------------------------------------ data integrity


def test_limits_entries_all_carry_a_verification_date():
    """`last_verified` exists because limits rot silently.

    The comment on the field says this table should not be trusted until it is
    re-checked. Enforcing presence here keeps the expiry mechanism honest.
    """
    for provider_id, limits in PROVIDER_LIMITS.items():
        assert limits.last_verified, f"{provider_id} has no verification date"
        assert d.is_dataclass(limits)


def test_locality_agrees_with_probeability():
    """The one dimension with no contradiction.

    Every `LOCAL` provider has a local health check, and every `REMOTE` one does
    not. Worth pinning precisely because it is the negative result: it says the
    divergence problem is specific to capability, not systemic.
    """
    local_health_kinds = {"local_process", "cli"}
    for provider_id in set(PROVIDER_CATALOGUE.list_ids()) & set(
        RUNTIME_SPECS.list_ids()
    ):
        profile = PROVIDER_CATALOGUE.get(provider_id)
        spec = RUNTIME_SPECS.get(provider_id)
        health = getattr(spec.health_check, "value", spec.health_check)
        if profile.locality.value == "LOCAL":
            assert health in local_health_kinds, (
                f"{provider_id} is LOCAL but probes as {health!r}"
            )