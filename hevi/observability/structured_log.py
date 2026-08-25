import json
import logging
from typing import Any

from hevi.observability.trace import current_trace_context

logger = logging.getLogger("hevi.structured")


def log_event(
    *,
    stage: str,
    event: str,
    level: str = "info",
    **fields: Any,
) -> None:
    """Log a structured event in JSON format, including current trace_id."""
    record = {
        **current_trace_context().log_fields(),
        "stage": stage,
        "event": event,
        "level": level,
        **fields,
    }
    
    msg = json.dumps(record, ensure_ascii=False)
    
    if level == "error":
        logger.error(msg)
    elif level == "warning":
        logger.warning(msg)
    else:
        logger.info(msg)
