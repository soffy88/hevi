"""qnlr_gen_adapter A0 v0 单测——全部 mock 底层入口，零真机成本。

覆盖摸底文档 QNLR-AQIN-ADAPTER-001 §5 自测项：
①三类 + T-V 各自 mock 底层、断言 decision_trail/cost 记全；
②超帽 check_and_reserve 抛且 ok=False、花费不动；
③单价越界触发 §3.5 暂停路径、不发起调用；
④产物类调用确有 register（pack_id 回填 fingerprint）。
"""

from __future__ import annotations

from typing import Any

import pytest

from hevi.qnlr.gen_adapter import (
    CNY_PER_USD,
    AdapterResult,
    GenAdapter,
)


def _reg_ok(**kw: Any) -> str:
    return "pack_test_001"


def _make(cap_cny: float = 80.0, register: bool = True) -> GenAdapter:
    # ledger_path=None：单测默认不落盘（避免写进已跟踪的真实 ledger）；落盘另有专测。
    return GenAdapter(cap_cny=cap_cny, register_fn=_reg_ok if register else None, ledger_path=None)


# ----------------- T-V 视频（付费路，G0 烟测同一条）-----------------


async def test_generate_video_happy_path() -> None:
    calls: list[tuple[Any, ...]] = []

    async def fake_video(prompt: str, output_path: str, **kw: Any) -> str:
        calls.append((prompt, output_path, kw))
        return output_path

    adp = _make()
    res = await adp.generate_video(
        prompt="test clip",
        output_path="output/g0.mp4",
        duration_s=5,
        seed=7,
        ts="2026-07-23T00:00:00Z",
        video_fn=fake_video,
    )
    assert res.ok is True
    assert res.op == "T-V"
    assert res.artifact_path == "output/g0.mp4"
    assert res.cost_usd == pytest.approx(0.14 * 5)  # happyhorse_1_1_maas $0.14/s
    assert res.unit_price_cny == pytest.approx(0.14 * CNY_PER_USD, rel=1e-3)  # ¥0.945/s < ¥1/s
    assert res.pack_id == "pack_test_001"
    # cost 累计进 breaker
    assert adp.spent_usd == pytest.approx(0.70)
    assert adp.spent_cny == pytest.approx(0.70 * CNY_PER_USD)
    # decision_trail 记全 + ts 由调用方传入（adapter 不取时钟）
    t = res.decision_trail
    assert t["op"] == "T-V" and t["provider"] == "happyhorse_1_1_maas"
    assert t["cost_usd"] == pytest.approx(0.70)
    assert t["ts"] == "2026-07-23T00:00:00Z"
    assert t["fingerprint"] == "pack_test_001"
    assert t["inputs_digest"]  # 非空
    assert len(calls) == 1


async def test_generate_video_cap_exceeded() -> None:
    """②超帽：cap ¥1 → $0.148 限额，5s×$0.14=$0.70 预留即拒，且不发起调用、花费不动。"""
    called = False

    async def fake_video(*a: Any, **k: Any) -> str:
        nonlocal called
        called = True
        return "x"

    adp = _make(cap_cny=1.0)
    res = await adp.generate_video(
        prompt="p", output_path="o.mp4", duration_s=5, video_fn=fake_video
    )
    assert res.ok is False
    assert "超金额帽" in (res.reason or "")
    assert called is False
    assert adp.spent_usd == 0.0


async def test_generate_video_unit_price_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """③单价越界：patch 高价 provider → ¥1.35/s > ¥1/s → §3.5 暂停，不发起调用。"""
    called = False

    async def fake_video(*a: Any, **k: Any) -> str:
        nonlocal called
        called = True
        return "x"

    def fake_pricing() -> dict[str, dict[str, Any]]:
        return {"pricey_route": {"unit": "per_second", "price_usd": 0.20}}

    monkeypatch.setattr("hevi.qnlr.gen_adapter.get_pricing_table", fake_pricing)
    adp = _make()
    res = await adp.generate_video(
        prompt="p", output_path="o.mp4", provider="pricey_route", duration_s=5, video_fn=fake_video
    )
    assert res.ok is False
    assert "§3.5" in (res.reason or "")
    assert res.unit_price_cny == pytest.approx(0.20 * CNY_PER_USD)
    assert called is False
    assert adp.spent_usd == 0.0


