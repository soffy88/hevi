"""Clean-room HEVI regression contracts; no upstream code or media is used."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "case",
    [
        "MEDIA_METADATA_CACHE",
        "LARGE_LIBRARY_DURATION_PROBE",
        "TTS_METADATA_FAILURE",
        "VOICE_TRUNCATION_AFTER_NORMALIZATION",
        "BGM_MATCHING",
        "MISSING_BGM",
        "UNICODE_SENTENCE_SEGMENTATION",
        "NON_CHINESE_SUBTITLE_BOUNDARY",
        "BATCH_RENDER",
    ],
)
def test_clean_room_regression_case_is_named(case: str) -> None:
    assert case.isupper()
