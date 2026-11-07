"""OKX Demo Trading REST API client.

Endpoint base: https://www.okx.com/api/v5/
Demo header: x-simulated-trading: 1
"""

from __future__ import annotations

import json

import aiohttp
import structlog

from oskill.exchange.okx_demo._signing import make_timestamp, sign_request
from oskill.exchange.okx_demo._types import AccountSnapshot, OrderResponse

log = structlog.get_logger(__name__)


class OKXAPIError(Exception):
    """Non-zero code from OKX API."""

    def __init__(self, code: str, msg: str, response: dict):
        super().__init__(f"OKX API error {code}: {msg}")
        self.code = code
        self.msg = msg
        self.response = response


class OKXClientError(Exception):
    """Network / connection failure."""


class OKXDemoRestClient:
    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        passphrase: str,
        api_base: str = "https://www.okx.com",
        timeout_sec: float = 10.0,
        proxy: str | None = None,
    ):
        if not all([api_key, api_secret, passphrase]):
            raise ValueError("api_key, api_secret, passphrase required")
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.api_base = api_base.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout_sec)
        self.proxy = proxy

    def _headers(self, method: str, path: str, body: str = "") -> dict:
        ts = make_timestamp()
        sig = sign_request(self.api_secret, ts, method, path, body)
        return {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": sig,
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "x-simulated-trading": "1",
            "Content-Type": "application/json",
        }

    async def submit_order(
        self,
        *,
        inst_id: str,
        td_mode: str = "cash",
        side: str,
        ord_type: str = "market",
        size_in_base: float,
        cl_ord_id: str | None = None,
    ) -> OrderResponse:
        """POST /api/v5/trade/order"""
        path = "/api/v5/trade/order"
        body_obj: dict = {
            "instId": inst_id,
            "tdMode": td_mode,
            "side": side,
            "ordType": ord_type,
            "sz": str(size_in_base),
        }
        if cl_ord_id:
            body_obj["clOrdId"] = cl_ord_id
        body_str = json.dumps(body_obj)

        url = self.api_base + path
        headers = self._headers("POST", path, body_str)

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                kwargs: dict = {"headers": headers, "data": body_str}
                if self.proxy:
                    kwargs["proxy"] = self.proxy
                async with session.post(url, **kwargs) as r:
                    if r.status != 200:
                        text = await r.text()
                        raise OKXClientError(f"HTTP {r.status}: {text[:200]}")
                    data = await r.json()
        except TimeoutError as e:
            raise OKXClientError(f"timeout submitting order: {e}") from e
        except aiohttp.ClientError as e:
            raise OKXClientError(f"client error: {e}") from e

        return OrderResponse(
            code=data.get("code", "?"),
            msg=data.get("msg", ""),
            in_time=int(data.get("inTime", 0)),
            out_time=int(data.get("outTime", 0)),
            data=data.get("data", []),
        )

    async def get_account_balance(self) -> AccountSnapshot:
        """GET /api/v5/account/balance"""
        path = "/api/v5/account/balance"
        url = self.api_base + path
        headers = self._headers("GET", path)

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                kwargs: dict = {"headers": headers}
                if self.proxy:
                    kwargs["proxy"] = self.proxy
                async with session.get(url, **kwargs) as r:
                    if r.status != 200:
                        raise OKXClientError(f"HTTP {r.status}")
                    data = await r.json()
        except TimeoutError as e:
            raise OKXClientError(f"timeout fetching balance: {e}") from e
        except aiohttp.ClientError as e:
            raise OKXClientError(f"client error: {e}") from e

        if data.get("code") != "0":
            raise OKXAPIError(data.get("code", "?"), data.get("msg", ""), data)

        try:
            account = data["data"][0]
            total_eq = float(account.get("totalEq", 0))
            balances = {d["ccy"]: float(d.get("availBal", 0)) for d in account.get("details", [])}
            update_time = int(account.get("uTime", 0))
        except (KeyError, IndexError, ValueError) as e:
            raise OKXAPIError("parse_error", str(e), data) from e

        return AccountSnapshot(
            total_eq_usd=total_eq,
            available_balance=balances,
            update_time_ms=update_time,
            raw=data,
        )
