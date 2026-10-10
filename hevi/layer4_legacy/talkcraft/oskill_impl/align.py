"""Word/character-level voice sync on CPU (port of talkcraft timestamps_cpu.py).

The script is the ground truth: ASR only supplies *times*.  Each script
character is matched to an ASR character with ``difflib``; matched characters
take the ASR time, unmatched ones are interpolated between their neighbours.
``match_ratio`` is recorded per sentence so a gate can reject bad alignment
instead of trusting it.

oskill layer: pure functions only; the model call lives in omodul_impl/_whisper.py.
"""

from __future__ import annotations

import difflib
from collections.abc import Sequence

from hevi.layer4_legacy.talkcraft.oprim_impl.sync import AlignedChar, SentenceTiming, norm_chars

try:  # Simplified-Chinese folding; whisper sometimes emits traditional forms.
    from zhconv import convert as _zh_convert  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional
    _zh_convert = None


def _to_simplified(text: str) -> str:
    return _zh_convert(text, "zh-cn") if _zh_convert else text


def chars_from_words(*, words: Sequence[tuple[str, float, float]]) -> list[AlignedChar]:
    """Split ASR words into characters, spreading each word's span evenly."""
    out: list[AlignedChar] = []
    for word, start, end in words:
        chars = norm_chars(_to_simplified(word))
        if not chars:
            continue
        span = max(0.0, end - start) / len(chars)
        for i, ch in enumerate(chars):
            out.append(AlignedChar(ch, start + i * span, start + (i + 1) * span))
    return out


def align_script(
    *,
    script: str,
    asr_chars: Sequence[AlignedChar],
    start_s: float,
    end_s: float,
) -> tuple[list[AlignedChar], float]:
    """Map every script character to a time.  Returns (chars, match_ratio).

    ``asr_chars`` times are relative to the sentence audio; output times are
    absolute (offset by ``start_s``) and clamped to [start_s, end_s].
    """
    target = norm_chars(script)
    if not target:
        return [], 0.0
    dur = max(1e-3, end_s - start_s)
    asr = "".join(c.char for c in asr_chars)
    times: list[tuple[float, float] | None] = [None] * len(target)
    matched = 0
    if asr:
        sm = difflib.SequenceMatcher(None, target, asr, autojunk=False)
        for block in sm.get_matching_blocks():
            for k in range(block.size):
                a = asr_chars[block.b + k]
                times[block.a + k] = (a.start_s, a.end_s)
                matched += 1
    # interpolate gaps between anchors (sentence edges are anchors 0 / dur)
    i = 0
    n = len(target)
    while i < n:
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < n and times[j] is None:
            j += 1
        left = times[i - 1][1] if i > 0 and times[i - 1] else 0.0
        right = times[j][0] if j < n and times[j] else dur
        step = max(0.0, right - left) / (j - i)
        for k in range(i, j):
            times[k] = (left + (k - i) * step, left + (k - i + 1) * step)
        i = j
    out = []
    for ch, t in zip(target, times, strict=True):
        assert t is not None
        s = min(max(start_s, start_s + t[0]), end_s)
        e = min(max(s, start_s + t[1]), end_s)
        out.append(AlignedChar(ch, round(s, 3), round(e, 3)))
    return out, matched / n
