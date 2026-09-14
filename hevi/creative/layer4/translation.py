"""Long-form translation with resumable, glossary-aware segments."""

from __future__ import annotations

import importlib
import io
import subprocess
import zipfile
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from hevi.obase.creative import (
    GlossaryEntry,
    ProvenanceRef,
    TranslationProject,
    TranslationSegment,
)

Translator = Callable[[str, str, str, tuple[GlossaryEntry, ...]], str]


class TranslationModule:
    def ingest(
        self,
        *,
        project_id: UUID,
        source_artifact_id: UUID,
        text: str,
        source_language: str,
        target_language: str,
        source_ref: ProvenanceRef | None = None,
    ) -> tuple[TranslationProject, tuple[TranslationSegment, ...]]:
        if not text.strip():
            raise ValueError("TRANSLATION_EMPTY_SOURCE")
        paragraphs = tuple(part.strip() for part in text.split("\n\n") if part.strip())
        segments = tuple(
            TranslationSegment(source_text=paragraph, ordinal=index, source_ref=source_ref)
            for index, paragraph in enumerate(paragraphs)
        )
        project = TranslationProject(
            project_id=project_id,
            source_artifact_id=source_artifact_id,
            source_language=source_language,
            target_language=target_language,
            segment_ids=tuple(segment.segment_id for segment in segments),
        )
        return project, segments

    def ingest_path(
        self,
        *,
        project_id: UUID,
        source_artifact_id: UUID,
        path: str | Path,
        source_language: str,
        target_language: str,
    ) -> tuple[TranslationProject, tuple[TranslationSegment, ...]]:
        source = Path(path)
        if not source.is_file():
            raise FileNotFoundError(source)
        text = self._read_document(source)
        return self.ingest(
            project_id=project_id,
            source_artifact_id=source_artifact_id,
            text=text,
            source_language=source_language,
            target_language=target_language,
            source_ref=ProvenanceRef(ref_id=str(source), ref_type="TRANSLATION_SOURCE"),
        )

    def translate(
        self,
        project: TranslationProject,
        segments: tuple[TranslationSegment, ...],
        *,
        translator: Translator,
    ) -> tuple[TranslationProject, tuple[TranslationSegment, ...]]:
        if {segment.segment_id for segment in segments} != set(project.segment_ids):
            raise ValueError("TRANSLATION_SEGMENT_SET_MISMATCH")
        translated = tuple(
            segment.model_copy(
                update={
                    "translated_text": translator(
                        segment.source_text,
                        project.source_language,
                        project.target_language,
                        project.glossary,
                    )
                }
            )
            for segment in sorted(segments, key=lambda item: item.ordinal)
        )
        if any(not segment.translated_text for segment in translated):
            raise ValueError("TRANSLATION_EMPTY_OUTPUT")
        return project.model_copy(update={"status": "REVIEW"}), translated

    def resume(
        self,
        project: TranslationProject,
        segments: tuple[TranslationSegment, ...],
        *,
        translator: Translator,
    ) -> tuple[TranslationProject, tuple[TranslationSegment, ...]]:
        pending = tuple(segment for segment in segments if not segment.translated_text)
        if not pending:
            return project, segments
        translated = tuple(
            segment.model_copy(
                update={
                    "translated_text": translator(
                        segment.source_text,
                        project.source_language,
                        project.target_language,
                        project.glossary,
                    )
                }
            )
            for segment in pending
        )
        by_id = {segment.segment_id: segment for segment in segments}
        by_id.update({segment.segment_id: segment for segment in translated})
        return project.model_copy(update={"status": "REVIEW"}), tuple(
            by_id[segment_id] for segment_id in project.segment_ids
        )

    def export_text(self, segments: tuple[TranslationSegment, ...], *, fmt: str) -> bytes:
        ordered = sorted(segments, key=lambda item: item.ordinal)
        if any(not segment.translated_text for segment in ordered):
            raise ValueError("TRANSLATION_INCOMPLETE")
        text = "\n\n".join(segment.translated_text or "" for segment in ordered)
        if fmt == "txt":
            return text.encode("utf-8")
        if fmt == "markdown":
            return ("# Translation\n\n" + text).encode("utf-8")
        if fmt == "epub":
            return self._epub(text)
        raise ValueError(f"unsupported translation export: {fmt}")

    @staticmethod
    def _read_document(path: Path) -> str:
        if path.suffix.lower() in {".txt", ".md", ".markdown"}:
            return path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".epub":
            with zipfile.ZipFile(path) as archive:
                html = [
                    archive.read(name).decode("utf-8", errors="replace")
                    for name in archive.namelist()
                    if name.endswith((".xhtml", ".html"))
                ]
            return "\n\n".join(html)
        if path.suffix.lower() == ".pdf":
            try:
                pdf_module = importlib.import_module("pypdf")
            except ImportError:
                completed = subprocess.run(
                    ["pdftotext", "-layout", str(path), "-"],
                    capture_output=True,
                    check=False,
                    timeout=30,
                )
                if completed.returncode != 0:
                    raise RuntimeError("PDF_READER_UNAVAILABLE") from None
                return completed.stdout.decode("utf-8", errors="replace")
            return "\n\n".join(
                page.extract_text() or "" for page in pdf_module.PdfReader(path).pages
            )
        raise ValueError(f"unsupported translation input: {path.suffix}")

    @staticmethod
    def _epub(text: str) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            archive.writestr(
                "OEBPS/content.xhtml",
                "<html><body>" + text.replace("\n\n", "</p><p>") + "</body></html>",
            )
        return buffer.getvalue()


__all__ = ["TranslationModule", "Translator"]
