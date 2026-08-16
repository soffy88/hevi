"""Round 3d(dramaclaw 二轮对照)测试: 能力契约 / 资产包导出 / 图片池。"""

from __future__ import annotations

from pathlib import Path

from hevi.assembly.export_pack_workflow import (
    ExportPackConfig,
    ExportPackInput,
    build_export_manifest,
    build_zip,
    export_pack_workflow,
    write_manifest,
)
from hevi.canvas.skill_contract import (
    CAPABILITIES,
    MEDIA_TYPES,
    SkillCapabilities,
    SkillDefinition,
    SkillInputSpec,
    SkillOutputSpec,
    SkillRegistry,
    validate_skill_definition,
)
from hevi.director.image_pool import (
    ImagePool,
    PoolImage,
    content_hash,
    pick_best_for_beat,
)

# ---- 能力契约 ----

def test_capabilities_defaults_minimal():
    caps = SkillCapabilities()
    assert all(getattr(caps, cap) is False for cap in CAPABILITIES)


def test_validate_apply_requires_propose():
    skill = SkillDefinition(
        skill_id="bad-apply",
        provider="tool",
        capabilities=SkillCapabilities(can_apply_canvas_patch=True),
        outputs=[
            SkillOutputSpec(role="out", label="x", media_type="node_patch", node_type="video")
        ],
    )
    issues = validate_skill_definition(skill)
    assert any("can_apply_canvas_patch 必须伴随" in i for i in issues)


def test_validate_apply_requires_patch_output():
    skill = SkillDefinition(
        skill_id="apply-no-patch",
        provider="tool",
        capabilities=SkillCapabilities(
            can_propose_canvas_patch=True, can_apply_canvas_patch=True
        ),
        inputs=[SkillInputSpec(role="in", label="x")],
        outputs=[
            SkillOutputSpec(role="out", label="x", media_type="image", node_type="image")
        ],
    )
    issues = validate_skill_definition(skill)
    assert any("无 node_patch/graph_patch 输出" in i for i in issues)


def test_validate_read_canvas_requires_input():
    skill = SkillDefinition(
        skill_id="read-no-input",
        provider="agent",
        capabilities=SkillCapabilities(can_read_canvas=True),
    )
    issues = validate_skill_definition(skill)
    assert any("读画布但无输入规格" in i for i in issues)


def test_registry_register_and_query():
    registry = SkillRegistry()
    good = SkillDefinition(
        skill_id="video-gen",
        provider="workflow",
        capabilities=SkillCapabilities(
            can_read_canvas=True,
            can_propose_canvas_patch=True,
            can_apply_canvas_patch=True,
        ),
        inputs=[SkillInputSpec(role="canvas", label="画布", required=True)],
        outputs=[
            SkillOutputSpec(role="patch", label="改图", media_type="graph_patch", node_type="graph")
        ],
    )
    assert registry.register(good) == []
    assert registry.get("video-gen") is good
    assert registry.with_capability("can_apply_canvas_patch") == [good]
    assert registry.register(SkillDefinition(skill_id="bad", provider="nope")) != []


def test_output_media_types_enum():
    skill = SkillDefinition(
        skill_id="bad-media",
        provider="tool",
        outputs=[SkillOutputSpec(role="o", label="x", media_type="nope", node_type="x")],
    )
    assert any("bad media_type" in i for i in validate_skill_definition(skill))
    assert "node_patch" in MEDIA_TYPES


# ---- 资产包导出 ----

def _touch(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(p.name.encode("utf-8"))  # 不同文件不同内容(哈希可区分)
    return p


def test_manifest_collects_and_missing(tmp_path):
    cfg = ExportPackConfig(
        out_dir=tmp_path, project_name="Acme", episode_no=1, zip_path=tmp_path / "e1.zip"
    )
    inp = ExportPackInput(
        video=_touch(tmp_path / "video.mp4"),
        srt=_touch(tmp_path / "sub.srt"),
    )
    manifest = build_export_manifest(cfg, inp)
    arcs = [e["arc"] for e in manifest.entries]
    assert "video.mp4" in arcs and "subtitles.srt" in arcs
    assert any("shot_list.json" in m for m in manifest.missing)  # 缺项记 missing


def test_build_zip_and_manifest(tmp_path):
    cfg = ExportPackConfig(
        out_dir=tmp_path, project_name="Acme", episode_no=1, zip_path=tmp_path / "e1.zip"
    )
    inp = ExportPackInput(video=_touch(tmp_path / "video.mp4"), srt=_touch(tmp_path / "sub.srt"))
    manifest = build_export_manifest(cfg, inp)
    mp = write_manifest(manifest, tmp_path / "manifest.json")
    assert mp.exists()
    zf = build_zip(manifest, tmp_path / "e1.zip")
    assert zf.exists()
    import zipfile

    with zipfile.ZipFile(zf) as z:
        names = z.namelist()
    assert "video.mp4" in names and "manifest.json" in names


def test_export_pack_workflow(tmp_path):
    cfg = ExportPackConfig(
        out_dir=tmp_path, project_name="Acme", episode_no=2, zip_path=tmp_path / "e2.zip"
    )
    inp = ExportPackInput(
        video=_touch(tmp_path / "video.mp4"),
        stylepack_ref="国风水墨 v3",
        extra_files={"notes.md": _touch(tmp_path / "notes.md")},
    )
    res = __import__("asyncio").run(export_pack_workflow(cfg, inp, tmp_path))
    assert res["status"] == "completed"
    assert res["zip_path"] is not None
    assert (tmp_path / "manifest.json").exists()


def test_export_pack_workflow_no_entries(tmp_path):
    cfg = ExportPackConfig(
        out_dir=tmp_path, project_name="A", episode_no=1, zip_path=tmp_path / "x.zip"
    )
    res = __import__("asyncio").run(export_pack_workflow(cfg, ExportPackInput(), tmp_path))
    assert res["status"] == "completed"
    assert res["zip_path"] is None  # 无产物不产出空 zip


# ---- 图片池 ----

def test_pool_dedupe_by_content_hash(tmp_path):
    pool = ImagePool()
    a = _touch(tmp_path / "a.png")
    pool.add(PoolImage(path=a, pool_id="p1", content_hash=content_hash(a), beat_id="b1"))
    added = pool.add(PoolImage(path=a, pool_id="p2", content_hash=content_hash(a), beat_id="b1"))
    assert added is False  # 同内容不重复入池
    assert len(pool.images) == 1


def test_pool_by_beat_and_pick(tmp_path):
    pool = ImagePool()
    a = _touch(tmp_path / "a.png")
    b = _touch(tmp_path / "b.png")
    pool.add(PoolImage(path=a, pool_id="p1", content_hash=content_hash(a), beat_id="b1"))
    pool.add(PoolImage(path=b, pool_id="p2", content_hash=content_hash(b), beat_id="b1"))
    assert len(pool.by_beat("b1")) == 2
    best = pick_best_for_beat(pool, "b1", coverage={"p1": 0.9, "p2": 0.5})
    assert best is not None and best.pool_id == "p1"
    assert pick_best_for_beat(pool, "nope") is None


def test_pool_roundtrip_json(tmp_path):
    pool = ImagePool()
    a = _touch(tmp_path / "a.png")
    pool.add(
        PoolImage(
            path=a, pool_id="p1", content_hash=content_hash(a),
            beat_id="b1", grid="3x3", row=1, col=2,
        )
    )
    p = tmp_path / "pool.json"
    pool.save(p)
    loaded = ImagePool.load(p)
    assert len(loaded.images) == 1
    assert loaded.images[0].grid == "3x3" and loaded.images[0].row == 1
