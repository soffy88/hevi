"""P8.1.5 — Observation coverage, without a second identity or a second probe.

P8.1 was correct and nearly useless: 2 of 16 catalogue providers had any declared
way to be observed, so every video provider reported ``UNKNOWN`` and P8.2 would have
qualified infrastructure rather than the production fleet.

Closing that gap is exactly the kind of change that quietly becomes a fork. A runtime
coverage table is a natural place to start restating what a provider *is* — it already
lists every provider id, so adding ``locality`` next to it feels harmless and is not.
These tests hold the line:

* coverage is **declared**, and gaps are named rather than defaulted away
* the table describes **how to observe**, never **what a provider is**
* env var **names** only; a value would be a secret in source
* no HTTP client, because a probe already exists and a second one would be a fork
* no control flow branches on a provider id; lookups are how you reach the data
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib

import pytest

from hevi.provider_policy.runtime import PROVIDER_SPECS
from hevi.providers.facts import PROVIDER_CATALOGUE, ProviderKind, ProviderProfile
from hevi.providers.runtime_specs import (
    RUNTIME_SPECS,
    HealthCheckKind,
    ProviderRuntimeSpec,
    RuntimeSpecRegistry,
    combined_coverage_report,
    coverage_report,
    get_runtime_spec,
    observed_provider_ids,
)
from hevi.runtime.provider.models import ProviderRuntimeStatus

SPECS_SRC = pathlib.Path("hevi/providers/runtime_specs.py")


# ══════════════════════════════════════════════════════════════════════════
# R2 — coverage is reported, and gaps are explicable
# ══════════════════════════════════════════════════════════════════════════


def test_coverage_report_is_produced():
    report = combined_coverage_report()
    assert report["total_catalogue"] == 20
    assert report["observed"] + report["unobserved"] == report["total_catalogue"]


def test_coverage_is_much_wider_than_p8_1_managed():
    """P8.1 observed 2 of 16. The video fleet must no longer be invisible."""
    report = combined_coverage_report()
    assert report["observed"] >= 15, (
        f"only {report['observed']}/{report['total_catalogue']} observable; "
        "P8.1's gap was 2"
    )


def test_every_gap_is_named_and_explained():
    """A gap that is counted but not named cannot be acted on."""
    report = combined_coverage_report()
    assert set(report["unobserved_reasons"]) == set(report["unobserved_ids"])
    for provider_id in report["unobserved_ids"]:
        assert report["unobserved_reasons"][provider_id]


def test_unobserved_ids_are_real_catalogue_members():
    catalogue = set(PROVIDER_CATALOGUE.list_ids())
    report = combined_coverage_report()
    assert set(report["unobserved_ids"]) <= catalogue


def test_wan_cloud_gap_is_documented_not_invented():
    """wan_cloud has no endpoint or credential anywhere in the codebase.

    P8.1.5 could have declared a plausible-looking fal endpoint to reach 16/16. It
    does not, because a declared observation that was never grounded is worse than an
    honest gap: it would report a provider as observable when nothing can check it.
    """
    report = combined_coverage_report()
    assert "wan_cloud" in report["unobserved_ids"]
    assert get_runtime_spec("wan_cloud") is None


def test_coverage_accounts_for_both_registries():
    """The P8.1 gap was visible only because nobody added the two up."""
    assert observed_provider_ids() == (
        set(RUNTIME_SPECS.list_ids()) | {s.provider_id for s in PROVIDER_SPECS}
    )
    assert {"voicebox", "longcat"} <= observed_provider_ids()
    assert "wan_local" in observed_provider_ids()


def test_registry_only_report_is_still_available():
    assert coverage_report()["total_catalogue"] == 20


# ══════════════════════════════════════════════════════════════════════════
# R1 — identity stays with the catalogue
# ══════════════════════════════════════════════════════════════════════════


def test_runtime_spec_has_only_observation_fields():
    names = {f.name for f in dataclasses.fields(ProviderRuntimeSpec)}
    assert names == {
        "provider_id", "health_check", "auth_requirements", "target", "notes"
    }


@pytest.mark.parametrize(
    "forbidden",
    ["locality", "license", "license_class", "capabilities", "capability_state",
     "quality", "ranking", "kind", "status"],
)
def test_runtime_spec_declares_no_provider_fact(forbidden):
    """A `locality` field here would be a second fact source.

    Local providers are declared LOCAL_PROCESS *because that is how they are
    observed*, not because of what they are. Encoding the second would let an
    observation override identity.
    """
    names = {f.name for f in dataclasses.fields(ProviderRuntimeSpec)}
    assert forbidden not in names


def test_spec_module_defines_no_fact_field_or_enum():
    tree = ast.parse(SPECS_SRC.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assert not node.target.id.startswith(
                ("locality", "license", "licence", "capability", "quality")
            ), f"runtime_specs.py:{node.lineno} declares fact {node.target.id}"
        if isinstance(node, ast.ClassDef):
            assert not node.name.startswith("ProviderProfile")


def test_spec_module_does_not_write_to_the_catalogue():
    text = SPECS_SRC.read_text()
    assert ".register(" not in text.split("class RuntimeSpecRegistry")[0], (
        "the module-level seed must not register into ProviderCatalogue"
    )


def test_runtime_specs_cannot_mutate_the_catalogue():
    """Uses a local registry: registering into the module-level one would leak into
    every later test, which is how a spec table starts shadowing real coverage."""
    before = PROVIDER_CATALOGUE.to_dict()
    local = RuntimeSpecRegistry()
    local.register(ProviderRuntimeSpec("transient.probe", HealthCheckKind.HTTP, ("X_KEY",)))
    assert local.has("transient.probe")
    assert PROVIDER_CATALOGUE.to_dict() == before
    assert PROVIDER_CATALOGUE.get("transient.probe") is None
    assert "transient.probe" not in RUNTIME_SPECS.list_ids()


def test_unknown_provider_has_no_spec_and_no_invented_facts():
    assert get_runtime_spec("not.a.provider") is None
    with pytest.raises(KeyError, match="NO_RUNTIME_SPEC"):
        RUNTIME_SPECS.resolve("not.a.provider")


def test_duplicate_spec_registration_is_refused():
    with pytest.raises(ValueError, match="RUNTIME_SPEC_DUPLICATE"):
        RUNTIME_SPECS.register(get_runtime_spec("wan_local"))


# ══════════════════════════════════════════════════════════════════════════
# R3 — no provider-id branching; the table is data
# ══════════════════════════════════════════════════════════════════════════


def test_no_control_flow_branches_on_a_provider_id():
    """`if provider_id == "veo3"` is forbidden; `RUNTIME_SPECS["veo3"]` is the point."""
    tree = ast.parse(SPECS_SRC.read_text())
    catalogue = set(PROVIDER_CATALOGUE.list_ids())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        for operand in operands:
            if isinstance(operand, ast.Constant) and operand.value in catalogue:
                raise AssertionError(
                    f"{SPECS_SRC.name}:{node.lineno} compares against provider id "
                    f"{operand.value!r}; use RUNTIME_SPECS[{operand.value!r}] instead"
                )


def test_no_provider_id_string_literals_in_control_flow():
    """Stronger form: provider ids may appear only as spec data, never in a branch."""
    tree = ast.parse(SPECS_SRC.read_text())
    catalogue = set(PROVIDER_CATALOGUE.list_ids())
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Compare, ast.If, ast.IfExp)):
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Constant)
                    and isinstance(sub.value, str)
                    and sub.value in catalogue
                ):
                    offenders.append(f"{SPECS_SRC.name}:{sub.lineno} {sub.value}")
    assert offenders == [], f"provider id used in control flow: {offenders}"


def test_spec_ids_come_from_the_catalogue():
    """Every declared provider is a real catalogue member, not an invented one."""
    for provider_id in RUNTIME_SPECS.list_ids():
        assert PROVIDER_CATALOGUE.get(provider_id) is not None, (
            f"{provider_id} has a runtime spec but no catalogue entry"
        )


# ══════════════════════════════════════════════════════════════════════════
# R4 — health check kinds are not unified behind HTTP
# ══════════════════════════════════════════════════════════════════════════


def test_four_health_check_kinds_exist():
    assert {k.value for k in HealthCheckKind} == {
        "http", "cli", "local_process", "queue"
    }


def test_the_video_fleet_uses_more_than_one_kind():
    """Forcing everything into HTTP is the failure R4 exists to prevent."""
    kinds = {s.health_check for s in RUNTIME_SPECS.by_kind(HealthCheckKind.HTTP)}
    assert len(kinds) >= 1
    used = {kind.value for kind in HealthCheckKind
            if RUNTIME_SPECS.by_kind(kind)}
    assert len(used) >= 3, f"only {used} kinds in use; coverage looks nominal, not real"


def test_local_providers_are_declared_as_local_mechanisms():
    """Grounded in how they actually run, not in what they are called.

    This is the assertion that would break if someone 'fixed' the specs by inferring
    a kind from the provider's name — the exact defect P7.1 removed elsewhere.
    """
    assert RUNTIME_SPECS.resolve("wan_local").health_check is HealthCheckKind.CLI
    assert RUNTIME_SPECS.resolve("ltx2_local").health_check is HealthCheckKind.CLI
    assert RUNTIME_SPECS.resolve("h3_local").health_check is HealthCheckKind.LOCAL_PROCESS
    assert RUNTIME_SPECS.resolve("manim").health_check is HealthCheckKind.LOCAL_PROCESS


def test_hosted_providers_are_declared_as_remote_mechanisms():
    assert RUNTIME_SPECS.resolve("veo3").health_check is HealthCheckKind.QUEUE
    assert RUNTIME_SPECS.resolve("wan_2_7").health_check is HealthCheckKind.HTTP


def test_ltx2_local_is_not_local_because_of_its_name():
    """It routes to wan_local, so CLI is right — and it was declared, not inferred."""
    spec = RUNTIME_SPECS.resolve("ltx2_local")
    assert spec.health_check is HealthCheckKind.CLI
    assert "wan_local" in spec.notes


def test_unknown_health_check_kind_is_refused():
    with pytest.raises(ValueError, match="UNKNOWN_HEALTH_CHECK_KIND"):
        ProviderRuntimeSpec(provider_id="x", health_check="carrier_pigeon")


# ══════════════════════════════════════════════════════════════════════════
# R5 — auth stays out of runtime status
# ══════════════════════════════════════════════════════════════════════════


def test_auth_requirements_hold_names_only():
    """Names are configuration. A value in source is a leaked secret."""
    for provider_id in RUNTIME_SPECS.list_ids():
        spec = RUNTIME_SPECS.resolve(provider_id)
        for name in spec.auth_requirements:
            assert name.isupper(), f"{provider_id}: {name!r} is not a variable name"
            assert "=" not in name and " " not in name


def test_lowercase_auth_requirement_is_refused():
    with pytest.raises(ValueError, match="AUTH_REQUIREMENT_MUST_BE_A_NAME"):
        ProviderRuntimeSpec(
            provider_id="x", health_check=HealthCheckKind.HTTP,
            auth_requirements=("sk-live-abc123",),
        )


def test_no_environment_value_appears_in_the_specs_module():
    text = SPECS_SRC.read_text()
    for marker in ("sk-", "Bearer ", "token=", "api_key=", "secret="):
        assert marker not in text, f"possible secret material in specs: {marker!r}"


def test_runtime_status_carries_no_auth_material():
    """P8.1's boundary, re-asserted against the new registry."""
    names = {f.name for f in dataclasses.fields(ProviderRuntimeStatus)}
    for forbidden in ("token", "endpoint", "env", "credential", "auth", "api_key"):
        assert forbidden not in names
    spec = RUNTIME_SPECS.resolve("veo3")
    assert spec.auth_requirements, "the spec does declare its credential requirement"
    status = ProviderRuntimeStatus(provider_id="veo3")
    assert "FAL_API_KEY" not in str(status.to_dict())


