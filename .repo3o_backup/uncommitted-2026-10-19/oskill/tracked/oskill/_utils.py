import re
from typing import Any


def extract_confidence(content: Any) -> float:
    """Helper to extract confidence score from text."""
    text = str(content).lower()
    # Support "confidence: 0.85" or "0.85 certain" or just "0.85"
    match = re.search(r"(?:confidence[:\s]+|certain[:\s]*|)(0?\.\d+|1\.0|1)(?:\s+|$)", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return 0.5
