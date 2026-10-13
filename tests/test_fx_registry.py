"""Tests for the unified FX template registry, sources, and API router.

Coverage:
- Registry data structure: add/get/filter/count/categories/sources/serialization
- Sources: talkcraft (dynamic count vs tplMeta.ts), xfade, sfx
- API: list, category/source/q filters, detail, 404s, invalid params, previews
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.fx import FXRegistry, FXTemplate, Category, Source
from hevi.fx.loader import get_registry, load_all, reset_registry
from hevi.fx.registry import template_slug, preview_mp4_path, preview_thumbnail_path
from hevi.fx.sources import load_sfx, load_talkcraft, load_talkcraft_with_skipped, load_xfade
from hevi.fx.sources.talkcraft import TplMetaError

REPO_ROOT = Path(__file__).resolve().parents[1]
TPL_META_PATH = REPO_ROOT / "hevi-remotion-talkcraft" / "src" / "cards" / "tplMeta.ts"
SFX_DIR = REPO_ROOT / "assets" / "audio" / "sfx"
PREVIEW_DIR = REPO_ROOT / "output" / "fx_previews"
INDEX_PATH = PREVIEW_DIR / "index.json"
CONTACT_SHEET_PATH = PREVIEW_DIR / "contact_sheet.png"

FFPROBE = shutil.which("ffprobe") or "/home/soffy/.local/bin/ffprobe"
FFMPEG = shutil.which("ffmpeg") or "/home/soffy/.local/bin/ffmpeg"


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
        reg.add(
            FXTemplate(id="t1", name_zh="A", category=Category.TRANSITION, source=Source.TALKCRAFT)
        )
        reg.add(
            FXTemplate(id="t2", name_zh="B", category=Category.CHARACTER, source=Source.TALKCRAFT)
        )
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
        reg.add(
            FXTemplate(
                id="tc:fade",
                name_zh="淡入淡出",
                category=Category.TRANSITION,
                source=Source.TALKCRAFT,
                tags=["fade", "transition"],
            )
        )
        reg.add(
            FXTemplate(
                id="tc:blur",
                name_zh="模糊",
                category=Category.STYLE,
                source=Source.TALKCRAFT,
                tags=["blur"],
            )
        )
        assert [t.id for t in reg.filter(q="FADE")] == ["tc:fade"]
        # query also matches name_zh
        assert [t.id for t in reg.filter(q="模糊")] == ["tc:blur"]

    def test_filter_combined(self) -> None:
        reg = FXRegistry()
        reg.add(
            FXTemplate(
                id="t1",
                name_zh="A",
                category=Category.TRANSITION,
                source=Source.TALKCRAFT,
                tags=["fade"],
            )
        )
        reg.add(
            FXTemplate(
                id="t2",
                name_zh="B",
                category=Category.TRANSITION,
                source=Source.XFADE,
                tags=["wipe"],
            )
        )
        reg.add(
            FXTemplate(
                id="t3",
                name_zh="C",
                category=Category.STYLE,
                source=Source.TALKCRAFT,
                tags=["fade"],
            )
        )
        assert [t.id for t in reg.filter(category="transition", source="talkcraft")] == ["t1"]
        assert [t.id for t in reg.filter(category="transition", q="fade")] == ["t1"]

    def test_count_categories_sources(self) -> None:
        reg = FXRegistry()
        assert reg.count() == 0
        reg.add(
            FXTemplate(id="t1", name_zh="A", category=Category.TRANSITION, source=Source.TALKCRAFT)
        )
        reg.add(FXTemplate(id="t2", name_zh="B", category=Category.TRANSITION, source=Source.XFADE))
        reg.add(FXTemplate(id="t3", name_zh="C", category=Category.STYLE, source=Source.TALKCRAFT))
        assert reg.count() == 3
        assert reg.categories() == {"transition": 2, "style": 1}
        assert reg.sources() == {"talkcraft": 2, "xfade": 1}

    def test_to_dict(self) -> None:
        t = FXTemplate(
            id="test:1",
            name_zh="测试",
            category=Category.STYLE,
            source=Source.CUSTOM,
            source_ref="ref1",
            tags=["a", "b"],
            duration_hint=2.0,
            preview_mp4="output/fx_previews/test__1.mp4",
            thumbnail="output/fx_previews/test__1.jpg",
        )
        d = t.to_dict()
        assert d == {
            "id": "test:1",
            "name_zh": "测试",
            "category": "style",
            "source": "custom",
            "source_ref": "ref1",
            "tags": ["a", "b"],
            "duration_hint": 2.0,
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
            assert t.category in (
                Category.TRANSITION,
                Category.CHARACTER,
                Category.STYLE,
                Category.OVERLAY,
            )
            assert t.source_ref
            assert t.name_zh
            assert t.tags

    def test_no_entries_skipped_in_repo_meta(self) -> None:
        """Every card in the repo's tplMeta.ts maps to a known category."""
        templates, skipped = load_talkcraft_with_skipped()
        assert skipped == [], f"repo tplMeta.ts has unmapped categories: {skipped}"
        assert len(templates) == len(_tpl_meta_ids())

    def test_unknown_category_is_warned_and_skipped_not_dropped(
        self, tmp_path: Path, caplog
    ) -> None:
        """An unmapped category is logged + returned, never silently dropped."""
        meta = tmp_path / "tplMeta.ts"
        meta.write_text(
            "export const TPL_META = {\n"
            '  "known-card": { name: "已知卡", category: "运镜" },\n'
            '  "weird-card": { name: "未知卡", category: "未知类" },\n'
            "};\n",
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING, logger="hevi.fx.sources.talkcraft"):
            templates, skipped = load_talkcraft_with_skipped(meta)

        assert [t.source_ref for t in templates] == ["known-card"]
        assert [s["id"] for s in skipped] == ["weird-card"]
        assert skipped[0]["category_zh"] == "未知类"
        assert "未知类" in skipped[0]["reason"]
        # a warning was actually emitted naming the skipped card
        assert any("weird-card" in rec.getMessage() for rec in caplog.records)

    def test_missing_tpl_meta_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_talkcraft_with_skipped(tmp_path / "nope.ts")

    def test_unparseable_tpl_meta_raises(self, tmp_path: Path) -> None:
        meta = tmp_path / "tplMeta.ts"
        meta.write_text("// no entries here at all\n", encoding="utf-8")
        with pytest.raises(TplMetaError):
            load_talkcraft_with_skipped(meta)

    def test_registry_reports_skipped(self) -> None:
        """load_all() carries the per-source skipped map (empty for the repo)."""
        reg = load_all()
        assert reg.skipped_count() == 0
        assert reg.skipped.get("talkcraft") == []


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
        assert cats["transition"] > len(load_xfade()), (
            "transition must include talkcraft 转场结构 too"
        )

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

    def test_list_exposes_skipped_and_load_errors(self, client: TestClient) -> None:
        """The list response surfaces any dropped entries (never silent)."""
        data = client.get("/api/fx/templates").json()
        assert "skipped" in data
        assert "load_errors" in data
        # the real repo has no unmapped categories and no source load errors
        assert data["skipped"].get("talkcraft") == []
        assert data["load_errors"] == {}

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
        assert all(
            t["source"] == "xfade" and t["category"] == "transition" for t in xf["templates"]
        )

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
        assert all(
            t["category"] == "transition" and t["source"] == "xfade" for t in data["templates"]
        )

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
        missing = [t for t in reg.list_all() if not preview_mp4_path(t.id).exists()]
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
                assert r.status_code == 200, (
                    f"registry claims a preview but API returned {r.status_code}"
                )
            else:
                assert not preview_mp4_path(t.id).exists()


