"""Guard tests: avcraft admission state (3O Batch 4).

Locks the reviewed admission: shotprompt deferred, timeline IO in
obase, lazy imports, package manifest, no stray IO in oskill.
"""

from __future__ import annotations

import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
AV = REPO / "hevi" / "avcraft"


def test_shotprompt_deferred_absent():
    assert not (AV / "oskill" / "shotprompt.py").exists()
    assert not (AV / "oskill" / "shotprompt.py").is_file()


def test_package_imports_without_deferred_module():
    import hevi.avcraft as av
    import hevi.avcraft.obase as obase
    import hevi.avcraft.oskill as oskill

    assert av.__manifest__["spec"] == "HELIOS_3O_SPEC_v3_0"
    assert "oskill.shotprompt" in av.__manifest__["deferred"]
    assert "shotprompt" not in oskill.__dict__
    assert hasattr(obase, "save_timeline") and hasattr(obase, "load_timeline")


def test_timeline_io_lives_in_obase():
    import hevi.avcraft.obase.timeline_io as tio
    import hevi.avcraft.oskill.timeline as tl

    assert tl.save_timeline is tio.save_timeline
    assert tl.load_timeline is tio.load_timeline
    # No file IO implementation left in the oskill tree.
    for path in (AV / "oskill").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "write_text" not in text, path
        assert "read_text" not in text, path


def test_shotprompt_call_path_fails_loudly_when_deferred(tmp_path):
    from hevi.avcraft.omodul import sequence_plan as sp

    state = {
        "table": {"shots": [{"id": "s1"}]},
        "bible": {},
        "shots": {"s1": {"status": "pending"}},
    }
    with pytest.raises(ModuleNotFoundError, match="shotprompt"):
        sp._refresh(state)


def test_enrich_compile_path_fails_loudly_when_deferred():
    from hevi.avcraft.omodul import storyboard_enrich as se

    table = {"title": "t", "shots": [{"id": "s1", "camera": {"move": "static"}}]}
    with pytest.raises(ModuleNotFoundError, match="shotprompt"):
        se.storyboard_enrich(table, catalog={"by_id": {}, "by_slug": {}})


def test_manifest_lists_admitted_modules_only():
    import hevi.avcraft as av

    listed = {m for layer in av.__manifest__["layers"].values() for m in layer}
    on_disk = set()
    for layer in ("obase", "oskill", "omodul"):
        for path in (AV / layer).glob("*.py"):
            if path.name != "__init__.py":
                on_disk.add(path.stem)
    assert listed == on_disk, (sorted(listed ^ on_disk),)