async def test_generate_video_provider_not_priced() -> None:
    called = False

    async def fake_video(*a: Any, **k: Any) -> str:
        nonlocal called
        called = True
        return "x"

    adp = _make()
    res = await adp.generate_video(
        prompt="p", output_path="o.mp4", provider="ghost_provider", video_fn=fake_video
    )
    assert res.ok is False
    assert "不在 pricing_table" in (res.reason or "")
    assert called is False


async def test_generate_video_call_failure_rollback() -> None:
    """provider 调用失败 → 回滚预留，花费归零，显式失败不静默。"""

    async def boom(*a: Any, **k: Any) -> str:
        raise RuntimeError("maas 500")

    adp = _make()
    res = await adp.generate_video(prompt="p", output_path="o.mp4", duration_s=5, video_fn=boom)
    assert res.ok is False
    assert "provider 调用失败" in (res.reason or "")
    assert adp.spent_usd == 0.0  # 预留已回滚


# ----------------- T-3 img2img / txt2img（本地免费）-----------------


async def test_refine_image_local_free() -> None:
    seen: dict[str, Any] = {}

    async def fake_gen(**kw: Any) -> dict[str, Any]:
        seen.update(kw)
        return {"path": kw["output_path"]}

    adp = _make()
    res = await adp.refine_image(
        prompt="qin hall", output_path="base.png", seed=3, ts="T", gen_fn=fake_gen
    )
    assert res.ok is True and res.op == "T-3"
    assert res.cost_usd == 0.0  # 本地免费
    assert res.decision_trail["model_or_tier"] == "txt2img"  # 无 init_image
    assert res.pack_id == "pack_test_001"
    assert seen["extra"] is None  # txt2img 不置 init_image


async def test_refine_image_img2img_sets_init() -> None:
    seen: dict[str, Any] = {}

    async def fake_gen(**kw: Any) -> dict[str, Any]:
        seen.update(kw)
        return {}

    adp = _make()
    res = await adp.refine_image(
        prompt="refine", output_path="r.png", init_image="src.png", gen_fn=fake_gen
    )
    assert res.ok is True
    assert res.decision_trail["model_or_tier"] == "img2img"
    assert seen["extra"] == {"init_image": "src.png"}


async def test_refine_image_cloud_rejected() -> None:
    adp = _make()
    res = await adp.refine_image(prompt="p", output_path="o.png", engine="cloud")
    assert res.ok is False and res.op == "T-3"
    assert "额度墙" in (res.reason or "")


# ----------------- T-2 compose（本地免费）-----------------


def _compose_args() -> dict[str, Any]:
    return {
        "present": ["a", "b"],
        "view_path_by_cid": {"a": "a.png", "b": "b.png"},
        "pos_desc_by_cid": {"a": "L", "b": "R"},
        "size": (1024, 576),
        "out_path": "comp.png",
    }


async def test_compose_layout_free() -> None:
    def fake_compose(**kw: Any) -> str:
        return "comp.png"

    adp = _make()
    res = adp.compose_layout(**_compose_args(), compose_fn=fake_compose)
    assert res.ok is True and res.op == "T-2"
    assert res.cost_usd == 0.0
    assert res.pack_id == "pack_test_001"


async def test_compose_layout_none_is_explicit_failure() -> None:
    def fake_compose(**kw: Any) -> None:
        return None  # 视图缺失

    adp = _make()
    res = adp.compose_layout(**_compose_args(), compose_fn=fake_compose)
    assert res.ok is False
    assert "不静默降级" in (res.reason or "")


# ----------------- T-1 subject 摄取（本地免费）-----------------


async def test_ingest_subject() -> None:
    events: list[str] = []

    class FakeService:
        async def create_subject(self, **kw: Any) -> dict[str, Any]:
            events.append("create")
            return {"id": "subj_001"}

        async def generate_subject3d(self, subject_id: str) -> dict[str, Any]:
            events.append(f"3d:{subject_id}")
            return {}

    adp = _make()
    res = await adp.ingest_subject(
        service=FakeService(),
        kind="character",
        name="嬴政",
        reference_images=["ref.png"],
        ts="T",
    )
    assert res.ok is True and res.op == "T-1"
    assert res.artifact_path == "subj_001"
    assert res.cost_usd == 0.0
    assert events == ["create", "3d:subj_001"]
    assert res.decision_trail["ts"] == "T"


