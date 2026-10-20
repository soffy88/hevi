"""Offline contract tests for story.branch_forecast / story.branch_adopt.

Clean-room story branching (hevi.storybranch + hevi.capabilities.storybranch).
All tests use a fake injected generator: zero paid calls, zero network.

Note: registration is explicit here because the coordinator wires
``hevi/capabilities/__init__.py`` separately -- this module must be
importable and register on its own.
"""

import hashlib
import json
import re
from pathlib import Path

import pytest

import hevi.capabilities as caps
import hevi.capabilities.storybranch as sb_cap
from hevi.capabilities.errors import CapabilityError
from hevi.storybranch import core

sb_cap.register_storybranch_capabilities_once()


# ---------------------------------------------------------------------------
# Fixtures / fake generator
# ---------------------------------------------------------------------------


STATE = {
    "canon_facts": ["林小满已拿到城门钥匙", "师父失踪三日"],
    "characters": [{"name": "林小满"}, {"name": "阿澈"}],
    "recent_summaries": ["第十二章: 小满在雨夜救下阿澈, 两人结盟。"],
    "author_intent": "下一章要让同盟经受第一次考验, 但不能让任何人死亡",
}


def fake_generator(state_dict, branch_count, seed):
    """Deterministic fake LLM: returns well-formed branch payloads."""
    branches = []
    for i in range(branch_count):
        branches.append(
            {
                "branch_id": f"branch-{i + 1}",
                "title": f"假分支{i + 1}",
                "beats": [f"节拍{i + 1}-开场", f"节拍{i + 1}-冲突", f"节拍{i + 1}-钩子"],
                "key_decisions": [
                    {"character": "林小满", "decision": f"决定{i + 1}: 是否交出钥匙"},
                ],
                "state_changes": [f"状态变化{i + 1}: 同盟信任度下降"],
                "risks": [f"风险{i + 1}: 节奏过快"],
                "intent_match": round(0.9 - i * 0.1, 2),
            }
        )
    return branches


@pytest.fixture()
def injected(monkeypatch):
    monkeypatch.setattr(sb_cap, "_generator_fn", fake_generator)
    yield fake_generator
    monkeypatch.setattr(sb_cap, "_generator_fn", None)


@pytest.fixture(autouse=True)
def _hermetic_default_backend(monkeypatch):
    # Keep the placeholder/injection tests hermetic even on machines with
    # a real key in the env: the default Monid backend only engages when a
    # test opts in by setting a fake MONID_API_KEY explicitly.
    monkeypatch.delenv("MONID_API_KEY", raising=False)
    monkeypatch.setattr(sb_cap, "_generator_fn", None)
    yield
    monkeypatch.setattr(sb_cap, "_generator_fn", None)


def _forecast_via_capability(tmp_path: Path, branch_count: int = 3):
    cap = caps.get("story.branch_forecast")
    out_dir = tmp_path / "forecast"
    result = cap.render_safe(
        {**STATE, "branch_count": branch_count},
        out_dir,
        duration=1.0,
        aspect="9:16",
        seed=7,
    )
    return result, out_dir


# ---------------------------------------------------------------------------
# Registration / describe
# ---------------------------------------------------------------------------


def test_storybranch_capabilities_registered_and_listable() -> None:
    names = caps.names()
    assert "story.branch_forecast" in names
    assert "story.branch_adopt" in names
    listed = [c.name for c in caps.list(kind="line")]
    assert "story.branch_forecast" in listed
    assert "story.branch_adopt" in listed


def test_storybranch_describe_has_params_schema() -> None:
    from hevi.capabilities.registry import describe

    by_name = {item["name"]: item for item in describe()}
    for expected in ("story.branch_forecast", "story.branch_adopt"):
        assert expected in by_name
        assert by_name[expected].get("description"), expected
        assert by_name[expected].get("params_schema"), expected


def test_register_once_is_idempotent() -> None:
    # First call in this process already happened at import time of the test
    # module; a second explicit call must not raise or duplicate-break.
    assert sb_cap.register_storybranch_capabilities_once() == []
    assert caps.names().count("story.branch_forecast") == 1


# ---------------------------------------------------------------------------
# Illegal params
# ---------------------------------------------------------------------------


def test_forecast_rejects_invalid_params(tmp_path: Path) -> None:
    cap = caps.get("story.branch_forecast")
    # missing required author_intent
    with pytest.raises(CapabilityError):
        cap.render_safe({}, tmp_path / "a", duration=1.0, aspect="9:16", seed=1)
    # empty author_intent
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {**STATE, "author_intent": ""},
            tmp_path / "b",
            duration=1.0,
            aspect="9:16",
            seed=1,
        )
    # branch_count below / above the 2-5 window
    for bad in (1, 6):
        with pytest.raises(CapabilityError):
            cap.render_safe(
                {**STATE, "branch_count": bad},
                tmp_path / f"c{bad}",
                duration=1.0,
                aspect="9:16",
                seed=1,
            )
    # unknown extra property
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {**STATE, "bogus": 1}, tmp_path / "d", duration=1.0, aspect="9:16", seed=1
        )


