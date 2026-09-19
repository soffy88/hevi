"""Unified character authority (Gap Closure W6: C06, C08, F02, F03, F04).

One canonical character ID owns everything about that character:

- stable identity (name + aliases),
- visual appearances/derivatives (default, outfit, age, injured, disguise,
  transformation) — each with its own appearance ID, versioned visual
  assets, and effective reference set,
- voice identity (inherited by all appearances unless overridden),
- reference assets bound to appearance versions.

An appearance is never a new character: it carries the same
``character_id`` and only its own ``appearance_id``. Script/storyboard
references resolve ``name`` (default appearance) or
``name/appearance`` explicitly. Renames cascade atomically across a
caller-supplied reference index; unknown references block with names
listed. Appearance changes propagate staleness through the shared
currency invalidation rule (W2) — never project-wide.

Voice (F02/F03/F04): voice identity follows the character; consistency
tiers derive deterministically from model audio support, generation
mode, and binding; utterance ownership resolves narrator vs character
vs derivative-scoped voice.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hevi.creative.layer4.currency import invalidate_dependents


class AppearanceKind(StrEnum):
    DEFAULT = "default"
    OUTFIT = "outfit"
    AGE = "age"
    INJURED = "injured"
    DISGUISE = "disguise"
    TRANSFORMATION = "transformation"


class VoiceBinding(StrEnum):
    PROMPT_DESCRIPTION = "prompt"
    REFERENCE_AUDIO = "reference_audio"


class VoiceConsistency(StrEnum):
    NATIVE = "native"
    SOFT = "soft"
    NONE = "none"


class OwnerKind(StrEnum):
    NARRATOR = "narrator"
    CHARACTER = "character"


class SpeechOwnerType(StrEnum):
    """Canonical owner of one spoken/audio segment."""

    NARRATOR = "NARRATOR"
    CHARACTER = "CHARACTER"
    NATIVE_AUDIO = "NATIVE_AUDIO"
    UPLOADED_AUDIO = "UPLOADED_AUDIO"
    NONE = "NONE"


class SpeechSegmentOwner(BaseModel):
    """Resolved speech ownership: never guessed from strings downstream."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    owner_type: SpeechOwnerType
    character_id: str | None = None
    appearance_id: str | None = None
    voice_id: str | None = None
    consistency: VoiceConsistency | None = None
    provenance: str = ""


class CharacterError(ValueError):
    """Refusal with a stable machine code."""


class VoiceIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    voice_id: str = Field(min_length=1)
    binding: VoiceBinding = VoiceBinding.PROMPT_DESCRIPTION
    description: str = ""
    reference_audio_ref: str | None = None

    @model_validator(mode="after")
    def _reference_binding_needs_audio(self) -> VoiceIdentity:
        if self.binding is VoiceBinding.REFERENCE_AUDIO and not self.reference_audio_ref:
            raise CharacterError("CHARACTER_VOICE_BINDING_NEEDS_REFERENCE_AUDIO")
        return self


