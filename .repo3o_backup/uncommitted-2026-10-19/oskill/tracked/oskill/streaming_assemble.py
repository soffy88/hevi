"""K-20 streaming_assemble — assemble streaming deltas into a complete Message.

Composes oprim:
    - merge_streaming_parts
    - parts_to_message
    - make_reasoning_part

Sync (pure algorithm). Stateless.
"""

from __future__ import annotations

from collections import defaultdict
from typing import cast

from oprim import make_reasoning_part, merge_streaming_parts, parts_to_message
from oprim._hicode_types import Message, Part, PartDelta


def streaming_assemble(deltas: list[PartDelta]) -> Message:
    """Assemble a list of streaming PartDelta objects into a complete Message.

    Composes: merge_streaming_parts (per-index group), parts_to_message,
              make_reasoning_part (for reasoning deltas).

    Args:
        deltas: List of PartDelta objects from streaming response.

    Returns:
        Complete Message with all parts assembled.

    Raises:
        ValueError: If deltas is empty.
    """
    if not deltas:
        raise ValueError("deltas must not be empty")

    # Group deltas by part index
    groups: dict[int, list[PartDelta]] = defaultdict(list)
    for delta in deltas:
        groups[delta.index].append(delta)

    parts: list[Part] = []
    for idx in sorted(groups.keys()):
        group = groups[idx]
        if not group:
            continue

        part_type = group[0].type

        if part_type == "reasoning":
            # Special handling: concatenate reasoning text
            reasoning_text = "".join(d.text or "" for d in group)
            parts.append(make_reasoning_part(reasoning_text))
        else:
            # Use merge_streaming_parts for text and tool_call
            try:
                merged = merge_streaming_parts(group)
                parts.append(merged)
            except ValueError:
                # Skip empty/invalid groups
                pass

    return cast(Message, parts_to_message(parts, role="assistant"))
