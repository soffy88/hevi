"""P10-E canonical hash layer.

Two properties matter and are enforced here, not by convention:

1. Domain separation. The digest is stamped with HASH_DOMAIN + the contract
   version, so a ShotSpec digest can never be mistaken for a bare
   `direction_content.content_hash` / `direction_plan.plan_hash` over the same
   payload. Cross-layer comparisons stay meaningful.
2. Self-reference exclusion. The payload hashed for a ShotSpec excludes its own
   `spec_hash` field, so sealing a spec does not change its digest.

Primitives are reused from direction_plan.plan_hash rather than re-derived.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import asdict
from typing import Any

from hevi.creative.direction_plan.models import plan_hash

SHOT_SPEC_VERSION = "p10e-shotspec-0.1"
HASH_DOMAIN = "hevi.creative.direction_shot/ShotSpec"
CHAIN_DOMAIN = "hevi.creative.direction_shot/RevisionChain"

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_SELF_FIELD = "spec_hash"


def is_hash(value: str) -> bool:
    return bool(_SHA256_HEX.match(value or ""))


def canonical_body(spec: Any) -> dict[str, Any]:
    """Full canonical payload of a spec, minus the self-referential hash field."""
    body = asdict(spec)
    body.pop(_SELF_FIELD, None)
    return body


def shot_spec_hash(spec: Any) -> str:
    """Reproducible, version-stamped, domain-separated digest of one ShotSpec."""
    return plan_hash([HASH_DOMAIN, SHOT_SPEC_VERSION, canonical_body(spec)])


def chain_hash(previous: str, spec_hashes: Sequence[str]) -> str:
    """Link one revision's ordered spec digests onto the prior revision hash."""
    return plan_hash([CHAIN_DOMAIN, SHOT_SPEC_VERSION, previous, list(spec_hashes)])
