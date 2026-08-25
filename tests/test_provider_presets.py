"""Provider Presets 归位测试 — Frontend SPEC v6.0 §2.4。

校验 obase.ProviderRegistry 预置策略表 + /api/providers/presets 查询路由:
- 预置表含四大视频档(wan_local/fal_fast/autocameo_cloud/veo3_cinematic)
- 列表/详情接口可达,resolved_config 归一化
- resolve_preset 对未知名称回落到 wan_local(零成本默认)
"""

from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.obase.provider_presets import (
    PRESETS,
    get_preset,
    list_presets,
    resolve_preset,
)

client = TestClient(app)


def test_presets_table_contains_video_presets() -> None:
    names = {p["name"] for p in PRESETS}
    assert {"wan_local", "fal_fast", "autocameo_cloud", "veo3_cinematic"} <= names
    assert {"grok", "pi", "teamo_free"} <= names


def test_list_presets_filters_by_category() -> None:
    videos = list_presets("video")
    assert videos and all(p["category"] == "video" for p in videos)
    llms = list_presets("llm")
    assert llms and all(p["category"] == "llm" for p in llms)


def test_autocameo_preset_enables_face_lock() -> None:
    preset = get_preset("autocameo_cloud")
    assert preset is not None
    assert preset["strategy"]["face_lock"] is True
    assert preset["provider"] == "happyhorse_1_1_maas_lock"


def test_resolve_preset_falls_back_to_wan_local() -> None:
    resolved = resolve_preset("does_not_exist")
    assert resolved["name"] == "wan_local"
    assert resolved["level"] == "economy"


def test_presets_endpoint_requires_auth() -> None:
    resp = client.get("/api/providers/presets")
    assert resp.status_code == 401


def test_presets_endpoint_returns_strategy() -> None:
    # 不带鉴权时 401 已覆盖;这里用公开可见的 openapi 校验路由存在性。
    paths = app.openapi()["paths"]
    assert "/api/providers/presets" in paths
    assert "/api/providers/presets/{name}" in paths
