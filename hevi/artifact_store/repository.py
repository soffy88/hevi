"""PostgreSQL persistence for content-addressed artifact metadata."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from obase.persistence import PgPool

from hevi.monitoring.metrics import (
    artifact_commit_outcomes_total,
    artifact_integrity_outcomes_total,
    object_store_latency_seconds,
)
from hevi.production.artifacts import Artifact, ArtifactManifest

from .lifecycle import expiry_for_role
from .object_store import ObjectStore


def _stable_artifact_id(
    production_id: str, revision_id: str | None, artifact: Artifact
) -> uuid.UUID:
    key = ":".join(
        [
            production_id,
            revision_id or "",
            artifact.logical_role or artifact.kind,
            artifact.sha256 or artifact.path,
        ]
    )
    return uuid.uuid5(uuid.NAMESPACE_URL, f"hevi:artifact:{key}")


class ArtifactRepository:
    def __init__(self, pool: PgPool, object_store: ObjectStore | None = None) -> None:
        self.pool = pool
        self.object_store = object_store

    async def get_manifest(
        self, production_id: str, *, revision_id: str | None = None
    ) -> ArtifactManifest | None:
        """Load the canonical artifact manifest from PostgreSQL.

        ``video_tasks.config_json.artifact_manifest`` remains a compatibility
        projection, but delivery can rebuild the manifest from this table
        after a task projection is lost or stale.
        """
        clauses = ["production_id = $1"]
        params: list[object] = [uuid.UUID(production_id)]
        if revision_id:
            clauses.append("revision_id = $2")
            params.append(uuid.UUID(revision_id))
        sql = (
            "SELECT id, revision_id, kind, logical_role, uri, sha256, byte_size, "
            "media_type, created_by_attempt_id, metadata "
            "FROM artifacts WHERE "
            + " AND ".join(clauses)
            + " ORDER BY created_at ASC, id ASC"
        )
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        if not rows:
            return None
        seen_kinds: set[str] = set()
        artifacts: list[Artifact] = []
        for row in rows:
            kind = str(row["kind"])
            artifacts.append(
                Artifact(
                    kind=kind,
                    path=str(row["uri"]),
                    media_type=row["media_type"],
                    primary=kind not in seen_kinds,
                    artifact_id=str(row["id"]),
                    uri=str(row["uri"]),
                    sha256=row["sha256"],
                    byte_size=row["byte_size"],
                    logical_role=row["logical_role"],
                    created_by_attempt_id=row["created_by_attempt_id"],
                    metadata=dict(row["metadata"] or {}),
                )
            )
            seen_kinds.add(kind)
        first = rows[0]
        return ArtifactManifest(
            production_id=production_id,
            revision_id=str(first["revision_id"]) if first["revision_id"] else revision_id,
            attempt_id=artifacts[0].created_by_attempt_id,
            tenant_id=str(artifacts[0].metadata.get("tenant_id") or "anonymous"),
            artifacts=artifacts,
        )

    async def commit(self, manifest: ArtifactManifest) -> ArtifactManifest:
        """Commit a manifest and emit integrity/commit operation metrics."""
        try:
            result = await self._commit(manifest)
        except Exception:
            artifact_commit_outcomes_total.labels(status="error").inc()
            artifact_integrity_outcomes_total.labels(status="failed").inc()
            raise
        artifact_commit_outcomes_total.labels(status="success").inc()
        artifact_integrity_outcomes_total.labels(status="verified").inc()
        return result

    async def _commit(self, manifest: ArtifactManifest) -> ArtifactManifest:
        """Persist a manifest idempotently and return ids assigned to artifacts."""

        if not manifest.production_id:
            raise ValueError("artifact manifest requires production_id")
        production_id = uuid.UUID(manifest.production_id)
        revision_id = uuid.UUID(manifest.revision_id) if manifest.revision_id else None
        source_artifacts = list(manifest.artifacts)
        if self.object_store is not None:
            source_artifacts = []
            for artifact in manifest.artifacts:
                if not Path(artifact.path).is_file():
                    # A retry may already carry an object URI and therefore
                    # not have the worker's scratch file anymore.  Accept
                    # only a fully materialized content-addressed reference;
                    # persisting a bare container path would reintroduce
                    # result_video_path as production truth.
                    if not (
                        artifact.uri
                        and artifact.uri.startswith(("file://", "s3://"))
                        and artifact.sha256
                        and artifact.byte_size is not None
                    ):
                        raise FileNotFoundError(
                            f"artifact source is missing and has no durable object reference: "
                            f"{artifact.path}"
                        )
                    source_artifacts.append(artifact)
                    continue
                store_started = monotonic()
                try:
                    stored = await self.object_store.put_file(
                        artifact.path,
                        media_type=artifact.media_type,
                        key_prefix="/".join(
                            part.strip("/")
                            for part in (
                                str(manifest.tenant_id or "anonymous"),
                                str(manifest.production_id),
                            )
                            if part.strip("/")
                        ),
                    )
                finally:
                    object_store_latency_seconds.labels(
                        backend=self.object_store.__class__.__name__, operation="put_file"
                    ).observe(monotonic() - store_started)
                source_artifacts.append(
                    artifact.model_copy(
                        update={
                            "uri": stored.uri,
                            "sha256": stored.sha256,
                            "byte_size": stored.byte_size,
                        }
                    )
                )
        for artifact in source_artifacts:
            if not (
                artifact.uri
                and artifact.uri.startswith(("file://", "s3://"))
                and artifact.sha256
                and artifact.byte_size is not None
            ):
                raise ValueError(
                    "production artifact requires object URI, sha256, and byte_size"
                )
        source_artifacts = [
            artifact.model_copy(
                update={
                    "metadata": {
                        **artifact.metadata,
                        "tenant_id": manifest.tenant_id or "anonymous",
                    }
                }
            )
            for artifact in source_artifacts
        ]
        committed: list[Artifact] = []
        now = datetime.now(UTC).replace(tzinfo=None)
        async with self.pool.acquire() as conn, conn.transaction():
            for artifact in source_artifacts:
                artifact_id = (
                    uuid.UUID(artifact.artifact_id)
                    if artifact.artifact_id
                    else _stable_artifact_id(manifest.production_id, manifest.revision_id, artifact)
                )
                expires_at = expiry_for_role(artifact.logical_role)
                await conn.execute(
                    """
                    INSERT INTO artifacts
                        (id, production_id, revision_id, kind, logical_role, uri,
                         sha256, byte_size, media_type, created_by_attempt_id,
                         metadata, created_at, expires_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                    ON CONFLICT (id) DO UPDATE SET
                        revision_id = EXCLUDED.revision_id,
                        uri = EXCLUDED.uri,
                        sha256 = EXCLUDED.sha256,
                        byte_size = EXCLUDED.byte_size,
                        media_type = EXCLUDED.media_type,
                        metadata = EXCLUDED.metadata,
                        expires_at = EXCLUDED.expires_at
                    """,
                    artifact_id,
                    production_id,
                    revision_id,
                    artifact.kind,
                    artifact.logical_role or "",
                    artifact.uri or artifact.path,
                    artifact.sha256,
                    artifact.byte_size,
                    artifact.media_type,
                    artifact.created_by_attempt_id,
                    artifact.metadata,
                    now,
                    expires_at,
                )
                committed.append(artifact.model_copy(update={"artifact_id": str(artifact_id)}))
            for child in committed:
                child_id = uuid.UUID(child.artifact_id or "")
                for parent_id in child.parent_artifact_ids:
                    await conn.execute(
                        """
                        INSERT INTO artifact_relations
                            (parent_artifact_id, child_artifact_id, relation_type)
                        VALUES ($1, $2, 'derived_from')
                        ON CONFLICT DO NOTHING
                        """,
                        uuid.UUID(parent_id),
                        child_id,
                    )
        return manifest.model_copy(update={"artifacts": committed})


__all__ = ["ArtifactRepository"]
