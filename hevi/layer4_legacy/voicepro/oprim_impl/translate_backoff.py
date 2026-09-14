"""翻译退避:指数重试间隔 + 失败保原文。

对齐 Voice-Pro `abus_translate_deep._translate_with_retry`(2/4/8s,最多 4 次)。
3O 归属(待上游): `oprim.translate_backoff`。
"""

from __future__ import annotations

from hevi.voicepro.schemas import TranslateLineResult

MAX_RETRIES = 4
REQUEST_INTERVAL_S = 0.2
INITIAL_DELAY_S = 2.0


def retry_delays(
    *,
    max_retries: int = MAX_RETRIES,
    initial_s: float = INITIAL_DELAY_S,
) -> list[float]:
    """attempt 之间的睡眠;长度为 max_retries-1。"""
    if max_retries <= 1:
        return []
    delay = initial_s
    waits: list[float] = []
    for _ in range(max_retries - 1):
        waits.append(delay)
        delay *= 2
    return waits


def should_keep_original(result: str | None, source: str) -> bool:
    if result is None:
        return True
    text = result.strip()
    return not text


def merge_batch_and_retries(
    sources: list[str],
    batch: dict[int, str],
    singles: dict[int, str] | None = None,
    *,
    attempts: dict[int, int] | None = None,
) -> list[TranslateLineResult]:
    """批量译文 + 漏译单条重试 → 每行结果;仍空则保原文。"""
    singles = singles or {}
    attempts = attempts or {}
    rows: list[TranslateLineResult] = []
    for index, source in enumerate(sources):
        candidate = singles.get(index)
        if candidate is None:
            candidate = batch.get(index)
        kept = should_keep_original(candidate, source)
        translated = source if kept else str(candidate).strip()
        rows.append(
            TranslateLineResult(
                index=index,
                source=source,
                translated=translated,
                kept_original=kept,
                attempts=int(attempts.get(index, 1)),
            )
        )
    return rows
