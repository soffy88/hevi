"""oskill.evaluate_tax_inclusive_pricing — 由含税价反推净价与税额。纯内存算法。"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def evaluate_tax_inclusive_pricing(price: int, *, tax_rate: float) -> dict:
    """由含税价(毛价)反推净价(税前价)与税额,均以整数分计。

    语义约定(确定性契约):
        - 入参 ``price`` 为**含税**毛价 ``gross_cents``。
        - 净价 ``net_cents = round_half_up(gross / (1 + tax_rate / 100))``,采用
          ROUND_HALF_UP(四舍五入,0.5 进位),而非银行家舍入。
        - 税额 ``tax_cents = gross_cents - net_cents``,由此**恒等**保证
          ``gross_cents == net_cents + tax_cents``(不因舍入产生 1 分误差)。
        - ``tax_rate`` 为百分比(如 ``13.0`` 表示 13%);``0`` 表示免税,此时
          ``net_cents == gross_cents`` 且 ``tax_cents == 0``。

    Args:
        price: 含税毛价(整数分,非负)。
        tax_rate: 税率百分比(如 ``13.0``,非负)。

    Returns:
        形如 ``{"gross_cents": int, "net_cents": int, "tax_cents": int}`` 的字典,
        三者均为整数分且 ``gross_cents == net_cents + tax_cents``。

    Raises:
        ValueError: ``price`` 非整数 / 为负;或 ``tax_rate`` 非数值 / 为负。
    """
    if isinstance(price, bool) or not isinstance(price, int):
        raise ValueError(f"evaluate_tax_inclusive_pricing: price must be int, got {price!r}")
    if price < 0:
        raise ValueError(f"evaluate_tax_inclusive_pricing: price must be >= 0, got {price}")
    if isinstance(tax_rate, bool) or not isinstance(tax_rate, (int, float)):
        raise ValueError(
            f"evaluate_tax_inclusive_pricing: tax_rate must be a number, got {tax_rate!r}"
        )
    if tax_rate < 0:
        raise ValueError(f"evaluate_tax_inclusive_pricing: tax_rate must be >= 0, got {tax_rate}")

    factor = Decimal(1) + Decimal(str(tax_rate)) / Decimal(100)
    net = int((Decimal(price) / factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    tax = price - net

    return {
        "gross_cents": price,
        "net_cents": net,
        "tax_cents": tax,
    }
