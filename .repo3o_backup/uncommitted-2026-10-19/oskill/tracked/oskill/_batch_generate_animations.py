"""K-batch_generate_animations: concurrent batch animation generation."""

from __future__ import annotations

import asyncio

from oprim._animation_types import AnimationResult

from oskill._generate_animation import generate_animation


async def batch_generate_animations(
    *,
    jobs: list[dict],
    llm,
    max_concurrent: int = 5,
) -> list[AnimationResult]:
    """Run generate_animation for each job concurrently, bounded by a semaphore.

    Each job dict: {template, variables, domain_prompt}.
    Results are returned in the same order as jobs.
    Exceptions inside individual jobs are caught and returned as failed
    AnimationResult (is_valid=False, entity_meta contains the error).
    """
    if not jobs:
        return []

    sem = asyncio.Semaphore(max_concurrent)

    async def _run(job: dict, idx: int) -> AnimationResult:
        async with sem:
            try:
                return await generate_animation(
                    template=job["template"],
                    variables=job.get("variables", {}),
                    domain_prompt=job.get("domain_prompt", ""),
                    llm=llm,
                )
            except Exception as exc:
                return AnimationResult(
                    html="",
                    is_valid=False,
                    validation_violations=["generation_error"],
                    entity_meta={"error": str(exc), "job_index": idx},
                )

    tasks = [_run(job, i) for i, job in enumerate(jobs)]
    return list(await asyncio.gather(*tasks))
