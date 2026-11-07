"""Tests for oskill.select_reference (M5 — ≥6 tests)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from oskill._schemas import ShotFrame
from oskill.select_reference import select_reference


@dataclass
class _Shot:
    shot_id: str
    description: str = "a scene"


def _make_llm(response: dict) -> object:
    """Return a minimal mock LLM callable."""

    def _llm(messages: list, **_: object) -> dict:
        return {"content": json.dumps(response)}

    return _llm


def _make_frame(
    shot_id: str,
    index: int,
    chars: list[str],
    env: str,
    tmp_path: Path,
) -> ShotFrame:
    p = tmp_path / f"{shot_id}.png"
    p.write_bytes(b"\x89PNG" + b"\x00" * 32)
    return ShotFrame(
        shot_id=shot_id,
        scene_id=f"scene_{index}",
        timeline_index=index,
        frame_path=p,
        characters_present=chars,
        environment_id=env,
    )


class TestSelectReference:
    async def test_single_character_single_environment(self, tmp_path: Path) -> None:
        """Single char + env present in history → ReferenceSet populated."""
        frame = _make_frame("s001", 0, ["hero"], "forest", tmp_path)
        llm = _make_llm(
            {
                "character_refs": {"hero": str(frame.frame_path)},
                "environment_refs": {"forest": str(frame.frame_path)},
                "selected_from": ["s001"],
            }
        )
        result = await select_reference(
            llm=llm,
            current_shot=_Shot("s002"),
            timeline_history=[frame],
            characters=["hero"],
            environments=["forest"],
        )
        assert "hero" in result.character_refs
        assert "forest" in result.environment_refs
        assert "s001" in result.selected_from

    async def test_multi_character_cross_shots(self, tmp_path: Path) -> None:
        """Multiple characters found across different shots."""
        f1 = _make_frame("s001", 0, ["hero"], "city", tmp_path)
        f2 = _make_frame("s002", 1, ["villain"], "city", tmp_path)
        llm = _make_llm(
            {
                "character_refs": {
                    "hero": str(f1.frame_path),
                    "villain": str(f2.frame_path),
                },
                "environment_refs": {"city": str(f1.frame_path)},
                "selected_from": ["s001", "s002"],
            }
        )
        result = await select_reference(
            llm=llm,
            current_shot=_Shot("s003"),
            timeline_history=[f1, f2],
            characters=["hero", "villain"],
            environments=["city"],
        )
        assert set(result.character_refs.keys()) == {"hero", "villain"}
        assert len(result.selected_from) == 2

    async def test_character_not_in_history_absent_from_result(self, tmp_path: Path) -> None:
        """Character that never appeared → not in character_refs (needs generation)."""
        frame = _make_frame("s001", 0, ["hero"], "forest", tmp_path)
        llm = _make_llm(
            {
                "character_refs": {"hero": str(frame.frame_path)},
                "environment_refs": {},
                "selected_from": ["s001"],
            }
        )
        result = await select_reference(
            llm=llm,
            current_shot=_Shot("s002"),
            timeline_history=[frame],
            characters=["hero", "new_char"],
            environments=["forest"],
        )
        assert "hero" in result.character_refs
        assert "new_char" not in result.character_refs

    async def test_environment_reuse_same_id(self, tmp_path: Path) -> None:
        """Same environment appears multiple times → best frame selected."""
        f1 = _make_frame("s001", 0, ["hero"], "forest", tmp_path)
        f2 = _make_frame("s002", 1, ["hero"], "forest", tmp_path)
        llm = _make_llm(
            {
                "character_refs": {},
                "environment_refs": {"forest": str(f2.frame_path)},
                "selected_from": ["s002"],
            }
        )
        result = await select_reference(
            llm=llm,
            current_shot=_Shot("s003"),
            timeline_history=[f1, f2],
            characters=[],
            environments=["forest"],
        )
        assert result.environment_refs["forest"] == f2.frame_path

    async def test_empty_timeline_returns_empty_refs(self, tmp_path: Path) -> None:
        """Empty timeline → empty ReferenceSet without LLM call."""
        called = []

        def _llm(**_: object) -> dict:
            called.append(1)
            return {"content": "{}"}

        result = await select_reference(
            llm=_llm,
            current_shot=_Shot("s001"),
            timeline_history=[],
            characters=["hero"],
            environments=["forest"],
        )
        assert result.character_refs == {}
        assert result.environment_refs == {}
        assert called == []  # no LLM call needed

    async def test_llm_semantic_matching_called(self, tmp_path: Path) -> None:
        """LLM is called with candidates and returns structured response."""
        frame = _make_frame("s001", 0, ["hero"], "forest", tmp_path)
        received_messages: list = []

        def _llm(messages: list, **_: object) -> dict:
            received_messages.extend(messages)
            return {
                "content": json.dumps(
                    {
                        "character_refs": {"hero": str(frame.frame_path)},
                        "environment_refs": {},
                        "selected_from": ["s001"],
                    }
                )
            }

        await select_reference(
            llm=_llm,
            current_shot=_Shot("s002"),
            timeline_history=[frame],
            characters=["hero"],
            environments=[],
        )
        assert len(received_messages) == 2
        user_content = json.loads(received_messages[1]["content"])
        assert "candidates" in user_content
        assert user_content["needed_characters"] == ["hero"]
