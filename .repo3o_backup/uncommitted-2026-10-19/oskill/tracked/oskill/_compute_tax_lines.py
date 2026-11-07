"""oskill.compute_tax_lines — 为每条商品行按税率表逐行计算税额明细。纯内存算法。"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def compute_tax_lines(items: list[dict], *, rates: list[dict]) -> list[dict]:
    """为每条商品行叠加全部税率,产出 (商品行 × 税率) 的税额明细列表。

    语义约定(确定性契约):
        - 对 ``items`` 中的每一条商品行,依次套用 ``rates`` 中的每一个税率,
          每个 (商品行, 税率) 组合产出一条独立的税额明细。因此返回长度等于
          ``len(items) * len(rates)``;任一列表为空时返回 ``[]``。
        - 税额以分为单位,``tax_cents = round_half_up(line_total_cents *
          rate_percent / 100)``,采用 ROUND_HALF_UP(四舍五入,0.5 进位),
          而非 Python 内置 ``round`` 的银行家舍入。
        - 本函数不做任何汇总,逐行原样记录,供下游 ``compute_line_item_totals``
          自行聚合(两者刻意各自独立,不互相调用)。

    Args:
        items: 商品行列表,每项须含:
            - ``item_id``: 商品行唯一标识(用于下游回溯);
            - ``line_total_cents``: 该行小计(整数分,非负)。
        rates: 税率列表,每项须含:
            - ``rate_percent``: 税率百分比(如 ``13.0`` 表示 13%,非负);
            - ``rate_id`` (可选): 税率标识,缺省时明细中记为 ``None``。

    Returns:
        税额明细列表,每项形如::

            {"item_id": ..., "rate_id": ..., "rate_percent": ..., "tax_cents": ...}

        其中 ``tax_cents`` 为整数分。

    Raises:
        ValueError: 商品行缺少 ``item_id`` / ``line_total_cents``,或
            ``line_total_cents`` 非整数 / 为负;或税率缺少 ``rate_percent`` /
            为负。
    """
    lines: list[dict] = []
    for item in items:
        if "item_id" not in item:
            raise ValueError("compute_tax_lines: item missing 'item_id'")
        if "line_total_cents" not in item:
            raise ValueError("compute_tax_lines: item missing 'line_total_cents'")
        subtotal = item["line_total_cents"]
        if isinstance(subtotal, bool) or not isinstance(subtotal, int):
            raise ValueError(f"compute_tax_lines: line_total_cents must be int, got {subtotal!r}")
        if subtotal < 0:
            raise ValueError(f"compute_tax_lines: line_total_cents must be >= 0, got {subtotal}")

        for rate in rates:
            if "rate_percent" not in rate:
                raise ValueError("compute_tax_lines: rate missing 'rate_percent'")
            rate_percent = rate["rate_percent"]
            if isinstance(rate_percent, bool) or not isinstance(rate_percent, (int, float)):
                raise ValueError(
                    f"compute_tax_lines: rate_percent must be a number, got {rate_percent!r}"
                )
            if rate_percent < 0:
                raise ValueError(
                    f"compute_tax_lines: rate_percent must be >= 0, got {rate_percent}"
                )

            tax = (Decimal(subtotal) * Decimal(str(rate_percent)) / Decimal(100)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
            lines.append(
                {
                    "item_id": item["item_id"],
                    "rate_id": rate.get("rate_id"),
                    "rate_percent": rate_percent,
                    "tax_cents": int(tax),
                }
            )

    return lines
