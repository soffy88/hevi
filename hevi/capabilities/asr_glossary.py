"""Audited ASR misrecognition glossary (``audio.asr_transcribe``).

This is a SEPARATE table from ``edit.subtitle_discipline``'s caption
glossary (``apply_glossary`` there unifies proper-name spellings in
captions). The two must never be confused: this table corrects
specific ASR misrecognitions that were observed in the 2026-11-01
ASR-fix measurement run, and it applies ONLY to the observed
(transcribed) side, never to expected script lines.

Versioned: new entries need a measured misrecognition as evidence
plus a review record; whole-sentence rewrites are forbidden (the
E3 S02 ``太阳月 地影月长`` case is deliberately NOT in this table:
any fix for it would rewrite the segment from the expected text,
which is circular reasoning -- that case is fixed by changing the
model, not by glossary).

Entries are stored in traditional-to-simplified (t2s) normalised
form, i.e. the form the text has AFTER ``traditional_to_simplified``
runs. In particular entry 4 uses ``着`` (``光写着照过来``): the
OpenCC/built-in t2s step leaves ``著`` untouched, so a raw base-model
transcript reading ``光写著照过来`` does NOT hit entry 4 -- that is
the measured behaviour (E3/base glossary coverage 0.8707, entry 4
not hit). Entry 4 fires only when the transcribed form already uses
``着``. Do not "fix" this by mapping ``著`` -> ``着`` globally: that
would corrupt words such as ``著名``.
"""

from __future__ import annotations

GLOSSARY_VERSION = "asr-glossary-v1"

# Each entry: (misrecognised form, corrected form, evidence).
# Evidence cites the measurement run that observed the misrecognition.
ASR_GLOSSARY: tuple[tuple[str, str, str], ...] = (
    (
        "邓隆",
        "灯笼",
        "E2 S01, 2026-11-01 ASR-fix measurement: base model output "
        "contained 鄧隆 (t2s: 邓隆) where the script line is 灯笼该点起来了",
    ),
    (
        "木河",
        "木盒",
        "E2 S03, 2026-11-01 ASR-fix measurement: base model output "
        "contained 木河 (t2s form) where the script line is 火柴放在木盒里",
    ),
    (
        "我们来亮一亮",
        "我们来量一量",
        "E3 S04, 2026-11-01 ASR-fix measurement: small/large model output "
        "contained 我们来亮一亮 where the script line is 我们来量一量",
    ),
    (
        "光写着照过来",
        "光斜着照过来",
        "E3 S06, 2026-11-01 ASR-fix measurement: audited exact phrase; "
        "the base-model raw form uses 著 and therefore does not hit "
        "this t2s-form entry (see module docstring)",
    ),
)


def asr_glossary_entries() -> list[dict[str, str]]:
    """The glossary as auditable records (version + evidence)."""
    return [
        {
            "version": GLOSSARY_VERSION,
            "misrecognised": src,
            "corrected": dst,
            "evidence": evidence,
        }
        for src, dst, evidence in ASR_GLOSSARY
    ]


def apply_asr_glossary(text: str) -> tuple[str, list[str]]:
    """Apply the audited glossary to ``text`` (observed side only).

    Exact-substring replacement, longest source first, each hit
    recorded once per entry as ``"<src>-><dst>"``. No whole-sentence
    rewrites, no global homophone rewriting: a string only changes
    when it contains one of the four audited misrecognitions verbatim.
    Returns ``(new_text, hits)``; ``hits`` is empty when nothing matched.
    """
    out = str(text)
    hits: list[str] = []
    for src, dst, _evidence in sorted(ASR_GLOSSARY, key=lambda e: -len(e[0])):
        if src and src in out:
            out = out.replace(src, dst)
            hits.append(f"{src}->{dst}")
    return out, hits
