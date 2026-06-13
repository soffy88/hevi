import httpx


class HeviError(Exception):
    """Base error for Hevi."""
    pass


class UnretryableError(HeviError):
    """Errors that should NOT be retried (e.g. 401, 400, quota exhausted)."""
    pass


class RetryableError(HeviError):
    """Errors that CAN be retried (e.g. 429, 5xx, timeout)."""
    pass


class RateLimitError(RetryableError):
    """429 Rate Limit."""
    pass


def classify_error(exc: Exception) -> HeviError:
    """Classify an exception into Hevi errors."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 429:
            return RateLimitError(f"Rate limited: {exc}")
        if status in (401, 403, 400, 404):
            return UnretryableError(f"Client error (unretryable): {exc}")
        if 500 <= status < 600:
            return RetryableError(f"Server error: {exc}")
    
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, TimeoutError)):
        return RetryableError(f"Network/Timeout error: {exc}")
        
    # Default to unretryable if we don't know (to avoid infinite loops on logic bugs)
    return UnretryableError(f"Unknown error (assumed unretryable): {exc}")