def test_credentialed_providers_are_listed():
    assert set(RUNTIME_SPECS.credentialed_ids()) <= set(RUNTIME_SPECS.list_ids())
    assert "veo3" in RUNTIME_SPECS.credentialed_ids()
    assert "wan_local" not in RUNTIME_SPECS.credentialed_ids()


# ══════════════════════════════════════════════════════════════════════════
# no second probe client
# ══════════════════════════════════════════════════════════════════════════


def test_specs_module_contains_no_network_or_process_client():
    """Checked on the AST, not the text.

    The module docstring says "driven through subprocess" because that is *why* the
    kind is CLI. A text scan cannot tell describing a mechanism from invoking one.
    """
    tree = ast.parse(SPECS_SRC.read_text())
    banned = {"httpx", "aiohttp", "requests", "urllib", "socket", "subprocess",
              "curl", "shutil", "urlopen", "Popen", "check_output"}
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", getattr(node.func, "attr", ""))
            assert name not in banned, f"runtime_specs.py calls {name}()"
    assert not (imported & banned), f"runtime_specs.py imports {imported & banned}"


def test_specs_module_defines_no_probe_functions():
    """A method named like a probe would be a probe. `.get` is a lookup, not one."""
    tree = ast.parse(SPECS_SRC.read_text())
    methods = [
        n.name for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    for banned in ("probe", "fetch", "download", "render", "generate", "execute",
                   "submit", "ping"):
        assert not any(banned in m for m in methods), (
            f"runtime_specs.py defines a {banned}* function; it declares, it does not act"
        )
    assert not any(
        isinstance(n, ast.AsyncFunctionDef) for n in ast.walk(tree)
    ), "runtime_specs.py declares no async work"


def test_the_existing_probe_remains_the_only_one():
    from hevi.provider_policy.runtime import probe_provider

    assert callable(probe_provider)
    assert probe_provider.__module__ == "hevi.provider_policy.runtime"


# ══════════════════════════════════════════════════════════════════════════
# registry mechanics
# ══════════════════════════════════════════════════════════════════════════


def test_spec_requires_a_provider_id():
    with pytest.raises(ValueError, match="RUNTIME_SPEC_WITHOUT_ID"):
        ProviderRuntimeSpec(provider_id="", health_check=HealthCheckKind.HTTP)


def test_registry_lookup_and_listing():
    assert "wan_local" in RUNTIME_SPECS.list_ids()
    assert RUNTIME_SPECS.has("wan_local")
    assert not RUNTIME_SPECS.has("nope")
    assert set(RUNTIME_SPECS.to_dict()) == set(RUNTIME_SPECS.list_ids())


def test_empty_registry_reports_gaps_rather_than_hiding_them():
    empty = RuntimeSpecRegistry()
    report = empty.coverage_report()
    assert report["probeable"] == 0
    assert report["unobserved"] == report["total_catalogue"]
    assert report["full_coverage"] is False


def test_spec_round_trips_to_dict():
    spec = RUNTIME_SPECS.resolve("kling_v2")
    payload = spec.to_dict()
    assert payload["provider_id"] == "kling_v2"
    assert payload["health_check"] == "queue"
    assert isinstance(payload["auth_requirements"], list)


def test_no_spec_declares_a_provider_profile_subclass():
    """Belt and braces: the spec type is not a fact type in disguise."""
    assert not issubclass(ProviderRuntimeSpec, ProviderProfile)
    assert not issubclass(ProviderRuntimeSpec, ProviderKind)
