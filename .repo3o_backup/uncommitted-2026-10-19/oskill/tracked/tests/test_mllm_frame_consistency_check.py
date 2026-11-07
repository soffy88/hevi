"""Tests for oskill.mllm_frame_consistency_check (M6 — ≥6 tests)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from oskill._schemas import ReferenceSet
from oskill.mllm_frame_consistency_check import (
    FrameConsistencyError,
    mllm_frame_consistency_check,
)


@dataclass
class _Criteria:
    threshold: float = 0.7
    dimensions: list[str] = field(
        default_factory=lambda: ["character_appearance", "environment", "style"]
    )


def _make_mllm(score_map: dict[str, float]) -> object:
    """Mock VLM that returns a score for each image path."""

    def _mllm(messages: list, image_paths: list[str] | None = None, **_: object) -> dict:
        content = json.loads(messages[-1]["content"])
        fp = content.get("candidate_frame", "")
        score = score_map.get(fp, 0.5)
        return {"content": json.dumps({"score": score, "breakdown": {}})}

    return _mllm


def _make_ref(tmp_path: Path) -> ReferenceSet:
    char_img = tmp_path / "char_ref.png"
    char_img.write_bytes(b"\x89PNG" + b"\x00" * 32)
    env_img = tmp_path / "env_ref.png"
    env_img.write_bytes(b"\x89PNG" + b"\x00" * 32)
    return ReferenceSet(
        character_refs={"hero": char_img},
        environment_refs={"forest": env_img},
        selected_from=["s001"],
    )


class TestMllmFrameConsistencyCheck:
    async def test_single_candidate_scored(self, tmp_path: Path) -> None:
        """Single candidate → scored and returned as best_frame."""
        frame = tmp_path / "c1.png"
        frame.write_bytes(b"\x89PNG" + b"\x00" * 64)
        ref = _make_ref(tmp_path)
        mllm = _make_mllm({str(frame): 0.85})

        result = await mllm_frame_consistency_check(
            mllm=mllm,
            candidate_frames=[frame],
            reference=ref,
            criteria=_Criteria(),
        )
        assert result.best_frame == frame
        assert result.scores[str(frame)] == pytest.approx(0.85)
        assert result.passed is True

    async def test_multi_candidate_best_selected(self, tmp_path: Path) -> None:
        """Multiple candidates → highest-scoring frame chosen as best_frame."""
        frames = [tmp_path / f"c{i}.png" for i in range(3)]
        for f in frames:
            f.write_bytes(b"\x89PNG" + b"\x00" * 64)
        ref = _make_ref(tmp_path)
        scores = {str(frames[0]): 0.5, str(frames[1]): 0.9, str(frames[2]): 0.6}
        mllm = _make_mllm(scores)

        result = await mllm_frame_consistency_check(
            mllm=mllm,
            candidate_frames=frames,
            reference=ref,
            criteria=_Criteria(),
        )
        assert result.best_frame == frames[1]

    async def test_all_below_threshold_passed_false(self, tmp_path: Path) -> None:
        """All scores below threshold → passed=False."""
        frames = [tmp_path / f"low{i}.png" for i in range(2)]
        for f in frames:
            f.write_bytes(b"\x89PNG" + b"\x00" * 32)
        ref = _make_ref(tmp_path)
        mllm = _make_mllm({str(f): 0.3 for f in frames})

        result = await mllm_frame_consistency_check(
            mllm=mllm,
            candidate_frames=frames,
            reference=ref,
            criteria=_Criteria(threshold=0.7),
        )
        assert result.passed is False

    async def test_character_ref_passed_to_mllm(self, tmp_path: Path) -> None:
        """Reference set information is included in VLM prompt."""
        frame = tmp_path / "c.png"
        frame.write_bytes(b"\x89PNG" + b"\x00" * 32)
        ref = _make_ref(tmp_path)
        received: list[dict] = []

        def _mllm(messages: list, **_: object) -> dict:
            content = json.loads(messages[-1]["content"])
            received.append(content)
            return {"content": json.dumps({"score": 0.8, "breakdown": {}})}

        await mllm_frame_consistency_check(
            mllm=_mllm, candidate_frames=[frame], reference=ref, criteria=_Criteria()
        )
        assert "reference" in received[0]
        assert "hero" in received[0]["reference"]["character_refs"]

    async def test_environment_style_scoring(self, tmp_path: Path) -> None:
        """Criteria with custom dimensions accepted without error."""
        frame = tmp_path / "c.png"
        frame.write_bytes(b"\x89PNG" + b"\x00" * 32)
        ref = _make_ref(tmp_path)
        mllm = _make_mllm({str(frame): 0.75})

        criteria = _Criteria(dimensions=["environment", "lighting_style"])
        result = await mllm_frame_consistency_check(
            mllm=mllm, candidate_frames=[frame], reference=ref, criteria=criteria
        )
        assert result.passed is True

    async def test_empty_candidates_raises(self, tmp_path: Path) -> None:
        """Empty candidate_frames → FrameConsistencyError."""
        ref = _make_ref(tmp_path)

        def _mllm(**_: object) -> dict:
            return {"content": "{}"}

        with pytest.raises(FrameConsistencyError, match="empty"):
            await mllm_frame_consistency_check(
                mllm=_mllm, candidate_frames=[], reference=ref, criteria=_Criteria()
            )
