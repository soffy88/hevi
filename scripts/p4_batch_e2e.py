#!/usr/bin/env python3
"""P4 batch E2E: 10 jobs (3 profiles + 7 tiny) through the canonical scheduler."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, "/data/soffy/projects/hevi")

from hevi.ops.p4_runner import run_job_mission
from hevi.ops.p4_scheduler import Scheduler, create_batch
from hevi.ops.p4_types import ProductionJob

ROOT = Path("/data/soffy/projects/hevi/output/p4/batch-A")

TINY = [
    ("SCIENCE_EXPLAINER", "Stars and gravity", "Stars hold their shape by balancing gravity against pressure. When fuel runs out, the balance breaks and collapse begins."),
    ("HISTORICAL_NARRATIVE", "Paper road", "In ancient Chang'an, paper carried laws across the empire. Documents outlived the hands that wrote them."),
    ("EMOTIONAL_BOOK_REVIEW", "Quiet courage", "Fear knocked every evening that winter. Meditations by Marcus Aurelius taught me to answer calmly and keep going."),
    ("SCIENCE_EXPLAINER", "Tides", "The moon pulls the oceans into tides twice each day. Gravity reaches across empty space to move water."),
    ("HISTORICAL_NARRATIVE", "Harbor ledger", "Harbor clerks compared cargo marks against ledgers each dawn. Honest records kept the port alive for centuries."),
    ("EMOTIONAL_BOOK_REVIEW", "Morning page", "Grief visited again before sunrise today. Meditations by Marcus Aurelius reminded me that mornings can be gentle."),
    ("SCIENCE_EXPLAINER", "Light delay", "Sunlight needs eight minutes to reach Earth. Every sunrise is a message from the recent past."),
]

BOOK_1SEG = (
    "After my father passed away, solitude followed me through every quiet evening. "
    "Empty rooms kept his habits long after he was gone. "
    "Grief arrived without schedule, softening only when I stopped fighting it. "
    "Loneliness taught me to listen instead of running."
)
SCIENCE_1SEG = (
    "A black hole forms when a massive star collapses under its own gravity. "
    "The accretion disk around it glows with intense X-ray emission. "
    "Binary black holes spiral inward, merging in gravitational waves. "
    "Orbital visualizations reveal the warped spacetime near the event horizon."
)
HISTORY_1SEG = (
    "In the seventh century, Tang dynasty Chang'an became a meeting place for merchants and monks. "
    "Porcelain and silk traveled west while ideas traveled east along desert routes. "
    "Merchants compared Tang coins with Sogdian silver at every market. "
    "The consequence shaped maps, documents, and memory across centuries."
)


def _segments_field(narration: str) -> int:
    return 1


async def _runner(job: ProductionJob, _root: Path) -> dict[str, object]:
    return await run_job_mission(job, Path("/data/soffy/projects/hevi/output/p4/batch-A") / job.job_id)


async def main() -> int:
    jobs = [
        ProductionJob(job_id="job-book", profile_id="EMOTIONAL_BOOK_REVIEW",
                      topic="Solitude after loss", narration=BOOK_1SEG, priority=0,
                      book_meta={"title": "Meditations", "author": "Marcus Aurelius",
                                 "verified": True, "note": "PARAPHRASE"}),
        ProductionJob(job_id="job-science", profile_id="SCIENCE_EXPLAINER",
                      topic="Black hole formation", narration=SCIENCE_1SEG, priority=5),
        ProductionJob(job_id="job-history", profile_id="HISTORICAL_NARRATIVE",
                      topic="Tang Chang'an market", narration=HISTORY_1SEG, priority=5),
    ]
    for i, (prof, topic, narr) in enumerate(TINY):
        jobs.append(ProductionJob(job_id=f"job-tiny-{i}", profile_id=prof,
                                  topic=topic, narration=narr, priority=9))
    batch, store = create_batch(ROOT, jobs, concurrency_limit=2, budget_usd=100.0)
    batch.set_status("QUEUED")
    store.save(batch)
    sched = Scheduler(store)
    await sched.run(batch, _runner)
    store.save(batch)
    view = sched.dashboard(batch)
    (ROOT / "batch_report.json").write_text(json.dumps(view, indent=2), encoding="utf-8")
    print(json.dumps({"batch": batch.batch_id, "status": batch.status,
                      "metrics": sched.metrics_view(batch)}, indent=2))
    return 0 if batch.status == "COMPLETED" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
