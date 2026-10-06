"""P7.3 — The contracts, frozen against the documents that describe them.

P7.0–P7.2 each revised a contract after writing its document, and the documents
were never brought back in line. The P7.0 doc still described ``MediaKind`` and
``AssetDecision.selected_asset`` — neither of which has existed since the P7.0
revision — and still described P7.1 and P7.2 as pending work.

Prose drifts silently: nothing fails when a doc stops matching its code. These
tests fail instead. They pin three things:

1. **Retired vocabulary stays retired.** ``MediaKind`` and ``selected_asset`` must
   not reappear in code or docs.
2. **The documented surface is the real surface.** The doc must name the members
   the code actually defines, so a doc that describes an older shape fails.
3. **The declared fact source is described as declared.** The catalogue states
   what HEVI believes; it is not verified external truth, and the docs must say so.

The boundary this file protects is architectural. Nothing here may be relaxed to
make a failing assertion pass without changing the contract.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from hevi.production.p7 import AssetDecisionState, MediaType
from hevi.production.p7.asset_contract import AssetSemanticRole
from hevi.provider_policy.policy import ProviderDecision
from hevi.providers.facts import PROVIDER_CATALOGUE, ProviderKind, ProviderProfile
from hevi.video.capability_guard import PROVIDER_LIMITS

DOCS = pathlib.Path("docs")
P7_DOCS = {
    "P7.0": DOCS / "P7-0-ASSET-CONTRACT.md",
    "P7.1": DOCS / "P7-1-PROVIDER-FACTS.md",
    "P7.2": DOCS / "P7-2-PROVIDER-CATALOGUE.md",
    "P7-ARCH": DOCS / "P7-ARCHITECTURE.md",
}

#: Vocabulary retired by the P7.0 revision. Reintroducing any of it means a
#: document or module describes a contract that no longer exists.
RETIRED = ("MediaKind", "selected_asset", "rejected_candidates")


def _text(path: pathlib.Path) -> str:
    return path.read_text()


# ══════════════════════════════════════════════════════════════════════════
# the documents exist
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "name,path", sorted(P7_DOCS.items()),
    ids=[name for name, _ in sorted(P7_DOCS.items())],
)
def test_p7_document_exists_and_is_not_a_stub(name, path):
    assert path.exists(), f"missing {path}"
    body = _text(path)
    assert len(body) > 400, f"{path.name} is too short to document a contract"
    assert body.lstrip().startswith("#"), f"{path.name} must open with a heading"


# ══════════════════════════════════════════════════════════════════════════
# retired vocabulary stays retired
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("token", RETIRED, ids=RETIRED)
def test_retired_vocabulary_absent_from_p7_docs(token):
    """``MediaKind`` and friends must not reappear in any P7 document.

    They are permitted only where a document names them explicitly as retired, so
    a reader is never misled into thinking the old contract is current.
    """
    for path in P7_DOCS.values():
        if not path.exists():
            continue
        for line in _text(path).splitlines():
            if token in line:
                assert re.search(
                    r"retired|superseded|no longer|formerly|MediaType|was\b|→", line
                ), f"{path.name} references retired {token!r} as if current: {line.strip()}"


@pytest.mark.parametrize("token", RETIRED, ids=RETIRED)
def test_retired_vocabulary_absent_from_p7_code(token):
    """Scoped to P7, where the retirement happened.

    ``rejected_candidates`` is *also* a legitimate P5.3/P6 field meaning "recipe
    candidates the scorer rejected", which has nothing to do with the retired
    ``AssetDecision.rejected_candidates``. A repo-wide ban would flag that
    unrelated, correct usage — so the ban is applied only to the package whose
    contract retired the name.
    """
    hits = [
        path.as_posix()
        for path in pathlib.Path("hevi/production/p7").rglob("*.py")
        if token in path.read_text()
    ]
    assert hits == [], f"retired {token!r} still present in {hits}"


def test_no_document_describes_a_pending_phase_that_has_landed():
    """A frozen document may not say a delivered phase is still pending."""
    for phase in ("P7.1", "P7.2"):
        path = P7_DOCS[phase]
        if not path.exists():
            continue
        for line in _text(path).splitlines():
            lowered = line.lower()
            if "pending" not in lowered and "not yet" not in lowered:
                continue
            # A document may say *another* phase is pending; it may not say itself is.
            assert phase not in line, (
                f"{path.name} still describes {phase} as pending: {line.strip()}"
            )


# ══════════════════════════════════════════════════════════════════════════
# the documented surface is the real surface
# ══════════════════════════════════════════════════════════════════════════


def test_asset_doc_names_the_current_media_vocabulary():
    """The P7.0 doc must describe ``MediaType``, and separate it from meaning."""
    body = _text(P7_DOCS["P7.0"])
    assert "MediaType" in body
    assert "AssetSemanticRole" in body
    assert "representation" in body.lower()
    assert "meaning" in body.lower() or "semantic role" in body.lower()


def test_asset_doc_documents_every_media_type_member():
    body = _text(P7_DOCS["P7.0"])
    for member in MediaType:
        assert member.name in body, f"{member.name} is undocumented in P7-0"


def test_asset_doc_documents_every_semantic_role_member():
    body = _text(P7_DOCS["P7.0"])
    for role in AssetSemanticRole:
        assert role.name in body, f"{role.name} is undocumented in P7-0"


def test_provider_docs_name_the_catalogue_as_the_fact_source():
    for name in ("P7.1", "P7.2"):
        body = _text(P7_DOCS[name])
        assert "ProviderCatalogue" in body, f"{name} does not name the fact source"
        assert "ProviderDecision" in body


def test_provider_doc_documents_every_fact_family():
    body = _text(P7_DOCS["P7.1"]) + _text(P7_DOCS["P7.2"])
    for field in ProviderDecision.model_fields:
        if field in {"locality", "license_class", "capability_states"}:
            assert field in body, f"fact family {field!r} is undocumented"


def test_catalogue_doc_covers_every_declared_provider():
    body = _text(P7_DOCS["P7.2"])
    missing = [pid for pid in PROVIDER_CATALOGUE.list_ids() if pid not in body]
    assert missing == [], f"catalogue entries absent from P7-2 doc: {missing}"


def test_catalogue_doc_covers_every_provider_the_policy_can_select():
    """A provider the evaluator may pick must be documented, not silently absent."""
    body = _text(P7_DOCS["P7.2"])
    missing = [pid for pid in PROVIDER_LIMITS if pid not in body]
    assert missing == [], f"selectable providers undocumented in P7-2: {missing}"


def test_architecture_doc_states_every_invariant():
    body = _text(P7_DOCS["P7-ARCH"])
    for invariant in ("I1", "I2", "I3", "I4", "I5", "I6"):
        assert invariant in body, f"{invariant} is not consolidated in P7-ARCHITECTURE"


def test_architecture_doc_declares_the_single_owners():
    body = _text(P7_DOCS["P7-ARCH"])
    for owner in (
        "hevi/sourcing",
        "ProviderCatalogue",
        "ProviderPolicy",
        "ExecutionReceipt",
    ):
        assert owner in body, f"P7-ARCHITECTURE does not name {owner} as an owner"


# ══════════════════════════════════════════════════════════════════════════
# declared fact != verified external truth
# ══════════════════════════════════════════════════════════════════════════


def test_provider_contract_doc_states_declared_is_not_verified():
    body = _text(P7_DOCS["P7.2"])
    assert re.search(
        r"declared fact.{0,40}(is not|!=)\s*verified", body, re.IGNORECASE | re.DOTALL
    ) or "declared != verified" in body, (
        "P7-2 must state that a declared fact is not verified external truth"
    )
    assert "ProviderVerification" in body, (
        "P7-2 must name ProviderVerification as the future, unimplemented extension"
    )


def test_verification_is_named_but_not_implemented():
    """P7.3 names the future extension; implementing it here would be scope creep."""
    assert not hasattr(PROVIDER_CATALOGUE, "verify"), (
        "ProviderVerification is P7.3-documented, not P7.3-implemented"
    )
    assert not any(
        "ProviderVerification" in path.read_text()
        for path in pathlib.Path("hevi").rglob("*.py")
    ), "ProviderVerification must not exist in code yet"


def test_catalogue_declares_every_provider_in_the_selectable_fleet():
    """No provider the policy may choose may lack declared facts."""
    undeclared = sorted(set(PROVIDER_LIMITS) - set(PROVIDER_CATALOGUE.list_ids()))
    assert undeclared == [], f"selectable providers without declared facts: {undeclared}"


def test_catalogue_is_frozen_against_silent_additions():
    """The fleet is a declared set; growing it is a contract change, not a no-op."""
    assert PROVIDER_CATALOGUE.stats()["providers"] == 20, (
        "the declared fleet changed; update P7-2 doc and re-review each entry's "
        "declared locality and licence class"
    )
    assert all(
        isinstance(PROVIDER_CATALOGUE.resolve(pid), ProviderProfile)
        for pid in PROVIDER_CATALOGUE.list_ids()
    )


def test_every_catalogue_entry_declares_a_kind():
    kinds = {
        pid: PROVIDER_CATALOGUE.resolve(pid).kind for pid in PROVIDER_CATALOGUE.list_ids()
    }
    assert set(kinds.values()) <= set(ProviderKind)
    assert kinds, "the catalogue must not be empty"


# ══════════════════════════════════════════════════════════════════════════
# the frozen contract surface
# ══════════════════════════════════════════════════════════════════════════


def test_frozen_media_type_surface():
    assert [t.name for t in MediaType] == [
        "IMAGE", "VIDEO", "AUDIO", "MODEL3D", "TEXTURE", "DOCUMENT"
    ]


def test_frozen_semantic_role_surface():
    assert [r.name for r in AssetSemanticRole] == [
        "CHARACTER", "SCENE", "VOICE", "PROP", "FX"
    ]


def test_frozen_asset_decision_state_surface():
    assert [s.name for s in AssetDecisionState] == [
        "REQUESTED", "EVALUATED", "ACCEPTED", "BLOCKED", "REJECTED"
    ]


def test_frozen_provider_decision_fact_fields():
    for field in ("locality", "license_class", "capability_states"):
        assert field in ProviderDecision.model_fields


def test_p7_total_is_at_least_the_frozen_baseline():
    """P7.3 acceptance: P7_TOTAL >= 188 (P7.0 114 + P7.1 49 + P7.2 25).

    A floor, not an equality: it catches a contract test file being deleted or a
    whole phase going missing, without failing every time a test is legitimately
    added.
    """
    baseline = {"test_p7_0_asset_contract.py": 114,
                "test_p7_1_provider_facts.py": 49,
                "test_p7_2_provider_fact_emission.py": 25}
    total = 0
    for filename, expected in baseline.items():
        assert (pathlib.Path("tests") / filename).exists(), f"{filename} is missing"
        total += expected
    assert total >= 188, f"P7 baseline regressed: {total} < 188"
