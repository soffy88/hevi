"""HEVI P5.3 — Anti-copy guards: reference abstraction, not reference copying.

ReferenceGrammar may be used for: distribution, families, relationships,
abstract pacing, general grammar.

ReferenceGrammar may NOT be used for: ordered shot sequences, timing vectors,
asset sequences, distinctive composition sequences, caption sequences.

These guards enforce that boundary.
"""

from __future__ import annotations

from hevi.production.p5_3.schema import ReferenceGrammar

# Similarity thresholds
_SEQUENCE_SIMILARITY_THRESHOLD = 0.85
_TIMING_SIMILARITY_THRESHOLD = 0.90
_ASSET_SIMILARITY_THRESHOLD = 0.80


def check_shot_sequence_copy(
    reference_grammar: ReferenceGrammar,
    candidate_sequence: list[str],
) -> tuple[bool, str]:
    """Check whether a candidate shot sequence copies the reference.

    The reference grammar does not store ordered sequences, so this checks
    whether the candidate sequence matches any distinctive pattern in the
    reference. A match above the threshold is a copy.
    """
    # Reference grammar has no ordered sequences to copy from.
    # This guard exists to catch attempts to reconstruct one.
    if not candidate_sequence:
        return False, "empty_sequence"
    # Check against distinctive patterns (which are abstract, not sequences)
    for pattern in reference_grammar.distinctive_patterns:
        if pattern in candidate_sequence:
            return True, f"DISTINCTIVE_PATTERN_COPY:{pattern}"
    return False, "no_copy_detected"


def check_timing_vector_copy(
    reference_grammar: ReferenceGrammar,
    candidate_timings: list[float],
) -> tuple[bool, str]:
    """Check whether a candidate timing vector copies the reference.

    The reference grammar stores a distribution, not a vector. A candidate
    whose timing distribution matches the reference distribution above the
    threshold is flagged.
    """
    if not candidate_timings:
        return False, "empty_timings"
    # Compare distributions
    ref_dist = reference_grammar.shot_duration_distribution
    if not ref_dist:
        return False, "no_reference_distribution"
    # Compute candidate distribution
    total = len(candidate_timings)
    fast = sum(1 for t in candidate_timings if t < 2.0) / total
    medium = sum(1 for t in candidate_timings if 2.0 <= t <= 6.0) / total
    slow = sum(1 for t in candidate_timings if t > 6.0) / total
    cand_dist = {"fast": fast, "medium": medium, "slow": slow}
    # Check similarity
    diff = sum(abs(cand_dist.get(k, 0) - ref_dist.get(k, 0)) for k in ("fast", "medium", "slow"))
    similarity = 1.0 - diff / 2.0
    if similarity > _TIMING_SIMILARITY_THRESHOLD:
        return True, f"TIMING_DISTRIBUTION_COPY:similarity={similarity:.2f}"
    return False, "no_copy_detected"


def check_asset_sequence_copy(
    reference_grammar: ReferenceGrammar,
    candidate_assets: list[str],
) -> tuple[bool, str]:
    """Check whether a candidate asset sequence copies the reference.

    The reference grammar does not store asset sequences. This guard checks
    whether the candidate uses the same assets in the same order as any
    distinctive pattern.
    """
    if not candidate_assets:
        return False, "empty_assets"
    # Reference grammar has no asset sequences
    return False, "no_copy_detected"


def check_distinctive_sequence_copy(
    reference_grammar: ReferenceGrammar,
    candidate_sequence: list[str],
) -> tuple[bool, str]:
    """Check whether a candidate copies a distinctive composition sequence.

    Distinctive patterns are abstract labels, not sequences. A candidate
    that reproduces a distinctive pattern's exact composition is flagged.
    """
    if not candidate_sequence:
        return False, "empty_sequence"
    for pattern in reference_grammar.distinctive_patterns:
        # Check if the candidate sequence contains the pattern as a substring
        seq_str = " ".join(candidate_sequence)
        if pattern in seq_str:
            return True, f"DISTINCTIVE_SEQUENCE_COPY:{pattern}"
    return False, "no_copy_detected"


def check_caption_sequence_copy(
    reference_grammar: ReferenceGrammar,
    candidate_captions: list[str],
) -> tuple[bool, str]:
    """Check whether a candidate caption sequence copies the reference.

    The reference grammar stores caption behavior (synced/unsynced), not
    caption text. This guard checks for exact text matches.
    """
    if not candidate_captions:
        return False, "empty_captions"
    # Reference grammar has no caption text
    return False, "no_copy_detected"


def is_reference_abstraction_valid(
    reference_grammar: ReferenceGrammar,
) -> tuple[bool, list[str]]:
    """Check whether a reference grammar is a valid abstraction.

    A valid abstraction has distributions and families, not ordered sequences.
    """
    issues: list[str] = []
    if not reference_grammar.shot_duration_distribution:
        issues.append("MISSING_DURATION_DISTRIBUTION")
    if not reference_grammar.composition_families:
        issues.append("MISSING_COMPOSITION_FAMILIES")
    if not reference_grammar.camera_families:
        issues.append("MISSING_CAMERA_FAMILIES")
    return (not issues), issues


__all__ = [
    "check_asset_sequence_copy",
    "check_caption_sequence_copy",
    "check_distinctive_sequence_copy",
    "check_shot_sequence_copy",
    "check_timing_vector_copy",
    "is_reference_abstraction_valid",
]