def test_adopt_rejects_invalid_params(tmp_path: Path) -> None:
    cap = caps.get("story.branch_adopt")
    with pytest.raises(CapabilityError):
        cap.render_safe({}, tmp_path / "a", duration=1.0, aspect="9:16", seed=1)
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"branches_path": "/nonexistent/branches.json"},
            tmp_path / "b",
            duration=1.0,
            aspect="9:16",
            seed=1,
        )
    # file exists but branch_id missing from schema-required fields
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"branches_path": "/tmp/x.json", "bogus": True},
            tmp_path / "c",
            duration=1.0,
            aspect="9:16",
            seed=1,
        )


def test_adopt_missing_file_and_unknown_branch_raise(
    injected, tmp_path: Path
) -> None:
    cap = caps.get("story.branch_adopt")
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"branches_path": str(tmp_path / "nope.json"), "branch_id": "branch-1"},
            tmp_path / "out",
            duration=1.0,
            aspect="9:16",
            seed=1,
        )
    _, forecast_dir = _forecast_via_capability(tmp_path)
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {
                "branches_path": str(forecast_dir / "branches.json"),
                "branch_id": "branch-99",
            },
            tmp_path / "out2",
            duration=1.0,
            aspect="9:16",
            seed=1,
        )


# ---------------------------------------------------------------------------
# Core: fake generator -> 2-5 branches, fields complete
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("count", [2, 3, 5])
def test_core_forecast_with_fake_generator(count: int) -> None:
    forecast_obj = core.forecast_branches(
        STATE, branch_count=count, generator_fn=fake_generator, seed=11
    )
    assert len(forecast_obj.branches) == count
    assert forecast_obj.story_hash == core.compute_story_hash(STATE)
    for branch in forecast_obj.branches:
        assert branch.branch_id
        assert branch.title
        assert branch.beats and all(branch.beats)
        assert branch.key_decisions
        assert branch.state_changes
        assert branch.risks and all(branch.risks)
        assert 0.0 <= branch.intent_match <= 1.0
    # branches are isolated: unique ids, unique titles
    assert len({b.branch_id for b in forecast_obj.branches}) == count
    # comparison table structure
    comp = forecast_obj.comparison
    assert comp["branch_count"] == count
    assert len(comp["rows"]) == count
    assert comp["best_branch_id"] == "branch-1"  # highest fake intent_match
    assert set(comp["columns"]) >= {"branch_id", "title", "intent_match"}


def test_core_rejects_bad_generator_output() -> None:
    def one_branch(state_dict, branch_count, seed):
        return fake_generator(state_dict, 1, seed)

    with pytest.raises(ValueError):
        core.forecast_branches(STATE, branch_count=3, generator_fn=one_branch)

    def bad_match(state_dict, branch_count, seed):
        payloads = fake_generator(state_dict, branch_count, seed)
        payloads[0]["intent_match"] = 1.5
        return payloads

    with pytest.raises(ValueError):
        core.forecast_branches(STATE, branch_count=3, generator_fn=bad_match)

    def missing_beats(state_dict, branch_count, seed):
        payloads = fake_generator(state_dict, branch_count, seed)
        del payloads[0]["beats"]
        return payloads

    with pytest.raises(ValueError):
        core.forecast_branches(STATE, branch_count=3, generator_fn=missing_beats)

    with pytest.raises(ValueError):
        core.forecast_branches(STATE, branch_count=1, generator_fn=fake_generator)
    with pytest.raises(ValueError):
        core.forecast_branches(
            {**STATE, "author_intent": "  "},
            branch_count=3,
            generator_fn=fake_generator,
        )


def test_default_placeholder_generator_is_offline_and_valid() -> None:
    forecast_obj = core.forecast_branches(STATE, branch_count=4, seed=3)
    assert len(forecast_obj.branches) == 4
    assert forecast_obj.generator == "placeholder_generator"
    for branch in forecast_obj.branches:
        assert branch.beats and branch.risks
        assert 0.0 <= branch.intent_match <= 1.0


# ---------------------------------------------------------------------------
# Capability render: branches.json artifact + qa
# ---------------------------------------------------------------------------


