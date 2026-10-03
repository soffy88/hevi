"""P10a transition matrix + policy (§7, I1–I6). Pure: no IO, no LLM."""

from __future__ import annotations

import re

from hevi.creative.direction_state.errors import (
    IllegalTransitionError,
    MissingBindingError,
)
from hevi.creative.direction_state.state import Lifecycle

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")

# (from, action) -> to. REJECT maps to itself (I3); REQUEST_CHANGES is separate.
TRANSITIONS: dict[tuple[str, str], str] = {
    ("DRAFT", "PROPOSE"): "PROPOSED",
    ("PROPOSED", "SUBMIT_REVIEW"): "REVIEW_REQUIRED",
    ("REVIEW_REQUIRED", "REJECT"): "REVIEW_REQUIRED",
    ("REVIEW_REQUIRED", "REQUEST_CHANGES"): "PROPOSED",
    ("REVIEW_REQUIRED", "APPROVE"): "APPROVED",
    ("APPROVED", "COMPILE"): "COMPILED",
    ("COMPILED", "START_PRODUCTION"): "IN_PRODUCTION",
    ("IN_PRODUCTION", "VERIFY"): "VERIFIED",
    ("REVISION_PROPOSED", "APPROVE"): "APPROVED",
}

# CREATE_REVISION is handled by create_revision() (spans revisions); listed here
# so the matrix is total for documentation. It never mutates the old revision.
CROSS_REVISION: dict[tuple[str, str], str] = {
    ("VERIFIED", "CREATE_REVISION"): "REVISION_PROPOSED",
}


def resolve(from_state: str, action: str) -> str:
    """Return to_state or raise IllegalTransitionError (I1). No mutation."""
    key = (from_state, action)
    if key in TRANSITIONS:
        return TRANSITIONS[key]
    if key in CROSS_REVISION:
        return CROSS_REVISION[key]
    raise IllegalTransitionError(f"forbidden transition: {from_state} --{action}--> ?")


def check_bindings(action: str, to_state: str, revision: int, bindings: dict[str, str]) -> None:
    """I5: COMPILE/VERIFY require bindings. Raises MissingBindingError."""
    if action == "COMPILE" and to_state == Lifecycle.COMPILED:
        receipt = bindings.get("compile_receipt", "")
        if not receipt:
            raise MissingBindingError("COMPILE requires compile_receipt binding")
        if str(bindings.get("direction_revision", revision)) != str(revision):
            raise MissingBindingError("COMPILE binds a different direction_revision")
    if action == "VERIFY" and to_state == Lifecycle.VERIFIED:
        artifact = bindings.get("artifact_hash", "")
        if not _SHA256_HEX.match(artifact or ""):
            raise MissingBindingError("VERIFY requires artifact_hash (sha256 hex) binding")
        if not bindings.get("verification_receipt"):
            raise MissingBindingError("VERIFY requires verification_receipt binding")
