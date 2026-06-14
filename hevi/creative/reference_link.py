from __future__ import annotations

from hevi.subjects.subject_service import SubjectService


async def resolve_reference(
    subject_id: str,
    subject_service: SubjectService,
) -> str | None:
    """Resolve subject_id → reference_images[0] path string.

    Returns None if subject not found or has no reference images.
    """
    subject = await subject_service.get_subject(subject_id)
    if subject is None:
        return None
    refs: list[str] = subject.get("reference_images", [])
    return refs[0] if refs else None
