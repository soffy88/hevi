"""Provider selection for ai_drama.

Order: explicit ``AI_DRAMA_PROVIDER`` -> RunningHub -> MiniMax official ->
Offline.  A paid provider is selected only when its key and required workflow
config are present; otherwise selection silently (and visibly, in the report)
falls back to Offline.  No paid call is ever made without a key.
"""

from __future__ import annotations

import os
from typing import Any

from .base import VideoProvider, VideoRequest, VideoResult
from .kaggle_gpu import KaggleGPUProvider
from .minimax import MiniMaxH3APIProvider
from .offline import OfflineProvider
from .runninghub import RunningHubH3Provider


class WanProvider:
    """Reserved slot for Wan 3.x / first-last-frame capability.

    No key or endpoint is documented in this repository yet, so this provider
    is always unavailable; it exists so the abstraction has a named place for
    Wan without pretending it works.
    """

    name = "wan"

    def available(self) -> tuple[bool, str]:
        if not os.environ.get("WAN_API_KEY"):
            return False, "WAN_API_KEY 未设置；Wan 仅预留接口"
        return False, "Wan 接口骨架未接（无已核实的文档/端点）"

    def render(self, req: VideoRequest) -> VideoResult:
        raise RuntimeError("Wan provider 未接线")


def all_providers(ledger: Any = None) -> dict[str, Any]:
    return {
        "runninghub_h3": RunningHubH3Provider(ledger=ledger),
        "minimax_h3_api": MiniMaxH3APIProvider(ledger=ledger),
        "offline": OfflineProvider(),
        "kaggle_gpu": KaggleGPUProvider(),
        "wan": WanProvider(),
    }


def select_provider(ledger: Any = None, *, prefer: str | None = None) -> tuple[VideoProvider, dict[str, Any]]:
    providers = all_providers(ledger)
    status = {name: {"available": p.available()[0], "reason": p.available()[1]} for name, p in providers.items()}
    order = [prefer] if prefer else []
    order += [os.environ.get("AI_DRAMA_PROVIDER", ""), "runninghub_h3", "minimax_h3_api", "offline"]
    for name in order:
        if not name:
            continue
        provider = providers.get(name)
        if provider is not None and provider.available()[0]:
            return provider, status
    return providers["offline"], status
