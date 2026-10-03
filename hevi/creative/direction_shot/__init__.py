"""P10-E canonical ShotSpec contract layer (contracts/validator/revision/hash).

References the P10a/b/c/d layers, owns none of their authority:
see `contracts.py` for the reuse map.
"""

from hevi.creative.direction_shot.contracts import (
    CONTENT_PIN_KEYS,
    SHOT_STATUSES,
    ShotSpec,
    ShotTiming,
    ShotVerification,
)
from hevi.creative.direction_shot.errors import (
    ChainBrokenError,
    ShotSpecError,
    ShotSpecImmutableError,
    ShotSpecNotFoundError,
)
from hevi.creative.direction_shot.hashing import (
    CHAIN_DOMAIN,
    HASH_DOMAIN,
    SHOT_SPEC_VERSION,
    canonical_body,
    chain_hash,
    is_hash,
    shot_spec_hash,
)
from hevi.creative.direction_shot.revision import (
    REVISION_STATUSES,
    ShotSpecRevision,
    ShotSpecRevisionStore,
)
from hevi.creative.direction_shot.validator import (
    Finding,
    ShotRefIndex,
    ValidationReport,
    validate_shot_specs,
)

__all__ = [
    "CHAIN_DOMAIN",
    "CONTENT_PIN_KEYS",
    "ChainBrokenError",
    "Finding",
    "HASH_DOMAIN",
    "REVISION_STATUSES",
    "SHOT_STATUSES",
    "SHOT_SPEC_VERSION",
    "ShotRefIndex",
    "ShotSpec",
    "ShotSpecError",
    "ShotSpecImmutableError",
    "ShotSpecNotFoundError",
    "ShotSpecRevision",
    "ShotSpecRevisionStore",
    "ShotTiming",
    "ShotVerification",
    "ValidationReport",
    "canonical_body",
    "chain_hash",
    "is_hash",
    "shot_spec_hash",
    "validate_shot_specs",
]
