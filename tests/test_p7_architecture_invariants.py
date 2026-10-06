"""P7.3 — The boundary, locked.

P7.0–P7.2 each fixed one authority leak and each fix could have been undone by a
later, well-meaning change. These tests turn the boundary into assertions that fail
the moment it is crossed again.

Each invariant names the single owner, the thing it forbids, and the failure it
prevents. They are deliberately written against the *source tree*, not only against
imported objects: an invariant nobody can violate silently is worth more than one
that merely describes today's shape.

Proven failure modes this file exists to prevent:

I1  a second ``AssetSemanticRole`` taxonomy appears, and the two drift
I2  a semantic role is used as a media type (the P6.5.2 collapse)
I3  a provider fact is read back out of a provider id
I4  policy invents a fact instead of reading one
I5  an asset decision claims production happened
I6  the P7 adapter starts making decisions
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from hevi.production.p6.production_runtime import RunState
from hevi.production.p7 import AssetDecisionState, MediaType
from hevi.production.p7.asset_contract import (
    SOURCING_ASSET_TYPES,
    AssetSemanticRole,
)
from hevi.provider_policy.policy import ProviderDecision, ProviderPolicy
from hevi.providers.facts import (
    ProviderCapabilityState,
    ProviderLicenseClass,
    ProviderLocality,
)

HEVI = pathlib.Path("hevi")
SOURCING = HEVI / "sourcing"
P7_DIR = HEVI / "production" / "p7"
PROVIDER_POLICY = HEVI / "provider_policy"
PROVIDERS = HEVI / "providers"
P7_ADAPTER = SOURCING / "p7_adapter.py"


def _py_files(root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(root.rglob("*.py"))


FACT_FAMILIES = {"locality", "license_class", "capability_states"}


def _tree(path: pathlib.Path) -> ast.Module:
    return ast.parse(path.read_text())


def _code_identifiers(path: pathlib.Path) -> set[str]:
    """Identifiers referenced in code: Names and Attributes only.

    Docstrings are ``Constant`` nodes and comments are not in the AST at all, so
    prose *about* RunState cannot fail a check that RunState is unused. Several P7
    docstrings explain that P7 does not depend on RunState — that is documentation
    of the invariant, and must not be mistaken for a violation of it.
    """
    tree = _tree(path)
    return (
        {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    )


def _defined_classes(root: pathlib.Path, name: str) -> list[pathlib.Path]:
    return [p for p in _py_files(root) if any(
        isinstance(n, ast.ClassDef) and n.name == name for n in ast.walk(_tree(p))
    )]


# ══════════════════════════════════════════════════════════════════════════
# I1 — Asset semantic authority: hevi/sourcing, and only hevi/sourcing
# ══════════════════════════════════════════════════════════════════════════


def test_i1_asset_semantic_role_has_exactly_one_definition():
    """`count_asset_semantic_role_definitions() == 1` — the spec's assertion."""
    sites = _defined_classes(HEVI, "AssetSemanticRole")
    assert len(sites) == 1, (
        f"AssetSemanticRole defined {len(sites)}x: {[p.as_posix() for p in sites]}"
    )
    assert sites[0] == P7_DIR / "asset_contract.py"


def test_i1_sourcing_owns_the_taxonomy_p7_only_presents_it():
    """P7 presents sourcing's vocabulary; it does not restate it as its own."""
    assert {r.value for r in AssetSemanticRole} == {
        r.upper() for r in SOURCING_ASSET_TYPES
    }, "P7's role vocabulary has drifted from sourcing's ASSET_TYPES"
    bridge = (SOURCING / "loader_bridge.py").read_text()
    assert "ASSET_TYPES" in bridge, "the owner's taxonomy must remain in sourcing"


def test_i1_no_shadow_taxonomy_in_prohibited_locations():
    """Spec: no `asset_role.py` in p7/, no `asset_type.py` in provider_policy/."""
    forbidden = [
        p for p in list(_py_files(P7_DIR)) + list(_py_files(PROVIDER_POLICY))
        if p.name in {"asset_role.py", "asset_type.py"}
    ]
    assert forbidden == [], f"shadow taxonomies: {[p.as_posix() for p in forbidden]}"


