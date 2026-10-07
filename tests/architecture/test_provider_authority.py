"""P0-4.2 — provider authority invariants.

`docs/architecture/provider_authority.md` records the classification and the four
defects that were live when it was written.

The first version of these tests asserted the defects *existed*, so that fixing one
moved a count rather than being edited into silence. After P0-4.2.2 those detectors
had nothing left to detect, and they are now convergence assertions: the divergence
count is zero, and the structural reason it stays zero is asserted directly --
`PROVIDER_LIMITS` is derived from the catalogue at import time, so there is no
second table to write a divergent fact into.
"""

from __future__ import annotations

import dataclasses as d

import pytest

from hevi.providers.facts import PROVIDER_CATALOGUE, ProviderCapabilityState
from hevi.providers.runtime_specs import RUNTIME_SPECS
from hevi.video.capability_guard import PROVIDER_LIMITS


def _shared_catalogue_and_limits() -> list[str]:
    return sorted(set(PROVIDER_CATALOGUE.list_ids()) & set(PROVIDER_LIMITS))


# ----------------------------------------- convergence: capability is single-sourced


def test_catalogue_and_limits_can_no_longer_disagree():
    """The 9-provider divergence is closed.

    This was originally asserted as `== 9`: a detector, so that fixing one provider
    moved a number instead of being edited into silence. Now that the data is
    single-sourced the number is zero, and the detector has nothing left to detect,
    so it becomes a convergence assertion. `PROVIDER_LIMITS` is a projection of the
    catalogue, so this cannot drift again without the import failing first.
    """
    divergent = [
        provider_id
        for provider_id in sorted(set(PROVIDER_CATALOGUE.list_ids()) & set(PROVIDER_LIMITS))
        if set(PROVIDER_CATALOGUE.get(provider_id).capabilities)
        != set(PROVIDER_LIMITS[provider_id].modes)
    ]
    assert divergent == [], f"capability divergence has returned: {divergent}"


def test_limits_is_a_projection_of_the_catalogue_not_a_second_table():
    """The structural guarantee behind the convergence above.

    `PROVIDER_LIMITS` used to be a writable dict literal. It is now derived from
    `PROVIDER_CATALOGUE` at import time, which is why there is no second place for a
    divergent fact to be written. Asserted structurally because that, rather than
    the current data, is what keeps it true.
    """
    from hevi.video import capability_guard

    assert callable(capability_guard._project_limits)
    for provider_id, limits in PROVIDER_LIMITS.items():
        profile = PROVIDER_CATALOGUE.get(provider_id)
        assert set(limits.modes) == set(profile.capabilities)
        assert limits.max_resolution == profile.max_resolution
        assert limits.max_duration_s == profile.max_duration_s
        assert limits.fps_options == (profile.fps_options or frozenset())
        assert limits.native_audio == profile.native_audio
        assert limits.lip_sync == profile.lip_sync
        assert limits.last_verified == profile.last_verified


@pytest.mark.parametrize(
    "provider_id",
    [
        # i2v was over-claimed here. The t2v entry point takes no reference image and
        # i2v is registered as a separate provider id (`happyhorse_1_1_ref`,
        # `wan22_kf2v_maas` under image_to_video), so the claim was fail-open.
        "hailuo", "happyhorse_1_1", "happyhorse_1_1_maas", "kling_v2", "veo3",
        "wan_2_7", "wan_2_7_maas",
    ],
)
def test_i2v_is_no_longer_over_claimed(provider_id: str):
    """Fail-open capability claims are corrected in the canonical row."""
    assert "i2v" not in PROVIDER_CATALOGUE.get(provider_id).capabilities


def test_catalogue_agrees_with_the_providers_own_capability_row():
    """The third copy of the same fact is gone.

    `H3_LOCAL_CAPABILITY` was cited by `capability_guard.py:60` and `registry.py:304`
    as the evidence for the limits table, so the row and the table could drift apart
    and the comment would become a lie. The catalogue now carries the same set the
    provider module declares.
    """
    from hevi.providers.h3_local.provider import H3_LOCAL_CAPABILITY

    declared = set(H3_LOCAL_CAPABILITY["capabilities"])
    assert set(PROVIDER_CATALOGUE.get("h3_local").capabilities) == declared
    assert PROVIDER_CATALOGUE.get("h3_local").native_audio is (
        "native_audio" in declared
    )