# ---------------------------------------------------------------------------
# Preview acceptance — real index.json + real ffprobe (no mocks)
# ---------------------------------------------------------------------------


def _ffprobe(path: Path) -> dict:
    """Run the real ffprobe and return {duration_s, width, height, fps}."""
    r = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-show_entries",
            "stream=codec_type,width,height,r_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    data = json.loads(r.stdout)
    out = {
        "duration_s": float(data.get("format", {}).get("duration") or 0.0),
        "width": None,
        "height": None,
        "fps": None,
    }
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and s.get("width"):
            out["width"], out["height"] = int(s["width"]), int(s["height"])
            num, _, den = (s.get("r_frame_rate") or "0/1").partition("/")
            out["fps"] = float(num) / float(den or 1)
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_index() -> dict:
    if not INDEX_PATH.exists():
        pytest.skip("previews not rendered yet — run scripts/fx_preview.py")
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


class TestPreviewAcceptance:
    """Validate the rendered preview corpus from index.json + fresh ffprobe."""

    def test_index_exists_and_covers_registry(self) -> None:
        data = _load_index()
        records = data["templates"]
        reg = get_registry()
        assert len(records) == reg.count(), "index.json must cover every registry entry"
        assert {r["id"] for r in records} == {t.id for t in reg.list_all()}

    def test_at_least_80_successful(self) -> None:
        data = _load_index()
        ok = [r for r in data["templates"] if r["status"] == "ok"]
        assert len(ok) >= 80, f"only {len(ok)} previews rendered successfully"
        # summary must agree with the per-record data
        assert data["summary"]["ok"] == len(ok)
        assert data["summary"]["failed"] == len(data["templates"]) - len(ok)

    def test_every_ok_record_reprobes_to_2s_portrait_30fps(self) -> None:
        """Re-run ffprobe on disk (not the stored numbers) for a sample of ok rows."""
        data = _load_index()
        ok = [r for r in data["templates"] if r["status"] == "ok"]
        assert ok, "no ok previews to validate"
        # Sample deterministically: first + last of each source (bounded ffprobe cost)
        by_src: dict[str, list[dict]] = {}
        for r in ok:
            by_src.setdefault(r["source"], []).append(r)
        sample: list[dict] = []
        for rows in by_src.values():
            sample.extend(rows[:2] + rows[-1:])
        for rec in sample:
            mp4 = REPO_ROOT / rec["mp4_path"]
            assert mp4.exists(), f"{rec['id']}: index claims mp4 but file is missing"
            info = _ffprobe(mp4)
            assert abs(info["duration_s"] - 2.0) <= 0.1, (
                f"{rec['id']}: duration {info['duration_s']:.3f}s not 2±0.1s"
            )
            assert (info["width"], info["height"]) == (540, 960), (
                f"{rec['id']}: resolution {info['width']}x{info['height']}"
            )
            assert info["fps"] is not None and abs(info["fps"] - 30) <= 0.5

    def test_ok_records_are_non_static(self) -> None:
        """Every ok preview must clear the real motion metric.

        The old 0-255 mean-diff > 0.01 check was meaningless (146/166 ok rows
        were below 0.01 normalised). The index now records
        ``motion_frame_ratio`` (fraction of frames with a real per-pixel change)
        and the acceptance rule is ``>= MOTION_FRAME_RATIO_MIN`` (0.10).
        """
        data = _load_index()
        ok = [r for r in data["templates"] if r["status"] == "ok"]
        assert ok
        threshold = data["config"]["motion_frame_ratio_min"]
        for rec in ok:
            ratio = rec.get("motion_frame_ratio")
            assert ratio is not None, f"{rec['id']}: no motion_frame_ratio recorded"
            assert ratio >= threshold, (
                f"{rec['id']}: static-looking preview (motion_frame_ratio {ratio} < {threshold})"
            )
        # the summary must agree with the per-record data
        assert data["summary"]["below_motion_min"] == 0

    def test_motion_metric_is_measured_not_written_off(self) -> None:
        """The recorded motion metric must reproduce from the file on disk.

        Re-measures ``motion_frame_ratio`` for a sample of ok rows with ffmpeg
        and checks it matches the index (so the numbers are real, not written).
        """
        data = _load_index()
        # every ok row must also carry the peak-area / mean-norm companions
        for rec in data["templates"]:
            if rec["status"] != "ok":
                continue
            assert rec.get("motion_peak_area") is not None
            assert rec.get("motion_mean_norm") is not None
            assert rec.get("max_pixel_delta") is not None

        # Recompute for a bounded sample: one per source, foreground-cropped for
        # talkcraft exactly like the renderer does.
        ok = [r for r in data["templates"] if r["status"] == "ok"]
        sample: list[dict] = []
        seen_src: set[str] = set()
        for r in ok:
            if r["source"] not in seen_src:
                seen_src.add(r["source"])
                sample.append(r)
        assert len(sample) >= 3, "expected one ok row per source to re-measure"
        for rec in sample:
            mp4 = REPO_ROOT / rec["mp4_path"]
            region = "crop=540:486:0:237" if rec["source"] == "talkcraft" else None
            vf = (f"{region}," if region else "") + (
                "tblend=all_mode=difference,signalstats,metadata=print:key=lavfi.signalstats.YMAX"
            )
            r = subprocess.run(
                [FFMPEG, "-v", "info", "-i", str(mp4), "-vf", vf, "-f", "null", "-"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=120,
            )
            ymax = [
                float(x) for x in re.findall(r"lavfi\.signalstats\.YMAX=([0-9.eE+-]+)", r.stdout)
            ]
            assert ymax, f"{rec['id']}: could not re-measure motion"
            recomputed = sum(1 for x in ymax if x > 24) / len(ymax)
            assert abs(recomputed - rec["motion_frame_ratio"]) < 0.02, (
                f"{rec['id']}: index motion_frame_ratio {rec['motion_frame_ratio']} "
                f"!= recomputed {recomputed:.4f}"
            )

    def test_ok_mp4_sha256_matches_index(self) -> None:
        data = _load_index()
        ok = [r for r in data["templates"] if r["status"] == "ok"]
        sample = ok[:3] + ok[-3:]
        for rec in sample:
            mp4 = REPO_ROOT / rec["mp4_path"]
            assert _sha256(mp4) == rec["mp4_sha256"], f"{rec['id']}: sha256 drifted"

    def test_every_ok_has_a_thumbnail_on_disk(self) -> None:
        data = _load_index()
        for rec in data["templates"]:
            if rec["status"] != "ok":
                continue
            jpg = REPO_ROOT / rec["thumbnail_path"]
            assert jpg.exists(), f"{rec['id']}: missing thumbnail {jpg}"

    def test_sfx_thumbnails_are_distinct_and_not_blank(self) -> None:
        """The 5 sfx thumbnails must be pairwise-different and non-blank.

        The R1 sfx thumbnails were 4 identical all-black frames (sha 821ae959…).
        """
        import io

        import numpy as np
        from PIL import Image

        data = _load_index()
        sfx = [r for r in data["templates"] if r["source"] == "sfx" and r["status"] == "ok"]
        assert len(sfx) >= 5, f"expected >=5 sfx previews, got {len(sfx)}"
        shas = [r["thumbnail_sha256"] for r in sfx]
        assert len(set(shas)) == len(shas), f"sfx thumbnails not unique: {shas}"
        for rec in sfx:
            jpg = REPO_ROOT / rec["thumbnail_path"]
            img = Image.open(io.BytesIO(jpg.read_bytes())).convert("L")
            arr = np.asarray(img).astype(float)
            assert arr.std() > 5.0, f"{rec['id']}: thumbnail looks blank (std {arr.std():.2f})"

    def test_sfx_previews_have_no_black_frame(self) -> None:
        """Every sampled sfx frame must be non-black (R1: most of the 2s was black)."""
        data = _load_index()
        sfx = [r for r in data["templates"] if r["source"] == "sfx" and r["status"] == "ok"]
        assert sfx
        for rec in sfx:
            mp4 = REPO_ROOT / rec["mp4_path"]
            for t in ("0.1", "0.5", "1.0", "1.5", "1.9"):
                r = subprocess.run(
                    [
                        FFMPEG,
                        "-v",
                        "info",
                        "-ss",
                        t,
                        "-i",
                        str(mp4),
                        "-frames:v",
                        "1",
                        "-vf",
                        "signalstats,metadata=print:key=lavfi.signalstats.YAVG",
                        "-f",
                        "null",
                        "-",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=60,
                )
                vals = re.findall(r"lavfi\.signalstats\.YAVG=([0-9.eE+-]+)", r.stdout)
                assert vals, f"{rec['id']}@{t}s: could not measure brightness"
                assert float(vals[0]) > 0.5, (
                    f"{rec['id']}@{t}s: frame is (near) black (YAVG {vals[0]})"
                )

    def test_contact_sheet_covers_every_category(self) -> None:
        data = _load_index()
        assert CONTACT_SHEET_PATH.exists(), "contact_sheet.png not generated"
        assert CONTACT_SHEET_PATH.stat().st_size > 1024
        counts = data["contact_sheet"].get("counts", {})
        ok_cats = {r["category"] for r in data["templates"] if r["status"] == "ok"}
        for cat in ok_cats:
            assert counts.get(cat, 0) >= 4, f"contact sheet has <4 thumbnails for {cat}"
        # sfx thumbnails get their own row so the waveform previews are visible
        assert counts.get("sfx", 0) >= 4, "contact sheet is missing the sfx waveform row"
