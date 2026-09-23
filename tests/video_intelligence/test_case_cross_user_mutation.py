"""Database ownership adversarial checks for Video Intelligence.

These tests are opt-in because they use the real HEVI PostgreSQL database and
create/clean disposable rows.  They are not satisfied by repository mocks.
"""

from __future__ import annotations

import os
import uuid

import pytest
from asyncpg import ForeignKeyViolationError

pytestmark = pytest.mark.skipif(
    os.getenv("HEVI_LIVE_TESTS") != "1", reason="real PostgreSQL ownership checks are opt-in"
)


@pytest.mark.asyncio
async def test_cross_user_case_mutations_fail_closed() -> None:
    from hevi.db.pg_pool import get_hevi_pg_pool
    from hevi.video_intelligence.case_models import VideoCase
    from hevi.video_intelligence.case_repository import CaseRepository
    from hevi.video_intelligence.runtime_repository import (
        CaseAnalysisRepository,
        CaseReproductionRepository,
    )

    pool = await get_hevi_pg_pool()
    async with pool.acquire() as conn:
        users = await conn.fetch("SELECT id FROM users ORDER BY id LIMIT 2")
        task = await conn.fetchrow("SELECT id FROM video_tasks ORDER BY created_at LIMIT 1")
    if len(users) < 2 or task is None:
        pytest.skip("real database needs two users and one existing task")
    owner, attacker = (str(users[0]["id"]), str(users[1]["id"]))
    case_repo = CaseRepository(pool)
    case = await case_repo.create(
        VideoCase(id=str(uuid.uuid4()), user_id=owner, title="ownership-live"),
        idempotency_key=f"ownership-live-{uuid.uuid4()}",
    )
    analysis_repo = CaseAnalysisRepository(pool)
    reproduction_repo = CaseReproductionRepository(pool)
    analysis = None
    reproduction = None
    try:
        assert await case_repo.get_owned(case.id, user_id=attacker) is None
        assert await case_repo.update_owned(case.id, user_id=attacker, changes={"title": "x"}) is None
        assert await case_repo.delete_owned(case.id, user_id=attacker) is False
        assert await case_repo.attach_provenance(case.id, user_id=attacker, provenance=[]) is None

        analysis = await analysis_repo.create_pending(
            case_id=case.id, user_id=owner, key=f"analysis-{uuid.uuid4()}", analyzer_version="v1"
        )
        assert await analysis_repo.mark_running(str(analysis["id"]), user_id=attacker) is False

        with pytest.raises(ForeignKeyViolationError):
            await reproduction_repo.create_pending(
                case_id=case.id, user_id=attacker, workspace_id=None,
                key=f"foreign-{uuid.uuid4()}", provider_id="hyperframes", model_id="cpu",
                model_version=None, generation_mode="exact_structure", compiled_prompt="x",
                reference_bindings=[], parameters={}, task_id=str(task["id"]),
            )
        reproduction = await reproduction_repo.create_pending(
            case_id=case.id, user_id=owner, workspace_id=None,
            key=f"reproduction-{uuid.uuid4()}", provider_id="hyperframes", model_id="cpu",
            model_version=None, generation_mode="exact_structure", compiled_prompt="x",
            reference_bindings=[], parameters={}, task_id=str(task["id"]),
        )
        assert await reproduction_repo.get_owned(str(reproduction["id"]), user_id=attacker) is None
        assert await reproduction_repo.attach_verdict(
            str(reproduction["id"]), user_id=attacker, verdict_id=str(uuid.uuid4())
        ) is False
    finally:
        async with pool.acquire() as conn:
            if reproduction:
                await conn.execute("DELETE FROM case_reproductions WHERE id=$1", reproduction["id"])
            if analysis:
                await conn.execute("DELETE FROM video_case_analyses WHERE id=$1", analysis["id"])
            await conn.execute("DELETE FROM video_cases WHERE id=$1", uuid.UUID(case.id))
