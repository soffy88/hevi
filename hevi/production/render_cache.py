"""P0.9/P0.10 — the render cache and artifact deduplication.

§40 and §41 together, and they pull against each other in one place:

    §40  same content_hash  ->  reuse
    §41  cache hit is only reusable if the artifact is VALIDATED

An unvalidated artifact is not a deliverable, so a cache hit on one is a miss. This
module therefore has two levels and says which one answered:

* **deduplication** — a content-addressed store. Reusing bytes is always safe.
* **render cache** — keyed by render identity. Reusing *as output* additionally
  requires validation, because a file on disk proves nothing about whether it renders.

The key includes renderer and encoder versions (§41, R6, R7). Upgrading either must
invalidate, or the cache serves artifacts the new version would never have produced --
and, worse, attributes them to the old version in the receipt.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class CacheLevel(StrEnum):
    """Which question a lookup answered."""

    #: Exact content-addressed reuse. The bytes are the same by construction.
    DEDUPLICATED = "DEDUPLICATED"
    #: Reused as final output because a prior render produced it and it validated.
    CACHE_HIT = "CACHE_HIT"
    #: Present on disk but never validated -- cannot be reused as output.
    UNVALIDATED = "UNVALIDATED"
    MISS = "MISS"


@dataclass(frozen=True)
class CacheEntry:
    """One cached artifact."""

    key: str
    content_hash: str
    uri: str
    validated: bool
    renderer: str
    renderer_version: str
    duration_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "content_hash": self.content_hash,
            "uri": self.uri,
            "validated": self.validated,
            "renderer": self.renderer,
            "renderer_version": self.renderer_version,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True)
class CacheLookup:
    key: str
    level: CacheLevel
    entry: CacheEntry | None = None
    #: Why the entry was not reusable. Present on UNVALIDATED so a caller can log the
    #: reason instead of just observing a miss.
    reason: str = ""


def render_cache_key(
    *,
    timeline_hash: str,
    scene_hash: str,
    asset_hashes: tuple[str, ...],
    renderer: str,
    renderer_version: str,
    encoder: str | None = None,
    encoder_version: str | None = None,
    render_parameters: dict[str, Any] | None = None,
) -> str:
    """§41's cache key.

    ``asset_hashes`` is sorted, so the same assets in a different order hit. The
    timeline hash and scene hash are separate fields rather than one, because a scene can
    change without the timeline changing and vice versa; collapsing them would make one
    of those two invalidations impossible.
    """
    payload = {
        "asset_hashes": sorted(asset_hashes),
        "encoder": encoder,
        "encoder_version": encoder_version,
        "render_parameters": render_parameters or {},
        "renderer": renderer,
        "renderer_version": renderer_version,
        "scene_hash": scene_hash,
        "timeline_hash": timeline_hash,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


class ArtifactStore:
    """Content-addressed artifact store.

    Path layout follows §39: ``artifacts/{content_hash}/`` rather than a random UUID,
    so the same content lands in the same place twice and the filesystem itself becomes
    the deduplication index.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._by_hash: dict[str, CacheEntry] = {}
        self._by_key: dict[str, CacheEntry] = {}

    def path_for(self, content_hash: str, name: str = "artifact") -> Path:
        return self.root / content_hash / name

    def put(
        self,
        entry: CacheEntry,
        *,
        cache_key: str = "",
    ) -> CacheEntry:
        self._by_hash[entry.content_hash] = entry
        if cache_key:
            self._by_key[cache_key] = entry
        return entry

    def mark_validated(self, content_hash: str) -> CacheEntry | None:
        """Promote an entry once a real validation has observed it.

        This is the §41 gate. Nothing else may set ``validated``: a render that
        completed is not a validated artifact, and conflating them is how an unvalidated
        file becomes a final deliverable.
        """
        existing = self._by_hash.get(content_hash)
        if existing is None:
            return None
        promoted = CacheEntry(
            key=existing.key, content_hash=existing.content_hash, uri=existing.uri,
            validated=True, renderer=existing.renderer,
            renderer_version=existing.renderer_version,
            duration_ms=existing.duration_ms, metadata=existing.metadata,
        )
        self._by_hash[content_hash] = promoted
        if existing.key in self._by_key:
            self._by_key[existing.key] = promoted
        return promoted

    def lookup_hash(self, content_hash: str) -> CacheLookup:
        entry = self._by_hash.get(content_hash)
        if entry is None:
            return CacheLookup(key=content_hash, level=CacheLevel.MISS,
                               reason="content_hash_unknown")
        if not entry.validated:
            return CacheLookup(key=content_hash, level=CacheLevel.UNVALIDATED,
                               entry=entry, reason="present_but_never_validated")
        return CacheLookup(key=content_hash, level=CacheLevel.DEDUPLICATED, entry=entry)

    def lookup_render(self, cache_key: str) -> CacheLookup:
        entry = self._by_key.get(cache_key)
        if entry is None:
            return CacheLookup(key=cache_key, level=CacheLevel.MISS,
                               reason="no_prior_render_with_this_identity")
        if not entry.validated:
            # §41: only a VALIDATED artifact may be reused as final output.
            return CacheLookup(key=cache_key, level=CacheLevel.UNVALIDATED,
                               entry=entry, reason="cache_entry_not_validated")
        return CacheLookup(key=cache_key, level=CacheLevel.CACHE_HIT, entry=entry)


def digest_file(path: Path) -> str:
    """sha256 over a file's bytes.

    Used instead of mtime or size, both of which collide: a re-render that produces
    identical bytes would look new, and an edit that preserves size would look old.
    """
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "ArtifactStore",
    "CacheEntry",
    "CacheLevel",
    "CacheLookup",
    "digest_file",
    "render_cache_key",
]
