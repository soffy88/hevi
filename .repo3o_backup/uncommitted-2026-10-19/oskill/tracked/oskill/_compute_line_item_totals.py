"""oskill.compute_line_item_totals — 汇总单条商品行的小计/税额/总计。纯内存算法。"""

from __future__ import annotations


def compute_line_item_totals(item: dict, *, taxes: list[dict]) -> dict:
    """汇总单条商品行的小计、税额与总计(均以整数分计)。

    语义约定(确定性契约):
        - 小计 ``subtotal_cents`` 优先取 ``item["line_total_cents"]``;若该键
          缺失,则退化为 ``unit_price_cents * quantity``。二者至少需满足其一。
        - 税额 ``tax_cents`` 为传入 ``taxes`` 列表中所有明细 ``tax_cents`` 之和。
          调用方须只传入本商品行自己的税额明细(通常来自 ``compute_tax_lines``
          按 ``item_id`` 过滤后的结果);本函数不再二次过滤,直接全额累加。
          ``taxes`` 为空时税额为 0。
        - 总计 ``total_cents = subtotal_cents + tax_cents``,恒等成立。
        - 本函数与 ``compute_tax_lines`` 刻意各自独立,不互相调用。

    Args:
        item: 单条商品行,须含 ``line_total_cents``(整数分,非负),或同时含
            ``unit_price_cents``(整数分,非负)与 ``quantity``(整数,非负)。
        taxes: 本商品行的税额明细列表,每项须含 ``tax_cents``(整数分)。

    Returns:
        形如 ``{"subtotal_cents": int, "tax_cents": int, "total_cents": int}``
        的汇总字典,三者均为整数分且 ``total_cents == subtotal_cents +
        tax_cents``。

    Raises:
        ValueError: 商品行既无 ``line_total_cents`` 也缺少完整的
            ``unit_price_cents`` / ``quantity``;或小计/单价/数量取值非法
            (非整数、为负);或某条税额明细缺少 ``tax_cents`` / 非整数。
    """
    if "line_total_cents" in item:
        subtotal = item["line_total_cents"]
        if isinstance(subtotal, bool) or not isinstance(subtotal, int):
            raise ValueError(
                f"compute_line_item_totals: line_total_cents must be int, got {subtotal!r}"
            )
        if subtotal < 0:
            raise ValueError(
                f"compute_line_item_totals: line_total_cents must be >= 0, got {subtotal}"
            )
    elif "unit_price_cents" in item and "quantity" in item:
        unit_price = item["unit_price_cents"]
        quantity = item["quantity"]
        if isinstance(unit_price, bool) or not isinstance(unit_price, int):
            raise ValueError(
                f"compute_line_item_totals: unit_price_cents must be int, got {unit_price!r}"
            )
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise ValueError(f"compute_line_item_totals: quantity must be int, got {quantity!r}")
        if unit_price < 0:
            raise ValueError(
                f"compute_line_item_totals: unit_price_cents must be >= 0, got {unit_price}"
            )
        if quantity < 0:
            raise ValueError(f"compute_line_item_totals: quantity must be >= 0, got {quantity}")
        subtotal = unit_price * quantity
    else:
        raise ValueError(
            "compute_line_item_totals: item needs 'line_total_cents' or both "
            "'unit_price_cents' and 'quantity'"
        )

    tax_total = 0
    for line in taxes:
        if "tax_cents" not in line:
            raise ValueError("compute_line_item_totals: tax line missing 'tax_cents'")
        tax = line["tax_cents"]
        if isinstance(tax, bool) or not isinstance(tax, int):
            raise ValueError(f"compute_line_item_totals: tax_cents must be int, got {tax!r}")
        tax_total += tax

    return {
        "subtotal_cents": subtotal,
        "tax_cents": tax_total,
        "total_cents": subtotal + tax_total,
    }
