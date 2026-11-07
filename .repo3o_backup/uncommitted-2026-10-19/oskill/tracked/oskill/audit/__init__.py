"""VCP audit utilities: hash chain re-computation and Merkle batch proofs."""

from __future__ import annotations

from oprim.crypto import rfc6962_inclusion_proof, rfc6962_merkle_root, sha256_hash
from oprim.serialization import canonical_json

_GENESIS = b"\x00" * 32
_STRIP_FIELDS = frozenset({"hash_prev", "hash_current", "signature", "signing_key_id"})


def event_hash_chain(events: list[dict]) -> list[dict]:
    """Re-compute VCP hash chain for a sequence of event body dicts.

    Each dict must represent the event body before hash-chain fields are attached
    (i.e., as constructed by omodul.audit.vcp_silver_record before hash computation).
    Fields hash_prev / hash_current / signature / signing_key_id are stripped if
    present, so the function is safe to call on already-chained events (idempotent
    re-computation for verification).

    Parameters
    ----------
    events : list[dict]
        Ordered sequence of event body dicts. Each must contain at minimum:
        event_id, event_timestamp, policy_id, policy_version, conformance_tier,
        event_type, strategy_instance_id, strategy_id, determinism_evidence,
        faithfulness_evidence, decision_payload.

    Returns
    -------
    list[dict]
        New list of dicts, each with hash_prev (bytes) and hash_current (bytes)
        set according to the chain: hash_current = SHA256(hash_prev || canonical_json(body)).

    Notes
    -----
    input_snapshot_hash inside determinism_evidence must be a lowercase hex string
    (as returned by oprim.crypto.sha256_hash). Uppercase hex would produce a different
    canonical JSON and thus a different hash.
    """
    result: list[dict] = []
    prev_hash: bytes = _GENESIS

    for event in events:
        body = {k: v for k, v in event.items() if k not in _STRIP_FIELDS}
        canonical_bytes = canonical_json(body).encode()
        hash_raw = sha256_hash(prev_hash + canonical_bytes)
        hash_current = bytes.fromhex(hash_raw) if isinstance(hash_raw, str) else hash_raw

        out = dict(event)
        out["hash_prev"] = prev_hash
        out["hash_current"] = hash_current
        result.append(out)
        prev_hash = hash_current

    return result


def merkle_batch_proof(event_hashes: list[bytes], target_index: int) -> dict:
    """Compute RFC 6962 Merkle root and inclusion proof for a batch of event hashes.

    Parameters
    ----------
    event_hashes : list[bytes]
        Ordered list of event hash_current values (each 32 bytes).
    target_index : int
        0-indexed position of the target event.

    Returns
    -------
    dict with keys:
        merkle_root : bytes — 32-byte RFC 6962 Merkle tree root
        inclusion_proof : list[bytes] — sibling hashes (each 32 bytes)
        leaf_index : int — same as target_index
        tree_size : int — len(event_hashes)

    References
    ----------
    .. [1] RFC 6962 §2.1 Certificate Transparency Merkle Tree Hash.
    """
    if not event_hashes:
        raise ValueError("event_hashes must not be empty")
    if not isinstance(target_index, int) or target_index < 0 or target_index >= len(event_hashes):
        raise ValueError(f"target_index {target_index!r} out of range [0, {len(event_hashes)})")

    root = rfc6962_merkle_root(event_hashes)
    proof = rfc6962_inclusion_proof(event_hashes, leaf_index=target_index)

    return {
        "merkle_root": root,
        "inclusion_proof": proof,
        "leaf_index": target_index,
        "tree_size": len(event_hashes),
    }
