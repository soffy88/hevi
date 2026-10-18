"""B6 — Economic calendar surprise detection."""

from __future__ import annotations

from typing import Any


def calendar_surprise_detect(
    *,
    events: list[dict[str, Any]],
    importance_filter: int = 0,
) -> list[dict[str, Any]]:
    """Detect surprises in economic calendar events.

    Parameters
    ----------
    events : list of dicts with keys: name, actual, forecast, importance (1-3)
    importance_filter : minimum importance level (0 = all)

    Returns
    -------
    list of surprise dicts with: name, actual, forecast, surprise_pct, severity (minor/major)
    """
    surprises: list[dict[str, Any]] = []

    for event in events:
        importance = event.get("importance", 1)
        if importance < importance_filter:
            continue

        actual = event.get("actual")
        forecast = event.get("forecast")

        if actual is None:
            continue

        if forecast is None or forecast == 0:
            # Use absolute difference when forecast is 0 or missing
            diff = abs(float(actual))
            surprise_pct = diff * 100 if diff > 0 else 0.0
        else:
            surprise_pct = abs((float(actual) - float(forecast)) / float(forecast)) * 100

        if surprise_pct < 5.0:
            continue

        severity = "major" if surprise_pct >= 50.0 else "minor"

        surprises.append(
            {
                "name": event.get("name", ""),
                "actual": actual,
                "forecast": forecast,
                "surprise_pct": round(surprise_pct, 2),
                "severity": severity,
                "importance": importance,
            }
        )

    return surprises
