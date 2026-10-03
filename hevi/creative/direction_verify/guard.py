"""相似度护栏(默认关闭)+ Q4 人工 attestation 记录。

护栏:成片与 benchmark 参考的感知相似不得过近。默认 off;开启后超阈值 → FAIL。
方法:非周期内容的感知哈希(aHash 64bit)+ 音频指纹粗判;高数值≠真实相似
(R-P10-03 同源教训),故阈值保守且结果只作 may 级信号。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np
from PIL import Image
from PIL.Image import Resampling

from hevi.creative.direction_verify.errors import VerifyError

DEFAULT_THRESHOLD = 0.90  # hamming 距离 <= 10% 视为过近(越低越严)


def guard_enabled() -> bool:
    return os.getenv("P10_SIMILARITY_GUARD", "").strip().lower() in {"1", "true", "yes", "on"}


def perceptual_hash(path: str) -> int:
    """aHash:8x8 灰度均值哈希。内容非周期时才有意义(见 R-P10-03)。"""
    img = Image.open(path).convert("L").resize((8, 8), Resampling.BILINEAR)
    pixels = np.asarray(img, dtype=float)
    return int((pixels > pixels.mean()).flatten().dot(1 << np.arange(64)))


def hamming_similarity(a: int, b: int) -> float:
    return 1.0 - bin(a ^ b).count("1") / 64.0


@dataclass(frozen=True)
class SimilarityVerdict:
    enabled: bool
    similarity: float = 0.0
    threshold: float = DEFAULT_THRESHOLD
    result: str = "NOT_EVALUABLE"

    def validate(self) -> None:
        if self.result not in ("PASS", "FAIL", "NOT_EVALUABLE"):
            raise VerifyError("bad similarity result", code="SIM_BAD_RESULT")


def check_similarity(candidate_path: str, reference_paths: list[str],
                     *, threshold: float = DEFAULT_THRESHOLD,
                     enabled: bool | None = None) -> SimilarityVerdict:
    on = guard_enabled() if enabled is None else enabled
    if not on or not reference_paths:
        return SimilarityVerdict(enabled=False, threshold=threshold)
    candidate = perceptual_hash(candidate_path)
    best = max(hamming_similarity(candidate, perceptual_hash(ref)) for ref in reference_paths)
    verdict = SimilarityVerdict(True, best, threshold, "FAIL" if best >= threshold else "PASS")
    verdict.validate()
    return verdict


# ── Q4:人工 attestation 记录 ──


@dataclass(frozen=True)
class Attestation:
    check_id: str
    actor: str
    verdict: str  # PASS | FAIL
    note: str = ""
    artifact_hash: str = ""
    at: str = ""
    second_actor: str = ""  # Q4 双人复核:非空即双人


@dataclass
class AttestationLog:
    records: list[Attestation] = field(default_factory=list)

    def attest(self, record: Attestation) -> Attestation:
        if record.verdict not in ("PASS", "FAIL"):
            raise VerifyError("attestation verdict must be PASS|FAIL", code="ATTEST_BAD_VERDICT")
        if not record.actor or not record.artifact_hash:
            raise VerifyError("attestation requires actor + artifact_hash",
                              code="ATTEST_INCOMPLETE")
        self.records.append(record)
        return record

    def status(self, check_id: str, *, require_second: bool = False) -> str:
        hits = [r for r in self.records if r.check_id == check_id]
        if not hits:
            return "INCONCLUSIVE"
        latest = hits[-1]
        if require_second and not latest.second_actor:
            return "INCONCLUSIVE"
        return latest.verdict