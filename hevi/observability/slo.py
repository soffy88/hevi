"""Operational SLO targets from the Hevi architecture contract."""

SLO_TARGETS: dict[str, str] = {
    "production_api_availability": ">=99.9%",
    "task_state_durability": ">=99.99%",
    "event_propagation_p95": "<2s",
    "duplicate_execution": "<0.1%",
    "billing_duplicate_charge": "0",
    "completed_artifact_availability": "100%",
    "crash_discovery": "<=2m",
    "recovery_resume_retry_human": "<=10m",
}

__all__ = ["SLO_TARGETS"]
