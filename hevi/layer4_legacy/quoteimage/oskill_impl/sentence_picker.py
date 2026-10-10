from __future__ import annotations

import logging
from typing import Any

from oprim.llm.llm_call import llm_call

logger = logging.getLogger(__name__)

def pick_sentences_rule(segments: list[dict[str, Any]], count: int = 4) -> list[dict[str, Any]]:
    # Simple rule: filter short sentences, and pick consecutive 'count' sentences near the middle.
    valid = [s for s in segments if len(s["text"]) >= 4]
    if not valid:
        return segments[:count]
    
    mid = len(valid) // 2
    start = max(0, mid - count // 2)
    end = min(len(valid), start + count)
    return valid[start:end]

def pick_sentences(segments: list[dict[str, Any]], count: int = 4) -> list[dict[str, Any]]:
    if not segments:
        return []
    
    # Try LLM first
    prompt = f"请从以下句子中挑选出最具连续金句性质的 {count} 句话（必须连贯且字数不宜过少），输出其序号，逗号分隔，如：3,4,5,6\n"
    for i, seg in enumerate(segments):
        prompt += f"{i}: {seg['text']}\n"
    
    try:
        resp = llm_call(prompt, provider="ollama", temperature=0.1, max_tokens=50)
        # Parse the output
        nums = []
        for word in resp.text.replace(',', ' ').split():
            try:
                n = int(word)
                if 0 <= n < len(segments):
                    nums.append(n)
            except ValueError:
                pass
        
        if len(nums) == count:
            return [segments[i] for i in sorted(nums)]
    except Exception as e:
        logger.warning("LLM sentence picking failed, fallback to rule: %s", e)
    
    return pick_sentences_rule(segments, count)
