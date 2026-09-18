"""W10 gates: legacy serve/voice paths delegate to canonical authorities."""

from __future__ import annotations

import pytest

from hevi.creative.layer4.character_authority import (
    AppearanceKind,
    CharacterAuthority,
    authority_from_voice_map,
    voice_for_speaker,
)
from hevi.creative.layer4.presentation import (
    AudioMode,
    PresentationError,
    for_download,
    infer_audio_mode,
    snapshot_for_serving,
)
from hevi.production.artifacts import Artifact, ArtifactManifest


def _manifest() -> ArtifactManifest:
    return ArtifactManifest(
        production_id="p1",
        artifacts=[
            Artifact(
                artifact_id="v-main",
                kind="video",
                path="/v/main.mp4",
                media_type="video/mp4",
                primary=True,
                logical_role="final_video",
            ),
            Artifact(
                artifact_id="v-old",
                kind="video",
                path="/v/old.mp4",
                media_type="video/mp4",
                primary=False,
            ),
            Artifact(
                artifact_id="a-tts",
                kind="tts",
                path="/v/tts.mp3",
                media_type="audio/mpeg",
                primary=True,
            ),
        ],
    )


def _probe() -> dict[str, int]:
    return {
        "/v/main.mp4": 6000,
        "v-main": 6000,
        "/v/old.mp4": 5000,
        "/v/tts.mp3": 5900,
        "a-tts": 5900,
    }


def test_serve_prefers_stored_snapshot_without_reselection() -> None:
    from hevi.creative.layer4.presentation import PresentationSelector
    from tests.creative_runtime.test_presentation import _audio, _subs, _video

    stored = PresentationSelector().select(
        project_id="p1",
        production_run_id="r1",
        revision_id="rev-9",
        scope_id="s1",
        video_candidates=(_video(),),
        actual_durations_ms={"vid-1": 5230, "aud-1": 5100, "sub-1": 5230},
        audio_mode=AudioMode.TTS,
        audio_candidates=(_audio(),),
        subtitle_candidates=(_subs(),),
        dependency_revisions={"graph": "7"},
    )
    task = {"id": "r1", "config_json": {"presentation_snapshot": stored.model_dump(mode="json")}}
    served = snapshot_for_serving(_manifest(), task=task, probe_durations_ms=_probe())
    assert served.snapshot_id == stored.snapshot_id
    assert served.video.artifact_id == "vid-1"


def test_serve_materializes_from_manifest_with_probed_actuals() -> None:
    served = snapshot_for_serving(_manifest(), probe_durations_ms=_probe())
    view = for_download(served)
    assert view["video_artifact_id"] == "v-main"  # primary wins, same as legacy _select
    assert view["video_version"] == 1
    assert view["audio_artifact_id"] == "a-tts"
    assert view["audio_mode"] == "tts"
    assert view["effective_duration_ms"] == 6000


def test_serve_refuses_when_unprovable() -> None:
    with pytest.raises(PresentationError, match="PRESENTATION_DURATION_UNKNOWN"):
        snapshot_for_serving(_manifest(), probe_durations_ms={})


def test_infer_audio_mode_matrix() -> None:
    assert infer_audio_mode(_manifest()) is AudioMode.TTS
    assert (
        infer_audio_mode(ArtifactManifest(artifacts=[Artifact(kind="video", path="/v/x.mp4")]))
        is AudioMode.SILENT
    )
    assert (
        infer_audio_mode(
            ArtifactManifest(
                artifacts=[
                    Artifact(kind="video", path="/v/x.mp4"),
                    Artifact(kind="audio", path="/v/a.wav"),
                ]
            )
        )
        is AudioMode.NATIVE
    )


def test_preferred_id_selection_matches_snapshot() -> None:
    from fastapi import HTTPException

    from hevi.artifact_store.http import _select

    manifest = _manifest()
    assert _select(manifest, "video", preferred_artifact_id="v-old").path == "/v/old.mp4"
    assert _select(manifest, "video", preferred_artifact_id=None).path == "/v/main.mp4"
    assert _select(manifest, "video", preferred_artifact_id="missing").path == "/v/main.mp4"
    with pytest.raises(HTTPException):
        _select(ArtifactManifest(artifacts=[]), "video", preferred_artifact_id="x")


def test_voice_map_authority_preserves_plain_names() -> None:
    voice_map = {"Anna": "voice-a", "Bob": "voice-b"}
    authority = authority_from_voice_map(voice_map)
    for name, voice in voice_map.items():
        assert voice_for_speaker(authority, name, default="fallback") == voice
    assert voice_for_speaker(authority, "Ghost", default="fallback") == "fallback"
    assert voice_for_speaker(authority, "Anna", is_dialogue=False) is None
    assert voice_for_speaker(authority, None, default="fallback") == "fallback"
    assert voice_for_speaker(authority, "Narrator", default="mapped") == "mapped"


def test_voice_map_authority_resolves_appearance_suffix() -> None:
    authority = CharacterAuthority()
    from hevi.creative.layer4.character_authority import VoiceIdentity

    authority.register(
        character_id="ch-anna", canonical_name="Anna", voice=VoiceIdentity(voice_id="v-anna")
    )
    authority.add_appearance("ch-anna", appearance_id="wolf", kind=AppearanceKind.TRANSFORMATION)
    assert voice_for_speaker(authority, "Anna/wolf", default="fallback") == "v-anna"
    assert voice_for_speaker(authority, "Anna", default="fallback") == "v-anna"
