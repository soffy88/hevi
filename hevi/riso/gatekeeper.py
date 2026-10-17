"""Content guardrails (不编内容规则) implemented as strict code gates.

Rules:
1. Only delete, never rewrite: Screen text MUST be a subsequence of the source sentence.
2. Exact numbers: No rounding, no inferring new conclusions (e.g. "40分钟变2分钟" -> NO "20倍").
3. Leave unsaid things blank: Unnamed categories must remain blank/numbered placeholders.
4. Slot capacity: Delete characters when too long, never shrink font below threshold.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from hevi.riso.constants import SLOT_CONSTRAINTS

# Punctuation to ignore during subsequence matching
_PUNCT_REGEX = re.compile(
    r"[\s\.,;:!\?'\"`~@#\$%\^&\*\(\)\-_=\+\[\]\{\}\|\\/<>\u3000-\u303F\uFF00-\uFFEF]"
)

# Regex to extract numbers, units, and multipliers
_NUM_EXTRACT_REGEX = re.compile(
    r"(\d+(?:\.\d+)?(?:%|倍|万|亿|千|元|年|月|日|分|秒|点)?|[一二三四五六七八九十百千万亿]+(?:倍|%|年|月)?)"
)


def normalize_for_subsequence(text: str) -> str:
    """Normalize text by lowercasing, removing punctuation and whitespace."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    cleaned = _PUNCT_REGEX.sub("", normalized)
    return cleaned.lower()


def is_subsequence(sub: str, full: str) -> bool:
    """Check whether sub is a strict character subsequence of full."""
    norm_sub = normalize_for_subsequence(sub)
    norm_full = normalize_for_subsequence(full)

    if not norm_sub:
        return True
    if not norm_full:
        return False

    sub_idx = 0
    sub_len = len(norm_sub)

    for ch in norm_full:
        if ch == norm_sub[sub_idx]:
            sub_idx += 1
            if sub_idx == sub_len:
                return True
    return False


def extract_numbers_and_metrics(text: str) -> list[str]:
    """Extract numeric figures, multipliers, and percentages from text."""
    matches = _NUM_EXTRACT_REGEX.findall(text)
    return [m.strip() for m in matches if m.strip()]


def check_numbers_preserved(screen_text: str, source_text: str) -> tuple[bool, str]:
    """Verify all numbers, ratios, or multipliers on screen originate from source text.

    Rejects calculated conclusions (e.g., '40分钟变2分钟' -> screen text '20倍').
    """
    screen_nums = extract_numbers_and_metrics(screen_text)
    source_nums = extract_numbers_and_metrics(source_text)

    # Check for direct presence of each numeric expression
    for s_num in screen_nums:
        # Digits only check
        digit_only = re.sub(r"\D", "", s_num)
        if digit_only:
            # Check if this exact digit sequence appears in source
            if digit_only not in re.sub(r"\D", " ", source_text).split() and digit_only not in source_text:
                return (
                    False,
                    f"Number '{s_num}' on screen does not appear in source text: '{source_text}'",
                )
        # Check multiplier / conclusion words (e.g., '20倍', '50%')
        if ("倍" in s_num or "%" in s_num) and s_num not in source_text:
            return (
                False,
                f"Calculated metric/ratio '{s_num}' not present in source sentence: '{source_text}'",
            )

    return (True, "")


def check_unsaid_blanks(items: list[str], source_text: str) -> tuple[bool, str]:
    """Check that unnamed elements are left blank rather than hallucinated."""
    for i, it in enumerate(items):
        it_clean = it.strip()
        # Placeholders like "01", "步骤1", "待替换", or empty are allowed
        if not it_clean or re.match(r"^(\d+|步骤\d+|待替换|类别\d+|[\-_]+)$", it_clean):
            continue
        # If item has actual text content, it must be a subsequence of source
        if not is_subsequence(it_clean, source_text):
            return (
                False,
                f"Item [{i}] '{it_clean}' is hallucinated content not in source sentence: '{source_text}'",
            )
    return (True, "")


def check_slot_limits(
    slot: str,
    text: str,
    font_size_px: int | None = None,
) -> tuple[bool, str]:
    """Check character count limit and font size floor for a given slot."""
    constraints = SLOT_CONSTRAINTS.get(slot)
    if not constraints:
        return (True, "")

    max_chars = constraints["max_chars"]
    min_font_px = constraints["min_font_px"]

    if len(text.strip()) > max_chars:
        return (
            False,
            f"Slot '{slot}' text length {len(text.strip())} exceeds maximum {max_chars} chars ('{text}')",
        )

    if font_size_px is not None and font_size_px < min_font_px:
        return (
            False,
            f"Slot '{slot}' font size {font_size_px}px below minimum required {min_font_px}px",
        )

    return (True, "")


def truncate_to_subsequence(text: str, max_chars: int) -> str:
    """Trim text to max_chars while ensuring result remains a valid subsequence."""
    trimmed = text.strip()
    if len(trimmed) <= max_chars:
        return trimmed
    return trimmed[:max_chars]


@dataclass
class GatekeeperResult:
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def raise_if_failed(self) -> None:
        if not self.passed:
            raise ValueError(f"Gatekeeper validation failed: {'; '.join(self.errors)}")


def validate_screen_content(
    template: str,
    data: dict[str, Any],
    source_sentence: str,
) -> GatekeeperResult:
    """Run all content gatekeeper checks on template data against the source sentence."""
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Collect all screen text fields
    text_slots: list[tuple[str, str, int | None]] = []
    items_list: list[str] = []

    for k, v in data.items():
        if isinstance(v, str):
            text_slots.append((k, v, None))
        elif isinstance(v, list) and all(isinstance(x, str) for x in v):
            items_list.extend(v)
            for idx, item_str in enumerate(v):
                text_slots.append((f"{k}_{idx}", item_str, None))
        elif isinstance(v, dict):
            for sub_k, sub_v in v.items():
                if isinstance(sub_v, str):
                    text_slots.append((f"{k}.{sub_k}", sub_v, None))

    # 2. Subsequence checks for every text slot
    for slot_name, text_val, font_size in text_slots:
        val_clean = text_val.strip()
        if not val_clean:
            continue
        # Skip technical placeholders like "待替换" in shot template
        if template == "shot" and "待替换" in val_clean:
            continue
        # Pure numeric labels or indices (e.g., '01', 'STEP 1') can be structural
        if re.match(r"^(0\d|\d+|STEP\s*\d+|第[一二三四五六七八九十\d]+步?)$", val_clean, re.IGNORECASE):
            continue

        if not is_subsequence(val_clean, source_sentence):
            errors.append(
                f"Subsequence violation in slot '{slot_name}': '{val_clean}' is not a subsequence of '{source_sentence}'"
            )

        # Number check
        ok_num, num_err = check_numbers_preserved(val_clean, source_sentence)
        if not ok_num:
            errors.append(num_err)

        # Slot limit check
        base_slot = slot_name.split(".")[0].split("_")[0]
        ok_slot, slot_err = check_slot_limits(base_slot, val_clean, font_size)
        if not ok_slot:
            errors.append(slot_err)

    # 3. Unsaid blanks check
    if items_list:
        ok_blank, blank_err = check_unsaid_blanks(items_list, source_sentence)
        if not ok_blank:
            errors.append(blank_err)

    return GatekeeperResult(passed=(len(errors) == 0), errors=errors, warnings=warnings)
