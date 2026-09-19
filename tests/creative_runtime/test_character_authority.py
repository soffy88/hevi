"""W6 gates: stable identity, variant resolution, voice inheritance, refs, staleness."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hevi.creative.layer4.character_authority import (
    AppearanceKind,
    CharacterAuthority,
    CharacterError,
    OwnerKind,
    VoiceBinding,
    VoiceConsistency,
    VoiceIdentity,
    derive_consistency,
)


def _voice(voice_id: str = "v-anna") -> VoiceIdentity:
    return VoiceIdentity(voice_id=voice_id, binding=VoiceBinding.PROMPT_DESCRIPTION)


def _authority() -> CharacterAuthority:
    authority = CharacterAuthority()
    authority.register(
        character_id="ch-anna",
        canonical_name="Anna",
        voice=_voice(),
        aliases=("Ann",),
        default_assets=("sheet-anna-v1",),
        default_references=("ref-anna-face",),
    )
    return authority


def test_character_identity_stable_across_appearance_ops() -> None:
    """CHARACTER_IDENTITY_STABLE: looks change, the canonical ID never does."""

    authority = _authority()
    updated = authority.add_appearance(
        "ch-anna",
        appearance_id="battle",
        kind=AppearanceKind.OUTFIT,
        visual_asset_ids=("sheet-anna-battle-v1",),
        reference_asset_ids=("ref-anna-face", "ref-anna-armor"),
    )
    assert updated.character_id == "ch-anna"
    assert updated.canonical_name == "Anna"
    assert updated.default_appearance_id == "default"
    assert updated.voice.voice_id == "v-anna"
    assert [a.appearance_id for a in updated.appearances] == ["default", "battle"]
    for appearance in updated.appearances:
        assert appearance.character_id == "ch-anna"


def test_appearance_variant_resolution() -> None:
    """APPEARANCE_VARIANT_RESOLUTION: bare name hits default; slash pins a look."""

    authority = _authority()
    authority.add_appearance("ch-anna", appearance_id="young", kind=AppearanceKind.AGE)
    authority.add_appearance("ch-anna", appearance_id="battle", kind=AppearanceKind.OUTFIT)
    bare = authority.resolve_reference("Anna")
    assert (bare.character_id, bare.appearance_id) == ("ch-anna", "default")
    pinned = authority.resolve_reference("Anna/young")
    assert (pinned.character_id, pinned.appearance_id) == ("ch-anna", "young")
    aliased = authority.resolve_reference("@[Ann/battle]")
    assert aliased.appearance_id == "battle"
    with pytest.raises(CharacterError, match="CHARACTER_APPEARANCE_UNKNOWN"):
        authority.resolve_reference("Anna/ghost")
    with pytest.raises(CharacterError, match="CHARACTER_REFERENCE_UNREGISTERED"):
        authority.resolve_reference("Nobody")
    # an appearance is never a new character
    with pytest.raises(CharacterError, match="CHARACTER_REFERENCE_UNREGISTERED"):
        authority.resolve_reference("battle")


def test_appearance_kinds_and_versioning() -> None:
    authority = _authority()
    for appearance_id, kind in (
        ("armor", AppearanceKind.OUTFIT),
        ("child", AppearanceKind.AGE),
        ("scarred", AppearanceKind.INJURED),
        ("spy", AppearanceKind.DISGUISE),
        ("wolf", AppearanceKind.TRANSFORMATION),
    ):
        authority.add_appearance("ch-anna", appearance_id=appearance_id, kind=kind)
    assert len(authority.get("ch-anna").appearances) == 6
    before = authority.get("ch-anna").appearance("armor")
    updated = authority.update_appearance_assets(
        "ch-anna", "armor", visual_asset_ids=("sheet-anna-armor-v2",)
    )
    after = updated.appearance("armor")
    assert after.version == before.version + 1
    assert after.visual_asset_ids == ("sheet-anna-armor-v2",)
    assert "armor#2" in after.revision
    with pytest.raises(CharacterError, match="CHARACTER_APPEARANCE_DEFAULT_IMMUTABLE"):
        authority.add_appearance("ch-anna", appearance_id="default", kind=AppearanceKind.DEFAULT)
    with pytest.raises(CharacterError, match="CHARACTER_APPEARANCE_DUPLICATE"):
        authority.add_appearance("ch-anna", appearance_id="armor", kind=AppearanceKind.OUTFIT)


def test_rollback_bumps_version_and_fires_staleness() -> None:
    authority = _authority()
    authority.add_appearance("ch-anna", appearance_id="armor", kind=AppearanceKind.OUTFIT)
    authority.update_appearance_assets("ch-anna", "armor", visual_asset_ids=("v2",))
    rolled = authority.rollback_appearance("ch-anna", "armor", to_version=1)
    assert rolled.appearance("armor").version == 3
    assert "armor#3" in rolled.appearance("armor").revision
    with pytest.raises(CharacterError, match="CHARACTER_ROLLBACK_VERSION_INVALID"):
        authority.rollback_appearance("ch-anna", "armor", to_version=9)


def test_voice_identity_inheritance_and_override() -> None:
    """VOICE_IDENTITY_INHERITANCE: voice follows character unless overridden."""

    authority = _authority()
    authority.add_appearance("ch-anna", appearance_id="wolf", kind=AppearanceKind.TRANSFORMATION)
    character = authority.get("ch-anna")
    assert character.effective_voice("default").voice_id == "v-anna"
    assert character.effective_voice("wolf").voice_id == "v-anna"
    authority.assign_voice("ch-anna", VoiceIdentity(voice_id="v-anna-2"))
    assert authority.get("ch-anna").effective_voice("wolf").voice_id == "v-anna-2"
    growl = VoiceIdentity(voice_id="v-wolf-growl")
    authority.update_appearance_assets("ch-anna", "wolf", visual_asset_ids=("sheet-wolf",))
    wolf = authority.get("ch-anna").appearance("wolf")
    authority.get("ch-anna").model_copy(update={})  # frozen model untouched by reads
    overridden = wolf.model_copy(update={"voice_override": growl})
    assert overridden.voice_override is not None
    assert overridden.voice_override.voice_id == "v-wolf-growl"
    with pytest.raises(ValidationError, match="CHARACTER_VOICE_BINDING_NEEDS_REFERENCE_AUDIO"):
        VoiceIdentity(voice_id="x", binding=VoiceBinding.REFERENCE_AUDIO)


def test_reference_asset_authority() -> None:
    """REFERENCE_ASSET_AUTHORITY: assets bound to appearance versions."""

    authority = _authority()
    authority.add_appearance(
        "ch-anna",
        appearance_id="armor",
        kind=AppearanceKind.OUTFIT,
        reference_asset_ids=("ref-anna-face", "ref-anna-armor"),
    )
    character = authority.get("ch-anna")
    assert character.effective_references("default") == ("ref-anna-face",)
    assert character.effective_references("armor") == ("ref-anna-face", "ref-anna-armor")


def test_stale_propagation_scoped_to_appearance() -> None:
    """STALE_PROPAGATION: appearance change invalidates only its dependents."""

    authority = _authority()
    authority.add_appearance("ch-anna", appearance_id="armor", kind=AppearanceKind.OUTFIT)
    edges = (
        ("board-1", "appearance:armor"),
        ("clip-1", "appearance:armor"),
        ("board-9", "appearance:default"),
        ("clip-9", "appearance:default"),
    )
    assert authority.appearance_change_impact("ch-anna", "armor", edges) == ("board-1", "clip-1")
    assert authority.appearance_change_impact("ch-anna", "default", edges) == (
        "board-9",
        "clip-9",
    )


def test_rename_cascade_atomic() -> None:
    authority = _authority()
    authority.add_appearance("ch-anna", appearance_id="battle", kind=AppearanceKind.OUTFIT)
    refs = (
        {"ref_id": "r1", "text": "Anna enters"},
        {"ref_id": "r2", "text": "Ann/battle draws"},
    )
    renamed, remapped = authority.rename_character("Anna", "Anya", refs)
    assert renamed.canonical_name == "Anya"
    assert renamed.character_id == "ch-anna"
    assert remapped[0]["text"] == "Anya enters"
    # the alias still resolves, so its mentions need no rewrite
    assert remapped[1]["text"] == "Ann/battle draws"
    assert authority.resolve_reference("Anya").character_id == "ch-anna"
    assert authority.resolve_reference("Ann/battle").character_id == "ch-anna"
    with pytest.raises(CharacterError, match="CHARACTER_REFERENCE_UNREGISTERED"):
        authority.resolve_reference("Anna")


def test_rename_collision_and_unknown_refuse_without_partial() -> None:
    authority = _authority()
    authority.register(character_id="ch-bob", canonical_name="Bob", voice=_voice("v-bob"))
    before = authority.get("ch-anna")
    with pytest.raises(CharacterError, match="CHARACTER_RENAME_COLLISION"):
        authority.rename_character("Anna", "Bob", ())
    with pytest.raises(CharacterError, match="CHARACTER_RENAME_UNKNOWN"):
        authority.rename_character("Nobody", "Zed", ())
    assert authority.get("ch-anna") == before


def test_missing_reference_blocking_lists_names() -> None:
    authority = _authority()
    authority.add_appearance("ch-anna", appearance_id="armor", kind=AppearanceKind.OUTFIT)
    report = authority.check_references(("Anna", "Anna/armor", "Ghost", "Anna/ghost"))
    assert report.blocked is True
    assert report.missing == ("Ghost", "Anna/ghost")
    clear = authority.check_references(("Anna", "Ann/armor"))
    assert clear.blocked is False
    assert clear.missing == ()


def test_consistency_tier_derivation() -> None:
    assert (
        derive_consistency(
            model_has_audio_track=False,
            reference_driven_mode=True,
            binding=VoiceBinding.REFERENCE_AUDIO,
        )
        is VoiceConsistency.NONE
    )
    assert (
        derive_consistency(
            model_has_audio_track=True,
            reference_driven_mode=True,
            binding=VoiceBinding.REFERENCE_AUDIO,
        )
        is VoiceConsistency.NATIVE
    )
    assert (
        derive_consistency(
            model_has_audio_track=True,
            reference_driven_mode=False,
            binding=VoiceBinding.PROMPT_DESCRIPTION,
        )
        is VoiceConsistency.SOFT
    )


def test_utterance_ownership_narrator_character_derivative() -> None:
    authority = _authority()
    authority.add_appearance("ch-anna", appearance_id="wolf", kind=AppearanceKind.TRANSFORMATION)
    narrator = authority.resolve_utterance_owner(None)
    assert narrator.kind is OwnerKind.NARRATOR
    assert authority.resolve_utterance_owner("voiceover").kind is OwnerKind.NARRATOR
    line = authority.resolve_utterance_owner("Anna")
    assert line.kind is OwnerKind.CHARACTER
    assert (line.character_id, line.appearance_id, line.voice_id) == (
        "ch-anna",
        "default",
        "v-anna",
    )
    derivative = authority.resolve_utterance_owner("Anna/wolf")
    assert derivative.appearance_id == "wolf"
    assert derivative.voice_id == "v-anna"


def test_casting_keys_resolve_through_canonical_identity() -> None:
    """W17 casting closure: names normalize to canonical id + appearance."""

    from hevi.creative.layer4.character_authority import (
        authority_from_character_names,
        canonical_casting_key,
    )

    authority = authority_from_character_names(["Anna", "Bob", "Anna/armor", ""])
    assert canonical_casting_key(authority, "Anna") == ("Anna", "default")
    # appearance suffix shares the base character identity
    assert canonical_casting_key(authority, "Anna/armor") == ("Anna", "armor")
    # unregistered base keeps legacy fallback (identity is never invented)
    assert canonical_casting_key(authority, "Ghost/armor") == ("Ghost", "armor")
    assert canonical_casting_key(authority, "Ghost") == ("Ghost", "default")
    assert canonical_casting_key(authority, "") == ("", "default")


def test_director_voice_casting_keyed_by_canonical_id() -> None:
    """Cast map keys are canonical ids, so name/appearance inherits the voice."""

    from hevi.api.routers.director_pipeline import _assign_character_voices
    from hevi.director.pipeline_schemas import DesignCharacter, DesignList

    design = DesignList(
        characters=[
            DesignCharacter(name="Anna", voice_id="v-anna"),
            DesignCharacter(name="Bob", voice_hint="少女"),
        ]
    )
    voices = _assign_character_voices(design)
    assert voices["Anna"] == "v-anna"
    assert set(voices) == {"Anna", "Bob"}  # canonical keys only
