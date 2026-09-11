"""Add queryable indexes for the canonical production snapshot.

The immutable revision JSON remains the snapshot source. These tables are
normalized lookup/projection indexes, so legacy readers can coexist while the
canonical graph becomes authoritative. No ArtifactStore or MPT table is
duplicated.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: str | None = "f0e1d2c3b4a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS production_graph_entities (
            project_id UUID NOT NULL REFERENCES productions(id) ON DELETE CASCADE,
            revision_id UUID NOT NULL REFERENCES production_revisions(id) ON DELETE CASCADE,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (revision_id, entity_type, entity_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_production_graph_entities_project_type
        ON production_graph_entities (project_id, entity_type, entity_id)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS production_graph_edges (
            project_id UUID NOT NULL REFERENCES productions(id) ON DELETE CASCADE,
            revision_id UUID NOT NULL REFERENCES production_revisions(id) ON DELETE CASCADE,
            edge_id TEXT NOT NULL,
            edge_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (revision_id, edge_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_production_graph_edges_lookup
        ON production_graph_edges (project_id, source_id, target_id, edge_type)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS production_graph_readiness (
            project_id UUID NOT NULL REFERENCES productions(id) ON DELETE CASCADE,
            revision_id UUID NOT NULL REFERENCES production_revisions(id) ON DELETE CASCADE,
            shot_id TEXT NOT NULL,
            state TEXT NOT NULL,
            passed BOOLEAN NOT NULL,
            blockers JSONB NOT NULL DEFAULT '[]'::jsonb,
            warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
            checks JSONB NOT NULL DEFAULT '{}'::jsonb,
            evaluated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (revision_id, shot_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS production_graph_readiness")
    op.execute("DROP TABLE IF EXISTS production_graph_edges")
    op.execute("DROP TABLE IF EXISTS production_graph_entities")