def test_forecast_capability_writes_branches_json(injected, tmp_path: Path) -> None:
    result, out_dir = _forecast_via_capability(tmp_path, branch_count=4)
    branches_path = Path(result.qa["branches_json"])
    assert branches_path == out_dir / "branches.json"
    assert branches_path.is_file()
    assert result.sha256
    assert result.qa["branch_count"] == 4
    assert result.qa["stale"] is False
    assert result.qa["story_hash"] == core.compute_story_hash(STATE)
    assert result.qa["generator"] == "fake_generator"

    payload = json.loads(branches_path.read_text(encoding="utf-8"))
    assert payload["story_hash"] == result.qa["story_hash"]
    assert len(payload["branches"]) == 4
    assert len(payload["comparison"]["rows"]) == 4
    for branch in payload["branches"]:
        assert branch["beats"] and branch["key_decisions"]
        assert branch["state_changes"] and branch["risks"]
        assert 0.0 <= branch["intent_match"] <= 1.0

    # Contract pattern (multimodel precedent): deleting the artifact must
    # break verification -- the file check no longer passes.
    verified = core.verify_forecast_file(branches_path)
    assert verified["ok"] is True and verified["branch_count"] == 4
    branches_path.unlink()
    assert not branches_path.exists()
    with pytest.raises(FileNotFoundError):
        core.verify_forecast_file(branches_path)
    with pytest.raises(FileNotFoundError):
        core.load_forecast(branches_path)


# ---------------------------------------------------------------------------
# Adopt: plan file exists, canon untouched
# ---------------------------------------------------------------------------


