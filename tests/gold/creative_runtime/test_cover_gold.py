"""Gold behaviour for the cover visual asset runtime."""

from __future__ import annotations

import hashlib
from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image

from hevi.creative.omodul import CoverModule
from hevi.obase.creative import CoverBrief


def _brief():
    return CoverBrief(
        project_id=uuid4(),
        title="Owned Cover",
        visual_concept="winter harbour",
        palette=("#1b2a41", "#f2f2f2"),
    )


def _png(brief: CoverBrief) -> tuple[bytes, str]:
    image = Image.new("RGB", (32, 32), brief.palette[0])
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue(), "image/png"


def test_cover_produces_verified_artifact(tmp_path) -> None:
    brief = _brief()
    target = tmp_path / "cover.png"
    generation = CoverModule().create(brief=brief, provider=_png, output_path=target)
    assert target.is_file()
    assert generation.artifact.sha256 == hashlib.sha256(target.read_bytes()).hexdigest()
    assert generation.artifact.source_ids == (brief.object_id,)
    assert any(ref.ref_type == "COVER_ARTIFACT" for ref in generation.artifact.provenance)
    with Image.open(target) as reopened:
        reopened.load()
        assert reopened.format == "PNG"


def test_cover_rejects_empty_provider_result() -> None:
    with pytest.raises(ValueError, match="COVER_EMPTY_PROVIDER_RESULT"):
        CoverModule().create(brief=_brief(), provider=lambda _: (b"", "image/png"))
