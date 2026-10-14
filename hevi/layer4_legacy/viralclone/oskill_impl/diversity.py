"""Perceptual hash and text diversity gate algorithms (oskill layer)."""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.viralclone.oprim_impl.specs import DiversityRecord


def compute_frame_phash(image_path: str | Path) -> str:
    """Compute 64-bit perceptual hash (pHash) of a frame."""
    try:
        import imagehash
        from PIL import Image

        img = Image.open(image_path)
        return str(imagehash.phash(img))
    except Exception:
        # Fallback using DCT with PIL/numpy
        import numpy as np
        from PIL import Image

        img = Image.open(image_path).convert("L").resize((32, 32), Image.Resampling.BILINEAR)
        arr = np.asarray(img, dtype=np.float32)
        med = float(np.median(arr))
        bits = (arr > med).flatten()[:64]
        return hex(int("".join("1" if b else "0" for b in bits), 2))[2:].zfill(16)


def compute_phash_hamming_distance(hash1_hex: str, hash2_hex: str) -> int:
    """Compute Hamming distance between two hex hashes."""
    try:
        val1 = int(hash1_hex, 16)
        val2 = int(hash2_hex, 16)
        xor = val1 ^ val2
        return bin(xor).count("1")
    except Exception:
        return 64


def compute_text_similarity(text1: str, text2: str) -> float:
    """Compute normalized sequence similarity ratio between two texts [0.0, 1.0]."""
    t1 = "".join(text1.split())
    t2 = "".join(text2.split())
    if not t1 and not t2:
        return 1.0
    if not t1 or not t2:
        return 0.0
    matcher = difflib.SequenceMatcher(None, t1, t2)
    return round(float(matcher.ratio()), 4)


def evaluate_variant_pair_diversity(
    id1: str,
    id2: str,
    text1: str,
    text2: str,
    frame_hashes1: list[str],
    frame_hashes2: list[str],
    *,
    min_phash_distance: int = 6,
    max_text_similarity: float = 0.88,
) -> DiversityRecord:
    """Evaluate pairwise diversity between two variants using pHash and script similarity."""
    t_sim = compute_text_similarity(text1, text2)

    # Compare corresponding sample frames or minimum distance
    distances: list[int] = []
    pairs = zip(frame_hashes1, frame_hashes2, strict=False)
    for h1, h2 in pairs:
        distances.append(compute_phash_hamming_distance(h1, h2))

    min_dist = min(distances) if distances else 64
    avg_dist = sum(distances) / len(distances) if distances else 64.0
    phash_sim = round(1.0 - (avg_dist / 64.0), 4)

    # Gate: BOTH the visual distance and the script similarity must clear their
    # thresholds. A zero/too-small pHash distance fails on its own, regardless of
    # how different the text is (identical shots are not a new variant).
    passed = True
    reasons: list[str] = []
    if min_dist < min_phash_distance:
        passed = False
        reasons.append(f"phash_dist={min_dist} (<{min_phash_distance})")
    if t_sim > max_text_similarity:
        passed = False
        reasons.append(f"text_sim={t_sim} (>{max_text_similarity})")
    reason = "PASS" if passed else "DIVERSITY_REJECTED: " + " and ".join(reasons)

    return DiversityRecord(
        pair=[id1, id2],
        phash_distance=int(min_dist),
        phash_similarity=phash_sim,
        text_similarity=t_sim,
        passed=passed,
        reason=reason,
    )


def compute_variant_diversity_matrix(
    variants: list[dict[str, Any]],
    *,
    min_phash_distance: int = 6,
    max_text_similarity: float = 0.88,
) -> tuple[list[DiversityRecord], bool]:
    """Compute all pairwise diversity records; return (records, all_passed)."""
    records: list[DiversityRecord] = []
    all_passed = True

    for i in range(len(variants)):
        for j in range(i + 1, len(variants)):
            v1 = variants[i]
            v2 = variants[j]
            rec = evaluate_variant_pair_diversity(
                v1["variant_id"],
                v2["variant_id"],
                v1.get("script_text", ""),
                v2.get("script_text", ""),
                v1.get("frame_hashes", []),
                v2.get("frame_hashes", []),
                min_phash_distance=min_phash_distance,
                max_text_similarity=max_text_similarity,
            )
            records.append(rec)
            if not rec.passed:
                all_passed = False

    return records, all_passed
