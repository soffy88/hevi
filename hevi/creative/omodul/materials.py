"""Project-scoped material library and citation references."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from hevi.creative.oprim.memory import CreativeMemoryIndex, MemoryRecord
from hevi.obase.creative import CreativeSource, Material


@dataclass(frozen=True)
class MaterialCitation:
    material_id: UUID
    source_id: UUID
    locator: str | None


class MaterialModule:
    def import_material(
        self,
        *,
        project_id: UUID,
        name: str,
        material_type: str,
        uri: str,
        license_ref: str | None = None,
        purpose: str | None = None,
    ) -> tuple[Material, CreativeSource]:
        source = CreativeSource(
            project_id=project_id,
            title=name,
            source_type="UPLOADED",
            uri=uri,
            license_ref=license_ref,
        )
        material = Material(
            project_id=project_id,
            name=name,
            material_type=material_type,  # type: ignore[arg-type]
            source_id=source.object_id,
            purpose=purpose,
        )
        return material, source

    def archive(self, material: Material) -> Material:
        return material.model_copy(update={"archive": True, "revision": material.revision + 1})

    def bind(self, material: Material, *, project_id: UUID) -> Material:
        if material.project_id != project_id:
            raise ValueError("MATERIAL_PROJECT_MISMATCH")
        return material

    def index(self, index: CreativeMemoryIndex, material: Material, text: str) -> None:
        index.add(
            MemoryRecord(
                project_id=material.project_id,
                record_id=str(material.object_id),
                kind="material",
                text=text,
                source_ref=str(material.source_id),
            )
        )

    def cite(self, material: Material, locator: str | None = None) -> MaterialCitation:
        return MaterialCitation(material.object_id, material.source_id, locator)


__all__ = ["MaterialCitation", "MaterialModule"]
