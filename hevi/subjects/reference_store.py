from __future__ import annotations

from pathlib import Path


class ReferenceStore:
    """Abstracts reference-image path management (local or minio-backed).

    In production, base_dir points at a mounted volume or minio prefix.
    In tests, pass a tmp_path fixture value.
    """

    def __init__(self, base_dir: str | Path = "data/reference_images") -> None:
        self._base_dir = Path(base_dir)

    def path_for(self, subject_id: str, filename: str) -> str:
        return str(self._base_dir / subject_id / filename)

    def validate_refs(self, refs: list[str]) -> list[str]:
        """Return refs with empty/whitespace-only entries stripped."""
        return [r for r in refs if r.strip()]

    def subject_dir(self, subject_id: str) -> Path:
        return self._base_dir / subject_id
