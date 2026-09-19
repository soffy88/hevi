"""D2-B: persistent creative identity system (HEVI Layer 4).

Upgrades the project-scoped ``CharacterAuthority`` into a persistent,
owner-scoped identity system WITHOUT breaking project ownership:

- ``GlobalCreativeIdentity`` — a persistent fictional character / virtual
  presenter / brand mascot / recurring narrator owned by exactly one
  owner (user/tenant scope). Identity carries the appearance library,
  voice identity, reference assets and canon constraints, versioned
  monotonically. "Global" never means all-users-global.
- ``ProjectCharacterBinding`` — how ONE project uses an identity: which
  identity version and which appearance versions it pinned, plus an
  allow-listed override set. Projects inherit but can never silently
  mutate the global identity.
- ``ContinuityLedger`` — structured continuity facts (character state,
  appearance, location/scene, prop, relationship, story) with source
  provenance, tracked per episode/scene/shot/revision. No unrestricted
  free-form memory: every fact has a category and a source.
- ``validate_pre_production`` — production pre-check returning
  PASS/WARN/BLOCK. BLOCK is reserved for true hard constraints
  (unknown identity, owner mismatch, canon hard-constraint breach).

Reuses ``Appearance``/``VoiceIdentity`` from ``character_authority`` —
no second character authority, no second memory authority.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from hevi.creative.layer4.character_authority import (
    Appearance,
    AppearanceKind,
    CharacterError,
    VoiceIdentity,
)


class IdentityError(CharacterError):
    """Refusal with a stable machine code (subclass: still a character error)."""


class IdentityKind(StrEnum):
    CHARACTER = "character"
    PRESENTER = "presenter"
    MASCOT = "mascot"
    NARRATOR = "narrator"


class ContinuityCategory(StrEnum):
    CHARACTER_STATE = "character_state"
    APPEARANCE = "appearance"
    LOCATION = "location"
    PROP = "prop"
    RELATIONSHIP = "relationship"
    STORY = "story"


class ContinuitySeverity(StrEnum):
    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"


#: Project bindings may only override these presentation-level fields.
#: Anything structural (appearances, voice binding, canon) must change
#: the global identity (new version) — never a silent project edit.
OVERRIDABLE_FIELDS: tuple[str, ...] = ("display_name", "voice_description")


def _require_owner(owner_id: str) -> str:
    owner = str(owner_id or "").strip()
    if not owner or owner.lower() == "anonymous":
        raise IdentityError("IDENTITY_OWNER_REQUIRED")
    return owner


class VoiceVersionRecord(BaseModel):
    """One historical voice assignment, stamped with the identity version
    that introduced it. Lets pinned historical productions resolve the
    voice that was current when they were made."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    identity_version: int = Field(ge=1)
    voice: VoiceIdentity