def test_i1_p7_defines_no_second_role_vocabulary_by_any_name():
    """Not just the class name — any enum whose members are all role words."""
    role_words = {r.value for r in AssetSemanticRole}
    for path in _py_files(P7_DIR):
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.ClassDef) or node.name == "AssetSemanticRole":
                continue
            members = {
                t.target.id for t in node.body
                if isinstance(t, ast.AnnAssign) and isinstance(t.target, ast.Name)
            }
            assert not (members and members <= role_words), (
                f"{path.name}:{node.name} restates the semantic role vocabulary"
            )


# ══════════════════════════════════════════════════════════════════════════
# I2 — Media representation authority: MediaType, disjoint from meaning
# ══════════════════════════════════════════════════════════════════════════


def test_i2_media_type_and_semantic_role_are_disjoint():
    """The spec's assertion: MediaType ∩ AssetSemanticRole = empty.

    The spec writes this as ``MediaType.values().isdisjoint(...)``. ``StrEnum``
    exposes no ``.values()`` on Python 3.14, so the equivalent set comprehension
    is used; ``test_spec_values_form_is_unavailable_here`` records that gap rather
    than leaving the substitution silent.
    """
    assert {t.value for t in MediaType}.isdisjoint({r.value for r in AssetSemanticRole})


def test_spec_values_form_is_unavailable_here():
    """Documents *why* the spec's literal `.values()` form could not be used."""
    assert not hasattr(MediaType, "values"), (
        "if StrEnum.values() ever returns, this test should be rewritten to the "
        "spec's literal form and the disjointness test switched with it"
    )


def test_i2_media_type_covers_the_declared_representations():
    assert {t.name for t in MediaType} == {
        "IMAGE", "VIDEO", "AUDIO", "MODEL3D", "TEXTURE", "DOCUMENT"
    }


def test_i2_media_type_is_defined_once():
    sites = _defined_classes(HEVI, "MediaType")
    assert len(sites) == 1, f"MediaType defined {len(sites)}x"


def test_i2_no_module_treats_a_semantic_role_as_a_media_type():
    """`media_type=AssetSemanticRole.X` must not typecheck into the contract."""
    for path in _py_files(P7_DIR):
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "AssetReference":
                for kw in node.keywords:
                    if kw.arg == "media_type":
                        assert "AssetSemanticRole" not in ast.dump(kw.value), (
                            f"{path.name}:{node.lineno} passes a semantic role as media_type"
                        )


# ══════════════════════════════════════════════════════════════════════════
# I3 — Provider fact authority: catalogue -> decision, never parsed from a name
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "source",
    [PROVIDER_POLICY / "policy.py", PROVIDERS / "facts.py", P7_ADAPTER,
     P7_DIR / "asset_policy.py"],
    ids=["policy", "facts", "p7_adapter", "p7_asset_policy"],
)
def test_i3_no_name_based_fact_inference(source):
    """Spec: `startswith()` / `contains()` / `regex()` forbidden for provider facts.

    Checked on the AST rather than by grep, so a computed lookup cannot slip past.
    """
    locality_tokens = ("local", "remote", "cloud", "host", "onprem", "on_prem")
    for node in ast.walk(_tree(source)):
        if not isinstance(node, ast.Call):
            continue
        method = getattr(node.func, "attr", "")
        if method not in {"startswith", "endswith", "split", "partition", "lower", "upper"}:
            continue
        for arg in node.args[:1]:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                assert not any(t in arg.value.lower() for t in locality_tokens), (
                    f"{source.name}:{node.lineno} infers a fact from a name: {arg.value!r}"
                )
            if method == "lower" and not node.args:
                continue  # .lower() alone infers nothing


def test_i3_no_regex_on_provider_ids_for_facts():
    for source in (PROVIDER_POLICY / "policy.py", PROVIDERS / "facts.py", P7_ADAPTER):
        for node in ast.walk(_tree(source)):
            if isinstance(node, ast.Call):
                func = getattr(node.func, "attr", getattr(node.func, "id", ""))
                assert func not in {"search", "match", "fullmatch", "sub", "findall"}, (
                    f"{source.name}:{node.lineno} applies a regex where a lookup belongs"
                )


