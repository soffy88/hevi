"""OKX Demo private WebSocket (orders + account channels).

Default endpoint: wss://wspap.okx.com:8443/ws/v5/private
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

import aiohttp
import structlog

from oskill.exchange.okx_demo._signing import make_timestamp, sign_request
from oskill.exchange.okx_demo._types import FillEvent

log = structlog.get_logger(__name__)

_DEFAULT_WS_URL = "wss://wspap.okx.com:8443/ws/v5/private"


class OKXDemoWSPrivate:
    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        passphrase: str,
        on_order_event: Callable[[FillEvent], Awaitable[None]],
        on_account_event: Callable[[dict], Awaitable[None]] | None = None,
        ws_url: str = _DEFAULT_WS_URL,
        proxy: str | None = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.on_order_event = on_order_event
        self.on_account_event = on_account_event
        self.ws_url = ws_url
        self.proxy = proxy
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def _login_payload(self) -> dict:
        ts = make_timestamp()
        sig = sign_request(self.api_secret, ts, "GET", "/users/self/verify")
        return {
            "op": "login",
            "args": [
                {
                    "apiKey": self.api_key,
                    "passphrase": self.passphrase,
                    "timestamp": ts,
                    "sign": sig,
                }
            ],
        }

    def _subscribe_payload(self) -> dict:
        args: list[dict] = [{"channel": "orders", "instType": "ANY"}]
        if self.on_account_event:
            args.append({"channel": "account"})
        return {"op": "subscribe", "args": args}

    async def start(self):
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except TimeoutError:
                self._task.cancel()

    async def _run(self):
        backoff = 1
        while not self._stop.is_set():
            try:
                await self._run_once()
                backoff = 1
            except Exception as e:
                log.exception("okx_ws_private_error", error=str(e))
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _run_once(self):
        kwargs: dict = {"max_msg_size": 4 * 1024 * 1024}
        if self.proxy:
            kwargs["proxy"] = self.proxy

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(self.ws_url, **kwargs) as ws:
                await ws.send_json(self._login_payload())
                login_resp = await ws.receive(timeout=10)
                if login_resp.type != aiohttp.WSMsgType.TEXT:
                    raise RuntimeError(f"login expected TEXT, got {login_resp.type}")
                login_data = json.loads(login_resp.data)
                if login_data.get("code") != "0":
                    raise RuntimeError(f"login failed: {login_data}")

                log.info("okx_ws_private_login_ok")
                await ws.send_json(self._subscribe_payload())

                async for msg in ws:
                    if self._stop.is_set():
                        break
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue
                    await self._dispatch(data)

    async def _dispatch(self, data: dict):
        if "event" in data:
            log.debug("ws_event", data=data)
            return

        arg = data.get("arg", {})
        channel = arg.get("channel")

        if channel == "orders":
            for item in data.get("data", []):
                fill_event = FillEvent(
                    inst_id=item.get("instId", ""),
                    ord_id=item.get("ordId", ""),
                    cl_ord_id=item.get("clOrdId", ""),
                    fill_id=item.get("fillId", ""),
                    side=item.get("side", ""),
                    fill_px=float(item.get("fillPx", 0) or 0),
                    fill_sz=float(item.get("fillSz", 0) or 0),
                    fill_time_ms=int(item.get("fillTime", 0) or 0),
                    fee=float(item.get("fee", 0) or 0),
                    fee_ccy=item.get("feeCcy", ""),
                    state=item.get("state", ""),
                    raw=item,
                )
                await self.on_order_event(fill_event)
        elif channel == "account" and self.on_account_event:
            for item in data.get("data", []):
                await self.on_account_event(item)
