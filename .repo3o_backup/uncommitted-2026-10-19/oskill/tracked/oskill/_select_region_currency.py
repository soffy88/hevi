"""oskill.select_region_currency — 按用户国家码选出首个匹配区域的币种。纯内存算法。"""

from __future__ import annotations


def select_region_currency(regions: list[dict], *, user_country: str) -> str:
    """返回首个 ``countries`` 含 ``user_country`` 的区域的币种代码。

    语义约定(确定性契约):
        - 按 ``regions`` 列表顺序线性扫描,命中第一个 ``countries`` 列表中包含
          ``user_country`` 的区域,返回其 ``currency``。
        - 国家码匹配为**精确、区分大小写**的字符串相等比较(国家码通常为大写
          ISO 3166-1 alpha-2,如 ``"CN"``);本函数不做归一化或大小写折叠。
        - 无任何区域命中(含 ``regions`` 为空)时抛 ``ValueError``,不返回默认
          币种——与 house guard 风格一致,宁可显式失败也不静默兜底。

    Args:
        regions: 区域列表,每项须含:
            - ``currency``: 币种代码(如 ``"CNY"``);
            - ``countries``: 该区域覆盖的国家码列表(如 ``["CN", "HK"]``);
            - ``code`` (可选): 区域标识,本函数不使用。
        user_country: 用户国家码(非空字符串)。

    Returns:
        首个匹配区域的 ``currency`` 字符串。

    Raises:
        ValueError: ``user_country`` 为空 / 非字符串;或某区域缺少
            ``currency`` / ``countries``;或没有任何区域命中。
    """
    if not isinstance(user_country, str) or not user_country:
        raise ValueError(
            f"select_region_currency: user_country must be a non-empty str, got {user_country!r}"
        )

    for region in regions:
        if "currency" not in region:
            raise ValueError("select_region_currency: region missing 'currency'")
        if "countries" not in region:
            raise ValueError("select_region_currency: region missing 'countries'")
        if user_country in region["countries"]:
            return region["currency"]

    raise ValueError(f"select_region_currency: no region matches country {user_country!r}")
