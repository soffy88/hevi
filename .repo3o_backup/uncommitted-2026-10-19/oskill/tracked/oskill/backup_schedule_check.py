"""Backup schedule check oskill."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import boto3
from oprim import OprimConnectionError
from pydantic import BaseModel


class BackupScheduleCheckResult(BaseModel):
    app_slug: str
    last_backup_at: str | None
    age_hours: float | None
    status: Literal["ok", "overdue", "no_backup_found"]
    max_age_hours: int


def backup_schedule_check(
    *,
    app_slug: str,
    backup_bucket: str,
    s3_prefix: str,
    max_age_hours: int = 24,
    aws_endpoint_url: str | None = None,
    aws_access_key_id: str | None = None,
    aws_secret_access_key: str | None = None,
) -> BackupScheduleCheckResult:
    """Checks if the latest backup is within the expected time window."""
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=aws_endpoint_url,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
        )

        response = s3.list_objects_v2(Bucket=backup_bucket, Prefix=s3_prefix)
        objects = response.get("Contents", [])

        if not objects:
            return BackupScheduleCheckResult(
                app_slug=app_slug,
                last_backup_at=None,
                age_hours=None,
                status="no_backup_found",
                max_age_hours=max_age_hours,
            )

        # Find the latest modified object
        latest_obj = max(objects, key=lambda x: x["LastModified"])
        last_modified = latest_obj["LastModified"]

        now = datetime.now(UTC)
        age_hours = (now - last_modified).total_seconds() / 3600

        status: Literal["ok", "overdue"] = "ok" if age_hours <= max_age_hours else "overdue"

        return BackupScheduleCheckResult(
            app_slug=app_slug,
            last_backup_at=last_modified.isoformat(),
            age_hours=round(age_hours, 2),
            status=status,
            max_age_hours=max_age_hours,
        )
    except Exception as exc:
        raise OprimConnectionError(f"S3 backup check failed for {app_slug}: {exc}") from exc
