"""Audit chain utilities — Merkle proof helpers for decision_audit."""

from __future__ import annotations

from oprim.crypto import rfc6962_inclusion_proof


def merkle_batch_proof(hashes: list[bytes], index: int) -> dict:
    """Return RFC 6962 inclusion proof for leaf at *index*.

    Parameters
    ----------
    hashes:
        All leaf hashes (same order used to build the root via
        ``oprim.crypto.rfc6962_merkle_root``).
    index:
        0-based position of the target leaf.

    Returns
    -------
    dict
        ``{"inclusion_proof": list[bytes]}`` — sibling hashes leaf→root.
    """
    return {"inclusion_proof": rfc6962_inclusion_proof(hashes, leaf_index=index)}