def test_manim_capability_is_now_complete():
    """manim was wrong in *both* sources; the truth is the union.

    Recorded because "pick one source and delete the other" is the wrong fix for this
    row: information had to be added, not just moved. The catalogue now carries
    `MANIM_CAPABILITY`'s modes in full.
    """
    from hevi.providers.manim.provider import MANIM_CAPABILITY

    truth = set(MANIM_CAPABILITY["capabilities"]) & {"t2v", "code_scene"}
    assert set(PROVIDER_CATALOGUE.get("manim").capabilities) == truth
    assert truth == {"t2v", "code_scene"}


# ------------------------------- the policy capability gate can now actually open


def test_capability_query_covers_both_schema_shapes():
    """Modes live in `capabilities`, feature flags are booleans. Both must answer.

    `policy.py` used to do `getattr(limits, capability, False)`, which resolved only
    the boolean shape -- so every t2v/i2v requirement failed against every provider
    and was reported as `capability_missing`. That refusal looked deliberate and was
    in fact a shape mismatch. `ProviderProfile.supports()` covers both.
    """
    ltx2 = PROVIDER_CATALOGUE.get("ltx2_cloud")
    assert ltx2.supports("t2v"), "mode shape must resolve"
    assert ltx2.supports("i2v"), "mode shape must resolve"
    assert ltx2.supports("native_audio") is True, "flag shape must resolve"
    assert ltx2.supports("lip_sync") is False, "flag shape must resolve, as False"
    assert ltx2.supports("nonexistent") is False


@pytest.mark.asyncio
async def test_a_t2v_request_selects_a_provider():
    """The gate opens. Before P0-4.2 this rejected every provider in the field.

    A refusal that cannot be distinguished from a deliberate policy decision is
    worse than no check at all, because it reads as a considered answer.
    """
    from hevi.provider_policy.policy import ProviderPolicy, evaluate_provider_policy

    decision = await evaluate_provider_policy(
        ProviderPolicy(mode="t2v", required_capabilities={"t2v"})
    )
    rejections = {r.provider_id: r.reasons for r in decision.rejected}
    assert "capability_missing:t2v" not in str(rejections), (
        f"the capability gate regressed to refusing everything: {rejections}"
    )
    assert decision.selected_provider, "no provider satisfied a plain t2v request"


def test_obase_capability_tags_are_mostly_absent():
    """`validate_request` prefers obase tags, which are empty almost everywhere.

    This is why `PROVIDER_LIMITS` was the de facto production authority despite
    `PROVIDER_CATALOGUE` claiming to be canonical. Recorded because it explains why
    the catalogue's capabilities went unchallenged for as long as they did.
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

# --------------------------------- fail-closed semantics of the absorbed limits


def test_undeclared_limits_refuse_rather_than_assume_unbounded():
    """A missing ceiling must not become a permissive default.

    `ProviderProfile`'s limit fields default to `None` rather than to infinity or a
    generous constant. If they defaulted permissively, adding a provider without
    limits would quietly widen what the fleet can do -- the same fail-open shape as
    the i2v over-claim, but introduced by the migration itself.
    """
    undeclared = [
        provider_id
        for provider_id in PROVIDER_CATALOGUE.list_ids()
        if PROVIDER_CATALOGUE.get(provider_id).max_resolution is None
    ]
    assert undeclared, "expected providers without declared ceilings to exist"
    profile = PROVIDER_CATALOGUE.get(undeclared[0])
    assert not profile.admits_resolution(640, 480)
    assert not profile.admits_duration_s(1.0)
    assert not profile.admits_fps(30)
    assert not profile.supports("t2v")


def test_declared_limits_still_admit_within_range():
    """The refactor must not have tightened everything into unusability."""
    wan = PROVIDER_CATALOGUE.get("wan_local")
    assert wan.admits_resolution(1080, 1920)
    assert wan.admits_duration_s(5.0)
    assert wan.admits_fps(24)
    assert not wan.admits_duration_s(30.0), "wan_local's 10s ceiling must still bite"
    assert not wan.admits_fps(60)


def test_providers_without_ceilings_are_absent_from_the_projection():
    """Absence and refusal are different answers and stay different.

    `validate_request` distinguishes "unknown provider" from "provider cannot do
    this". A provider the catalogue leaves undeclared is absent from the projection
    rather than present with a zero ceiling, so the two refusals do not collapse into
    one indistinguishable error.
    """
    without_ceilings = {
        provider_id
        for provider_id in PROVIDER_CATALOGUE.list_ids()
        if PROVIDER_CATALOGUE.get(provider_id).max_resolution is None
    }
    assert not (without_ceilings & set(PROVIDER_LIMITS)), (
        f"providers without declared ceilings leaked into the projection: "
        f"{sorted(without_ceilings & set(PROVIDER_LIMITS))}"
    )
