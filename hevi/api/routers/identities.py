"""D3-A/D: persistent identity product surface (HEVI API).

Canonical adoption of the D2 persistent-identity authority:

- ``POST /identities`` — create a persistent identity (PROJECT reuse must be
  explicit; one-off characters stay project-local Subjects, never forced here).
- ``GET /identities`` — list MY identities (same-owner only).
- ``GET /identities/{id}`` — inspect (appearances, voice, versions, bindings).
- ``POST /identities/{id}/appearances`` / ``/voice`` — global updates that
  bump the identity version; pinned project bindings are never touched.
- ``POST /projects/{project_id}/bindings`` — bind/reuse (idempotent per
  project+identity), ``GET`` list, ``POST /bindings/{id}/upgrade`` explicit.
- ``POST/DELETE /subjects/{subject_id}/link`` — link a project-local Subject
  to a persistent identity (same owner both sides).

Tenant isolation is enforced twice: the store filters by owner AND the
registry refuses cross-owner access. Cross-owner/anonymous → 404/401.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from hevi.api.routers.subjects import get_subject_service
from hevi.auth.dependencies import get_current_user
from hevi.creative.layer4.character_authority import AppearanceKind, VoiceBinding, VoiceIdentity
from hevi.creative.layer4.identity_store import IdentityStore, load_owner_registry
from hevi.creative.layer4.persistent_identity import (
    IdentityError,
    IdentityKind,
    PersistentIdentityRegistry,
)
from hevi.subjects.subject_service import SubjectService

router = APIRouter(prefix="/identities", tags=["identities"])


def _owner(user: dict[str, Any]) -> str:
    return str(user["id"])


def _store() -> IdentityStore:
    return IdentityStore()


def _load_registry(store: IdentityStore, owner_id: str) -> PersistentIdentityRegistry:
    return load_owner_registry(store, owner_id)


def _not_found(exc: IdentityError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


class IdentityCreateRequest(BaseModel):
    canonical_name: str
    kind: str = "character"
    voice_id: str = "unassigned"
    voice_binding: str = "prompt"
    voice_description: str = ""
    reference_audio_ref: str | None = None
    aliases: list[str] = []
    canon_constraints: list[str] = []
    default_references: list[str] = []


class AppearanceAddRequest(BaseModel):
    appearance_id: str
    kind: str = "outfit"
    reference_asset_ids: list[str] = []
    voice_override_id: str | None = None


class VoiceAssignRequest(BaseModel):
    voice_id: str
    binding: str = "prompt"
    description: str = ""
    reference_audio_ref: str | None = None


class BindingCreateRequest(BaseModel):
    identity_id: str
    overrides: dict[str, Any] = {}


class SubjectLinkRequest(BaseModel):
    identity_id: str


def _serialize_identity(
    registry: PersistentIdentityRegistry, identity_id: str, *, owner_id: str
) -> dict[str, Any]:
    for identity in registry.identities:
        if identity.identity_id == identity_id:
            dump = identity.model_dump(mode="json")
            dump["bindings"] = [
                binding.model_dump(mode="json")
                for binding in registry.bindings_for_identity(identity_id, owner_id=owner_id)
            ]
            return dump
    raise IdentityError(f"IDENTITY_UNKNOWN:{identity_id}")


@router.post("", status_code=201)
@router.post("/", status_code=201, include_in_schema=False)
async def create_identity(
    body: IdentityCreateRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    owner_id = _owner(user)
    store = _store()
    registry = _load_registry(store, owner_id)
    try:
        kind = IdentityKind(str(body.kind or "character").strip().lower())
    except ValueError:
        raise HTTPException(status_code=422, detail=f"unknown identity kind: {body.kind}") from None
    binding = (
        VoiceBinding.REFERENCE_AUDIO
        if str(body.voice_binding).strip().lower() in {"reference_audio", "reference", "audio"}
        else VoiceBinding.PROMPT_DESCRIPTION
    )
    try:
        voice = VoiceIdentity(
            voice_id=body.voice_id or "unassigned",
            binding=binding,
            description=body.voice_description,
            reference_audio_ref=body.reference_audio_ref,
        )
        identity = registry.create_identity(
            owner_id=owner_id,
            canonical_name=body.canonical_name,
            voice=voice,
            kind=kind,
            aliases=tuple(body.aliases),
            default_references=tuple(body.default_references),
            canon_constraints=tuple(body.canon_constraints),
        )
    except IdentityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store.save_identity(owner_id, identity.model_dump(mode="json"))
    return _serialize_identity(registry, identity.identity_id, owner_id=owner_id)


@router.get("")
async def list_identities(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> list[dict[str, Any]]:
    owner_id = _owner(user)
    store = _store()
    registry = _load_registry(store, owner_id)
    return [
        {
            "identity_id": identity.identity_id,
            "canonical_name": identity.canonical_name,
            "kind": identity.kind.value,
            "identity_version": identity.identity_version,
            "appearance_count": len(identity.appearance_library),
            "voice_id": identity.voice.voice_id,
            "binding_count": len(
                registry.bindings_for_identity(identity.identity_id, owner_id=owner_id)
            ),
            "linked_subjects": store.linked_subjects(owner_id, identity.identity_id),
        }
        for identity in registry.identities
    ]


@router.get("/{identity_id}")
async def inspect_identity(
    identity_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    owner_id = _owner(user)
    registry = _load_registry(_store(), owner_id)
    try:
        registry.get_identity(identity_id, owner_id=owner_id)
    except IdentityError as exc:
        raise _not_found(exc) from exc
    return _serialize_identity(registry, identity_id, owner_id=owner_id)


@router.post("/{identity_id}/appearances", status_code=201)
async def add_identity_appearance(
    identity_id: str,
    body: AppearanceAddRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    owner_id = _owner(user)
    store = _store()
    registry = _load_registry(store, owner_id)
    try:
        kind = AppearanceKind(str(body.kind or "outfit").strip().lower())
    except ValueError:
        raise HTTPException(
            status_code=422, detail=f"unknown appearance kind: {body.kind}"
        ) from None
    override = (
        VoiceIdentity(voice_id=body.voice_override_id) if body.voice_override_id else None
    )
    try:
        updated = registry.add_appearance(
            identity_id,
            owner_id=owner_id,
            appearance_id=body.appearance_id,
            kind=kind,
            reference_asset_ids=tuple(body.reference_asset_ids),
            voice_override=override,
        )
    except IdentityError as exc:
        if "IDENTITY_OWNER_MISMATCH" in str(exc) or "IDENTITY_UNKNOWN" in str(exc):
            raise _not_found(exc) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store.save_identity(owner_id, updated.model_dump(mode="json"))
    return _serialize_identity(registry, identity_id, owner_id=owner_id)


@router.post("/{identity_id}/voice")
async def assign_identity_voice(
    identity_id: str,
    body: VoiceAssignRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    owner_id = _owner(user)
    store = _store()
    registry = _load_registry(store, owner_id)
    binding = (
        VoiceBinding.REFERENCE_AUDIO
        if str(body.binding).strip().lower() in {"reference_audio", "reference", "audio"}
        else VoiceBinding.PROMPT_DESCRIPTION
    )
    try:
        voice = VoiceIdentity(
            voice_id=body.voice_id,
            binding=binding,
            description=body.description,
            reference_audio_ref=body.reference_audio_ref,
        )
        updated = registry.assign_voice(identity_id, voice, owner_id=owner_id)
    except IdentityError as exc:
        if "IDENTITY_OWNER_MISMATCH" in str(exc) or "IDENTITY_UNKNOWN" in str(exc):
            raise _not_found(exc) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store.save_identity(owner_id, updated.model_dump(mode="json"))
    return _serialize_identity(registry, identity_id, owner_id=owner_id)


@router.post("/projects/{project_id}/bindings", status_code=201)
async def bind_identity_to_project(
    project_id: str,
    body: BindingCreateRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Bind (or reuse: idempotent per project+identity) a persistent identity."""
    owner_id = _owner(user)
    store = _store()
    registry = _load_registry(store, owner_id)
    for existing in registry.bindings_for_project(project_id, owner_id=owner_id):
        if existing.identity_id == body.identity_id:
            return existing.model_dump(mode="json")
    try:
        binding = registry.bind(
            project_id=project_id,
            identity_id=body.identity_id,
            owner_id=owner_id,
            overrides=dict(body.overrides or {}),
        )
    except IdentityError as exc:
        if "IDENTITY_OWNER_MISMATCH" in str(exc) or "IDENTITY_UNKNOWN" in str(exc):
            raise _not_found(exc) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store.save_binding(owner_id, binding.model_dump(mode="json"))
    return binding.model_dump(mode="json")