class GlobalCreativeIdentity(BaseModel):
    """One persistent creative identity, owned by exactly one owner."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    identity_id: str = Field(min_length=1)
    owner_id: str = Field(min_length=1)
    kind: IdentityKind = IdentityKind.CHARACTER
    canonical_name: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    appearance_library: tuple[Appearance, ...] = ()
    voice: VoiceIdentity
    reference_asset_ids: tuple[str, ...] = ()
    canon_constraints: tuple[str, ...] = ()
    identity_version: int = Field(ge=1, default=1)
    revision: str = ""
    archived: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    appearance_history: tuple[Appearance, ...] = ()
    voice_history: tuple[VoiceVersionRecord, ...] = ()

    def appearance(self, appearance_id: str) -> Appearance:
        for candidate in self.appearance_library:
            if candidate.appearance_id == appearance_id:
                return candidate
        raise IdentityError(f"IDENTITY_APPEARANCE_UNKNOWN:{appearance_id}")

    def appearance_at_version(self, appearance_id: str, version: int) -> Appearance:
        """Resolve the appearance snapshot a pinned production used."""
        try:
            current = self.appearance(appearance_id)
        except IdentityError:
            current = None
        if current is not None and current.version == version:
            return current
        for snapshot in self.appearance_history:
            if snapshot.appearance_id == appearance_id and snapshot.version == version:
                return snapshot
        raise IdentityError(f"IDENTITY_APPEARANCE_VERSION_UNKNOWN:{appearance_id}#v{version}")

    def effective_voice(self, appearance_id: str | None = None) -> VoiceIdentity:
        if appearance_id is not None:
            override = self.appearance(appearance_id).voice_override
            if override is not None:
                return override
        return self.voice

    def voice_at_version(self, identity_version: int) -> VoiceIdentity:
        """Resolve the voice current at a pinned identity version."""
        best: VoiceIdentity | None = None
        best_version = 0
        for record in self.voice_history:
            if record.identity_version <= identity_version and record.identity_version > best_version:
                best = record.voice
                best_version = record.identity_version
        if best is None:
            raise IdentityError(f"IDENTITY_VOICE_VERSION_UNKNOWN:v{identity_version}")
        return best


class ProjectCharacterBinding(BaseModel):
    """How one project uses a persistent identity (pinned, explicit)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    binding_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    identity_id: str = Field(min_length=1)
    owner_id: str = Field(min_length=1)
    pinned_identity_version: int = Field(ge=1)
    pinned_appearance_versions: dict[str, int] = Field(default_factory=dict)
    overrides: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def is_stale(self, current_identity_version: int) -> bool:
        return self.pinned_identity_version < current_identity_version


