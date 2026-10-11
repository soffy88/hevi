from __future__ import annotations

import logging
from typing import Any

try:
    from hevi.providers.llm_pick import resolve_text_llm
except ImportError:
    resolve_text_llm = None


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
    
    # Try LLM first if registered
    if resolve_text_llm is not None:
        try:
            llm = resolve_text_llm()
            if llm is not None:
                prompt = (
                    f"Select exactly {count} contiguous or highly cohesive sentence indices from the following transcript "
                    f"for a quote card. Return only space-separated integer indices (0-indexed):\n"
                    + "\n".join(f"{i}: {s.get('text', '')}" for i, s in enumerate(segments))
                )
                resp = llm.generate(prompt)
                nums = []
                for word in str(resp).replace(",", " ").split():
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