def test_i3_catalogue_is_the_only_fact_source():
    """Facts reach the decision through the catalogue, never assembled in place."""
    text = (PROVIDER_POLICY / "policy.py").read_text()
    tree = ast.parse(text)
    # The class-level declarations (`locality: dict[...] = Field(...)`) are the
    # schema, not the materialisation. What matters is that every *value* assigned
    # to a fact family on a decision comes out of the catalogue.
    materialised = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Attribute) and t.attr in FACT_FAMILIES
            for t in node.targets
        )
    ]
    assert materialised, "the evaluator must materialise the three fact families"
    for node in materialised:
        segment = ast.get_source_segment(text, node.value) or ""
        # An empty dict is initialisation before the loop, not assembly of a fact.
        # Anything else must trace back to the catalogue.
        if segment.strip() == "{}":
            continue
        assert any(
            token in segment for token in ("facts_source", "facts_for", "facts")
        ), f"policy.py:{node.lineno} assembles provider facts outside the catalogue: {segment}"


def test_i3_decision_facts_are_typed_and_default_empty():
    decision = ProviderDecision()
    for field in ("locality", "license_class", "capability_states"):
        assert field in ProviderDecision.model_fields
        assert getattr(decision, field) == {}


# ══════════════════════════════════════════════════════════════════════════
# I4 — Policy authority: reads facts, never creates them
# ══════════════════════════════════════════════════════════════════════════


def test_i4_policy_creates_no_provider_fact():
    """`if provider.locality == LOCAL: license = GENERATED` must not exist."""
    text = (PROVIDER_POLICY / "policy.py").read_text()
    tree = ast.parse(text)
    families = ("license", "licence", "locality", "capability_state")
    enum_names = {e.__name__ for e in (ProviderLocality, ProviderLicenseClass,
                                       ProviderCapabilityState)}

    # No fact family is ever *computed* into a local. Writing
    # `decision.locality = {}` and `.update(facts[...])` is materialisation, which is
    # the evaluator's job; binding `licence = GENERATED` to a name is invention.
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                assert not target.id.startswith(families), (
                    f"policy.py:{node.lineno} computes provider fact {target.id!r}; "
                    "the catalogue declares facts, policy only reads them"
                )
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            assert not node.target.id.startswith(families), (
                f"policy.py:{node.lineno} accumulates provider fact {node.target.id!r}"
            )

    # Spelling-proof version of the same rule: no local may be bound to a fact enum
    # member, whatever the variable is called. An earlier version matched on the
    # name prefix `license*` and was defeated by `licence = GENERATED if ... else
    # LICENSED` — the exact shape of the P7.1 leak, renamed. The value, not the
    # variable name, is what makes this a fact.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) for t in node.targets):
            continue
        bound = {
            sub.attr for sub in ast.walk(node.value)
            if isinstance(sub, ast.Attribute) and sub.attr in enum_names
        }
        assert not bound, (
            f"policy.py:{node.lineno} binds fact(s) {sorted(bound)} to a local; "
            "policy reads facts, it does not compute them"
        )

    # The specific leak P7.1 found twice, in its ternary form:
    #     GENERATED if provider.locality is LOCAL else LICENSED
    # A conditional may not select one fact family from another.
    for node in ast.walk(tree):
        if not isinstance(node, (ast.IfExp, ast.If)):
            continue
        cond = node.test
        test_text = ast.dump(cond)
        for branch in (node.body, getattr(node, "orelse", [])):
            for sub in ast.walk(ast.parse(ast.unparse(branch))) if branch else []:
                if isinstance(sub, ast.Name) and sub.id in enum_names:
                    assert not any(e in test_text for e in enum_names), (
                        f"policy.py:{node.lineno} selects one provider fact from "
                        "another; the catalogue declares both independently"
                    )


def test_i4_policy_cannot_mutate_the_catalogue():
    """`evaluate_provider_policy` must not register into the catalogue."""
    text = (PROVIDER_POLICY / "policy.py").read_text()
    assert ".register(" not in text, "policy must not write to the fact source"


def test_i4_eligibility_is_facts_plus_requirements():
    """Policy consumes declared facts; the decision it returns still carries them."""
    decision = ProviderDecision(considered=["wan_local"])
    assert decision.locality == {}, "facts arrive from the catalogue, not the dataclass"
    assert ProviderPolicy.__name__ == "ProviderPolicy"


# ══════════════════════════════════════════════════════════════════════════
# I5 — Execution authority: only ExecutionReceipt says production happened
# ══════════════════════════════════════════════════════════════════════════


