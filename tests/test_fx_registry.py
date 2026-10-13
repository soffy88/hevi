"""Tests for the unified FX template registry, sources, and API router.

Coverage:
- Registry data structure: add/get/filter/count/categories/sources/serialization
- Sources: talkcraft (dynamic count vs tplMeta.ts), xfade, sfx
- API: list, category/source/q filters, detail, 404s, invalid params, previews
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.fx import FXRegistry, FXTemplate, Category, Source
from hevi.fx.loader import get_registry, load_all, reset_registry
from hevi.fx.registry import template_slug, preview_mp4_path, preview_thumbnail_path
from hevi.fx.sources import load_sfx, load_talkcraft, load_xfade

REPO_ROOT = Path(__file__).resolve().parents[1]
TPL_META_PATH = REPO_ROOT / "hevi-remotion-talkcraft" / "src" / "cards" / "tplMeta.ts"
SFX_DIR = REPO_ROOT / "assets" / "audio" / "sfx"


def _tpl_meta_ids() -> list[str]:
    """Parse tplMeta.ts on the fly so the count test never goes stale."""
    text = TPL_META_PATH.read_text(encoding="utf-8")
    return re.findall(r'^\s+"([^"]+)":\s*\{\s*name:', text, re.MULTILINE)


@pytest.fixture(scope="session", autouse=True)
def _fresh_registry():
    """Reset the registry singleton around the whole session."""
    reset_registry()
    yield
    reset_registry()


# ---------------------------------------------------------------------------
# Registry data structure
# ---------------------------------------------------------------------------


class TestFXRegistry:
    def test_add_and_get(self) -> None:
        reg = FXRegistry()
        t = FXTemplate(id="test:1", name_zh="测试", category=Category.STYLE, source=Source.CUSTOM)
        reg.add(t)
        assert reg.get("test:1") is not None
        assert reg.get("test:1").name_zh == "测试"
        assert reg.get("nope") is None

    def test_add_duplicate_raises(self) -> None:
        reg = FXRegistry()
        t = FXTemplate(id="test:1", name_zh="A", category=Category.STYLE, source=Source.CUSTOM)
        reg.add(t)
        with pytest.raises(ValueError, match="Duplicate"):
            reg.add(t)

    def test_filter_by_category(self) -> None:
        reg = FXRegistry()
        reg.add(FXTemplate(id="t1", name_zh="A", category=Category.TRANSITION, source=Source.TALKCRAFT))
        reg.add(FXTemplate(id="t2", name_zh="B", category=Category.CHARACTER, source=Source.TALKCRAFT))
        reg.add(FXTemplate(id="t3", name_zh="C", category=Category.TRANSITION, source=Source.XFADE))
        results = reg.filter(category="transition")
        assert len(results) == 2
        assert all(t.category == Category.TRANSITION for t in results)

    def test_filter_by_source(self) -> None:
        reg = FXRegistry()
        reg.add(FXTemplate(id="t1", name_zh="A", category=Category.STYLE, source=Source.TALKCRAFT))
        reg.add(FXTemplate(id="t2", name_zh="B", category=Category.STYLE, source=Source.XFADE))
        results = reg.filter(source="talkcraft")
        assert len(results) == 1
        assert results[0].source == Source.TALKCRAFT

    def test_filter_by_query(self) -> None:
        reg = FXRegistry()
        reg.add(FXTemplate(id="tc:fade", name_zh="淡入淡出", category=Category.TRANSITION,
                           source=Source.TALKCRAFT, tags=["fade", "transition"]))
        reg.add(FXTemplate(id="tc:blur", name_zh="模糊", category=Category.STYLE,
                           source=Source.TALKCRAFT, tags=["blur"]))
        assert [t.id for t in reg.filter(q="FADE")] == ["tc:fade"]
        # query also matches name_zh
        assert [t.id for t in reg.filter(q="模糊")] == ["tc:blur"]

    def test_filter_combined(self) -> None:
        reg = FXRegistry()
        reg.add(FXTemplate(id="t1", name_zh="A", category=Category.TRANSITION,
                           source=Source.TALKCRAFT, tags=["fade"]))
        reg.add(FXTemplate(id="t2", name_zh="B", category=Category.TRANSITION,
                           source=Source.XFADE, tags=["wipe"]))
        reg.add(FXTemplate(id="t3", name_zh="C", category=Category.STYLE,
                           source=Source.TALKCRAFT, tags=["fade"]))
        assert [t.id for t in reg.filter(category="transition", source="talkcraft")] == ["t1"]
        assert [t.id for t in reg.filter(category="transition", q="fade")] == ["t1"]

    def test_count_categories_sources(self) -> None:
        reg = FXRegistry()
        assert reg.count() == 0
        reg.add(FXTemplate(id="t1", name_zh="A", category=Category.TRANSITION, source=Source.TALKCRAFT))
        reg.add(FXTemplate(id="t2", name_zh="B", category=Category.TRANSITION, source=Source.XFADE))
        reg.add(FXTemplate(id="t3", name_zh="C", category=Category.STYLE, source=Source.TALKCRAFT))
        assert reg.count() == 3
        assert reg.categories() == {"transition": 2, "style": 1}
        assert reg.sources() == {"talkcraft": 2, "xfade": 1}

    def test_to_dict(self) -> None:
        t = FXTemplate(
            id="test:1", name_zh="测试", category=Category.STYLE, source=Source.CUSTOM,
            source_ref="ref1", tags=["a", "b"], duration_hint=2.0,
            preview_mp4="output/fx_previews/test__1.mp4", thumbnail="output/fx_previews/test__1.jpg",
        )
        d = t.to_dict()
        assert d == {
            "id": "test:1", "name_zh": "测试", "category": "style", "source": "custom",
            "source_ref": "ref1", "tags": ["a", "b"], "duration_hint": 2.0,
            "preview_mp4": "output/fx_previews/test__1.mp4",
            "thumbnail": "output/fx_previews/test__1.jpg",
        }

    def test_category_and_source_are_str_enums(self) -> None:
        assert Category("overlay").value == "overlay"
        with pytest.raises(ValueError):
            Category("bogus")
        assert Source("sfx").value == "sfx"


class TestSlugs:
    def test_template_slug_is_filesystem_safe(self) -> None:
        assert template_slug("tc:focus-dim-spotlight") == "tc__focus-dim-spotlight"
        assert template_slug("xfade:fade") == "xfade__fade"
        assert template_slug("sfx:chime") == "sfx__chime"
        # the slug must never be able to escape the preview directory
        assert "/" not in template_slug("tc:focus-dim-spotlight")
        assert template_slug("tc:x") == "tc__x"
        assert not template_slug("tc:x").startswith("..")

    def test_preview_paths_are_under_output(self) -> None:
        mp4 = preview_mp4_path("tc:x")
        jpg = preview_thumbnail_path("tc:x")
        assert mp4.name == "tc__x.mp4"
        assert jpg.name == "tc__x.jpg"
        assert mp4.parent == jpg.parent
        assert "fx_previews" in mp4.parts


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


class TestTalkcraftSource:
    def test_count_matches_tpl_meta_file(self) -> None:
        """Number of talkcraft entries must equal the real tplMeta.ts entry count."""
        ids = _tpl_meta_ids()
        templates = load_talkcraft()
        assert len(ids) >= 80, f"tplMeta.ts unexpectedly small: {len(ids)} entries"
        assert len(templates) == len(ids)
        assert {t.source_ref for t in templates} == set(ids)

    def test_ids_are_unique_and_prefixed(self) -> None:
        templates = load_talkcraft()
        ids = [t.id for t in templates]
        assert len(ids) == len(set(ids))
        assert all(t.id.startswith("tc:") for t in templates)

    def test_fields_are_valid(self) -> None:
        for t in load_talkcraft():
            assert t.source == Source.TALKCRAFT
            assert t.category in (Category.TRANSITION, Category.CHARACTER, Category.STYLE, Category.OVERLAY)
            assert t.source_ref
            assert t.name_zh
            assert t.tags


class TestXfadeSource:
    def test_entries_exist(self) -> None:
        templates = load_xfade()
        assert len(templates) >= 10
        names = [t.source_ref for t in templates]
        assert "fade" in names
        assert len(names) == len(set(names))
        assert all(t.id.startswith("xfade:") for t in templates)
        assert all(t.category == Category.TRANSITION for t in templates)
        assert all(t.source == Source.XFADE for t in templates)


class TestSfxSource:
    def test_matches_wav_files_on_disk(self) -> None:
        wavs = sorted(p.stem for p in SFX_DIR.glob("*.wav"))
        templates = load_sfx()
        assert wavs, "expected sfx wav files in assets/audio/sfx"
        assert len(templates) == len(wavs)
        assert {t.source_ref for t in templates} == set(wavs)
        assert all(t.id.startswith("sfx:") for t in templates)
        assert all(t.category == Category.OVERLAY for t in templates)
        assert all(t.source == Source.SFX for t in templates)


class TestLoadAll:
    def test_total_and_uniqueness(self) -> None:
        reg = load_all()
        assert isinstance(reg, FXRegistry)
        tc = _tpl_meta_ids()
        wavs = sorted(p.stem for p in SFX_DIR.glob("*.wav"))
        assert reg.count() == len(tc) + len(load_xfade()) + len(wavs)
        ids = [t.id for t in reg.list_all()]
        assert len(ids) == len(set(ids))
        assert reg.count() >= 80

    def test_all_categories_are_valid(self) -> None:
        valid = {"transition", "character", "style", "overlay"}
        assert set(load_all().categories()) <= valid

    def test_category_breakdown(self) -> None:
        cats = load_all().categories()
        assert cats["character"] >= 1, "人物互动 cards must map to character"
        assert cats["transition"] > len(load_xfade()), "transition must include talkcraft 转场结构 too"

    def test_sources_breakdown(self) -> None:
        srcs = load_all().sources()
        assert set(srcs) == {"talkcraft", "xfade", "sfx"}


# ---------------------------------------------------------------------------
# API router
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestFXAPI:
    def test_list_templates(self, client: TestClient) -> None:
        r = client.get("/api/fx/templates")
        assert r.status_code == 200
        data = r.json()
        assert set(data) >= {"total", "templates", "categories", "sources"}
        assert data["total"] >= 80
        assert data["total"] == len(data["templates"])
        assert data["categories"] == client.get("/api/fx/templates").json()["categories"]

    def test_list_filter_category(self, client: TestClient) -> None:
        r = client.get("/api/fx/templates", params={"category": "character"})
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 1
        assert all(t["category"] == "character" for t in data["templates"])
        # the filter must actually narrow the set
        full = client.get("/api/fx/templates").json()["total"]
        assert data["total"] < full

    def test_list_filter_source_talkcraft(self, client: TestClient) -> None:
        r = client.get("/api/fx/templates", params={"source": "talkcraft"})
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == len(_tpl_meta_ids())
        assert all(t["source"] == "talkcraft" for t in data["templates"])

    def test_list_filter_source_xfade_and_sfx(self, client: TestClient) -> None:
        xf = client.get("/api/fx/templates", params={"source": "xfade"}).json()
        assert xf["total"] == len(load_xfade())
        assert all(t["source"] == "xfade" and t["category"] == "transition" for t in xf["templates"])

        sfx = client.get("/api/fx/templates", params={"source": "sfx"}).json()
        assert sfx["total"] == len(load_sfx())
        assert all(t["source"] == "sfx" for t in sfx["templates"])

    def test_list_search(self, client: TestClient) -> None:
        r = client.get("/api/fx/templates", params={"q": "fade"})
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 1
        for t in data["templates"]:
            blob = " ".join([t["id"], t["name_zh"], *t["tags"]]).lower()
            assert "fade" in blob

    def test_list_combined_filter(self, client: TestClient) -> None:
        r = client.get("/api/fx/templates", params={"category": "transition", "source": "xfade"})
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == len(load_xfade())
        assert all(t["category"] == "transition" and t["source"] == "xfade" for t in data["templates"])

    def test_get_template(self, client: TestClient) -> None:
        tc_id = _tpl_meta_ids()[0]
        r = client.get(f"/api/fx/templates/tc:{tc_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == f"tc:{tc_id}"
        assert data["source"] == "talkcraft"
        assert data["category"] in ("transition", "character", "style", "overlay")

    def test_get_template_not_found(self, client: TestClient) -> None:
        r = client.get("/api/fx/templates/does-not-exist")
        assert r.status_code == 404
        assert "not found" in r.json()["detail"].lower()

    def test_invalid_category_and_source(self, client: TestClient) -> None:
        r = client.get("/api/fx/templates", params={"category": "bogus"})
        assert r.status_code == 400
        assert "Invalid category" in r.json()["detail"]

        r = client.get("/api/fx/templates", params={"source": "bogus"})
        assert r.status_code == 400
        assert "Invalid source" in r.json()["detail"]

    def test_preview_returns_404_when_not_rendered(self, client: TestClient) -> None:
        """A template with no on-disk preview yields a real 404, never a placeholder."""
        reg = get_registry()
        missing = [t for t in reg.list_all()
                   if not preview_mp4_path(t.id).exists()]
        if not missing:
            pytest.skip("every template already has a preview; nothing left to probe for 404")
        t = missing[0]
        r = client.get(f"/api/fx/templates/{t.id}/preview")
        assert r.status_code == 404
        assert "preview" in r.json()["detail"].lower()

    def test_preview_returns_200_when_rendered(self, client: TestClient) -> None:
        """A template with an on-disk preview is served as video/mp4."""
        reg = get_registry()
        present = [t for t in reg.list_all() if preview_mp4_path(t.id).exists()]
        if not present:
            pytest.skip("previews not rendered yet — run scripts/fx_preview.py")
        t = present[0]
        r = client.get(f"/api/fx/templates/{t.id}/preview")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("video/mp4")
        assert len(r.content) > 1024
        assert (preview_mp4_path(t.id).read_bytes()[:64]) == (r.content[:64])

    def test_thumbnail_endpoint_follows_disk_state(self, client: TestClient) -> None:
        reg = get_registry()
        checked = 0
        absent = 0
        for t in reg.list_all():
            path = preview_thumbnail_path(t.id)
            if path.exists():
                r = client.get(f"/api/fx/templates/{t.id}/thumbnail")
                assert r.status_code == 200
                assert r.headers["content-type"].startswith("image/jpeg")
                checked += 1
            else:
                r = client.get(f"/api/fx/templates/{t.id}/thumbnail")
                assert r.status_code == 404
                absent += 1
        if checked == 0:
            pytest.skip("previews not rendered yet — run scripts/fx_preview.py")
        assert absent == 0 or checked > 0

    def test_preview_404_for_unknown_template(self, client: TestClient) -> None:
        r = client.get("/api/fx/templates/ghost-id/preview")
        assert r.status_code == 404

    def test_preview_paths_are_registry_consistent(self, client: TestClient) -> None:
        """Registry preview_* fields agree with what the API can actually serve."""
        reg = get_registry()
        for t in reg.list_all():
            if t.preview_mp4:
                r = client.get(f"/api/fx/templates/{t.id}/preview")
                assert r.status_code == 200, f"registry claims a preview but API returned {r.status_code}"
            else:
                assert not preview_mp4_path(t.id).exists()