async def test_register_none_skips_and_no_pack_id() -> None:
    async def fake_video(*a: Any, **k: Any) -> str:
        return "o.mp4"

    adp = _make(register=False)
    res = await adp.generate_video(prompt="p", output_path="o.mp4", video_fn=fake_video)
    assert res.ok is True
    assert res.pack_id is None
    assert res.decision_trail["fingerprint"] is None


def test_adapter_result_shape() -> None:
    r = AdapterResult(ok=True, op="T-V")
    assert r.cost_usd == 0.0 and r.pack_id is None and r.decision_trail == {}


# ----------------- 付费落盘 ledger（任务 1：内存态→持久可查询）-----------------


async def test_paid_call_writes_ledger(tmp_path: Any) -> None:
    """付费调用把结构化记录落盘：含 fingerprint/provider/模型/时长/单价/金额/trail digest。"""
    from hevi.qnlr.cost_ledger import read_records

    async def fake_video(prompt: str, output_path: str, **kw: Any) -> str:
        return output_path

    ledger = tmp_path / "ledger.jsonl"
    adp = GenAdapter(cap_cny=80.0, register_fn=_reg_ok, ledger_path=ledger)
    res = await adp.generate_video(
        prompt="p",
        output_path="o.mp4",
        duration_s=5,
        ts="2026-07-23T00:00:00Z",
        video_fn=fake_video,
    )
    assert res.ok is True
    rows = read_records(ledger)
    assert len(rows) == 1
    row = rows[0]
    assert row["provider"] == "happyhorse_1_1_maas"
    assert row["model_or_tier"] == "happyhorse_1_1"
    assert row["unit"] == "per_second" and row["quantity"] == 5
    assert row["unit_price_cny"] == pytest.approx(0.14 * CNY_PER_USD, rel=1e-3)
    assert row["cost_cny"] == pytest.approx(0.70 * CNY_PER_USD, rel=1e-3)
    assert row["fingerprint"] == "pack_test_001"
    assert row["trail_digest"] and row["ts"] == "2026-07-23T00:00:00Z"
    assert row["cumulative_cny"] == pytest.approx(0.70 * CNY_PER_USD, rel=1e-3)
    assert row["cap_cny"] == 80.0


async def test_local_free_call_does_not_write_ledger(tmp_path: Any) -> None:
    """本地免费调用（cost_usd=0）不落 ledger——只记付费。"""
    from hevi.qnlr.cost_ledger import read_records

    async def fake_gen(**kw: Any) -> None:
        return None

    ledger = tmp_path / "ledger.jsonl"
    adp = GenAdapter(register_fn=_reg_ok, ledger_path=ledger)
    res = await adp.refine_image(prompt="p", output_path="a.png", gen_fn=fake_gen, ts="T")
    assert res.ok is True and res.cost_usd == 0.0
    assert read_records(ledger) == []


async def test_failed_paid_call_does_not_write_ledger(tmp_path: Any) -> None:
    """付费调用失败（回滚预留、零支出）不落 ledger——只记真实支出。"""
    from hevi.qnlr.cost_ledger import read_records

    async def boom(**kw: Any) -> str:
        raise RuntimeError("provider down")

    ledger = tmp_path / "ledger.jsonl"
    adp = GenAdapter(register_fn=_reg_ok, ledger_path=ledger)
    res = await adp.generate_video(prompt="p", output_path="o.mp4", duration_s=5, video_fn=boom)
    assert res.ok is False
    assert read_records(ledger) == []


def test_cost_ledger_missing_field_rejected(tmp_path: Any) -> None:
    """记账不完整（缺字段）拒绝落盘——不静默写半条。"""
    from hevi.qnlr.cost_ledger import append_record

    with pytest.raises(ValueError, match="缺字段"):
        append_record(tmp_path / "l.jsonl", {"op": "T-V", "provider": "x"})
