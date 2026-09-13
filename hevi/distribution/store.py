from __future__ import annotations

import json
import os
from pathlib import Path

from hevi.distribution.models import DistributionJob


class DistributionJobStore:
    """Small durable projection; task orchestration remains HEVI-owned."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def get(self, job_id: str) -> DistributionJob | None:
        if not self.path.is_file():
            return None
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        item = raw.get(job_id)
        return DistributionJob.model_validate(item) if item else None

    def put(self, job: DistributionJob) -> DistributionJob:
        current: dict[str, object] = {}
        if self.path.is_file():
            current = json.loads(self.path.read_text(encoding="utf-8"))
        current[job.distribution_job_id] = job.model_dump(mode="json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        with temp.open("r+b") as stream:
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(self.path)
        return job
