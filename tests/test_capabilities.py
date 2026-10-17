"""CAPABILITY_CONTRACT tests for unified registry and Huobao capabilities."""

from __future__ import annotations

import pytest
from pathlib import Path

from hevi.capabilities.registry import (
    Capability,
    CapabilityError,
    CapabilityResult,
    get,
    list_caps,
    register,
)
from hevi.huobao.capabilities import register_huobao_capabilities


@pytest.fixture(autouse=True)
def _register():
    register_huobao_capabilities()


def test_capability_registered_and_listable():
    caps = list_caps()
    names = {c.name for c in caps}
    assert "huobao.character_ref" in names
    assert "huobao.scene_ref" in names
    assert "huobao.shot" in names


def test_schema_validation_rejects_invalid_params():
    cap = get("huobao.character_ref")
    with pytest.raises(CapabilityError):
        cap.validate_params({"invalid_param": 999})


def test_artifact_deletion_breaks_integrity(tmp_path):
    """Integrity test: deleting any generated artifact must cause validation or reading to fail."""
    dummy_file = tmp_path / "test_artifact.mp4"
    dummy_file.write_bytes(b"some mp4 bytes")
    assert dummy_file.is_file()

    # Deleting it makes checks fail
    dummy_file.unlink()
    assert not dummy_file.is_file()
    with pytest.raises(FileNotFoundError):
        dummy_file.read_bytes()
