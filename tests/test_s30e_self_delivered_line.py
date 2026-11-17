"""S30E: a line that renders itself (ai_drama) must reach the studio contract.

``ai_drama`` runs its own pipeline and hands back a ``delivery`` block; before
the fix the studio saw an empty ``fulfill`` and reported "failed" even though
the film was on disk, so 真人短剧 / 漫剧 / 历史现场·电影感短片 never delivered.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hevi.studio import fulfill as fulfill_mod
from hevi.studio import slate as slate_mod


class _FakeManifest:
    def model_dump(self, mode: str = "json") -> dict:
        return {"artifacts": [], "verified": False}


@pytest.fixture()
def fake_manifest(monkeypatch: pytest.MonkeyPatch):
    async def _fake(paths, *, require_audio: bool = False):
        return _FakeManifest(), {"verdict": "pass", "passed": True, "violations": []}

    monkeypatch.setattr(fulfill_mod, "_verified_video_manifest", _fake)


def test_fulfill_from_delivery_maps_the_film(tmp_path: Path, fake_manifest) -> None:
    film = tmp_path / "final.mp4"
    film.write_bytes(b"stub")
    res = asyncio.run(
        fulfill_mod.fulfill_from_delivery(
            {"delivery": {"final": str(film), "duration_s": 17.7}, "line_id": "ai_drama"}
        )
    )
    assert res["status"] == "completed"
    assert res["result_video_path"] == str(film)
    assert res["artifact_manifest"]["verified"] is True
    assert res["quality"]["passed"] is True
    assert res["provenance"]


def test_fulfill_from_delivery_reports_a_missing_film(tmp_path: Path, fake_manifest) -> None:
    res = asyncio.run(
        fulfill_mod.fulfill_from_delivery(
            {"delivery": {"final": str(tmp_path / "nope.mp4")}, "line_id": "ai_drama"}
        )
    )
    assert res["status"] == "failed"
    assert "成片不存在" in res["reason"]


def test_run_slate_maps_a_self_delivered_line(tmp_path: Path, fake_manifest, monkeypatch) -> None:
    film = tmp_path / "final.mp4"
    film.write_bytes(b"stub")

    async def _fake_run(manifest, initial_data, *, run_id=None, **kwargs):
        return SimpleNamespace(
            state="completed",
            data={
                "delivery": {"final": str(film), "duration_s": 17.7},
                "line_id": "ai_drama",
                "handoff": "shortdrama",
            },
        )

    monkeypatch.setattr(slate_mod, "run_with_checkpoint", _fake_run)
    result = asyncio.run(
        slate_mod.run_slate(
            slate_mod.Slate(line_id="ai_drama", slots={"topic": "一个信使"}, execute=True),
        )
    )
    assert result.status == "completed"
    assert result.data.get("result_video_path") == str(film)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
