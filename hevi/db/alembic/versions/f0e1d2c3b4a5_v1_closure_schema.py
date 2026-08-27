"""Converge the V1.0 production contracts on one Alembic head.

The repository had several independently authored V1 migrations.  Some
databases were stamped on one branch while others were stamped on another,
which left production tables absent even though an Alembic upgrade appeared
successful.  This migration is deliberately idempotent: it merges the valid
heads and fills only missing objects/columns on databases that already
contain part of the V1 schema.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f0e1d2c3b4a5"
down_revision: tuple[str, str, str] = (
    "c0d1e2f3a4b8",
    "c0d1e2f3a4b9",
    "e1f2a3b4c5d6",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS production_constraints (
            id VARCHAR(128) NOT NULL,
            production_id UUID NOT NULL REFERENCES productions(id) ON DELETE CASCADE,
            revision_id UUID NOT NULL REFERENCES production_revisions(id) ON DELETE CASCADE,
            type VARCHAR(64) NOT NULL,
            severity VARCHAR(16) NOT NULL,
            scope VARCHAR(255) NOT NULL,
            source_path TEXT NOT NULL DEFAULT '',
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            compile_required BOOLEAN NOT NULL DEFAULT TRUE,
            verification_required BOOLEAN NOT NULL DEFAULT TRUE,
            fallback_policy VARCHAR(16) NOT NULL DEFAULT 'fail',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (revision_id, id)
        );
        CREATE INDEX IF NOT EXISTS ix_production_constraints_revision_type
            ON production_constraints (revision_id, type);

        CREATE TABLE IF NOT EXISTS constraint_dependencies (
            revision_id UUID NOT NULL REFERENCES production_revisions(id) ON DELETE CASCADE,
            constraint_id VARCHAR(128) NOT NULL,
            depends_on_revision_id UUID NOT NULL REFERENCES production_revisions(id) ON DELETE CASCADE,
            depends_on_id VARCHAR(128) NOT NULL,
            PRIMARY KEY (revision_id, constraint_id, depends_on_revision_id, depends_on_id)
        );

        CREATE TABLE IF NOT EXISTS constraint_coverage (
            revision_id UUID PRIMARY KEY REFERENCES production_revisions(id) ON DELETE CASCADE,
            expected_fields INTEGER NOT NULL DEFAULT 0,
            derived_constraints INTEGER NOT NULL DEFAULT 0,
            compiled_constraints INTEGER NOT NULL DEFAULT 0,
            consumed_constraints INTEGER NOT NULL DEFAULT 0,
            verified_constraints INTEGER NOT NULL DEFAULT 0,
            unsupported_constraints INTEGER NOT NULL DEFAULT 0,
            silent_drops INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS task_attempts (
            id UUID PRIMARY KEY,
            task_id UUID NOT NULL REFERENCES video_tasks(id) ON DELETE CASCADE,
            attempt_no INTEGER NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'claimed',
            worker_id VARCHAR(128) NOT NULL,
            lease_token VARCHAR(128) NOT NULL UNIQUE,
            lease_until TIMESTAMPTZ NULL,
            heartbeat_at TIMESTAMPTZ NULL,
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ NULL,
            error TEXT NULL,
            source_attempt_id UUID NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (task_id, attempt_no)
        );
        CREATE INDEX IF NOT EXISTS ix_task_attempts_task_status
            ON task_attempts (task_id, status, created_at);
        CREATE INDEX IF NOT EXISTS ix_task_attempts_lease_until
            ON task_attempts (lease_until);

        CREATE TABLE IF NOT EXISTS attempt_checkpoints (
            id UUID PRIMARY KEY,
            attempt_id UUID NOT NULL REFERENCES task_attempts(id) ON DELETE CASCADE,
            task_id UUID NOT NULL REFERENCES video_tasks(id) ON DELETE CASCADE,
            sequence INTEGER NOT NULL,
            stage VARCHAR(128) NOT NULL,
            progress_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
            completed_shots INTEGER NOT NULL DEFAULT 0,
            total_shots INTEGER NOT NULL DEFAULT 0,
            state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            artifact_manifest_json JSONB NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (attempt_id, sequence)
        );
        CREATE INDEX IF NOT EXISTS ix_attempt_checkpoints_task_latest
            ON attempt_checkpoints (task_id, created_at, sequence);

        ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS current_attempt_id UUID;
        ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS scheduled_at TIMESTAMPTZ;
        ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS scheduler_score DOUBLE PRECISION;
        ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS scheduler_policy_version INTEGER;
        ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS scheduler_decision_json JSONB;
        ALTER TABLE task_attempts ADD COLUMN IF NOT EXISTS source_attempt_id UUID;
        CREATE INDEX IF NOT EXISTS ix_video_tasks_scheduled_queue
            ON video_tasks (status, scheduled_at, scheduler_score);

        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_video_tasks_current_attempt'
            ) THEN
                ALTER TABLE video_tasks ADD CONSTRAINT fk_video_tasks_current_attempt
                    FOREIGN KEY (current_attempt_id) REFERENCES task_attempts(id);
            END IF;
        END $$;

        CREATE TABLE IF NOT EXISTS scheduler_leases (
            name VARCHAR(64) PRIMARY KEY,
            owner_id VARCHAR(128) NOT NULL,
            lease_until TIMESTAMPTZ NOT NULL,
            heartbeat_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )

    op.execute(
        """
        ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
        CREATE INDEX IF NOT EXISTS ix_artifacts_expires_at
            ON artifacts (expires_at) WHERE expires_at IS NOT NULL;

        CREATE TABLE IF NOT EXISTS evaluations (
            id UUID PRIMARY KEY,
            production_id UUID NULL REFERENCES productions(id) ON DELETE SET NULL,
            revision_id UUID NULL REFERENCES production_revisions(id) ON DELETE SET NULL,
            task_id UUID NULL REFERENCES video_tasks(id) ON DELETE CASCADE,
            attempt_id VARCHAR(128) NULL,
            scope VARCHAR(255) NOT NULL DEFAULT 'production',
            evaluator VARCHAR(128) NOT NULL DEFAULT 'hevi.quality',
            status VARCHAR(32) NOT NULL DEFAULT 'completed',
            passed BOOLEAN NOT NULL DEFAULT FALSE,
            score DOUBLE PRECISION NOT NULL DEFAULT 0,
            residual_severity DOUBLE PRECISION NOT NULL DEFAULT 0,
            residual_count INTEGER NOT NULL DEFAULT 0,
            evidence_artifact_id TEXT NULL,
            details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_evaluations_task_created
            ON evaluations (task_id, created_at);
        CREATE INDEX IF NOT EXISTS ix_evaluations_production_created
            ON evaluations (production_id, created_at);

        CREATE TABLE IF NOT EXISTS violations (
            id UUID PRIMARY KEY,
            evaluation_id UUID NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
            taxonomy VARCHAR(128) NOT NULL,
            severity DOUBLE PRECISION NOT NULL DEFAULT 0,
            message TEXT NOT NULL DEFAULT '',
            repairable BOOLEAN NOT NULL DEFAULT FALSE,
            scope VARCHAR(255) NOT NULL DEFAULT '',
            details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_violations_evaluation
            ON violations (evaluation_id, created_at);
        CREATE INDEX IF NOT EXISTS ix_violations_taxonomy
            ON violations (taxonomy, created_at);

        CREATE TABLE IF NOT EXISTS repair_plans (
            id UUID PRIMARY KEY,
            production_id UUID NULL REFERENCES productions(id) ON DELETE SET NULL,
            task_id UUID NOT NULL REFERENCES video_tasks(id) ON DELETE CASCADE,
            evaluation_id UUID NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
            violation_set_hash VARCHAR(64) NOT NULL,
            action VARCHAR(64) NOT NULL,
            scope VARCHAR(255) NOT NULL DEFAULT 'production',
            expected_gain DOUBLE PRECISION NOT NULL DEFAULT 0,
            max_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
            status VARCHAR(32) NOT NULL DEFAULT 'planned',
            decision_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            source_attempt_id UUID NULL,
            source_verdict_id UUID NULL,
            rerun_nodes JSONB NOT NULL DEFAULT '[]'::jsonb,
            preserve_artifact_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        ALTER TABLE repair_plans ADD COLUMN IF NOT EXISTS source_attempt_id UUID;
        ALTER TABLE repair_plans ADD COLUMN IF NOT EXISTS source_verdict_id UUID;
        ALTER TABLE repair_plans ADD COLUMN IF NOT EXISTS rerun_nodes JSONB NOT NULL DEFAULT '[]'::jsonb;
        ALTER TABLE repair_plans ADD COLUMN IF NOT EXISTS preserve_artifact_ids JSONB NOT NULL DEFAULT '[]'::jsonb;
        CREATE INDEX IF NOT EXISTS ix_repair_plans_task_created
            ON repair_plans (task_id, created_at);
        CREATE INDEX IF NOT EXISTS ix_repair_plans_production_created
            ON repair_plans (production_id, created_at);
        """
    )


def downgrade() -> None:
    # The V1 closure migration is a graph merge/compatibility bridge.  Its
    # downgrade intentionally leaves shared tables in place; older revisions
    # still own their historical downgrade paths.
    pass