class ContinuityFactRecord(BaseModel):
    """One structured continuity fact with source provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: str = Field(min_length=1)
    identity_id: str = Field(min_length=1)
    category: ContinuityCategory
    statement: str = Field(min_length=1)
    episode: str = ""
    scene: str = ""
    shot: str = ""
    revision: str = ""
    source_artifact_id: str = ""
    provenance: str = ""
    supersedes: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ContinuityFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    severity: ContinuitySeverity
    code: str
    detail: str = ""


class ContinuityVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    verdict: ContinuitySeverity
    findings: tuple[ContinuityFinding, ...] = ()


class ContinuityLedger:
    """Append-only structured facts per identity, with provenance."""

    def __init__(self) -> None:
        self._facts: dict[str, list[ContinuityFactRecord]] = {}

    def record(self, fact: ContinuityFactRecord) -> ContinuityFactRecord:
        self._facts.setdefault(fact.identity_id, []).append(fact)
        return fact

    def facts_for_identity(self, identity_id: str) -> tuple[ContinuityFactRecord, ...]:
        return tuple(self._facts.get(identity_id, ()))

    def active_facts(self, identity_id: str) -> tuple[ContinuityFactRecord, ...]:
        """Facts not superseded by a newer fact. History is never deleted:
        superseded facts remain queryable via facts_for_identity."""
        facts = self._facts.get(identity_id, ())
        superseded = {fact.supersedes for fact in facts if fact.supersedes}
        return tuple(fact for fact in facts if fact.fact_id not in superseded)

    def facts_for_scope(
        self,
        identity_id: str,
        *,
        episode: str = "",
        scene: str = "",
        shot: str = "",
    ) -> tuple[ContinuityFactRecord, ...]:
        out: list[ContinuityFactRecord] = []
        for fact in self._facts.get(identity_id, ()):
            if episode and fact.episode != episode:
                continue
            if scene and fact.scene != scene:
                continue
            if shot and fact.shot != shot:
                continue
            out.append(fact)
        return tuple(out)

    def snapshot(self) -> dict[str, Any]:
        return {
            identity_id: [fact.model_dump(mode="json") for fact in facts]
            for identity_id, facts in self._facts.items()
        }

    def restore(self, snapshot: dict[str, Any]) -> None:
        restored: dict[str, list[ContinuityFactRecord]] = {}
        for identity_id, rows in (snapshot or {}).items():
            restored[str(identity_id)] = [
                ContinuityFactRecord.model_validate(row) for row in rows
            ]
        self._facts = restored


class PersistentIdentityRegistry:
    """Owner-scoped registry: global identities + per-project bindings.

    Private by default: every lookup is filtered by ``owner_id`` and any
    cross-owner access refuses. Same-owner cross-project reuse is
    explicit via :meth:`reuse_in_project`.
    """

    def __init__(self) -> None:
        self._identities: dict[str, GlobalCreativeIdentity] = {}
        self._bindings: dict[str, ProjectCharacterBinding] = {}
        self.ledger = ContinuityLedger()

    # -- identities ----------------------------------------------------

    def create_identity(
        self,
        *,
        owner_id: str,
        canonical_name: str,
        voice: VoiceIdentity,
        kind: IdentityKind = IdentityKind.CHARACTER,
        aliases: tuple[str, ...] = (),
        default_references: tuple[str, ...] = (),
        canon_constraints: tuple[str, ...] = (),
        identity_id: str = "",
    ) -> GlobalCreativeIdentity:
        owner = _require_owner(owner_id)
        resolved_id = identity_id.strip() or f"identity-{uuid4().hex[:12]}"
        if resolved_id in self._identities:
            raise IdentityError(f"IDENTITY_DUPLICATE_ID:{resolved_id}")
        default_appearance = Appearance(
            appearance_id="default",
            character_id=resolved_id,
            kind=AppearanceKind.DEFAULT,
            label="default",
            reference_asset_ids=default_references,
            revision=f"{resolved_id}@default#1",
        )
        identity = GlobalCreativeIdentity(
            identity_id=resolved_id,
            owner_id=owner,
            kind=kind,
            canonical_name=canonical_name.strip(),
            aliases=aliases,
            appearance_library=(default_appearance,),
            voice=voice,
            reference_asset_ids=default_references,
            canon_constraints=canon_constraints,
            identity_version=1,
            revision=f"{resolved_id}#1",
            voice_history=(VoiceVersionRecord(identity_version=1, voice=voice),),
        )
        self._identities[resolved_id] = identity
        return identity

    def get_identity(self, identity_id: str, *, owner_id: str) -> GlobalCreativeIdentity:
        owner = _require_owner(owner_id)
        try:
            identity = self._identities[identity_id]
        except KeyError:
            raise IdentityError(f"IDENTITY_UNKNOWN:{identity_id}") from None
        if identity.owner_id != owner:
            raise IdentityError("IDENTITY_OWNER_MISMATCH")
        return identity

    def add_appearance(
        self,
        identity_id: str,
        *,
        owner_id: str,
        appearance_id: str,
        kind: AppearanceKind,
        reference_asset_ids: tuple[str, ...] = (),
        voice_override: VoiceIdentity | None = None,
    ) -> GlobalCreativeIdentity:
        """Global mutation: bumps identity version; bindings stay pinned."""
        identity = self.get_identity(identity_id, owner_id=owner_id)
        if kind is AppearanceKind.DEFAULT:
            raise IdentityError("IDENTITY_APPEARANCE_DEFAULT_IMMUTABLE")
        if any(a.appearance_id == appearance_id for a in identity.appearance_library):
            raise IdentityError(f"IDENTITY_APPEARANCE_DUPLICATE:{appearance_id}")
        appearance = Appearance(
            appearance_id=appearance_id,
            character_id=identity_id,
            kind=kind,
            label=appearance_id,
            reference_asset_ids=reference_asset_ids,
            voice_override=voice_override,
            revision=f"{identity_id}@{appearance_id}#1",
        )
        updated = identity.model_copy(
            update={
                "appearance_library": (*identity.appearance_library, appearance),
                "identity_version": identity.identity_version + 1,
                "revision": f"{identity_id}#{identity.identity_version + 1}",
            }
        )
        self._identities[identity_id] = updated
        return updated

    def assign_voice(
        self, identity_id: str, voice: VoiceIdentity, *, owner_id: str
    ) -> GlobalCreativeIdentity:
        identity = self.get_identity(identity_id, owner_id=owner_id)
        new_version = identity.identity_version + 1
        updated = identity.model_copy(
            update={
                "voice": voice,
                "voice_history": (
                    *identity.voice_history,
                    VoiceVersionRecord(identity_version=new_version, voice=voice),
                ),
                "identity_version": new_version,
                "revision": f"{identity_id}#{new_version}",
            }
        )
        self._identities[identity_id] = updated
        return updated

    def rename_identity(
        self, identity_id: str, *, new_canonical_name: str, owner_id: str
    ) -> GlobalCreativeIdentity:
        """Rename the display name. The old canonical name becomes an alias,
        so historical casting (which used the old name) still resolves to the
        same canonical ID. Bumps the version; pinned bindings go stale."""
        identity = self.get_identity(identity_id, owner_id=owner_id)
        new_name = new_canonical_name.strip()
        if not new_name:
            raise IdentityError("IDENTITY_RENAME_EMPTY")
        if new_name == identity.canonical_name:
            return identity
        new_version = identity.identity_version + 1
        aliases = tuple(a for a in identity.aliases if a != new_name)
        if identity.canonical_name not in aliases:
            aliases = (identity.canonical_name, *aliases)
        updated = identity.model_copy(
            update={
                "canonical_name": new_name,
                "aliases": aliases,
                "identity_version": new_version,
                "revision": f"{identity_id}#{new_version}",
            }
        )
        self._identities[identity_id] = updated
        return updated

    def add_alias(
        self, identity_id: str, *, alias: str, owner_id: str
    ) -> GlobalCreativeIdentity:
        identity = self.get_identity(identity_id, owner_id=owner_id)
        clean = alias.strip()
        if not clean:
            raise IdentityError("IDENTITY_ALIAS_EMPTY")
        if clean == identity.canonical_name or clean in identity.aliases:
            return identity
        new_version = identity.identity_version + 1
        updated = identity.model_copy(
            update={
                "aliases": (*identity.aliases, clean),
                "identity_version": new_version,
                "revision": f"{identity_id}#{new_version}",
            }
        )
        self._identities[identity_id] = updated
        return updated

    def remove_alias(
        self, identity_id: str, *, alias: str, owner_id: str
    ) -> GlobalCreativeIdentity:
        """Only non-canonical aliases can be removed; the canonical name is
        immutable through this path (use rename, which preserves history)."""
        identity = self.get_identity(identity_id, owner_id=owner_id)
        clean = alias.strip()
        if clean == identity.canonical_name:
            raise IdentityError("IDENTITY_ALIAS_CANONICAL_IMMUTABLE")
        if clean not in identity.aliases:
            raise IdentityError(f"IDENTITY_ALIAS_UNKNOWN:{alias}")
        new_version = identity.identity_version + 1
        updated = identity.model_copy(
            update={
                "aliases": tuple(a for a in identity.aliases if a != clean),
                "identity_version": new_version,
                "revision": f"{identity_id}#{new_version}",
            }
        )
        self._identities[identity_id] = updated
        return updated

    def update_appearance_assets(
        self,
        identity_id: str,
        appearance_id: str,
        *,
        owner_id: str,
        visual_asset_ids: tuple[str, ...] | None = None,
        reference_asset_ids: tuple[str, ...] | None = None,
    ) -> GlobalCreativeIdentity:
        """Evolve one appearance vN -> vN+1. The prior snapshot is appended to
        appearance_history so pinned productions can still trace provenance.
        Bumps the identity version; existing bindings stay pinned."""
        identity = self.get_identity(identity_id, owner_id=owner_id)
        current = identity.appearance(appearance_id)
        evolved = current.model_copy(
            update={
                "visual_asset_ids": current.visual_asset_ids
                if visual_asset_ids is None
                else visual_asset_ids,
                "reference_asset_ids": current.reference_asset_ids
                if reference_asset_ids is None
                else reference_asset_ids,
                "version": current.version + 1,
                "revision": f"{identity_id}@{appearance_id}#{current.version + 1}",
            }
        )
        new_version = identity.identity_version + 1
        updated = identity.model_copy(
            update={
                "appearance_library": tuple(
                    evolved if a.appearance_id == appearance_id else a
                    for a in identity.appearance_library
                ),
                "appearance_history": (*identity.appearance_history, current),
                "identity_version": new_version,
                "revision": f"{identity_id}#{new_version}",
            }
        )
        self._identities[identity_id] = updated
        return updated

    def resolve_pinned_appearance(
        self, binding: ProjectCharacterBinding, appearance_id: str
    ) -> Appearance:
        """The exact appearance snapshot a pinned binding produced against."""
        identity = self.get_identity(binding.identity_id, owner_id=binding.owner_id)
        pinned = binding.pinned_appearance_versions.get(appearance_id)
        if pinned is None:
            raise IdentityError(f"IDENTITY_APPEARANCE_NOT_PINNED:{appearance_id}")
        return identity.appearance_at_version(appearance_id, pinned)

    def resolve_pinned_voice(
        self, binding: ProjectCharacterBinding
    ) -> VoiceIdentity:
        """The voice current when the binding pinned its identity version."""
        identity = self.get_identity(binding.identity_id, owner_id=binding.owner_id)
        return identity.voice_at_version(binding.pinned_identity_version)

    # -- bindings ------------------------------------------------------

    def bind(
        self,
        *,
        project_id: str,
        identity_id: str,
        owner_id: str,
        overrides: dict[str, Any] | None = None,
    ) -> ProjectCharacterBinding:
        owner = _require_owner(owner_id)
        project = str(project_id or "").strip()
        if not project:
            raise IdentityError("IDENTITY_BINDING_PROJECT_REQUIRED")
        identity = self.get_identity(identity_id, owner_id=owner)
        clean_overrides = dict(overrides or {})
        illegal = sorted(set(clean_overrides) - set(OVERRIDABLE_FIELDS))
        if illegal:
            raise IdentityError(f"IDENTITY_OVERRIDE_NOT_ALLOWED:{','.join(illegal)}")
        binding = ProjectCharacterBinding(
            binding_id=f"binding-{uuid4().hex[:12]}",
            project_id=project,
            identity_id=identity.identity_id,
            owner_id=owner,
            pinned_identity_version=identity.identity_version,
            pinned_appearance_versions={
                appearance.appearance_id: appearance.version
                for appearance in identity.appearance_library
            },
            overrides=clean_overrides,
        )
        self._bindings[binding.binding_id] = binding
        return binding

    def reuse_in_project(
        self, *, identity_id: str, owner_id: str, new_project_id: str
    ) -> ProjectCharacterBinding:
        """Cross-project reuse: same owner, same identity, NEW binding.

        One authority (this registry); each project pins its own versions.
        """
        return self.bind(
            project_id=new_project_id, identity_id=identity_id, owner_id=owner_id
        )

    def get_binding(self, binding_id: str, *, owner_id: str) -> ProjectCharacterBinding:
        owner = _require_owner(owner_id)
        try:
            binding = self._bindings[binding_id]
        except KeyError:
            raise IdentityError(f"IDENTITY_BINDING_UNKNOWN:{binding_id}") from None
        if binding.owner_id != owner:
            raise IdentityError("IDENTITY_OWNER_MISMATCH")
        return binding

    @property
    def identities(self) -> tuple[GlobalCreativeIdentity, ...]:
        return tuple(self._identities.values())

    def archive_identity(self, identity_id: str, *, owner_id: str) -> GlobalCreativeIdentity:
        """Archive instead of delete: bindings/facts/history are preserved, so
        historical projects never dangle. Archived identities are hidden from
        default listing but remain resolvable by explicit id."""
        identity = self.get_identity(identity_id, owner_id=owner_id)
        updated = identity.model_copy(update={"archived": True})
        self._identities[identity_id] = updated
        return updated

    def unarchive_identity(self, identity_id: str, *, owner_id: str) -> GlobalCreativeIdentity:
        identity = self.get_identity(identity_id, owner_id=owner_id)
        updated = identity.model_copy(update={"archived": False})
        self._identities[identity_id] = updated
        return updated

    def bindings_for_project(self, project_id: str, *, owner_id: str) -> tuple[ProjectCharacterBinding, ...]:
        owner = _require_owner(owner_id)
        return tuple(
            binding
            for binding in self._bindings.values()
            if binding.project_id == project_id and binding.owner_id == owner
        )

    def bindings_for_identity(self, identity_id: str, *, owner_id: str) -> tuple[ProjectCharacterBinding, ...]:
        owner = _require_owner(owner_id)
        return tuple(
            binding
            for binding in self._bindings.values()
            if binding.identity_id == identity_id and binding.owner_id == owner
        )

    def upgrade_binding(
        self, binding_id: str, *, owner_id: str
    ) -> ProjectCharacterBinding:
        """Explicit upgrade to current identity/appearance versions."""
        binding = self.get_binding(binding_id, owner_id=owner_id)
        identity = self.get_identity(binding.identity_id, owner_id=owner_id)
        upgraded = binding.model_copy(
            update={
                "pinned_identity_version": identity.identity_version,
                "pinned_appearance_versions": {
                    appearance.appearance_id: appearance.version
                    for appearance in identity.appearance_library
                },
            }
        )
        self._bindings[binding_id] = upgraded
        return upgraded

    def snapshot(self) -> dict[str, Any]:
        """Export identities + bindings for durable persistence (D3-A)."""
        return {
            "identities": [
                identity.model_dump(mode="json")
                for identity in self._identities.values()
            ],
            "bindings": [
                binding.model_dump(mode="json") for binding in self._bindings.values()
            ],
        }

    def restore(self, snapshot: dict[str, Any]) -> None:
        """Reload identities + bindings after process restart (D3-A/C7)."""
        identities: dict[str, GlobalCreativeIdentity] = {}
        for row in (snapshot or {}).get("identities", ()):
            identity = GlobalCreativeIdentity.model_validate(row)
            identities[identity.identity_id] = identity
        bindings: dict[str, ProjectCharacterBinding] = {}
        for row in (snapshot or {}).get("bindings", ()):
            binding = ProjectCharacterBinding.model_validate(row)
            bindings[binding.binding_id] = binding
        self._identities = identities
        self._bindings = bindings
        names: dict[str, str] = {}
        for identity in identities.values():
            for name in (identity.canonical_name, *identity.aliases):
                key = name.strip().lower()
                if key in names and names[key] != identity.identity_id:
                    raise IdentityError(f"CHARACTER_NAME_COLLISION:{name}")
                names[key] = identity.identity_id
        self._names = names


def validate_pre_production(
    *,
    registry: PersistentIdentityRegistry,
    binding: ProjectCharacterBinding,
    owner_id: str,
    planned_appearance_id: str = "default",
    planned_voice_id: str = "",
    planned_location: str = "",
    planned_props: tuple[str, ...] = (),
    planned_statements: tuple[str, ...] = (),
) -> ContinuityVerdict:
    """Pre-production continuity check: PASS / WARN / BLOCK.

    BLOCK is reserved for hard constraints only: unknown identity, owner
    mismatch, unknown appearance, or a planned statement contradicting a
    recorded canon hard constraint. Everything else degrades to WARN.
    """
    findings: list[ContinuityFinding] = []
    try:
        identity = registry.get_identity(binding.identity_id, owner_id=owner_id)
    except IdentityError as exc:
        return ContinuityVerdict(
            verdict=ContinuitySeverity.BLOCK,
            findings=(
                ContinuityFinding(
                    severity=ContinuitySeverity.BLOCK,
                    code=str(exc),
                    detail="identity unavailable to this owner",
                ),
            ),
        )
    if binding.owner_id != identity.owner_id:
        return ContinuityVerdict(
            verdict=ContinuitySeverity.BLOCK,
            findings=(
                ContinuityFinding(
                    severity=ContinuitySeverity.BLOCK,
                    code="IDENTITY_OWNER_MISMATCH",
                    detail="binding owner does not own the identity",
                ),
            ),
        )

    try:
        appearance = identity.appearance(planned_appearance_id)
    except IdentityError:
        return ContinuityVerdict(
            verdict=ContinuitySeverity.BLOCK,
            findings=(
                ContinuityFinding(
                    severity=ContinuitySeverity.BLOCK,
                    code=f"IDENTITY_APPEARANCE_UNKNOWN:{planned_appearance_id}",
                    detail="planned appearance is not in the identity library",
                ),
            ),
        )

    pinned = binding.pinned_appearance_versions.get(planned_appearance_id)
    if pinned is not None and pinned < appearance.version:
        findings.append(
            ContinuityFinding(
                severity=ContinuitySeverity.WARN,
                code="IDENTITY_APPEARANCE_VERSION_DRIFT",
                detail=(
                    f"binding pins v{pinned}, identity is v{appearance.version}; "
                    "upgrade binding or stay pinned explicitly"
                ),
            )
        )
    if binding.is_stale(identity.identity_version):
        findings.append(
            ContinuityFinding(
                severity=ContinuitySeverity.WARN,
                code="IDENTITY_VERSION_DRIFT",
                detail=(
                    f"binding pins identity v{binding.pinned_identity_version}, "
                    f"current v{identity.identity_version}"
                ),
            )
        )

    if planned_voice_id:
        expected = identity.effective_voice(planned_appearance_id).voice_id
        if planned_voice_id != expected:
            findings.append(
                ContinuityFinding(
                    severity=ContinuitySeverity.WARN,
                    code="IDENTITY_VOICE_MISMATCH",
                    detail=f"planned voice {planned_voice_id!r} != bound voice {expected!r}",
                )
            )

    known_locations = {
        fact.statement
        for fact in registry.ledger.facts_for_identity(identity.identity_id)
        if fact.category is ContinuityCategory.LOCATION
    }
    if planned_location and known_locations and planned_location not in known_locations:
        findings.append(
            ContinuityFinding(
                severity=ContinuitySeverity.WARN,
                code="IDENTITY_LOCATION_UNRECORDED",
                detail=f"location {planned_location!r} has no continuity fact yet",
            )
        )
    known_props = {
        fact.statement
        for fact in registry.ledger.facts_for_identity(identity.identity_id)
        if fact.category is ContinuityCategory.PROP
    }
    findings.extend(
        ContinuityFinding(
            severity=ContinuitySeverity.WARN,
            code="IDENTITY_PROP_UNRECORDED",
            detail=f"prop {prop!r} has no continuity fact yet",
        )
        for prop in planned_props
        if known_props and prop not in known_props
    )

    canon = [constraint.lower() for constraint in identity.canon_constraints]
    for statement in planned_statements:
        lowered = statement.lower()
        for constraint in canon:
            # A hard-constraint breach is an explicit negation marker:
            # the plan states the opposite of canon ("not <constraint>").
            if f"not {constraint}" in lowered or f"no {constraint}" in lowered:
                return ContinuityVerdict(
                    verdict=ContinuitySeverity.BLOCK,
                    findings=(
                        *findings,
                        ContinuityFinding(
                            severity=ContinuitySeverity.BLOCK,
                            code="IDENTITY_CANON_CONTRADICTION",
                            detail=f"planned statement contradicts canon: {constraint!r}",
                        ),
                    ),
                )

    if not findings:
        return ContinuityVerdict(verdict=ContinuitySeverity.PASS, findings=())
    return ContinuityVerdict(verdict=ContinuitySeverity.WARN, findings=tuple(findings))


__all__ = [
    "OVERRIDABLE_FIELDS",
    "ContinuityCategory",
    "ContinuityFactRecord",
    "ContinuityFinding",
    "ContinuityLedger",
    "ContinuitySeverity",
    "ContinuityVerdict",
    "GlobalCreativeIdentity",
    "IdentityError",
    "IdentityKind",
    "PersistentIdentityRegistry",
    "ProjectCharacterBinding",
    "VoiceVersionRecord",
    "validate_pre_production",
]
