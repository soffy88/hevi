"""抖音直播间弹幕输入（公开网页 websocket，只读，无需登录/API key）。

基于开源 DouyinLiveWebFetcher（MIT，/data/soffy/projects/DouyinLiveWebFetcher），
签名用内嵌 V8（mini-racer），不需要 node。只取聊天消息（WebcastChatMessage）。
断线自动重连（指数退避，最长 60 s）。
"""
from __future__ import annotations

import functools
import os
import sys
import threading
import time
from collections.abc import Callable

FETCHER_DIR = os.environ.get("HEVI_DOUYIN_FETCHER", "/data/soffy/projects/DouyinLiveWebFetcher")


def _load():
    if FETCHER_DIR not in sys.path:
        sys.path.insert(0, FETCHER_DIR)
    import liveMan  # type: ignore

    liveMan.generateSignature = functools.partial(liveMan.generateSignature, script_file=os.path.join(FETCHER_DIR, "sign.js"))
    return liveMan


def start_douyin(live_id: str, on_chat: Callable[[str, str], None], stop: threading.Event, on_status: Callable[[str], None] | None = None) -> threading.Thread:
    liveMan = _load()
    status = on_status or (lambda s: print(f"[douyin] {s}", flush=True))

    class Fetcher(liveMan.DouyinLiveWebFetcher):
        def _parseChatMsg(self, payload):
            m = liveMan.ChatMessage().parse(payload)
            on_chat(m.user.nick_name or "观众", m.content)

        def _wsOnOpen(self, ws):
            status(f"connected room {live_id}")
            super()._wsOnOpen(ws)

        def _wsOnClose(self, ws, *a):
            status("closed")

        def _wsOnError(self, ws, error):
            status(f"error {error}")

    # silence the fetcher's own console prints for everything except chat
    for name in dir(Fetcher):
        if name.startswith("_parse") and name != "_parseChatMsg":
            setattr(Fetcher, name, lambda self, payload: None)
    
    def run():
        backoff = 2
        while not stop.is_set():
            try:
                f = Fetcher(live_id)
                status(f"room_id {f.room_id}")
                f.start()  # blocks until the socket closes
                backoff = 2
            except Exception as e:  # noqa: BLE001 - keep the stream alive whatever the source does
                status(f"reconnect after {type(e).__name__}: {e}")
            time.sleep(backoff)
            backoff = min(60, backoff * 2)

    t = threading.Thread(target=run, daemon=True, name="douyin")
    t.start()
    return t
