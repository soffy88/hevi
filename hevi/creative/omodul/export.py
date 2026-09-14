"""Creative export formats and manifest chaining."""

from __future__ import annotations

import hashlib
import json
import zipfile
from io import BytesIO
from typing import Literal
from uuid import UUID

from hevi.obase.creative import CreativeArtifact, ExportArtifact, ProvenanceRef


class ExportModule:
    def export_text(
        self,
        *,
        project_id: UUID,
        source: CreativeArtifact,
        title: str,
        chapters: tuple[str, ...],
        fmt: str,
    ) -> ExportArtifact:
        if not chapters:
            raise ValueError("EXPORT_EMPTY")
        if source.quality_gate_status != "PASS":
            raise ValueError("EXPORT_SOURCE_QUALITY_GATE_REQUIRED")
        if fmt not in {"txt", "markdown", "epub"}:
            raise ValueError(f"unsupported export format: {fmt}")
        body = "\n\n".join(chapters)
        if fmt == "txt":
            payload = body.encode("utf-8")
            export_format: Literal["TXT", "MARKDOWN", "EPUB", "PDF", "JSON", "PLAYABLE"] = "TXT"
            media_type = "text/plain"
        elif fmt == "markdown":
            payload = (f"# {title}\n\n{body}\n").encode()
            export_format = "MARKDOWN"
            media_type = "text/markdown"
        else:
            payload = self._epub(title, chapters)
            export_format = "EPUB"
            media_type = "application/epub+zip"
        digest = hashlib.sha256(payload).hexdigest()
        return ExportArtifact(
            project_id=project_id,
            artifact_type="CREATIVE_EXPORT",
            uri=f"memory://export/{digest}",
            media_type=media_type,
            sha256=digest,
            source_ids=(source.object_id,),
            export_format=export_format,
            provenance=(
                ProvenanceRef(
                    ref_id=str(source.object_id), ref_type="SOURCE_ARTIFACT", sha256=source.sha256
                ),
            ),
            quality_gate_status="PASS",
        )

    @staticmethod
    def export_json(value: object) -> bytes:
        return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
            "utf-8"
        )

    @staticmethod
    def _epub(title: str, chapters: tuple[str, ...]) -> bytes:
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            html = "".join(
                f"<h2>{title} {index}</h2><p>{chapter}</p>"
                for index, chapter in enumerate(chapters, start=1)
            )
            archive.writestr("OEBPS/content.xhtml", f"<html><body>{html}</body></html>")
        return buffer.getvalue()


__all__ = ["ExportModule"]
