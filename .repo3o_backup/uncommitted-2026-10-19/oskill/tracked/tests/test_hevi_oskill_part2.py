"""Tests for hevi oskill: reference_generator, subtitle_generator, metadata_generate, threeo_ingester."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from oskill._schemas import (
    MetadataConstraints,
    Scene,
    Script,
    Shot,
    ShotPlan,
    Storyboard,
)
from oskill.metadata_generate import MetadataGenerateError, metadata_generate
from oskill.reference_generator import ReferenceGeneratorError, reference_generator
from oskill.subtitle_generator import SubtitleGeneratorError, subtitle_generator
from oskill.threeo_ingester import ThreeOIngestError, ThreeOSetupError, threeo_ingester


def _make_llm(response: Any):
    def _llm(*, messages: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
        if isinstance(response, str):
            return {"content": response}
        return {"content": json.dumps(response, ensure_ascii=False)}

    return _llm


def _make_shots() -> list[ShotPlan]:
    return [
        ShotPlan(shot_id="s1", image_prompt="cat", tts_text="Hello", duration_s=3.0),
        ShotPlan(shot_id="s2", image_prompt="dog", tts_text="World", duration_s=2.0),
    ]


def _make_script() -> Script:
    return Script(
        title="T",
        description="D",
        scenes=[Scene(index=0, narration="N", duration_s=5, visual_description="V")],
        estimated_duration_s=5,
    )


def _make_storyboard() -> Storyboard:
    return Storyboard(
        shots=[
            Shot(
                shot_id="s1",
                scene_index=0,
                visual_description="V",
                narration="N",
                duration_s=3,
                importance=8,
            ),
        ]
    )


def _make_constraints() -> MetadataConstraints:
    return MetadataConstraints(
        title_max_chars=100,
        description_max_chars=500,
        tags_max_count=10,
        tag_max_chars=30,
    )


# --- reference_generator tests ---


class TestReferenceGenerator:
    async def test_normal(self) -> None:
        data = [
            {"shot_id": "s1", "detailed_prompt": "detailed cat", "style_tags": ["cinematic"]},
            {"shot_id": "s2", "detailed_prompt": "detailed dog", "style_tags": ["warm"]},
        ]
        result = await reference_generator(shots=_make_shots(), llm=_make_llm(data))
        assert len(result) == 2
        assert result[0].detailed_prompt == "detailed cat"

    async def test_empty_shots_raises(self) -> None:
        with pytest.raises(ReferenceGeneratorError, match="must not be empty"):
            await reference_generator(shots=[], llm=_make_llm([]))

    async def test_invalid_json_raises(self) -> None:
        with pytest.raises(ReferenceGeneratorError, match="invalid JSON"):
            await reference_generator(shots=_make_shots(), llm=_make_llm("bad"))

    async def test_count_mismatch(self) -> None:
        data = [{"shot_id": "s1", "detailed_prompt": "x", "style_tags": []}]
        with pytest.raises(ReferenceGeneratorError, match="Count mismatch"):
            await reference_generator(shots=_make_shots(), llm=_make_llm(data))

    async def test_style_prompt_injected(self) -> None:
        captured: list[dict[str, Any]] = []

        def _llm(*, messages: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
            captured.append(messages[0])
            data = [
                {"shot_id": "s1", "detailed_prompt": "x", "style_tags": []},
                {"shot_id": "s2", "detailed_prompt": "y", "style_tags": []},
            ]
            return {"content": json.dumps(data)}

        await reference_generator(shots=_make_shots(), llm=_llm, style_prompt="anime")
        assert "anime" in captured[0]["content"]

    async def test_validation_failure(self) -> None:
        data = [{"bad": True}, {"bad": True}]
        with pytest.raises(ReferenceGeneratorError, match="Validation failed"):
            await reference_generator(shots=_make_shots(), llm=_make_llm(data))

    async def test_style_tags_list(self) -> None:
        data = [
            {"shot_id": "s1", "detailed_prompt": "p", "style_tags": ["a", "b"]},
            {"shot_id": "s2", "detailed_prompt": "p", "style_tags": ["c"]},
        ]
        result = await reference_generator(shots=_make_shots(), llm=_make_llm(data))
        assert result[0].style_tags == ["a", "b"]

    async def test_shot_id_preserved(self) -> None:
        data = [
            {"shot_id": "s1", "detailed_prompt": "p", "style_tags": []},
            {"shot_id": "s2", "detailed_prompt": "p", "style_tags": []},
        ]
        result = await reference_generator(shots=_make_shots(), llm=_make_llm(data))
        assert result[0].shot_id == "s1"


# --- subtitle_generator tests ---


class TestSubtitleGenerator:
    def test_srt_format(self, tmp_path: Path) -> None:
        out = tmp_path / "sub.srt"
        result = subtitle_generator(shots=_make_shots(), output_path=out)
        assert result == out
        content = out.read_text()
        assert "00:00:00,000 --> 00:00:03,000" in content
        assert "Hello" in content

    def test_ass_format(self, tmp_path: Path) -> None:
        out = tmp_path / "sub.ass"
        subtitle_generator(shots=_make_shots(), output_path=out, format="ass")
        content = out.read_text()
        assert "Dialogue:" in content
        assert "Hello" in content

    def test_timestamp_accumulation(self, tmp_path: Path) -> None:
        out = tmp_path / "sub.srt"
        subtitle_generator(shots=_make_shots(), output_path=out)
        content = out.read_text()
        assert "00:00:03,000 --> 00:00:05,000" in content

    def test_empty_shots_raises(self, tmp_path: Path) -> None:
        with pytest.raises(SubtitleGeneratorError, match="must not be empty"):
            subtitle_generator(shots=[], output_path=tmp_path / "sub.srt")

    def test_output_file_created(self, tmp_path: Path) -> None:
        out = tmp_path / "sub.srt"
        subtitle_generator(shots=_make_shots(), output_path=out)
        assert out.exists()

    def test_multiline_text(self, tmp_path: Path) -> None:
        shots = [
            ShotPlan(shot_id="s1", image_prompt="p", tts_text="Line one\nLine two", duration_s=5)
        ]
        out = tmp_path / "sub.srt"
        subtitle_generator(shots=shots, output_path=out)
        assert out.exists()

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        out = tmp_path / "sub" / "dir" / "sub.srt"
        subtitle_generator(shots=_make_shots(), output_path=out)
        assert out.exists()

    def test_single_shot(self, tmp_path: Path) -> None:
        shots = [ShotPlan(shot_id="s1", image_prompt="p", tts_text="Only", duration_s=10)]
        out = tmp_path / "sub.srt"
        subtitle_generator(shots=shots, output_path=out)
        content = out.read_text()
        assert "00:00:00,000 --> 00:00:10,000" in content


# --- metadata_generate tests ---


class TestMetadataGenerate:
    async def test_normal(self) -> None:
        data = {
            "title": "My Video",
            "description": "About cats",
            "tags": ["cat", "video"],
            "topics": ["animals"],
        }
        result = await metadata_generate(
            script=_make_script(),
            storyboard=_make_storyboard(),
            llm=_make_llm(data),
            constraints=_make_constraints(),
            style_prompt="fun",
        )
        assert result.title == "My Video"

    async def test_title_truncation(self) -> None:
        data = {"title": "A" * 200, "description": "D", "tags": [], "topics": []}
        constraints = MetadataConstraints(
            title_max_chars=10,
            description_max_chars=500,
            tags_max_count=10,
            tag_max_chars=30,
        )
        result = await metadata_generate(
            script=_make_script(),
            storyboard=_make_storyboard(),
            llm=_make_llm(data),
            constraints=constraints,
            style_prompt="x",
        )
        assert len(result.title) == 10

    async def test_tags_count_limit(self) -> None:
        data = {
            "title": "T",
            "description": "D",
            "tags": [f"tag{i}" for i in range(20)],
            "topics": [],
        }
        constraints = MetadataConstraints(
            title_max_chars=100,
            description_max_chars=500,
            tags_max_count=5,
            tag_max_chars=30,
        )
        result = await metadata_generate(
            script=_make_script(),
            storyboard=_make_storyboard(),
            llm=_make_llm(data),
            constraints=constraints,
            style_prompt="x",
        )
        assert len(result.tags) == 5

    async def test_empty_script_raises(self) -> None:
        empty = Script(title="T", description="D", scenes=[], estimated_duration_s=0)
        with pytest.raises(MetadataGenerateError, match="no scenes"):
            await metadata_generate(
                script=empty,
                storyboard=_make_storyboard(),
                llm=_make_llm({}),
                constraints=_make_constraints(),
                style_prompt="x",
            )

    async def test_invalid_json_raises(self) -> None:
        with pytest.raises(MetadataGenerateError, match="invalid JSON"):
            await metadata_generate(
                script=_make_script(),
                storyboard=_make_storyboard(),
                llm=_make_llm("bad"),
                constraints=_make_constraints(),
                style_prompt="x",
            )

    async def test_validation_failure(self) -> None:
        with pytest.raises(MetadataGenerateError, match="validation failed"):
            await metadata_generate(
                script=_make_script(),
                storyboard=_make_storyboard(),
                llm=_make_llm({"bad": True}),
                constraints=_make_constraints(),
                style_prompt="x",
            )

    async def test_description_truncation(self) -> None:
        data = {"title": "T", "description": "D" * 1000, "tags": [], "topics": []}
        constraints = MetadataConstraints(
            title_max_chars=100,
            description_max_chars=50,
            tags_max_count=10,
            tag_max_chars=30,
        )
        result = await metadata_generate(
            script=_make_script(),
            storyboard=_make_storyboard(),
            llm=_make_llm(data),
            constraints=constraints,
            style_prompt="x",
        )
        assert len(result.description) == 50

    async def test_topics_returned(self) -> None:
        data = {"title": "T", "description": "D", "tags": [], "topics": ["tech", "ai"]}
        result = await metadata_generate(
            script=_make_script(),
            storyboard=_make_storyboard(),
            llm=_make_llm(data),
            constraints=_make_constraints(),
            style_prompt="x",
        )
        assert result.topics == ["tech", "ai"]


# --- threeo_ingester tests ---


class TestThreeOIngester:
    async def test_normal_ingestion(self) -> None:
        # Create a fake module
        fake_mod = ModuleType("fake_omodul")
        fake_mod.workflow = lambda cfg: {"result": "data", "score": 0.8}  # type: ignore[attr-defined]
        sys.modules["fake_omodul"] = fake_mod

        data = {
            "topic": "test",
            "key_findings": ["f1"],
            "charts": [],
            "related_concepts": ["c1"],
            "source_omodul": "fake_omodul.workflow",
            "raw_report": {"result": "data"},
        }
        try:
            result = await threeo_ingester(
                omodul_function="fake_omodul.workflow",
                omodul_config={},
                llm=_make_llm(data),
            )
            assert result.topic == "test"
            assert result.key_findings == ["f1"]
        finally:
            del sys.modules["fake_omodul"]

    async def test_import_failure_raises(self) -> None:
        with pytest.raises(ThreeOSetupError, match="Cannot import"):
            await threeo_ingester(
                omodul_function="nonexistent_module.func",
                omodul_config={},
                llm=_make_llm({}),
            )

    async def test_invalid_function_format(self) -> None:
        with pytest.raises(ThreeOSetupError, match="Invalid"):
            await threeo_ingester(
                omodul_function="no_dot_here",
                omodul_config={},
                llm=_make_llm({}),
            )

    async def test_execution_failure(self) -> None:
        fake_mod = ModuleType("fail_omodul")
        fake_mod.workflow = lambda cfg: (_ for _ in ()).throw(RuntimeError("boom"))  # type: ignore[attr-defined]

        def _raise(cfg: Any) -> None:
            raise RuntimeError("boom")

        fake_mod.workflow = _raise  # type: ignore[attr-defined]
        sys.modules["fail_omodul"] = fake_mod
        try:
            with pytest.raises(ThreeOIngestError, match="execution failed"):
                await threeo_ingester(
                    omodul_function="fail_omodul.workflow",
                    omodul_config={},
                    llm=_make_llm({}),
                )
        finally:
            del sys.modules["fail_omodul"]

    async def test_llm_invalid_json(self) -> None:
        fake_mod = ModuleType("ok_omodul")
        fake_mod.workflow = lambda cfg: {"ok": True}  # type: ignore[attr-defined]
        sys.modules["ok_omodul"] = fake_mod
        try:
            with pytest.raises(ThreeOIngestError, match="invalid JSON"):
                await threeo_ingester(
                    omodul_function="ok_omodul.workflow",
                    omodul_config={},
                    llm=_make_llm("not json"),
                )
        finally:
            del sys.modules["ok_omodul"]

    async def test_validation_failure(self) -> None:
        fake_mod = ModuleType("val_omodul")
        fake_mod.workflow = lambda cfg: {"ok": True}  # type: ignore[attr-defined]
        sys.modules["val_omodul"] = fake_mod
        try:
            with pytest.raises(ThreeOIngestError, match="validation failed"):
                await threeo_ingester(
                    omodul_function="val_omodul.workflow",
                    omodul_config={},
                    llm=_make_llm({"incomplete": True}),
                )
        finally:
            del sys.modules["val_omodul"]

    async def test_source_omodul_set(self) -> None:
        fake_mod = ModuleType("src_omodul")
        fake_mod.workflow = lambda cfg: {"data": 1}  # type: ignore[attr-defined]
        sys.modules["src_omodul"] = fake_mod
        data = {
            "topic": "t",
            "key_findings": [],
            "charts": [],
            "related_concepts": [],
            "source_omodul": "src_omodul.workflow",
            "raw_report": {},
        }
        try:
            result = await threeo_ingester(
                omodul_function="src_omodul.workflow",
                omodul_config={},
                llm=_make_llm(data),
            )
            assert result.source_omodul == "src_omodul.workflow"
        finally:
            del sys.modules["src_omodul"]

    async def test_key_findings_list(self) -> None:
        fake_mod = ModuleType("kf_omodul")
        fake_mod.workflow = lambda cfg: {}  # type: ignore[attr-defined]
        sys.modules["kf_omodul"] = fake_mod
        data = {
            "topic": "t",
            "key_findings": ["a", "b", "c"],
            "charts": [],
            "related_concepts": [],
            "source_omodul": "kf_omodul.workflow",
            "raw_report": {},
        }
        try:
            result = await threeo_ingester(
                omodul_function="kf_omodul.workflow",
                omodul_config={},
                llm=_make_llm(data),
            )
            assert len(result.key_findings) == 3
        finally:
            del sys.modules["kf_omodul"]

    async def test_charts_field(self) -> None:
        fake_mod = ModuleType("ch_omodul")
        fake_mod.workflow = lambda cfg: {}  # type: ignore[attr-defined]
        sys.modules["ch_omodul"] = fake_mod
        data = {
            "topic": "t",
            "key_findings": [],
            "charts": [{"type": "bar"}],
            "related_concepts": [],
            "source_omodul": "ch_omodul.workflow",
            "raw_report": {},
        }
        try:
            result = await threeo_ingester(
                omodul_function="ch_omodul.workflow",
                omodul_config={},
                llm=_make_llm(data),
            )
            assert len(result.charts) == 1
        finally:
            del sys.modules["ch_omodul"]
