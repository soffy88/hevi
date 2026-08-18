"""批量翻译漏项 → 单条重试 → 仍失败保原文。

组合: `retry_delays` + `merge_batch_and_retries` + `should_keep_original`。
3O 归属(待上游): `oskill.translate_retry`。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from hevi.voicepro.oprim.translate_backoff import (
    merge_batch_and_retries,
    retry_delays,
    should_keep_original,
)
from hevi.voicepro.schemas import TranslateLineResult

TranslateFn = Callable[[str], Awaitable[str] | str]
SleepFn = Callable[[float], Awaitable[Any] | Any]


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


async def retry_one(
    text: str,
    translate_fn: TranslateFn,
    *,
    sleep_fn: SleepFn | None = None,
    max_retries: int = 4,
) -> tuple[str | None, int]:
    delays = retry_delays(max_retries=max_retries)
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            result = await _maybe_await(translate_fn(text))
            if not should_keep_original(result, text):
                return str(result).strip(), attempt + 1
        except Exception as exc:
            last_error = exc
        if attempt < len(delays) and sleep_fn is not None:
            await _maybe_await(sleep_fn(delays[attempt]))
    if last_error is not None:
        return None, max_retries
    return None, max_retries


async def fill_missing_lines(
    sources: list[str],
    batch: dict[int, str],
    translate_fn: TranslateFn,
    *,
    sleep_fn: SleepFn | None = None,
    max_retries: int = 4,
) -> list[TranslateLineResult]:
    singles: dict[int, str] = {}
    attempts: dict[int, int] = {}
    for index, source in enumerate(sources):
        existing = batch.get(index)
        if not should_keep_original(existing, source):
            attempts[index] = 1
            continue
        translated, used = await retry_one(
            source,
            translate_fn,
            sleep_fn=sleep_fn,
            max_retries=max_retries,
        )
        attempts[index] = used
        if translated is not None:
            singles[index] = translated
    return merge_batch_and_retries(sources, batch, singles, attempts=attempts)
