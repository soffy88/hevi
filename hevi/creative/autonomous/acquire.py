"""S2:本地素材 Acquirer —— probe → 兼容性 → 归一化 → canonical 候选/证据。

纪律:
- **探测复用** `hevi/qualification/media.py::validate_media`(canonical,path-in),
  不自己 spawn ffprobe(`tests/test_p9_1d_mutations.py:134` 明令禁止);
- **兼容性判定** 委托 `p7/constraint_check`(p7 语义,本包不重写);
- **不评分**:不打分、不排序、不挑 provider —— 那是 S3 canonical scorer 的事;
- 产出 canonical 形状:`AssetCandidate`(shot_readiness) + `AssetEvidence`(p7)。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hevi.creative.autonomous.canonical import AssetRequirement
from hevi.creative.autonomous.resolver import Acquirer
from hevi.production.p7.asset_contract import AssetStatus
from hevi.production.p7.constraint_check import CompatibilityReport, check_compatibility
from hevi.production.p7.evidence import AssetEvidence
from hevi.production.shot_readiness import AssetCandidate
from hevi.qualification.media import validate_media

MEDIA_SUFFIXES = (".mp4", ".mov", ".webm", ".mkv", ".wav", ".mp3", ".m4a",
                  ".png", ".jpg", ".jpeg", ".webp")

MEDIA_TYPE_BY_SUFFIX = {
    ".mp4": "VIDEO", ".mov": "VIDEO", ".webm": "VIDEO", ".mkv": "VIDEO",
    ".wav": "AUDIO", ".mp3": "AUDIO", ".m4a": "AUDIO",
    ".png": "IMAGE", ".jpg": "IMAGE", ".jpeg": "IMAGE", ".webp": "IMAGE",
}


@dataclass(frozen=True)
class NormalizedCandidate:
    """归一化产物:canonical 候选 + canonical 证据 + 兼容性结论。"""
    candidate: AssetCandidate
    evidence: AssetEvidence
    compatibility: CompatibilityReport

    @property
    def usable(self) -> bool:
        return self.compatibility.compatible and self.evidence.status is AssetStatus.AVAILABLE


def _observed_fields(validation: Any) -> dict[str, object]:
    """MediaValidation → probe 词汇(`OBSERVABLE_FIELDS` 的键)。"""
    observed: dict[str, object] = {
        "duration": validation.duration_s,
        "width": validation.width,
        "height": validation.height,
        "codec": validation.codec,
        "fps": validation.fps,
        "has_audio": validation.audio_stream,
    }
    if validation.width and validation.height:
        observed["resolution"] = (validation.width, validation.height)
    return observed


def normalize_local_asset(requirement: AssetRequirement, path: Path, *,
                          source: str = "local", license_name: str = "") -> NormalizedCandidate:
    """本地文件 → (AssetCandidate, AssetEvidence, CompatibilityReport)。

    fail-closed:探测不通过 → evidence 状态 REJECTED/BLOCKED,绝不产 AVAILABLE。
    `license_name` 为空时 evidence 不能标 AVAILABLE(p7 硬规则)。
    """
    validation = validate_media(path)
    observed = _observed_fields(validation)
    compatibility = check_compatibility(requirement, observed)
    asset_id = f"local:{path.name}"

    status = AssetStatus.AVAILABLE if (validation.passed and compatibility.compatible
                                       and license_name) else (
        AssetStatus.BLOCKED if validation.passed else AssetStatus.REJECTED)
    evidence = AssetEvidence(
        asset_id=asset_id, source=source, status=status, license=license_name,
        validation=f"probe_valid={validation.ffprobe_valid} errors={len(validation.errors)}",
        content_hash=validation.checksum,
    )
    candidate = AssetCandidate(
        candidate_id=asset_id, requirement_id=requirement.requirement_id,
        asset_ref=str(path),
        # confidence 保持 0 且 scored_by 空:本包不评分,由 S3 canonical scorer 生产
        verified=validation.passed and compatibility.compatible,
        reason="" if status is AssetStatus.AVAILABLE else ";".join(
            [*compatibility.blocked_keys, *compatibility.undecidable_keys,
             *validation.errors]),
    )
    return NormalizedCandidate(candidate, evidence, compatibility)


class LocalAssetAcquirer:
    """实现既有 `Acquirer` 协议:本地优先,不触付费 provider。

    `license_name` 必须由调用方给出(真实来源的授权信息);不猜、不留空默认。
    """

    def __init__(self, roots: tuple[str | Path, ...], *, license_name: str = "") -> None:
        if not license_name:
            raise ValueError("LOCAL_ACQUIRER_REQUIRES_LICENSE:license must be declared")
        self._roots = tuple(Path(r) for r in roots)
        self._license = license_name

    def available(self, requirement: AssetRequirement) -> tuple[Path, ...]:
        wanted = str(requirement.media_type.value).lower()
        suffix_wanted = {suffix for suffix, kind in MEDIA_TYPE_BY_SUFFIX.items()
                         if kind.lower() == wanted}
        found: list[Path] = []
        for root in self._roots:
            if not root.is_dir():
                continue
            found.extend(sorted(
                p for p in root.rglob("*")
                if p.is_file() and p.suffix.lower() in suffix_wanted))
        return tuple(found)

    async def acquire(self, requirement: AssetRequirement, provider_id: str,
                      context: dict[str, Any]) -> tuple[str, AssetEvidence]:
        """返回 (asset_ref, evidence)。无可兼容素材 → BLOCKED 证据 + 空 asset_ref。"""
        for path in self.available(requirement):
            normalized = normalize_local_asset(requirement, path,
                                               license_name=self._license)
            if normalized.usable:
                return str(path), normalized.evidence
        return "", AssetEvidence(asset_id=f"local-scan:{requirement.requirement_id}",
                                 source="local", status=AssetStatus.BLOCKED,
                                 license=self._license,
                                 validation="no compatible local asset found")


__all__ = [
    "MEDIA_SUFFIXES",
    "MEDIA_TYPE_BY_SUFFIX",
    "Acquirer",
    "LocalAssetAcquirer",
    "NormalizedCandidate",
    "normalize_local_asset",
]