def test_adopt_writes_plan_and_leaves_canon_untouched(
    injected, tmp_path: Path
) -> None:
    canon_path = tmp_path / "canon.json"
    canon_path.write_text(
        json.dumps(STATE, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    canon_bytes_before = canon_path.read_bytes()
    canon_hash_before = hashlib.sha256(canon_bytes_before).hexdigest()

    _, forecast_dir = _forecast_via_capability(tmp_path)

    cap = caps.get("story.branch_adopt")
    plan_dir = tmp_path / "plan"
    result = cap.render_safe(
        {
            "branches_path": str(forecast_dir / "branches.json"),
            "branch_id": "branch-2",
            "canon_path": str(canon_path),
        },
        plan_dir,
        duration=1.0,
        aspect="9:16",
        seed=5,
    )
    plan_path = Path(result.qa["branch_plan_json"])
    assert plan_path == plan_dir / "branch_plan.json"
    assert plan_path.is_file()
    assert result.sha256
    assert result.qa["adopted_branch_id"] == "branch-2"
    assert result.qa["canon_modified"] is False
    assert result.qa["stale"] is False

    plan = core.load_branch_plan(plan_path)
    assert plan["adopted_branch_id"] == "branch-2"
    assert plan["branch"]["title"] == "假分支2"
    assert plan["canon_modified"] is False

    # Canon itself must be byte-identical after adoption.
    assert canon_path.read_bytes() == canon_bytes_before
    assert hashlib.sha256(canon_path.read_bytes()).hexdigest() == canon_hash_before

    # Deleting the plan artifact breaks plan loading/verification.
    plan_path.unlink()
    assert not plan_path.exists()
    with pytest.raises(FileNotFoundError):
        core.load_branch_plan(plan_path)


def test_core_adopt_returns_plan_without_touching_canon(tmp_path: Path) -> None:
    forecast_obj = core.forecast_branches(
        STATE, branch_count=3, generator_fn=fake_generator, seed=9
    )
    branches_path = core.save_forecast(forecast_obj, tmp_path / "branches.json")
    canon_path = tmp_path / "canon.txt"
    canon_path.write_text("正史原文, 不可改动", encoding="utf-8")
    before = canon_path.read_bytes()

    plan = core.adopt_branch(
        branches_path, "branch-1", tmp_path / "out" / "branch_plan.json",
        canon_path=canon_path,
    )
    assert plan["adopted_branch_id"] == "branch-1"
    assert (tmp_path / "out" / "branch_plan.json").is_file()
    assert canon_path.read_bytes() == before


# ---------------------------------------------------------------------------
# Staleness: canon change -> old forecast is stale
# ---------------------------------------------------------------------------


def test_forecast_becomes_stale_after_canon_change() -> None:
    forecast_obj = core.forecast_branches(
        STATE, branch_count=3, generator_fn=fake_generator, seed=2
    )
    assert core.is_stale(forecast_obj, STATE) is False
    assert core.is_stale(forecast_obj, forecast_obj.story_hash) is False

    changed = {**STATE, "canon_facts": STATE["canon_facts"] + ["阿澈其实是城主之子"]}
    assert core.compute_story_hash(changed) != forecast_obj.story_hash
    assert core.is_stale(forecast_obj, changed) is True

    report = core.staleness_report(forecast_obj, changed)
    assert report["stale"] is True
    assert report["forecast_story_hash"] == forecast_obj.story_hash
    assert report["current_story_hash"] == core.compute_story_hash(changed)


def test_adopt_blocks_stale_forecast_unless_allowed(
    injected, tmp_path: Path
) -> None:
    result, forecast_dir = _forecast_via_capability(tmp_path)
    new_hash = core.compute_story_hash(
        {**STATE, "canon_facts": ["完全不同的正史"]}
    )
    cap = caps.get("story.branch_adopt")
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {
                "branches_path": str(forecast_dir / "branches.json"),
                "branch_id": "branch-1",
                "current_story_hash": new_hash,
            },
            tmp_path / "stale-plan",
            duration=1.0,
            aspect="9:16",
            seed=1,
        )
    # ... but an explicit allow_stale override adopts and flags it.
    ok = cap.render_safe(
        {
            "branches_path": str(forecast_dir / "branches.json"),
            "branch_id": "branch-1",
            "current_story_hash": new_hash,
            "allow_stale": True,
        },
        tmp_path / "stale-plan-ok",
        duration=1.0,
        aspect="9:16",
        seed=1,
    )
    assert ok.qa["stale"] is True
    assert Path(ok.qa["branch_plan_json"]).is_file()
    _ = result  # forecast result referenced for clarity


# ------------------------------------------- default Monid backend (offline)


def _monid_branch_payloads(branch_count: int) -> list[dict]:
    return [
        {
            "branch_id": f"branch-{i + 1}",
            "title": f"真分支{i + 1}",
            "beats": [f"真节拍{i + 1}-开场", f"真节拍{i + 1}-考验", f"真节拍{i + 1}-钩子"],
            "key_decisions": [
                {"character": "林小满", "decision": f"真决定{i + 1}: 守住钥匙"},
            ],
            "state_changes": [f"真状态变化{i + 1}: 同盟经受住考验"],
            "risks": [f"真风险{i + 1}: 铺垫不足"],
            "intent_match": round(0.88 - i * 0.07, 2),
        }
        for i in range(branch_count)
    ]


def test_forecast_default_backend_when_key_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No injection + MONID_API_KEY set -> Monid chat generates branches."""
    from hevi.audio import monid_client

    seen: dict = {}

    async def fake_run_endpoint(provider, endpoint, *, body=None, **_kwargs):
        seen["provider"] = provider
        seen["endpoint"] = endpoint
        seen["body"] = body
        prompt = body["messages"][-1]["content"]
        count = int(re.search(r"恰好 (\d+) 条", prompt).group(1))
        content = json.dumps(
            {"branches": _monid_branch_payloads(count)}, ensure_ascii=False
        )
        return ({"choices": [{"message": {"content": content}}]}, 0.0013)

    monkeypatch.setenv("MONID_API_KEY", "fake-key-for-tests")
    monkeypatch.setattr(monid_client, "run_endpoint", fake_run_endpoint)

    result, _out_dir = _forecast_via_capability(tmp_path, branch_count=3)
    assert result.qa["generator"] == "monid_gpt-4o-mini"
    assert result.qa["branch_count"] == 3
    payload = json.loads(Path(result.qa["branches_json"]).read_text(encoding="utf-8"))
    assert [b["title"] for b in payload["branches"]] == ["真分支1", "真分支2", "真分支3"]
    for branch in payload["branches"]:
        assert branch["beats"] and branch["key_decisions"]
        assert branch["state_changes"] and branch["risks"]
        assert 0.0 <= branch["intent_match"] <= 1.0
    # Same route as story.film_from_prompt (blockrun chat, gpt-4o-mini).
    assert seen["provider"] == "blockrun.ai"
    assert seen["endpoint"] == "/api/v1/chat/completions"
    assert seen["body"]["model"] == "gpt-4o-mini"


def test_forecast_injected_generator_wins_over_default_backend(
    injected, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.audio import monid_client

    async def forbidden_run_endpoint(*_args, **_kwargs):
        raise AssertionError("default backend must not run when injected")

    monkeypatch.setenv("MONID_API_KEY", "fake-key-for-tests")
    monkeypatch.setattr(monid_client, "run_endpoint", forbidden_run_endpoint)

    result, _out_dir = _forecast_via_capability(tmp_path, branch_count=3)
    assert result.qa["generator"] == "fake_generator"
    payload = json.loads(Path(result.qa["branches_json"]).read_text(encoding="utf-8"))
    assert payload["branches"][0]["title"] == "假分支1"


def test_forecast_without_key_falls_back_to_placeholder(tmp_path: Path) -> None:
    """No injection + no key -> deterministic placeholder, behavior unchanged."""
    result, _out_dir = _forecast_via_capability(tmp_path, branch_count=3)
    assert result.qa["generator"] == "placeholder_generator"
    payload = json.loads(Path(result.qa["branches_json"]).read_text(encoding="utf-8"))
    assert len(payload["branches"]) == 3
    assert all("占位分支" in b["title"] for b in payload["branches"])
