"""OKX Demo API response types (light dataclasses, no Pydantic)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OrderResponse:
    """OKX POST /api/v5/trade/order response."""

    code: str
    msg: str
    in_time: int
    out_time: int
    data: list[dict]


@dataclass
class FillEvent:
    """OKX WS private orders channel fill event."""

    inst_id: str
    ord_id: str
    cl_ord_id: str
    fill_id: str
    side: str
    fill_px: float
    fill_sz: float
    fill_time_ms: int
    fee: float
    fee_ccy: str
    state: str
    raw: dict = field(default_factory=dict)


@dataclass
class AccountSnapshot:
    """OKX account state."""

    total_eq_usd: float
    available_balance: dict
    update_time_ms: int
    raw: dict = field(default_factory=dict)
