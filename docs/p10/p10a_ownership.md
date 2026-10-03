"""P10a ownership resolution (step 1, frozen before implementation).

Inspected 2026-10-03:
- hevi/ops/p5_approval.py:38 ApprovalStore — file-backed (tmp+replace atomic),
  aggregate = P5 ContentItem approvals. NOT direction-shaped; not reused as store.
  P10a follows the same tmp+replace pattern, records direction approvals as its
  own transition events (different aggregate, no authority duplication).
- hevi/narrative/revision.py:15 RevisionStore — in-memory dict, asset-level, no
  events/durability. Not reusable for direction revisions.
- hevi/artifact_store/object_store.py — blob object store (async put/get).
  P10a snapshots are small JSON; uses plain files (approvals.json/.gates.jsonl
  precedent), NOT a new ledger backend/service.

Decision: new P10 component hevi/creative/direction_state/ holding ONLY
DirectionState + transition policy + file persistence adapter.
It references (never owns): approval actors, compile receipts, artifact hashes.
Priority applied: reuse pattern > adapter > extend > new; no duplicate authority.
"""