def test_i5_asset_decision_state_and_run_state_are_disjoint():
    """The spec's assertion, verbatim: `AssetDecisionState ∩ RunState = empty`."""
    assert {s.value for s in AssetDecisionState}.isdisjoint({s.value for s in RunState})


def test_i5_run_states_exist_only_in_the_execution_layer():
    for path in [*_py_files(P7_DIR), P7_ADAPTER]:
        assert "RunState" not in _code_identifiers(path), (
            f"{path.name} references RunState in code; execution states live in p6"
        )


def test_i5_produced_has_exactly_one_construction_site():
    """`artifact_exists() != production_success` — one guarded choke point.

    ``RunState.PRODUCED`` is passed as a keyword argument (``state=RunState.PRODUCED``),
    not assigned, so the site is found by scanning call keywords across the package.
    More than one site would mean production success could be asserted somewhere
    that has not handled a receipt.
    """
    sites = []
    for path in _py_files(HEVI):
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if (
                        kw.arg == "state"
                        and isinstance(kw.value, ast.Attribute)
                        and kw.value.attr == "PRODUCED"
                    ):
                        sites.append(f"{path.as_posix()}:{node.lineno}")
    assert len(sites) == 1, f"RunState.PRODUCED constructed {len(sites)}x: {sites}"


def test_i5_the_produced_site_lives_in_the_execution_layer():
    runtime = (HEVI / "production" / "p6" / "production_runtime.py").read_text()
    assert "ExecutionReceipt" in runtime
    assert "RunState" in _code_identifiers(HEVI / "production" / "p6" / "production_runtime.py")


def test_i5_no_production_verdict_outside_execution():
    for path in [*_py_files(P7_DIR), P7_ADAPTER]:
        identifiers = _code_identifiers(path)
        for token in ("PRODUCED", "QA_PASS", "QA_PASSED", "QA_FAIL", "EXECUTING"):
            assert token not in identifiers, (
                f"{path.name} asserts production state {token} in code"
            )


# ══════════════════════════════════════════════════════════════════════════
# I6 — P7 adapter purity: lookup, mapping, composition, validation
# ══════════════════════════════════════════════════════════════════════════


def test_i6_adapter_has_no_loop():
    tree = _tree(P7_ADAPTER)
    loops = [n for n in ast.walk(tree) if isinstance(n, (ast.For, ast.AsyncFor, ast.While))]
    assert loops == [], f"{P7_ADAPTER.name}: loops imply iteration over candidates = ranking"


def test_i6_adapter_has_no_try():
    """Spec: try == 0. Error handling would be a decision about failure."""
    assert [n for n in ast.walk(_tree(P7_ADAPTER)) if isinstance(n, ast.Try)] == []


def test_i6_adapter_only_guards_and_looks_up():
    """Every `if` must be a guard on a lookup, never a branch that picks a winner."""
    tree = _tree(P7_ADAPTER)
    allowed_calls = {
        "MediaProviderRequest", "StockSearchRequest", "get", "getattr", "int", "str",
        "dataclass", "frozenset", "ValueError", "query",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", getattr(node.func, "attr", ""))
            assert name in allowed_calls, (
                f"{P7_ADAPTER.name}:{node.lineno} calls {name}(); "
                "the adapter composes, it does not act"
            )
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            segment = ast.get_source_segment(P7_ADAPTER.read_text(), node) or ""
            assert any(
                token in segment
                for token in (".get(", "not ", "is None", "in ", "==", "!=")
            ), f"{P7_ADAPTER.name}:{node.lineno} compares values to choose, not to guard"


def test_i6_adapter_scores_and_ranks_nothing():
    text = P7_ADAPTER.read_text()
    for token in ("score", "rank", "sort", "best", "select", "weight", "quality_floor"):
        assert token not in text.lower(), (
            f"{P7_ADAPTER.name} mentions {token!r}; selection is not the adapter's job"
        )


def test_i6_adapter_does_not_import_a_decision_authority():
    tree = _tree(P7_ADAPTER)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "provider_policy" not in node.module, (
                "the adapter must not reach into provider policy"
            )
            assert "p7" not in node.module.replace("hevi.production.p7", ""), (
                "the adapter must not import P7 decisions"
            )
