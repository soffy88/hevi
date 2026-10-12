"""ollama LLM 原子：主持人人设「小雅」。逐句流式输出。"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterator

import httpx

from hevi.live_host.schemas import Engine

logger = logging.getLogger(__name__)

# 微调模型偶尔吐出的特殊标记（<tool_call>/<think> 等）与夹杂的英文碎片，播报前剔除
_TAG = re.compile(r"</?\s*(tool_call|tool_response|think)\s*>|<\|[^|>]*\|>")
_LATIN = re.compile(r"(?<![A-Za-z])(?!AI(?![A-Za-z]))[A-Za-z_][A-Za-z_]*")


def clean_text(t: str) -> str:
    t = _TAG.sub("", t)
    t = _LATIN.sub("", t)
    t = re.sub(r"[\u3040-\u30ff]+", "", t)  # 偶发日文假名
    return t

SYSTEM_PROMPT = (
    "你是{persona}，一个亲切、专业、幽默的中文直播主持人（赛博小雅）。"
    "你在直播间实时回答观众提问。要求：\n"
    "1. 用自然口语回答，像真人在直播，不要书面腔。\n"
    "2. 每次回答尽量简短（不超过{max_chars}字），适合逐句播报。\n"
    "3. 可以在句子之间用换行，方便分句朗读。\n"
    "4. 遇到不懂的就说不知道，不要编造。\n"
    "5. 你是 AI 生成的主持人，自然提及即可，不必每句声明。\n"
    "6. 只用简体中文回答，不要夹英文单词，不要表情符号和括号动作。"
)


class OllamaLLM(Engine):
    """本地 ollama 聊天；支持逐句流式（按标点切分）。"""

    name = "ollama"

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "xiaoya-qwen3-4b",
        persona: str = "小雅",
        max_reply_chars: int = 120,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.persona = persona
        self.max_reply_chars = max_reply_chars

    def available(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=5)
            return r.status_code == 200
        except Exception:  # pragma: no cover - 网络/服务不可用
            return False

    def _system(self) -> str:
        return SYSTEM_PROMPT.format(persona=self.persona, max_chars=self.max_reply_chars)

    def reply(self, question: str, *, stream: bool = True) -> str:
        """返回完整回复（非流式）。"""
        chunks = list(self.stream_reply(question))
        return "".join(chunks)

    def stream_reply(self, question: str) -> Iterator[str]:
        """按句子流式产出文本片段（标点触发分句）。"""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self._system()},
                {"role": "user", "content": question},
            ],
            "stream": True,
        }
        buffer = ""
        punct = "。！？!?；;\n"
        with httpx.Client(timeout=120) as client:
            with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as resp:
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        obj = _parse(line)
                    except Exception:  # pragma: no cover
                        continue
                    if not obj:
                        continue
                    piece = obj.get("message", {}).get("content", "")
                    if not piece:
                        continue
                    buffer += piece
                    if "<" in buffer and ">" not in buffer[buffer.rfind("<"):]:
                        continue  # 可能是被切开的特殊标记，等它收齐
                    buffer = clean_text(buffer).lstrip()
                    while True:
                        idx = next((i for i, c in enumerate(buffer) if c in punct), None)
                        if idx is None:
                            break
                        sentence = buffer[: idx + 1].strip()
                        buffer = buffer[idx + 1 :]
                        if sentence:
                            yield sentence
        tail = clean_text(buffer).strip()
        if tail:
            yield tail


def _parse(line: str) -> dict | None:
    import json

    try:
        return json.loads(line)
    except json.JSONDecodeError:  # pragma: no cover
        return None
