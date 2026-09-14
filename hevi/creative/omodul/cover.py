"""Cover direction through the existing HEVI visual asset boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from hevi.obase.creative import CoverBrief, CreativeArtifact, ProvenanceRef


@dataclass(frozen=True)
class CoverGeneration:
    brief: CoverBrief
    artifact: CreativeArtifact


class CoverModule:
    def create(
        self,
        *,
        brief: CoverBrief,
        provider: Callable[[CoverBrief], tuple[bytes, str]],
    ) -> CoverGeneration:
        payload, media_type = provider(brief)
        if not payload:
            raise ValueError("COVER_EMPTY_PROVIDER_RESULT")
        import hashlib

        digest = hashlib.sha256(payload).hexdigest()
        artifact = CreativeArtifact(
            project_id=brief.project_id,
            artifact_type="COVER",
            uri=f"memory://cover/{digest}",
            media_type=media_type,
            sha256=digest,
            source_ids=(brief.object_id,),
            provenance=(ProvenanceRef(ref_id=str(brief.object_id), ref_type="COVER_BRIEF"),),
            quality_gate_status="PASS",
        )
        return CoverGeneration(brief, artifact)


__all__ = ["CoverGeneration", "CoverModule"]
