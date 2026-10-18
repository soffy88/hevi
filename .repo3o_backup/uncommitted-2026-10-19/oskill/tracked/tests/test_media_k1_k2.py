"""Tests for K-1 and K-2 of the video/audio ingestion batch."""

from __future__ import annotations

import pytest
from oprim._media_types import FilterRules, TranscriptResult, VideoMeta

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _vm(
    video_id="v1",
    title="Python Tutorial",
    duration=300.0,
    upload_date="20240301",
    description="A tutorial",
) -> VideoMeta:
    return VideoMeta(
        video_id=video_id,
        title=title,
        duration=duration,
        url=f"https://yt.be/{video_id}",
        upload_date=upload_date,
        description=description,
    )


def _yes_llm():
    async def caller(*, messages, max_tokens=8, **kw):
        return {"content": [{"type": "text", "text": "YES"}]}

    return caller


def _no_llm():
    async def caller(*, messages, max_tokens=8, **kw):
        return {"content": [{"type": "text", "text": "NO"}]}

    return caller


def _md_llm(md: str = "# Title\n\n## Topic\n- Point [00:10](https://yt.be/v1?t=10)"):
    async def caller(*, messages, max_tokens=4096, **kw):
        return {"content": [{"type": "text", "text": md}]}

    return caller


_VIDEOS = [
    _vm("v1", "Python入门", 300.0, "20240301"),
    _vm("v2", "广告推广", 60.0, "20240302"),
    _vm("v3", "JavaScript高级", 900.0, "20231201"),
    _vm("v4", "Python进阶", 600.0, "20240401"),
]


# ===========================================================================
# K-1: video_filter_by_rules
# ===========================================================================


class TestVideoFilterByRules:
    async def test_pure_rules_no_llm(self):
        from oskill._video_filter_by_rules import video_filter_by_rules

        rules = FilterRules(min_duration=200.0)
        result = await video_filter_by_rules(_VIDEOS, rules=rules, llm=None)
        for v in result:
            assert v.duration >= 200.0

    async def test_llm_filter_yes_keeps_all(self):
        from oskill._video_filter_by_rules import video_filter_by_rules

        rules = FilterRules(llm_filter="Python相关内容")
        result = await video_filter_by_rules(_VIDEOS, rules=rules, llm=_yes_llm())
        assert len(result) == len(_VIDEOS)

    async def test_llm_filter_no_removes_all(self):
        from oskill._video_filter_by_rules import video_filter_by_rules

        rules = FilterRules(llm_filter="编程教程")
        result = await video_filter_by_rules(_VIDEOS, rules=rules, llm=_no_llm())
        assert result == []

    async def test_llm_none_skips_llm_step(self):
        from oskill._video_filter_by_rules import video_filter_by_rules

        rules = FilterRules(llm_filter="anything", limit=2)
        result = await video_filter_by_rules(_VIDEOS, rules=rules, llm=None)
        # LLM skipped; only rule limit=2 applied
        assert len(result) == 2

    async def test_empty_list_returns_empty(self):
        from oskill._video_filter_by_rules import video_filter_by_rules

        rules = FilterRules()
        result = await video_filter_by_rules([], rules=rules, llm=_yes_llm())
        assert result == []

    async def test_llm_failure_propagates(self):
        from oskill._video_filter_by_rules import video_filter_by_rules

        async def broken_llm(*, messages, **kw):
            raise RuntimeError("LLM service unavailable")

        rules = FilterRules(llm_filter="test")
        with pytest.raises(RuntimeError, match="LLM service"):
            await video_filter_by_rules([_vm()], rules=rules, llm=broken_llm)

    async def test_rules_then_llm_stacked(self):
        """Rule filters first, then LLM filters the result."""
        from oskill._video_filter_by_rules import video_filter_by_rules

        called_titles = []

        async def recording_llm(*, messages, **kw):
            for msg in messages:
                if "Video title:" in msg.get("content", ""):
                    called_titles.append(msg["content"])
            return {"content": "YES"}

        rules = FilterRules(min_duration=200.0, llm_filter="relevant")
        await video_filter_by_rules(_VIDEOS, rules=rules, llm=recording_llm)
        # Only videos with duration >= 200 should have been passed to LLM
        for title_ctx in called_titles:
            assert "广告推广" not in title_ctx  # duration 60 < 200, filtered before LLM

    async def test_title_exclude_runs_before_llm_filter(self):
        """title_exclude must eliminate videos before LLM sees them."""
        from oskill._video_filter_by_rules import video_filter_by_rules

        seen_titles = []

        async def spy_yes_llm(*, messages, **kw):
            for msg in messages:
                seen_titles.append(msg.get("content", ""))
            return {"content": "YES"}

        rules = FilterRules(title_exclude=["广告"], llm_filter="anything")
        await video_filter_by_rules(_VIDEOS, rules=rules, llm=spy_yes_llm)
        assert all("广告" not in t for t in seen_titles)

    async def test_limit_applied_after_rules(self):
        from oskill._video_filter_by_rules import video_filter_by_rules

        rules = FilterRules(limit=1)
        result = await video_filter_by_rules(_VIDEOS, rules=rules, llm=None)
        assert len(result) == 1


