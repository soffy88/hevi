"""入口测试 —— fx registry 注册 / API 端点 / CLI。"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.fx_sources import stickdir as fx_src
from hevi.layer4_legacy.stickdir import styles, whitelist

COPY = (
    "很多人以为效率来自更努力。其实真正的效率来自更少的选择。"
    "当选项变多，大脑每一步都要重新评估，决策成本会吃掉你全部的时间。"
    "顶尖的人不是做得更多，而是把不重要的事情直接删掉。"
    "删掉一件事，胜过完成三件事。所以别再问怎么才能做得更快，先问这件事到底该不该做。"
)


# ---------------------------------------------------------------------------
# fx registry
# ---------------------------------------------------------------------------


def test_fx_registry_five_stickman_styles():
    rows = fx_src.templates_as_dicts()
    assert len(rows) == 5
    assert {r["source_ref"] for r in rows} == set(whitelist.STYLE)
    for r in rows:
        assert r["id"].startswith("stickdir:")
        assert r["category"] == "style"
        assert r["source"] == "stickdir"
        assert "stickman" in r["tags"]
        assert r["name_zh"]


def test_fx_registry_ids_unique_and_follow_convention():
    ids = [r["id"] for r in fx_src.templates_as_dicts()]
    assert len(ids) == len(set(ids))
    # 约定: <source>:<slug>
    assert all(i.split(":", 1)[0] == "stickdir" for i in ids)


def test_load_stickdir_returns_entries():
    assert len(fx_src.load_stickdir()) == 5


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def _client():
    fastapi_testclient = pytest.importorskip("fastapi.testclient")
    from hevi.api.routers.stickdir import router

    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router, prefix="/api")
    return fastapi_testclient.TestClient(app)


def test_api_options():
    c = _client()
    r = c.get("/api/stickdir/options")
    assert r.status_code == 200
    body = r.json()
    assert set(body["aspect"]) == {"9:16", "16:9"}
    assert {s["key"] for s in body["style"]} == set(whitelist.STYLE)


def test_api_proposal_ok():
    c = _client()
    r = c.post("/api/stickdir/proposal", json={"copy": COPY, "aspect": "9:16", "style": "1B", "duration": 30})
    assert r.status_code == 200
    body = r.json()
    assert body["proposal"]["schema_version"].startswith("stickdir/")
    assert body["proposal"]["self_checks"]["fabrication_violations"] == []
    assert "定时分镜表" in body["markdown"]


def test_api_proposal_missing_aspect_is_422():
    c = _client()
    r = c.post("/api/stickdir/proposal", json={"copy": COPY, "style": "1B"})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_writes_proposal(tmp_path: Path):
    from hevi.layer4_legacy.stickdir import cli

    copy_file = tmp_path / "copy.txt"
    copy_file.write_text(COPY, encoding="utf-8")
    rc = cli.main([
        "--copy-file", str(copy_file), "--aspect", "9:16", "--duration", "30",
        "--style", "1B", "--out", str(tmp_path / "out"), "--no-llm",
    ])
    assert rc == 0
    assert (tmp_path / "out" / "proposal.json").is_file()
    assert (tmp_path / "out" / "proposal.md").is_file()
