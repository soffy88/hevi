"""弹幕输入源：stdin 逐行读取（文本弹幕）。"""

from __future__ import annotations

import sys
from collections.abc import Iterator

from hevi.live_host.schemas import TurnInput


def stdin_danmaku(prompt: str = "弹幕> ") -> Iterator[TurnInput]:
    """从 stdin 逐行读取弹幕，转为 TurnInput。Ctrl-D / 空行结束。"""
    print(prompt, end="", flush=True)
    for line in sys.stdin:
        text = line.strip()
        if not text:
            continue
        yield TurnInput(text=text, source="danmaku_stdin")