# ===========================================================================
# K-2: media_to_structured_md
# ===========================================================================

_TR = TranscriptResult(
    text="Python is great. Lists are useful. Dicts map keys to values.",
    segments=[
        {"start": 0.0, "end": 5.0, "text": "Python is great."},
        {"start": 5.0, "end": 10.0, "text": "Lists are useful."},
        {"start": 10.0, "end": 20.0, "text": "Dicts map keys to values."},
    ],
    language="en",
    duration=20.0,
)

_MD_RESPONSE = (
    "# Python Tutorial\n\n"
    "## Core Data Structures\n"
    "- Python is a great language [00:00](https://yt.be/v1?t=0)\n"
    "- Lists store ordered data [00:05](https://yt.be/v1?t=5)\n"
    "- Dicts map keys to values [00:10](https://yt.be/v1?t=10)\n"
)


class TestMediaToStructuredMd:
    async def test_transcript_result_input(self):
        from oskill._media_to_structured_md import media_to_structured_md

        result = await media_to_structured_md(
            transcript=_TR,
            title="Python Tutorial",
            source_url="https://yt.be/v1",
            llm=_md_llm(_MD_RESPONSE),
        )
        assert "# Python Tutorial" in result or result.startswith("#")

    async def test_plain_string_input(self):
        from oskill._media_to_structured_md import media_to_structured_md

        result = await media_to_structured_md(
            transcript="Python is great for data science.",
            title="Python Talk",
            source_url="https://yt.be/v2",
            llm=_md_llm("# Python Talk\n\n## Data Science\n- Great language\n"),
        )
        assert "Python Talk" in result

    async def test_timestamp_anchors_format(self):
        from oskill._media_to_structured_md import media_to_structured_md

        result = await media_to_structured_md(
            transcript=_TR,
            title="Python Tutorial",
            source_url="https://yt.be/v1",
            llm=_md_llm(_MD_RESPONSE),
        )
        import re

        # Check for timestamp anchors in [MM:SS](url?t=N) format
        anchors = re.findall(r"\[\d{2}:\d{2}\]\(https://yt\.be/v1\?t=\d+\)", result)
        assert len(anchors) >= 1

    async def test_empty_transcript_text_raises(self):
        from oskill._media_to_structured_md import media_to_structured_md

        empty_tr = TranscriptResult(text="", segments=[], language="zh", duration=0.0)
        with pytest.raises(ValueError, match="transcript"):
            await media_to_structured_md(
                transcript=empty_tr,
                title="Test",
                source_url="https://yt.be/v1",
                llm=_md_llm(),
            )

    async def test_empty_string_transcript_raises(self):
        from oskill._media_to_structured_md import media_to_structured_md

        with pytest.raises(ValueError, match="transcript"):
            await media_to_structured_md(
                transcript="   ",
                title="Test",
                source_url="https://yt.be/v1",
                llm=_md_llm(),
            )

    async def test_empty_title_raises(self):
        from oskill._media_to_structured_md import media_to_structured_md

        with pytest.raises(ValueError, match="title"):
            await media_to_structured_md(
                transcript=_TR,
                title="",
                source_url="https://yt.be/v1",
                llm=_md_llm(),
            )

    async def test_chinese_transcript(self):
        from oskill._media_to_structured_md import media_to_structured_md

        zh_tr = TranscriptResult(
            text="人工智能改变了世界。深度学习是核心技术。",
            segments=[{"start": 0.0, "end": 5.0, "text": "人工智能改变了世界。"}],
            language="zh",
            duration=5.0,
        )
        zh_md = (
            "# 人工智能讲座\n\n## 核心概念\n- 人工智能改变了世界 [00:00](https://yt.be/v3?t=0)\n"
        )
        result = await media_to_structured_md(
            transcript=zh_tr,
            title="人工智能讲座",
            source_url="https://yt.be/v3",
            llm=_md_llm(zh_md),
        )
        assert "人工智能" in result

    async def test_llm_exception_propagates(self):
        from oskill._media_to_structured_md import media_to_structured_md

        async def failing_llm(*, messages, **kw):
            raise RuntimeError("API timeout")

        with pytest.raises(RuntimeError, match="API timeout"):
            await media_to_structured_md(
                transcript=_TR,
                title="Test",
                source_url="https://yt.be/v1",
                llm=failing_llm,
            )

    async def test_bare_timestamp_marker_converted_to_link(self):
        """Bare [MM:SS] in LLM output should be converted to a link."""
        from oskill._media_to_structured_md import media_to_structured_md

        bare_md = "# Test\n\n## Topic\n- Key point [01:23]\n"
        result = await media_to_structured_md(
            transcript=_TR,
            title="Test",
            source_url="https://yt.be/v1",
            llm=_md_llm(bare_md),
        )
        import re

        assert re.search(r"\[01:23\]\(https://yt\.be/v1\?t=83\)", result)
