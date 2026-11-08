"""Public-beta film quota (free tier).

One account may submit at most ``HEVI_BETA_DAILY_FILMS`` finished films per
calendar day (Asia/Shanghai), each at most ``HEVI_BETA_MAX_DURATION_S`` seconds,
with at most ``HEVI_BETA_MAX_CONCURRENT`` active production at a time.

The counter is durable (``film_jobs``) rather than in-memory so a restart or a
second API process cannot hand out extra credits.  A reservation is written
before any render starts; it is marked ``completed`` when a film is produced and
``failed``/``released`` otherwise, so failures do not consume the daily quota.
"""

from .service import (
    BETA_DAILY_FILMS,
    BETA_MAX_CONCURRENT,
    BETA_MAX_DURATION_S,
    QuotaError,
    QuotaService,
    beta_free_enabled,
    get_quota_service,
    requested_duration_seconds,
    resolve_max_duration_s,
)

__all__ = [
    "BETA_DAILY_FILMS",
    "BETA_MAX_CONCURRENT",
    "BETA_MAX_DURATION_S",
    "QuotaError",
    "QuotaService",
    "beta_free_enabled",
    "get_quota_service",
    "requested_duration_seconds",
    "resolve_max_duration_s",
]
