"""S25：对话建画布 / 费用预估 / 备份 / 报错 / 素材 / 模板 / 技能 / 资产库 / 插件契约。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from hevi.canvas import (
    agent_build,
    backup_s25,
    diagnostics_s25,
    library_s25,
    material_ops_s25,
    plugin_contract_s25,
    pricing_s25,
    skills_s25,
    templates_s25,
)
from hevi.canvas.validation import EDGE_MATRIX


def _edges_legal(graph: dict) -> list[str]:
    types = {n["node_id"]: n["node_type"] for n in graph["nodes"]}
    bad = []
    for edge in graph["edges"]:
        src, dst = edge["from_node_id"], edge["to_node_id"]
        if types.get(dst) not in EDGE_MATRIX.get(types.get(src, ""), frozenset()):
            bad.append(f"{types.get(src)}->{types.get(dst)}")
    return bad


# ── 对话建画布 ──────────────────────────────────────────────────────────────


def test_plan_is_deterministic_and_edges_are_legal() -> None:
    a = agent_build.build_plan("深夜便利店，店员发现常客的小票停在五年前", format_id="live_drama")
    b = agent_build.build_plan("深夜便利店，店员发现常客的小票停在五年前", format_id="live_drama")
    assert a["confirm_token"] == b["confirm_token"]
    assert a["schema"] == agent_build.PLAN_SCHEMA
    assert a["numbers"]["nodes"] == len(a["nodes"])
    assert a["numbers"]["edges"] == len(a["edges"])
    assert a["steps"] and all(s["node_keys"] for s in a["steps"])
    graph = agent_build.apply_plan(a, confirm_token=a["confirm_token"])
    assert _edges_legal(graph) == []
    assert {n["node_id"] for n in graph["nodes"]} >= {"script", "assembly", "narration"}


def test_plan_patch_changes_only_target_and_token() -> None:
    plan = agent_build.build_plan("为什么飞机能飞起来", format_id="explainer")
    old_token = plan["confirm_token"]
    patched = agent_build.patch_plan_node(
        plan, "shot1_video", {"config": {"duration_s": 9, "provider": "wan_2_7"}}
    )
    assert patched["confirm_token"] != old_token
    assert patched["nodes"][0]["config"] == plan["nodes"][0]["config"]
    assert patched["shots"][0]["duration_s"] == 9
    assert patched["estimate"]["total_cny"] >= 0.0
    with pytest.raises(ValueError):
        agent_build.patch_plan_node(plan, "nope", {})


def test_apply_rejects_stale_token_and_prunes_selection() -> None:
    plan = agent_build.build_plan("一个小机器人第一次学会走路", format_id="animation")
    with pytest.raises(ValueError):
        agent_build.apply_plan(plan, confirm_token="stale")
    partial = agent_build.apply_plan(
        plan, confirm_token=plan["confirm_token"], selected_nodes=["script", "storyboard"]
    )
    ids = {n["node_id"] for n in partial["nodes"]}
    assert ids == {"script", "storyboard"}
    assert partial["edges"] == []


def test_plan_format_fallbacks_and_errors() -> None:
    with pytest.raises(ValueError):
        agent_build.build_plan("   ")
    with pytest.raises(ValueError):
        agent_build.build_plan("x", format_id="does-not-exist")
    auto = agent_build.build_plan("把这段访谈剪成三条短视频", slots={"media_path": "a.mp4"})
    assert auto["format"] == "material_cut"


# ── 费用预估（与 S22 同源） ─────────────────────────────────────────────────


def test_estimate_prices_video_from_same_table() -> None:
    from hevi.studio import craft_s22

    graph = {
        "nodes": [
            {"node_id": "v1", "node_type": "video", "config": {"provider": "wan_2_7", "duration_s": 5}},
            {"node_id": "i1", "node_type": "image", "config": {"prompt": "x"}},
            {"node_id": "a1", "node_type": "audio", "config": {"provider": "edge_tts"}},
            {"node_id": "m1", "node_type": "video", "config": {"tool_id": "nle.project"}},
        ]
    }
    est = pricing_s25.estimate_graph(graph)
    expected = round(craft_s22.model_price_cny_per_second("wan_2_7") * 5, 3)
    assert est["total_cny"] == expected
    assert est["unpriced_nodes"] == 1
    assert est["unpriced"][0]["node_id"] == "i1"
    assert pricing_s25.quote_text(est, seconds=5, shots=1).startswith("费用预估")


def test_estimate_matches_ledger_within_ten_percent(tmp_path, monkeypatch) -> None:
    from hevi.studio import craft_ledger

    monkeypatch.setenv("HEVI_CRAFT_LEDGER_PATH", str(tmp_path / "ledger.jsonl"))
    graph = {"nodes": [{"node_id": "v1", "node_type": "video", "config": {"provider": "wan_2_7", "duration_s": 5}}]}
    est = pricing_s25.estimate_graph(graph)
    craft_ledger.record(
        {"kind": "quote", "plan_id": "p1", "format": "explainer", "shot": 1,
         "route": "generation", "model": "wan_2_7", "seconds": 5, "cny": est["total_cny"]}
    )
    cmp = pricing_s25.compare_with_ledger("p1", est)
    assert cmp and abs(cmp["delta_pct"]) <= 10.0
    assert pricing_s25.compare_with_ledger("missing", est) is None


# ── 备份导出 / 导入 ─────────────────────────────────────────────────────────


def _graph_for_backup() -> dict:
    return {
        "name": "备份测试",
        "nodes": [
            {"node_id": "a", "node_type": "script", "config": {"content": "x"}},
            {"node_id": "b", "node_type": "image", "config": {"prompt": "y"}},
            {"node_id": "c", "node_type": "video", "config": {"provider": "wan_2_7"}},
        ],
        "edges": [
            {"edge_id": "e1", "from_node_id": "a", "to_node_id": "b", "kind": "data"},
            {"edge_id": "e2", "from_node_id": "b", "to_node_id": "c", "kind": "data"},
        ],
    }


def test_backup_roundtrip_and_tamper_detection() -> None:
    payload = backup_s25.export_backup(_graph_for_backup())
    report = backup_s25.verify_backup(payload)
    assert report["ok"] and report["checksum_ok"]
    assert report["stats"]["nodes"] == 3
    imported = backup_s25.import_backup(payload)
    assert len(imported["nodes"]) == 3
    tampered = json.loads(json.dumps(payload))
    tampered["graph"]["nodes"][0]["config"]["content"] = "改了"
    assert not backup_s25.verify_backup(tampered)["ok"]
    with pytest.raises(ValueError):
        backup_s25.import_backup(tampered)
    # 显式允许校验和不一致时仍要做结构校验
    backup_s25.import_backup(tampered, allow_checksum_mismatch=True)


def test_backup_rejects_illegal_edges() -> None:
    graph = _graph_for_backup()
    graph["edges"].append({"edge_id": "bad", "from_node_id": "a", "to_node_id": "a"})
    report = backup_s25.verify_backup(backup_s25.export_backup(graph))
    assert not report["ok"]
    codes = {f["code"] for f in report["findings"]}
    assert "illegal_edge" in codes


# ── 报错可读化 ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("error", "category"),
    [
        ("HTTP 429 Too Many Requests", "rate_limit"),
        ("401 Unauthorized: invalid api key sk-abcdefgh12345", "auth"),
        ("ReadTimeout: upstream timed out", "timeout"),
        ("insufficient credit balance", "quota"),
        ("no such file: /data/x.png", "media"),
        ("502 Bad Gateway from provider", "upstream"),
        ("ValueError: something odd", "unknown"),
    ],
)
def test_explain_failure_categories(error: str, category: str) -> None:
    out = diagnostics_s25.explain_failure(error, node_type="video")
    assert out["category"] == category
    assert out["title"] and out["action"]
    assert "sk-" not in out["raw"]


def test_redact_urls_and_bearer() -> None:
    text = diagnostics_s25.redact(
        "GET https://api.example.com/v1/gen?key=SECRET&x=1 failed; Authorization: Bearer abcdef12345"
    )
    assert "SECRET" not in text and "abcdef12345" not in text
    assert "https://api.example.com/v1/gen?…" in text


def test_annotate_graph_marks_failed_nodes() -> None:
    graph = {
        "nodes": [
            {"node_id": "a", "node_type": "video", "status": "failed",
             "config": {"prompt": "x"}, "review": {"result": "fail", "reasons": ["429 rate limit"]}},
            {"node_id": "b", "node_type": "image", "status": "completed", "config": {}},
        ]
    }
    out = diagnostics_s25.annotate_graph(graph)
    a = next(n for n in out["nodes"] if n["node_id"] == "a")
    b = next(n for n in out["nodes"] if n["node_id"] == "b")
    assert a["diagnostic"]["category"] == "rate_limit" and a["diagnostic"]["retryable"]
    assert "diagnostic" not in b


# ── 模板（带版本） ──────────────────────────────────────────────────────────


def test_templates_versions_and_swap(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HEVI_CANVAS_TEMPLATE_DIR", str(tmp_path / "templates"))
    builtins = templates_s25.ensure_builtin_templates()
    assert len(builtins) >= 7
    graph = _graph_for_backup()
    made = templates_s25.create_template(
        template_id="my-flow", name="我的流程", graph=graph, format_id="explainer"
    )
    assert made["version"] == 1
    v2 = templates_s25.publish_version("my-flow", graph, note="换素材")
    assert v2["version"] == 2
    old = templates_s25.get_template("my-flow", 1)
    assert old["version"] == 1
    slot = next(s for s in old["slots"] if s["field"] == "prompt")
    applied = templates_s25.apply_template("my-flow", {slot["key"]: "新的画面提示"}, version=1)
    assert applied["template_version"] == 1
    new_cfg = next(n for n in applied["nodes"] if n["node_id"] == "b")["config"]
    assert new_cfg["prompt"] == "新的画面提示"
    diff = templates_s25.diff_versions("my-flow", 1, 2)
    assert diff["summary"].startswith("v1 → v2")
    with pytest.raises(ValueError):
        templates_s25.apply_template("my-flow", {"nope": 1})
    with pytest.raises(ValueError):
        templates_s25.get_template("my-flow", 99)


# ── 素材加工 ────────────────────────────────────────────────────────────────


def _png(path: Path, size=(320, 240)) -> Path:
    Image.new("RGB", size, (40, 90, 160)).save(path)
    return path


def test_material_ops_offline(tmp_path: Path) -> None:
    src = _png(tmp_path / "src.png")
    cropped = material_ops_s25.crop(src, {"x": 10, "y": 20, "w": 100, "h": 50}, out_dir=tmp_path)
    assert (cropped["width"], cropped["height"]) == (100, 50)
    split = material_ops_s25.split_grid(src, cols=4, rows=3, out_dir=tmp_path)
    assert split["count"] == 12 and all(Path(t["path"]).is_file() for t in split["tiles"])
    annotated = material_ops_s25.annotate(
        src,
        [{"type": "box", "x": 5, "y": 5, "x2": 60, "y2": 60}, {"type": "text", "x": 20, "y": 80, "text": "注意"}],
        out_dir=tmp_path,
    )
    assert Path(annotated["path"]).is_file() and annotated["marks"] == 2
    assert material_ops_s25.inpaint_availability()["available"] is False
    caps = material_ops_s25.capabilities()
    assert caps["crop"]["available"] and caps["inpaint"]["mode"] == "coming_soon"


# ── 技能 / 资产库 / 插件契约 ────────────────────────────────────────────────


def test_skills_versions_and_toggle(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HEVI_CANVAS_SKILLS_STATE", str(tmp_path / "state.json"))
    items = skills_s25.list_skills()
    ids = {i["id"] for i in items}
    assert {"two-shot-storyboard", "interview-outline", "rights-log"} <= ids
    skill = skills_s25.get_skill("two-shot-storyboard")
    assert skill["version"] == 1 and "双镜头" in skill["content"]
    assert len(skill["sha256"]) == 64
    skills_s25.set_enabled("rights-log", False)
    assert "rights-log" not in {i["id"] for i in skills_s25.list_skills(include_disabled=False)}
    skills_s25.set_enabled("rights-log", True)
    assert len(skills_s25.skill_manifest()["skills"]) == 3


def test_library_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HEVI_CANVAS_LIBRARY_DIR", str(tmp_path / "lib"))
    repo = Path(__file__).resolve().parents[1]
    media = repo / "output" / "canvas_s25" / "test-library.png"
    media.parent.mkdir(parents=True, exist_ok=True)
    _png(media)
    try:
        item = library_s25.add_item(
            "u1", title="首帧", path=str(media), kind="image", source_graph="g", source_node="n"
        )
        assert library_s25.list_items("u1")[0]["id"] == item["id"]
        assert library_s25.list_items("u2") == []
        assert library_s25.remove_item("u1", item["id"])
        assert library_s25.list_items("u1") == []
        with pytest.raises(ValueError):
            library_s25.add_item("u1", title="越界", path="/etc/passwd")
    finally:
        media.unlink(missing_ok=True)


def test_plugin_contract() -> None:
    manifest = {
        "schema": plugin_contract_s25.PLUGIN_SCHEMA,
        "id": "my.node",
        "version": "1.0.0",
        "node_types": ["video"],
        "permissions": ["fs.read"],
        "timeout_s": 30,
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
    }
    ok = plugin_contract_s25.validate_manifest(manifest)
    assert ok["permissions"] == ["fs.read"]
    with pytest.raises(plugin_contract_s25.PluginContractError):
        plugin_contract_s25.validate_manifest({**manifest, "permissions": ["root"]})
    with pytest.raises(plugin_contract_s25.PluginContractError):
        plugin_contract_s25.validate_manifest({**manifest, "permissions": ["paid_generation"]})
    assert plugin_contract_s25.contract_doc()["status"] == "internal_only"


async def test_pg_node_store_bulk_sync(monkeypatch) -> None:
    import uuid
    from contextlib import asynccontextmanager

    from hevi.canvas import node_store as ns

    calls: list[tuple[str, int]] = []

    class Conn:
        async def executemany(self, sql, rows):
            calls.append((sql.split()[0] + " " + sql.split()[1], len(rows)))

        async def fetch(self, sql, *params):
            return []

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield Conn()

    store = ns.PgNodeStore(Pool())

    async def _empty(*args, **kwargs):
        return {}

    monkeypatch.setattr(store, "load_nodes", _empty)

    async def _rows(*args, **kwargs):
        return [{"id": uuid.uuid4(), "node_key": f"n{i}"} for i in range(500)]

    monkeypatch.setattr(ns, "query", _rows)
    nodes = [
        {"node_id": f"n{i}", "node_type": "text", "config": {"content": str(i)},
         "position": {"x": i, "y": 0}} for i in range(500)
    ]
    edges = [
        {"edge_id": f"e{i}", "from_node_id": f"n{i}", "to_node_id": f"n{i+1}", "kind": "data"}
        for i in range(499)
    ]
    out = await store.sync_graph(str(uuid.uuid4()), nodes, edges)
    assert out["nodes"] == 500
    inserts = [c for c in calls if c[0].startswith("INSERT")]
    assert inserts and inserts[0][1] == 500
    assert any(c[1] == 499 for c in inserts)
