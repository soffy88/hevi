"""Cover direction through the existing HEVI visual asset boundary."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

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
        output_path: str | Path | None = None,
    ) -> CoverGeneration:
        payload, media_type = provider(brief)
        if not payload:
            raise ValueError("COVER_EMPTY_PROVIDER_RESULT")
        digest = hashlib.sha256(payload).hexdigest()
        provenance = [ProvenanceRef(ref_id=str(brief.object_id), ref_type="COVER_BRIEF")]
        if output_path is not None:
            destination = Path(output_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
            provenance.append(
                ProvenanceRef(
                    ref_id=str(destination), ref_type="COVER_ARTIFACT", sha256=digest
                )
            )
        artifact = CreativeArtifact(
            project_id=brief.project_id,
            artifact_type="COVER",
            uri=f"memory://cover/{digest}",
            media_type=media_type,
            sha256=digest,
            source_ids=(brief.object_id,),
            provenance=tuple(provenance),
            quality_gate_status="PASS",
        )
        return CoverGeneration(brief, artifact)


__all__ = ["CoverGeneration", "CoverModule"]
