"""P10b Review Pack builder + revision content-pin hookup.

P10a DirectionState untouched: pins live in rev_<n>/content.json next to state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from hevi.creative.direction_content.errors import ContentValidationError
from hevi.creative.direction_content.models import content_hash


@dataclass(frozen=True)
class ReviewRefusal:
    decision_ref: str
    reason: str
    actor: str = ""
    command_id: str = ""


@dataclass(frozen=True)
class ReviewPack:
    base_revision: int
    new_revision: int
    changed_groups: dict[str, list[str]] = field(default_factory=dict)
    rerun_cost_class: str = "low"
    benchmark_provenance: tuple[str, ...] = ()
    stale_items: tuple[str, ...] = ()
    refusals: tuple[ReviewRefusal, ...] = ()
    pack_hash: str = ""


def build_review_pack(*, base_pins: dict[str, str], new_pins: dict[str, str],
                      base_revision: int, new_revision: int,
                      rerun_cost_class: str = "low",
                      benchmark_provenance: tuple[str, ...] = (),
                      stale_items: tuple[str, ...] = (),
                      refusals: tuple[ReviewRefusal, ...] = ()) -> ReviewPack:
    changed = {k: [old, new] for k, (old, new) in
               ((k, (base_pins.get(k, ""), v)) for k, v in new_pins.items())
               if old != new}
    return ReviewPack(base_revision, new_revision, changed, rerun_cost_class,
                      benchmark_provenance, stale_items, refusals,
                      content_hash([base_revision, new_revision, changed]))


def record_content_pins(store_root: str | Path, direction_id: str, revision: int,
                        pins: dict[str, str]) -> Path:
    """Pin content hashes for a revision. P10a state files untouched."""
    required = ("brief", "thesis", "benchmarks", "treatment")
    missing = [k for k in required if not pins.get(k)]
    if missing:
        raise ContentValidationError(f"content pins missing: {missing}", code="PINS_INCOMPLETE")
    path = Path(store_root) / direction_id / f"rev_{revision}" / "content.json"
    if not path.parent.is_dir():
        raise ContentValidationError(f"revision dir missing: {path.parent}", code="PINS_NO_REVISION")
    path.write_text(json.dumps({"pins": pins}, ensure_ascii=False, sort_keys=True, indent=2),
                    encoding="utf-8")
    return path


def verify_content_pins(store_root: str | Path, direction_id: str, revision: int,
                         actual: dict[str, str]) -> None:
    """Approval-void check: content changed without new revision -> fail-loud."""
    path = Path(store_root) / direction_id / f"rev_{revision}" / "content.json"
    recorded = json.loads(path.read_text(encoding="utf-8"))["pins"]
    drifted = [k for k, v in recorded.items() if actual.get(k) != v]
    if drifted:
        raise ContentValidationError(f"APPROVAL_VOID, content drifted: {drifted}",
                                     code="APPROVAL_VOID")