@router.get("/projects/{project_id}/bindings")
async def list_project_bindings(
    project_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> list[dict[str, Any]]:
    owner_id = _owner(user)
    registry = _load_registry(_store(), owner_id)
    return [
        binding.model_dump(mode="json")
        for binding in registry.bindings_for_project(project_id, owner_id=owner_id)
    ]


@router.post("/bindings/{binding_id}/upgrade")
async def upgrade_binding(
    binding_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    owner_id = _owner(user)
    store = _store()
    registry = _load_registry(store, owner_id)
    try:
        upgraded = registry.upgrade_binding(binding_id, owner_id=owner_id)
    except IdentityError as exc:
        if "IDENTITY_OWNER_MISMATCH" in str(exc) or "IDENTITY_BINDING_UNKNOWN" in str(exc):
            raise _not_found(exc) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store.save_binding(owner_id, upgraded.model_dump(mode="json"))
    return upgraded.model_dump(mode="json")


@router.post("/subjects/{subject_id}/link", status_code=201)
async def link_subject_to_identity(
    subject_id: str,
    body: SubjectLinkRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[SubjectService, Depends(get_subject_service)],
) -> dict[str, Any]:
    owner_id = _owner(user)
    subject = await svc.get_subject(subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    if subject.get("user_id") and subject["user_id"] != owner_id:
        raise HTTPException(status_code=404, detail="Subject not found")
    registry = _load_registry(_store(), owner_id)
    try:
        registry.get_identity(body.identity_id, owner_id=owner_id)
    except IdentityError as exc:
        raise _not_found(exc) from exc
    _store().link_subject(owner_id, subject_id, body.identity_id)
    return {"subject_id": subject_id, "identity_id": body.identity_id, "owner_id": owner_id}


@router.delete("/subjects/{subject_id}/link")
async def unlink_subject_from_identity(
    subject_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    owner_id = _owner(user)
    removed = _store().unlink_subject(owner_id, subject_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Link not found")
    return {"subject_id": subject_id, "unlinked": True}
