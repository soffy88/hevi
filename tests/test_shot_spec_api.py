"""ShotSpec API 单测(GAP_PLAN §2 W1):GET/PATCH/PUT + 校验 422 + 404。

用 FastAPI TestClient,把 ``get_repository`` 换成内存假仓库(不碰真 PG),
鉴权用 ``get_current_user`` override。真实注册表/manifest 做取值校验。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.api.routers.tasks import get_repository
from hevi.auth.dependencies import get_current_user

TASK_ID = uuid4()
OTHER_TASK_ID = uuid4()
USER = {"id": "spec-user"}


class _FakeRepo:
    """最小内存 shot 存储:只实现本 router 用到的 3 个方法。"""

    def __init__(self, task_id: UUID, shot_count: int = 3) -> None:
        self.tasks: dict[str, dict[str, Any]] = {
            str(task_id): {"id": str(task_id), "user_id": USER["id"]}
        }
        self.shots: dict[str, list[dict[str, Any]]] = {
            str(task_id): [
                {
                    "id": uuid4(),
                    "task_id": str(task_id),
                    "shot_index": i,
                    "status": "pending",
                    "selection_json": {},
                }
                for i in range(shot_count)
            ]
        }

    async def get_task(self, task_id: UUID) -> dict[str, Any] | None:
        return self.tasks.get(str(task_id))

    async def get_shots(self, task_id: UUID) -> list[dict[str, Any]]:
        return self.shots.get(str(task_id), [])

    async def save_shot(self, row: dict[str, Any]) -> None:
        shots = self.shots[str(row["task_id"])]
        for i, s in enumerate(shots):
            if s["id"] == row["id"]:
                shots[i] = row
                return


@pytest.fixture()
def repo() -> _FakeRepo:
    return _FakeRepo(TASK_ID)


@pytest.fixture()
def client(repo: _FakeRepo):
    app.dependency_overrides[get_current_user] = lambda: USER
    app.dependency_overrides[get_repository] = lambda: repo
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def _spec_url(i: int) -> str:
    return f"/api/tasks/{TASK_ID}/shots/{i}/spec"


# ── GET ──────────────────────────────────────────────────────────────────


def test_get_spec_defaults_to_null(client: TestClient) -> None:
    r = client.get(_spec_url(0))
    assert r.status_code == 200
    body = r.json()
    assert body["shot_index"] == 0
    assert body["spec"] is None


def test_get_spec_404_unknown_shot(client: TestClient) -> None:
    assert client.get(_spec_url(99)).status_code == 404


def test_get_spec_404_unknown_task(client: TestClient) -> None:
    assert client.get(f"/api/tasks/{OTHER_TASK_ID}/shots/0/spec").status_code == 404


# ── PATCH ────────────────────────────────────────────────────────────────


def test_patch_sets_fields_then_reads_back(client: TestClient) -> None:
    r = client.patch(
        _spec_url(0),
        json={
            "transition_in": "fade",
            "effect": "warm",
            "sfx": [{"id": "whoosh_air_up", "offset": 1.0}],
            "camera": "slow push in",
            "duration": 3.0,
        },
    )
    assert r.status_code == 200, r.text
    spec = r.json()["spec"]
    assert spec["effect"] == "warm"
    assert spec["sfx"] == [{"id": "whoosh_air_up", "offset": 1.0}]

    # 读回一致
    got = client.get(_spec_url(0)).json()["spec"]
    assert got == spec


def test_patch_is_partial(client: TestClient) -> None:
    """第二次 PATCH 只带 effect,不应清掉之前的 sfx/duration。"""
    client.patch(
        _spec_url(1),
        json={"effect": "warm", "duration": 4.0, "sfx": [{"id": "ding_bell", "offset": 0.5}]},
    )
    r = client.patch(_spec_url(1), json={"effect": "mono"})
    assert r.status_code == 200, r.text
    spec = r.json()["spec"]
    assert spec["effect"] == "mono"  # 被改
    assert spec["duration"] == 4.0  # 保留
    assert spec["sfx"] == [{"id": "ding_bell", "offset": 0.5}]  # 保留


def test_patch_explicit_null_clears_field(client: TestClient) -> None:
    client.patch(_spec_url(2), json={"effect": "cool", "duration": 3.0})
    r = client.patch(_spec_url(2), json={"effect": None})
    assert r.status_code == 200, r.text
    assert r.json()["spec"]["effect"] is None


def test_patch_unknown_transition_422(client: TestClient) -> None:
    r = client.patch(_spec_url(0), json={"transition_in": "not-a-transition"})
    assert r.status_code == 422


def test_patch_unknown_template_422(client: TestClient) -> None:
    r = client.patch(_spec_url(0), json={"template": "not-a-template"})
    assert r.status_code == 422


def test_patch_character_template_rejected_422(client: TestClient) -> None:
    """角色类模板因装配期无法绑定演员,ShotSpec 校验直接拒绝 (422: 装配期不可渲染)。"""
    r = client.patch(_spec_url(0), json={"template": "tc:lower-third-nameplate"})
    assert r.status_code == 422
    assert "装配期不可渲染" in r.text


def test_patch_unsupported_templates_rejected_422(client: TestClient) -> None:
    """R3: 文字动画/图表/计数/UI剧场/箭头标注及SFX等装配期无对应渲染器模板均返回 422。"""
    unsupported = [
        "tc:typewriter-reveal",
        "tc:word-slot-cycle",
        "tc:flying-words",
        "tc:per-character-rise",
        "tc:chat-message-flow",
        "tc:bar-chart-growth",
        "tc:chart-grow",
        "tc:line-chart-story-draw",
        "tc:metric-with-sparkline",
        "tc:number-counter",
        "tc:number-slab-pop",
        "tc:numbered-step-stack",
        "tc:ui-flow-theater",
        "tc:converging-arrows",
        "tc:callout-line-label",
        "tc:map-route-pin",
        "sfx:chime",
        "sfx:ding",
        "sfx:impact",
        "sfx:pop",
        "sfx:whoosh",
    ]
    for tid in unsupported:
        r = client.patch(_spec_url(1), json={"template": tid})
        assert r.status_code == 422, f"expected 422 for unsupported template {tid}, got {r.status_code}"
        assert "装配期不可渲染" in r.text


def test_patch_pure_transition_template_shot_0_rejected_422(client: TestClient) -> None:
    """R3: 纯接缝转场模板用于第 1 镜 (shot_index 0) 返回 422 (首镜无入场接缝)。"""
    # 镜0 使用纯转场模板 -> 422
    r0 = client.patch(_spec_url(0), json={"template": "tc:black-slam-transition"})
    assert r0.status_code == 422, r0.text
    assert "纯转场模板" in r0.text or "入场" in r0.text

    # 镜1 使用纯转场模板 -> 200 合法
    r1 = client.patch(_spec_url(1), json={"template": "tc:black-slam-transition"})
    assert r1.status_code == 200, r1.text
    assert r1.json()["spec"]["template"] == "tc:black-slam-transition"


def test_patch_supported_template_200(client: TestClient) -> None:
    """转场/风格/叠加类模板装配期有对应渲染动作,返回 200。"""
    r = client.patch(_spec_url(0), json={"template": "tc:crash-zoom-punch"})
    assert r.status_code == 200, r.text
    assert r.json()["spec"]["template"] == "tc:crash-zoom-punch"


def test_patch_valid_style_200(client: TestClient) -> None:
    """dirstyle 未合并期间,有 ffmpeg 映射的合法 style 枚举值返回 200。"""
    r = client.patch(_spec_url(0), json={"style": "noir"})
    assert r.status_code == 200, r.text
    assert r.json()["spec"]["style"] == "noir"


def test_patch_unknown_style_422(client: TestClient) -> None:
    """dirstyle 未合并期间,未知 style 值返回 422。"""
    r = client.patch(_spec_url(0), json={"style": "arbitrary_unmapped_style"})
    assert r.status_code == 422



def test_patch_unknown_effect_422(client: TestClient) -> None:
    r = client.patch(_spec_url(0), json={"effect": "not-an-effect"})
    assert r.status_code == 422


def test_patch_unknown_sfx_422(client: TestClient) -> None:
    r = client.patch(_spec_url(0), json={"sfx": [{"id": "not-a-sfx", "offset": 0.0}]})
    assert r.status_code == 422


def test_patch_sfx_offset_out_of_range_422(client: TestClient) -> None:
    # offset >= duration → 422
    r = client.patch(
        _spec_url(0),
        json={"duration": 3.0, "sfx": [{"id": "ding_bell", "offset": 3.0}]},
    )
    assert r.status_code == 422
    # 负 offset → 422
    r = client.patch(_spec_url(0), json={"sfx": [{"id": "ding_bell", "offset": -0.5}]})
    assert r.status_code == 422


def test_patch_duration_non_positive_422(client: TestClient) -> None:
    assert client.patch(_spec_url(0), json={"duration": 0}).status_code == 422


def test_patch_404_unknown_shot(client: TestClient) -> None:
    assert client.patch(_spec_url(99), json={"effect": "warm"}).status_code == 404


# ── PUT (batch) ──────────────────────────────────────────────────────────


def _put_url() -> str:
    return f"/api/tasks/{TASK_ID}/shots/spec"


def test_put_batch_replaces_group(client: TestClient) -> None:
    r = client.put(
        _put_url(),
        json={
            "specs": [
                {"shot_index": 0, "spec": {"effect": "warm"}},
                {"shot_index": 1, "spec": {"effect": "mono", "duration": 3.0}},
            ]
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 2
    assert client.get(_spec_url(0)).json()["spec"]["effect"] == "warm"
    assert client.get(_spec_url(1)).json()["spec"]["effect"] == "mono"
    # 未列出的镜号 2 规格清空
    assert client.get(_spec_url(2)).json()["spec"] is None


def test_put_batch_clears_unlisted(client: TestClient) -> None:
    client.patch(_spec_url(2), json={"effect": "cool"})
    r = client.put(_put_url(), json={"specs": [{"shot_index": 0, "spec": {"effect": "warm"}}]})
    assert r.status_code == 200
    assert client.get(_spec_url(2)).json()["spec"] is None


def test_put_batch_one_invalid_rejects_all_422(client: TestClient) -> None:
    r = client.put(
        _put_url(),
        json={
            "specs": [
                {"shot_index": 0, "spec": {"effect": "warm"}},
                {"shot_index": 1, "spec": {"effect": "bogus-effect"}},
            ]
        },
    )
    assert r.status_code == 422
    # 整体拒绝:合法的那条也不该落库。
    assert client.get(_spec_url(0)).json()["spec"] is None


def test_put_batch_unknown_shot_404(client: TestClient) -> None:
    r = client.put(_put_url(), json={"specs": [{"shot_index": 42, "spec": {"effect": "warm"}}]})
    assert r.status_code == 404


def test_put_batch_404_unknown_task(client: TestClient) -> None:
    r = client.put(
        f"/api/tasks/{OTHER_TASK_ID}/shots/spec",
        json={"specs": [{"shot_index": 0, "spec": {"effect": "warm"}}]},
    )
    assert r.status_code == 404


# ── 取值白名单来源(真实注册表)─────────────────────────────────────────


def test_valid_values_come_from_registries() -> None:
    from hevi.production.shot_spec import (
        rejected,
        template_render_supported,
        valid_sfx_ids,
        valid_style_ids,
        valid_template_ids,
        valid_transition_ids,
    )

    assert "fade" in valid_transition_ids()
    assert "whip" in valid_transition_ids()  # custom 转场
    assert len(valid_template_ids()) >= 100
    assert "whoosh_air_up" in valid_sfx_ids()  # manifest 资产
    assert "noir" in valid_style_ids()
    assert "sepia" in valid_style_ids()

    # R2 验收要求 1: 每个 valid_template_ids() 中的 id 必须满足:
    # 或者是装配期可渲染的,或者被 ShotSpec 校验拒绝 (422: 装配期不可渲染)
    assert all(template_render_supported(t) or rejected(t) for t in valid_template_ids())


def test_no_generic_template_fallback() -> None:
    """R3 验收 5: 对 valid_template_ids() 里每个被接受的 id，断言它在 TEMPLATE_RENDER_MAP 里有显式条目，

    并且 filter 不属于任何通用占位滤镜串。
    """
    from hevi.production.shot_spec import ShotSpec, template_render_supported, valid_template_ids
    from hevi.production.shot_spec_render import TEMPLATE_RENDER_MAP, template_filter

    forbidden_generic_filters = {
        "eq=saturation=1.2:contrast=1.05",
        "eq=brightness=0.04:contrast=1.12",
        "eq=saturation=1.25",
        "drawbox=x=30:y=30:w=iw-60:h=ih-60:color=white@0.3:t=2",
    }

    all_ids = valid_template_ids()
    accepted_ids = [t for t in all_ids if template_render_supported(t)]

    # 断言接受的模板集合非空，且每个均在 TEMPLATE_RENDER_MAP 中显式登记
    assert len(accepted_ids) >= 70, f"expected at least 70 supported templates, got {len(accepted_ids)}"
    for tid in accepted_ids:
        assert tid in TEMPLATE_RENDER_MAP, f"template {tid} supported but missing in TEMPLATE_RENDER_MAP"
        action = TEMPLATE_RENDER_MAP[tid]
        assert action.get("reason"), f"template {tid} missing reason in TEMPLATE_RENDER_MAP"

        # 检查其渲染 filter 绝不属于通用占位滤镜串
        filt = template_filter(ShotSpec(template=tid))
        assert filt not in forbidden_generic_filters, (
            f"template {tid} resolved to forbidden generic filter: {filt}"
        )