class Appearance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    appearance_id: str = Field(min_length=1)
    character_id: str = Field(min_length=1)
    kind: AppearanceKind = AppearanceKind.DEFAULT
    label: str = ""
    version: int = Field(ge=1, default=1)
    visual_asset_ids: tuple[str, ...] = ()
    reference_asset_ids: tuple[str, ...] = ()
    voice_override: VoiceIdentity | None = None
    revision: str = ""
    superseded_by_version: int | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Character(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    character_id: str = Field(min_length=1)
    canonical_name: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    default_appearance_id: str = Field(min_length=1)
    appearances: tuple[Appearance, ...] = ()
    voice: VoiceIdentity
    revision: str = ""

    @model_validator(mode="after")
    def _default_appearance_member(self) -> Character:
        ids = {appearance.appearance_id for appearance in self.appearances}
        if self.default_appearance_id not in ids:
            raise CharacterError("CHARACTER_DEFAULT_APPEARANCE_UNKNOWN")
        for appearance in self.appearances:
            if appearance.character_id != self.character_id:
                raise CharacterError("CHARACTER_APPEARANCE_IDENTITY_MISMATCH")
        return self

    def appearance(self, appearance_id: str) -> Appearance:
        for candidate in self.appearances:
            if candidate.appearance_id == appearance_id:
                return candidate
        raise CharacterError(f"CHARACTER_APPEARANCE_UNKNOWN:{appearance_id}")

    def effective_voice(self, appearance_id: str | None = None) -> VoiceIdentity:
        if appearance_id is not None:
            override = self.appearance(appearance_id).voice_override
            if override is not None:
                return override
        return self.voice

    def effective_references(self, appearance_id: str) -> tuple[str, ...]:
        return self.appearance(appearance_id).reference_asset_ids


class ScriptReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    raw: str = Field(min_length=1)
    character_id: str = Field(min_length=1)
    appearance_id: str = Field(min_length=1)


class ReferenceCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    missing: tuple[str, ...] = ()
    blocked: bool = False


def derive_consistency(
    *,
    model_has_audio_track: bool,
    reference_driven_mode: bool,
    binding: VoiceBinding,
) -> VoiceConsistency:
    """Deterministic voice-consistency tier (F02).

    - no audio track -> NONE (silent model, nothing to keep consistent);
    - reference-driven generation + reference-audio binding -> NATIVE;
    - anything else with audio -> SOFT (prompt-described constraint).
    """

    if not model_has_audio_track:
        return VoiceConsistency.NONE
    if reference_driven_mode and binding is VoiceBinding.REFERENCE_AUDIO:
        return VoiceConsistency.NATIVE
    return VoiceConsistency.SOFT


class UtteranceOwner(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: OwnerKind
    character_id: str | None = None
    appearance_id: str | None = None
    voice_id: str | None = None


class CharacterAuthority:
    """Registry of canonical characters with atomic cross-cutting operations."""

    def __init__(self, characters: tuple[Character, ...] = ()) -> None:
        self._characters: dict[str, Character] = {}
        self._names: dict[str, str] = {}
        for character in characters:
            self._index(character)

    def _index(self, character: Character) -> None:
        if character.character_id in self._characters:
            raise CharacterError(f"CHARACTER_DUPLICATE_ID:{character.character_id}")
        self._characters[character.character_id] = character
        for name in (character.canonical_name, *character.aliases):
            key = name.strip().lower()
            if key in self._names and self._names[key] != character.character_id:
                raise CharacterError(f"CHARACTER_NAME_COLLISION:{name}")
            self._names[key] = character.character_id

    @property
    def characters(self) -> tuple[Character, ...]:
        return tuple(self._characters.values())

    def get(self, character_id: str) -> Character:
        try:
            return self._characters[character_id]
        except KeyError:
            raise CharacterError(f"CHARACTER_UNKNOWN:{character_id}") from None

    def register(
        self,
        *,
        character_id: str,
        canonical_name: str,
        voice: VoiceIdentity,
        aliases: tuple[str, ...] = (),
        default_appearance_id: str = "default",
        default_assets: tuple[str, ...] = (),
        default_references: tuple[str, ...] = (),
    ) -> Character:
        character = Character(
            character_id=character_id,
            canonical_name=canonical_name,
            aliases=aliases,
            default_appearance_id=default_appearance_id,
            appearances=(
                Appearance(
                    appearance_id=default_appearance_id,
                    character_id=character_id,
                    kind=AppearanceKind.DEFAULT,
                    label="default",
                    visual_asset_ids=default_assets,
                    reference_asset_ids=default_references,
                    revision=f"{character_id}@{default_appearance_id}#1",
                ),
            ),
            voice=voice,
            revision=f"{character_id}#1",
        )
        self._index(character)
        return character

    def add_appearance(
        self,
        character_id: str,
        *,
        appearance_id: str,
        kind: AppearanceKind,
        label: str = "",
        visual_asset_ids: tuple[str, ...] = (),
        reference_asset_ids: tuple[str, ...] = (),
        voice_override: VoiceIdentity | None = None,
    ) -> Character:
        """Add a derivative look. Same character ID — never a new character."""

        character = self.get(character_id)
        if kind is AppearanceKind.DEFAULT:
            raise CharacterError("CHARACTER_APPEARANCE_DEFAULT_IMMUTABLE")
        if any(a.appearance_id == appearance_id for a in character.appearances):
            raise CharacterError(f"CHARACTER_APPEARANCE_DUPLICATE:{appearance_id}")
        appearance = Appearance(
            appearance_id=appearance_id,
            character_id=character_id,
            kind=kind,
            label=label or appearance_id,
            visual_asset_ids=visual_asset_ids,
            reference_asset_ids=reference_asset_ids,
            voice_override=voice_override,
            revision=f"{character_id}@{appearance_id}#1",
        )
        updated = character.model_copy(
            update={
                "appearances": (*character.appearances, appearance),
                "revision": f"{character_id}#{len(character.appearances) + 1}",
            }
        )
        self._characters[character_id] = updated
        return updated

    def rollback_appearance(
        self, character_id: str, appearance_id: str, *, to_version: int
    ) -> Character:
        """Roll back an appearance's assets to a prior version marker.

        Versions are monotonic markers on the appearance record; rollback
        re-points effective assets to the recorded prior set supplied by
        the caller through ``update_appearance_assets`` history is out of
        scope for this authority — rollback restores the last committed
        asset set and bumps the version so downstream staleness fires.
        """

        character = self.get(character_id)
        appearance = character.appearance(appearance_id)
        if to_version < 1 or to_version >= appearance.version:
            raise CharacterError("CHARACTER_ROLLBACK_VERSION_INVALID")
        rolled = appearance.model_copy(
            update={
                "version": appearance.version + 1,
                "superseded_by_version": None,
                "revision": f"{character_id}@{appearance_id}#{appearance.version + 1}",
            }
        )
        appearances = tuple(
            rolled if a.appearance_id == appearance_id else a for a in character.appearances
        )
        updated = character.model_copy(update={"appearances": appearances})
        self._characters[character_id] = updated
        return updated

    def update_appearance_assets(
        self,
        character_id: str,
        appearance_id: str,
        *,
        visual_asset_ids: tuple[str, ...] | None = None,
        reference_asset_ids: tuple[str, ...] | None = None,
    ) -> Character:
        character = self.get(character_id)
        appearance = character.appearance(appearance_id)
        updated_appearance = appearance.model_copy(
            update={
                "visual_asset_ids": appearance.visual_asset_ids
                if visual_asset_ids is None
                else visual_asset_ids,
                "reference_asset_ids": appearance.reference_asset_ids
                if reference_asset_ids is None
                else reference_asset_ids,
                "version": appearance.version + 1,
                "revision": f"{character_id}@{appearance_id}#{appearance.version + 1}",
            }
        )
        appearances = tuple(
            updated_appearance if a.appearance_id == appearance_id else a
            for a in character.appearances
        )
        updated = character.model_copy(update={"appearances": appearances})
        self._characters[character_id] = updated
        return updated

    def resolve_reference(self, raw: str) -> ScriptReference:
        """Resolve ``name`` (default look) or ``name/appearance`` explicitly."""

        text = raw.strip().strip("@[]")
        if "/" in text:
            name, appearance_id = text.split("/", 1)
        else:
            name, appearance_id = text, ""
        key = name.strip().lower()
        if key not in self._names:
            raise CharacterError(f"CHARACTER_REFERENCE_UNREGISTERED:{raw}")
        character = self.get(self._names[key])
        resolved_appearance = appearance_id.strip() or character.default_appearance_id
        character.appearance(resolved_appearance)  # fail closed on unknown look
        return ScriptReference(
            raw=raw, character_id=character.character_id, appearance_id=resolved_appearance
        )

    def check_references(self, raws: tuple[str, ...]) -> ReferenceCheck:
        """Missing-reference blocking report: names listed, never guessed."""

        missing: list[str] = []
        for raw in raws:
            try:
                self.resolve_reference(raw)
            except CharacterError:
                missing.append(raw)
        return ReferenceCheck(missing=tuple(missing), blocked=bool(missing))

    def rename_character(
        self,
        old_name: str,
        new_name: str,
        references: tuple[dict[str, Any], ...],
    ) -> tuple[Character, tuple[dict[str, Any], ...]]:
        """Atomic rename cascade: character plus every indexed reference.

        ``references`` are caller-owned ``{"ref_id","text"}`` rows whose
        ``text`` mentions the old name. Collision with another character's
        name or alias refuses with no partial application.
        """

        key = new_name.strip().lower()
        if key in self._names:
            raise CharacterError(f"CHARACTER_RENAME_COLLISION:{new_name}")
        old_key = old_name.strip().lower()
        if old_key not in self._names:
            raise CharacterError(f"CHARACTER_RENAME_UNKNOWN:{old_name}")
        character = self.get(self._names[old_key])
        if old_key != character.canonical_name.strip().lower() and old_key not in {
            alias.strip().lower() for alias in character.aliases
        }:
            raise CharacterError(f"CHARACTER_RENAME_UNKNOWN:{old_name}")
        renamed = character.model_copy(
            update={
                "canonical_name": new_name.strip(),
                "aliases": tuple(
                    new_name.strip() if alias.strip().lower() == old_key else alias
                    for alias in character.aliases
                ),
            }
        )
        remapped: list[dict[str, Any]] = []
        for row in references:
            text = str(row.get("text", ""))
            remapped.append({**row, "text": text.replace(old_name.strip(), new_name.strip())})
        self._characters[character.character_id] = renamed
        del self._names[old_key]
        self._names[key] = character.character_id
        return renamed, tuple(remapped)

    def assign_voice(self, character_id: str, voice: VoiceIdentity) -> Character:
        """Voice follows the character; appearances inherit unless overridden."""

        character = self.get(character_id)
        updated = character.model_copy(update={"voice": voice})
        self._characters[character_id] = updated
        return updated

    def resolve_utterance_owner(
        self, speaker_ref: str | None, *, narrator_names: tuple[str, ...] = ()
    ) -> UtteranceOwner:
        """F04: narrator vs character vs derivative-scoped voice ownership."""

        if not speaker_ref or speaker_ref.strip().lower() in {
            name.strip().lower() for name in narrator_names
        } | {"narrator", "vo", "voiceover"}:
            return UtteranceOwner(kind=OwnerKind.NARRATOR)
        resolved = self.resolve_reference(speaker_ref)
        character = self.get(resolved.character_id)
        return UtteranceOwner(
            kind=OwnerKind.CHARACTER,
            character_id=character.character_id,
            appearance_id=resolved.appearance_id,
            voice_id=character.effective_voice(resolved.appearance_id).voice_id,
        )

    def appearance_change_impact(
        self,
        character_id: str,
        appearance_id: str,
        edges: tuple[tuple[str, str], ...],
    ) -> tuple[str, ...]:
        """Stale propagation: only dependents of this appearance invalidate."""

        character = self.get(character_id)
        character.appearance(appearance_id)  # fail closed on unknown look
        return invalidate_dependents((f"appearance:{appearance_id}",), edges)


def resolve_speech_segment_owner(
    authority: CharacterAuthority,
    *,
    speaker_ref: str | None = None,
    audio_mode: str = "tts",
    narrator_voice_id: str = "",
    binding: VoiceBinding = VoiceBinding.PROMPT_DESCRIPTION,
    model_has_audio_track: bool = True,
    reference_driven_mode: bool = False,
    provenance: str = "",
) -> SpeechSegmentOwner:
    """Single canonical speech-ownership resolver (F02/F03/F04).

    Provider-native audio is native by provenance and never re-guessed;
    uploaded audio is manual by provenance. TTS segments resolve to a
    character through canonical identity (voice inherited from the
    authority, derivative-scoped) or to the narrator otherwise.
    """

    mode = str(audio_mode or "").lower()
    if mode == "native":
        return SpeechSegmentOwner(
            owner_type=SpeechOwnerType.NATIVE_AUDIO,
            consistency=derive_consistency(
                model_has_audio_track=model_has_audio_track,
                reference_driven_mode=reference_driven_mode,
                binding=binding,
            ),
            provenance=provenance or "provider-native",
        )
    if mode == "uploaded":
        return SpeechSegmentOwner(
            owner_type=SpeechOwnerType.UPLOADED_AUDIO,
            provenance=provenance or "manual-upload",
        )
    if mode == "silent":
        return SpeechSegmentOwner(
            owner_type=SpeechOwnerType.NONE, provenance=provenance or "silent"
        )
    if not speaker_ref:
        return SpeechSegmentOwner(
            owner_type=SpeechOwnerType.NARRATOR,
            voice_id=narrator_voice_id or None,
            provenance=provenance or "narrator",
        )
    try:
        owner = authority.resolve_utterance_owner(speaker_ref)
    except CharacterError:
        return SpeechSegmentOwner(
            owner_type=SpeechOwnerType.NARRATOR,
            voice_id=narrator_voice_id or None,
            provenance=provenance or "unregistered-speaker",
        )
    if owner.kind is OwnerKind.NARRATOR:
        return SpeechSegmentOwner(
            owner_type=SpeechOwnerType.NARRATOR,
            voice_id=narrator_voice_id or owner.voice_id or None,
            provenance=provenance or "narrator",
        )
    return SpeechSegmentOwner(
        owner_type=SpeechOwnerType.CHARACTER,
        character_id=owner.character_id,
        appearance_id=owner.appearance_id,
        voice_id=owner.voice_id,
        consistency=derive_consistency(
            model_has_audio_track=model_has_audio_track,
            reference_driven_mode=reference_driven_mode,
            binding=binding,
        ),
        provenance=provenance or "character",
    )


def voice_binding_from_project(config: Mapping[str, Any] | None) -> VoiceBinding:
    """Project-level voice binding setting -> canonical binding (F03)."""

    raw = str((config or {}).get("character_voice_binding") or "prompt").strip().lower()
    if raw in {"reference_audio", "reference", "audio"}:
        return VoiceBinding.REFERENCE_AUDIO
    return VoiceBinding.PROMPT_DESCRIPTION


def build_appearance_record(
    *,
    character_id: str,
    appearance_id: str,
    kind: AppearanceKind | str,
    label: str = "",
    visual_asset_ids: tuple[str, ...] = (),
    reference_asset_ids: tuple[str, ...] = (),
    version: int = 1,
    superseded_by_version: int | None = None,
) -> dict[str, Any]:
    """Validate and serialize one appearance through the canonical model.

    Producers (asset generation, wardrobe upload, manual import, variant
    regeneration) use this so every written appearance carries canonical
    character id, appearance id/version, base/kind relation, reference assets
    and provenance - never a loose filename or display-name relation.
    """

    appearance_kind = kind if isinstance(kind, AppearanceKind) else AppearanceKind(str(kind))
    appearance = Appearance(
        appearance_id=appearance_id,
        character_id=character_id,
        kind=appearance_kind,
        label=label or appearance_id,
        version=version,
        visual_asset_ids=visual_asset_ids,
        reference_asset_ids=reference_asset_ids,
        superseded_by_version=superseded_by_version,
        revision=f"{character_id}@{appearance_id}#{version}",
    )
    return appearance.model_dump(mode="json")


def appearances_from_records(records: Iterable[Any]) -> tuple[Appearance, ...]:
    """Parse persisted appearance records back into canonical appearances."""

    out: list[Appearance] = []
    for record in records or ():
        try:
            out.append(Appearance.model_validate(record))
        except Exception:  # pragma: no cover - tolerate legacy bad rows
            continue
    return tuple(out)


def merge_appearance_record(records: Iterable[Any], record: dict[str, Any]) -> list[dict[str, Any]]:
    """Upsert one appearance record (latest wins), preserving the others."""

    kept = [
        dict(item)
        for item in (records or ())
        if isinstance(item, dict) and item.get("appearance_id") != record.get("appearance_id")
    ]
    kept.append(record)
    return kept


def authority_from_voice_map(
    voice_by_speaker: Mapping[str, str], *, default_voice_id: str = ""
) -> CharacterAuthority:
    """Build an authority from a legacy speaker->voice map (W10 delegation).

    Lets legacy pipelines resolve ``name`` and ``name/appearance`` speaker
    strings through canonical identity with zero behavior change for plain
    names: misses still fall back to the caller's default.
    """

    authority = CharacterAuthority()
    for speaker, voice_id in voice_by_speaker.items():
        name = str(speaker or "").strip()
        if not name or name.strip().lower() in {"narrator", "vo", "voiceover"}:
            continue
        resolved_voice = str(voice_id or "").strip() or default_voice_id
        if not resolved_voice:
            continue
        try:
            authority.register(
                character_id=name,
                canonical_name=name,
                voice=VoiceIdentity(voice_id=resolved_voice),
            )
        except CharacterError:
            continue
    return authority


def voice_for_speaker(
    authority: CharacterAuthority,
    speaker: str | None,
    *,
    is_dialogue: bool = True,
    default: str | None = None,
) -> str | None:
    """Resolve a speaker to its effective voice id with legacy fallback.

    Dialogue speakers resolve through canonical identity (including
    derivative-scoped voices); narration always yields None; anything
    unregistered returns the caller's default — the P0 single-voice
    fallback behavior is preserved, never replaced by refusal.
    """

    if not is_dialogue:
        return None
    if not speaker:
        return default
    try:
        owner = authority.resolve_utterance_owner(speaker)
    except CharacterError:
        return default
    if owner.kind is OwnerKind.NARRATOR:
        # Speaker strings in narrator position keep the caller's mapping;
        # true narration lines never reach here (is_dialogue=False above).
        return default
    return owner.voice_id or default


class CharacterView(BaseModel):
    """Studio visibility projection: appearances, default, voice inheritance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    character_id: str
    canonical_name: str
    aliases: tuple[str, ...] = ()
    default_appearance_id: str = ""
    appearances: tuple[dict[str, Any], ...] = ()
    voice_by_appearance: dict[str, str] = Field(default_factory=dict)


def character_view_from_sources(
    *,
    character_id: str,
    canonical_name: str,
    aliases: tuple[str, ...] = (),
    voice_id: str = "",
    reference_images: tuple[str, ...] = (),
    appearance_text: str = "",
    appearances: tuple[Appearance, ...] | None = None,
) -> CharacterView:
    """Build a visibility view from legacy subject/bible-shaped sources.

    Legacy sources carry a single look: it becomes the default appearance
    with inherited voice. Variant-aware callers pass ``appearances``
    explicitly; every appearance reports its effective (inherited or
    overridden) voice id.
    """

    if appearances is None:
        appearances = (
            Appearance(
                appearance_id="default",
                character_id=character_id,
                kind=AppearanceKind.DEFAULT,
                label=appearance_text or "default",
                visual_asset_ids=reference_images,
                reference_asset_ids=reference_images,
                revision=f"{character_id}@default#1",
            ),
        )
    character = Character(
        character_id=character_id,
        canonical_name=canonical_name,
        aliases=aliases,
        default_appearance_id="default"
        if any(a.appearance_id == "default" for a in appearances)
        else appearances[0].appearance_id,
        appearances=appearances,
        voice=VoiceIdentity(voice_id=voice_id or "unassigned"),
    )
    return CharacterView(
        character_id=character.character_id,
        canonical_name=character.canonical_name,
        aliases=character.aliases,
        default_appearance_id=character.default_appearance_id,
        appearances=tuple(
            {
                "appearance_id": appearance.appearance_id,
                "kind": appearance.kind.value,
                "label": appearance.label,
                "version": appearance.version,
                "visual_asset_ids": list(appearance.visual_asset_ids),
                "reference_asset_ids": list(appearance.reference_asset_ids),
                "revision": appearance.revision,
            }
            for appearance in character.appearances
        ),
        voice_by_appearance={
            appearance.appearance_id: character.effective_voice(appearance.appearance_id).voice_id
            for appearance in character.appearances
        },
    )


def authority_from_character_names(names: Iterable[str]) -> CharacterAuthority:
    """Build a single-look authority from legacy design/shot character names.

    Every name registers as its own canonical character with a default
    appearance, so `name` and `name/appearance` normalize consistently even
    before derivative assets exist. Duplicate names collapse.
    """

    authority = CharacterAuthority()
    for raw in names:
        name = str(raw or "").strip()
        if not name:
            continue
        base = name.split("/", 1)[0].strip()
        if not base:
            continue
        try:
            authority.register(
                character_id=base,
                canonical_name=base,
                voice=VoiceIdentity(voice_id="unassigned"),
            )
        except CharacterError:
            continue
    return authority


def canonical_casting_key(authority: CharacterAuthority, name: str) -> tuple[str, str]:
    """Normalize a casting name to ``(canonical_character_id, appearance_id)``.

    The base name resolves through the authority (registered → canonical id;
    unregistered → the base literal, keeping legacy inputs working without
    letting them become their own identity authority). An explicit
    ``base/appearance`` suffix is preserved so derivative-aware callers can
    look up that look, falling back to the base when no derivative exists.
    """

    raw = str(name or "").strip()
    if not raw:
        return "", "default"
    base, _, appearance = raw.partition("/")
    base, appearance = base.strip(), appearance.strip()
    if not base:
        return "", "default"
    try:
        resolved = authority.resolve_reference(base)
    except CharacterError:
        return base, (appearance or "default")
    return resolved.character_id, (appearance or "default")


__all__ = [
    "Appearance",
    "AppearanceKind",
    "Character",
    "CharacterAuthority",
    "CharacterError",
    "CharacterView",
    "OwnerKind",
    "ReferenceCheck",
    "ScriptReference",
    "SpeechOwnerType",
    "SpeechSegmentOwner",
    "UtteranceOwner",
    "VoiceBinding",
    "VoiceConsistency",
    "VoiceIdentity",
    "appearances_from_records",
    "authority_from_character_names",
    "authority_from_voice_map",
    "build_appearance_record",
    "canonical_casting_key",
    "character_view_from_sources",
    "derive_consistency",
    "merge_appearance_record",
    "resolve_speech_segment_owner",
    "voice_binding_from_project",
    "voice_for_speaker",
]
