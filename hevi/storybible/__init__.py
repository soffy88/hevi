"""Story bible — file-based foreshadowing and canon ledgers.

Companion to the DB-backed ``hevi.storygraph`` layer: storygraph stores the
extracted story graph, the story bible tracks the long-form writing state
that lives on top of it (which setups are still unpaid, which facts are
canon). Everything is JSON files + pure logic; see ``ledger.py``.
"""

from hevi.storybible.ledger import (
    FORESHADOW_STATUSES,
    CanonFact,
    CanonLedger,
    CheckerFn,
    Contradiction,
    ForeshadowEntry,
    ForeshadowLedger,
    canon_path,
    check_claims_against_canon,
    default_storybible_dir,
    foreshadow_path,
    slugify_work,
)

__all__ = [
    "FORESHADOW_STATUSES",
    "CanonFact",
    "CanonLedger",
    "CheckerFn",
    "Contradiction",
    "ForeshadowEntry",
    "ForeshadowLedger",
    "canon_path",
    "check_claims_against_canon",
    "default_storybible_dir",
    "foreshadow_path",
    "slugify_work",
]
