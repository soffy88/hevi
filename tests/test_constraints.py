from hevi.constraints import (
    ProviderCapabilities,
    compile_graph,
    derive_constraints,
    verify_delivery,
)
from hevi.director.pipeline_schemas import DesignList, ShotList
from hevi.production.artifacts import ArtifactManifest


def test_constraint_graph_derives_identity_eyeline_and_camera() -> None:
    design = DesignList.model_validate(
        {
            "characters": [
                {"name": "甲", "subject_id": "subject-a", "wardrobe": "深色长衫"},
                {"name": "乙", "subject_id": "subject-b"},
            ],
            "scenes": [{"name": "茶室", "subject_id": "scene-a"}],
        }
    )
    shots = ShotList.model_validate(
        {
            "shots": [
                {
                    "shot_id": "S01",
                    "scene_no": 1,
                    "scene_name": "茶室",
                    "character_names": ["甲", "乙"],
                    "camera_angle": "侧45°",
                    "azimuth_deg": 45,
                    "dialogue_lines": [
                        {"character_name": "甲", "target_name": "乙", "text": "你来了。"}
                    ],
                    "blocking": [{"character_name": "甲", "position": "左侧", "facing": "乙"}],
                    "style_ref": "style:historical-realism",
                    "continuity_requirements": ["甲保持左侧站位"],
                    "safety_requirements": ["无现代武器"],
                    "delivery_requirements": ["字幕安全区内"],
                    "performance_track": {
                        "total_duration_s": 5.0,
                        "phases": [{"phase_id": "p1", "t_start_s": 0.0, "t_end_s": 5.0}],
                    },
                    "audio_track": {
                        "dialogue": "你来了。",
                        "segments": [{"t_start_s": 0.0, "t_end_s": 2.0}],
                    },
                }
            ]
        }
    )

    graph = derive_constraints(design_list=design, shot_list=shots, revision_id="rev-1")

    types = {item.type for item in graph.constraints}
    assert {
        "identity",
        "wardrobe",
        "scene",
        "camera",
        "dialogue_sync",
        "eyeline",
        "blocking",
        "performance",
        "timing",
        "audio",
        "style",
        "continuity",
        "safety",
        "delivery",
    } <= types
    assert graph.coverage.derived_constraints == len(graph.constraints)
    assert graph.coverage.silent_drops == 0
    graph.coverage.verified_constraints = graph.coverage.derived_constraints
    assert graph.coverage.verification_rate >= 0.98


def test_constraint_compiler_reports_unsupported_without_silent_drop() -> None:
    graph = derive_constraints(
        shot_list={
            "shots": [
                {
                    "shot_id": "S01",
                    "scene_no": 1,
                    "character_names": ["甲"],
                    "camera": "static",
                }
            ]
        }
    )
    result = compile_graph(
        graph,
        ProviderCapabilities(provider_id="image-provider", supported_constraints={"camera"}),
    )

    assert result.instructions
    assert result.unsupported
    assert result.silent_drops == []
    assert graph.coverage.silent_drops == 0

    verdict = verify_delivery(graph, result)
    assert not verdict.passed
    assert verdict.repair_actions


def test_artifact_manifest_records_content_hash(tmp_path) -> None:
    output = tmp_path / "episode.mp4"
    output.write_bytes(b"hevi-artifact")

    manifest = ArtifactManifest.for_video(output)

    artifact = manifest.artifacts[0]
    assert artifact.sha256
    assert artifact.byte_size == len(b"hevi-artifact")
    assert artifact.integrity_ok()
    assert manifest.verify_integrity() == []
