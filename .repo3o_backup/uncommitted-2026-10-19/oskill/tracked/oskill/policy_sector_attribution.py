"""政策新闻 → 板块归因 + 实际涨幅联合分析 (oskill B10)."""

from __future__ import annotations

from datetime import date
from typing import Literal

import oprim
from oprim.policy_event_extraction import PolicyNews, policy_event_extraction
from pydantic import BaseModel

from oskill._exceptions import OskillError


class SectorAttributionRow(BaseModel):
    """单个板块的政策归因 + 实际涨幅.

    Attributes:
        sector_name:      板块名称.
        impact_direction: 政策影响方向 (positive/negative/uncertain).
        severity:         政策严重程度.
        actual_change_pct: 当日实际涨跌幅 (None 若无行情数据).
    """

    sector_name: str
    impact_direction: str
    severity: str
    actual_change_pct: float | None = None


class PolicySectorAttributionResult(BaseModel):
    """policy_sector_attribution 结果."""

    rows: list[SectorAttributionRow]
    attributed_count: int
    matched_count: int


async def policy_sector_attribution(
    *,
    news: list[PolicyNews],
    industry_keyword_map: dict[str, str],
    as_of_date: date | None = None,
    top_n: int = 10,
    source: Literal["akshare"] = "akshare",
) -> PolicySectorAttributionResult:
    """Link policy event impacts to sector performance data.

    Internal oprim composition:
    - oprim.policy_event_extraction  (sync; extracts structured events from news)
    - oprim.industry_attribution     (sync; maps events to industry impacts)
    - oprim.fetch_sector_returns     (async; fetches actual sector performance)

    Args:
        news:                 Raw policy news items.
        industry_keyword_map: Keyword→industry mapping injected by caller
                              (e.g. ``{"新能源": "电力设备", "房市": "房地产"}``).
        as_of_date:           Trading date for sector return lookup.
        top_n:                Max sectors to return from performance query.
        source:               Data source for sector returns.

    Returns:
        :class:`PolicySectorAttributionResult` with attributed rows and match count.

    Raises:
        OskillError: On sector fetch failure.

    Example:
        >>> news = [PolicyNews(content="央行降准0.5个百分点，支持新能源发展")]
        >>> r = await policy_sector_attribution(
        ...     news=news, industry_keyword_map={"新能源": "电力设备"}
        ... )
        >>> r.attributed_count >= 0
        True
    """
    if not news:
        return PolicySectorAttributionResult(rows=[], attributed_count=0, matched_count=0)

    events = policy_event_extraction(policies=news)
    impacts = oprim.industry_attribution(events=events, industry=industry_keyword_map)

    try:
        sector_returns = await oprim.fetch_sector_returns(
            as_of_date=as_of_date, top_n=top_n, source=source
        )
    except Exception as exc:
        raise OskillError(f"policy_sector_attribution: sector fetch failed: {exc}") from exc

    sector_return_map = {sr.sector_name: sr.change_pct for sr in sector_returns}

    rows: list[SectorAttributionRow] = []
    for impact in impacts:
        rows.append(
            SectorAttributionRow(
                sector_name=impact.industry,
                impact_direction=impact.impact_direction,
                severity=impact.severity,
                actual_change_pct=sector_return_map.get(impact.industry),
            )
        )

    matched = sum(1 for r in rows if r.actual_change_pct is not None)
    return PolicySectorAttributionResult(
        rows=rows,
        attributed_count=len(impacts),
        matched_count=matched,
    )
