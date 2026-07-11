"""成本路由 v2 —— 经验质量分布测试(HEVI 路线图 Phase4 #46)。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hevi.cost.empirical_quality import (
    get_empirical_quality,
    rank_providers_by_empirical_quality,
)


@pytest.mark.asyncio
async def test_returns_none_below_min_sample_threshold():
    pool = MagicMock()
    with patch(
        "obase.persistence.query",
        new_callable=AsyncMock,
        return_value=[{"median": 0.9, "n": 3}],
    ):
        result = await get_empirical_quality(pool, provider="kling_v2")
    assert result is None


@pytest.mark.asyncio
async def test_returns_median_when_enough_samples():
    pool = MagicMock()
    with patch(
        "obase.persistence.query",
        new_callable=AsyncMock,
        return_value=[{"median": 0.82, "n": 12}],
    ):
        result = await get_empirical_quality(pool, provider="kling_v2")
    assert result == pytest.approx(0.82)


@pytest.mark.asyncio
async def test_returns_none_when_no_rows():
    pool = MagicMock()
    with patch("obase.persistence.query", new_callable=AsyncMock, return_value=[]):
        result = await get_empirical_quality(pool, provider="kling_v2")
    assert result is None


@pytest.mark.asyncio
async def test_filters_by_style_pack_id_when_given():
    pool = MagicMock()
    with patch(
        "obase.persistence.query",
        new_callable=AsyncMock,
        return_value=[{"median": 0.7, "n": 10}],
    ) as mock_query:
        await get_empirical_quality(pool, provider="kling_v2", style_pack_id="pack-1")
    call = mock_query.call_args
    assert "style_pack_id" in call.kwargs["sql"]
    assert call.kwargs["params"] == ["kling_v2", "pack-1"]


@pytest.mark.asyncio
async def test_rank_providers_omits_providers_without_enough_data():
    pool = MagicMock()

    async def _fake_query(pool_arg, *, sql, params):
        provider = params[0]
        data = {"kling_v2": [{"median": 0.9, "n": 20}], "hailuo": [{"median": 0.5, "n": 2}]}
        return data.get(provider, [])

    with patch("obase.persistence.query", side_effect=_fake_query):
        ranked = await rank_providers_by_empirical_quality(pool, candidates=["kling_v2", "hailuo"])
    assert ranked == {"kling_v2": 0.9}  # hailuo 样本不够,不出现在结果里(不是补 0)
