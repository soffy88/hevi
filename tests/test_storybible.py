"""Contract tests for the story bible capabilities (CAPABILITY_CONTRACT.md).

Covers ``story.foreshadow`` and ``story.canon_check`` plus the file ledgers
in ``hevi.storybible``. Offline and local-only: ledgers are JSON files under
pytest tmp dirs; no DB, no network, no keys.

Note: ``hevi.capabilities.storybible`` is registered explicitly here (the
package ``__init__`` wiring is the coordinator's job), mirroring how the
multimodel tests resolve their capabilities after import.
"""

import json
from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import compute_sha256
from hevi.capabilities.storybible import register_storybible_capabilities_once
from hevi.storybible import CanonLedger, ForeshadowLedger, check_claims_against_canon

register_storybible_capabilities_once()

WORK = "雾桥长篇"


def _render(name: str, params: dict, out_dir: Path):
    cap = caps.get(name)
    return cap.render_safe(params, out_dir, duration=1.0, aspect="16:9", seed=3)


def _plant_knife(out_dir: Path, base: Path) -> None:
    _render(
        "story.foreshadow",
        {
            "work": WORK,
            "action": "plant",
            "base_dir": str(base),
            "entry_id": "fs-knife",
            "description": "林雾的短刀在桥洞刻痕，与失踪的守桥人有关",
            "planted_chapter": 2,
            "expected_start": 8,
            "expected_end": 10,
        },
        out_dir,
    )


# ---------------------------------------------------------------------------
# Registration / contract surface
# ---------------------------------------------------------------------------


def test_storybible_capabilities_registered_and_listable() -> None:
    names = caps.names()
    assert "story.foreshadow" in names
    assert "story.canon_check" in names
    listed = [c.name for c in caps.list(kind="line")]
    assert "story.foreshadow" in listed
    assert "story.canon_check" in listed


def test_storybible_describe_has_params_schema() -> None:
    from hevi.capabilities.registry import describe

    by_name = {item["name"]: item for item in describe()}
    for expected in ("story.foreshadow", "story.canon_check"):
        assert expected in by_name
        assert by_name[expected].get("description"), expected
        assert by_name[expected]["params_schema"]["required"] == ["work", "action"]


def test_foreshadow_rejects_invalid_params(tmp_path: Path) -> None:
    cap = caps.get("story.foreshadow")
    with pytest.raises(CapabilityError):
        cap.render_safe({}, tmp_path, duration=1.0, aspect="16:9", seed=1)
    with pytest.raises(CapabilityError):
        # plant without the full expected window
        cap.render_safe(
            {"work": WORK, "action": "plant", "description": "x", "planted_chapter": 1},
            tmp_path,
            duration=1.0,
            aspect="16:9",
            seed=1,
        )
    with pytest.raises(CapabilityError):
        # payoff without chapter
        cap.render_safe(
            {"work": WORK, "action": "payoff", "entry_id": "fs-1"},
            tmp_path,
            duration=1.0,
            aspect="16:9",
            seed=1,
        )
    with pytest.raises(CapabilityError):
        # unknown action
        cap.render_safe(
            {"work": WORK, "action": "explode"},
            tmp_path,
            duration=1.0,
            aspect="16:9",
            seed=1,
        )
    with pytest.raises(CapabilityError):
        # extra params are refused
        cap.render_safe(
            {"work": WORK, "action": "list", "bogus": 1},
            tmp_path,
            duration=1.0,
            aspect="16:9",
            seed=1,
        )


def test_canon_check_rejects_invalid_params(tmp_path: Path) -> None:
    cap = caps.get("story.canon_check")
    with pytest.raises(CapabilityError):
        cap.render_safe({}, tmp_path, duration=1.0, aspect="16:9", seed=1)
    with pytest.raises(CapabilityError):
        # add_fact without value / source_chapter
        cap.render_safe(
            {"work": WORK, "action": "add_fact", "fact": "f", "subject": "s", "attribute": "a"},
            tmp_path,
            duration=1.0,
            aspect="16:9",
            seed=1,
        )
    with pytest.raises(CapabilityError):
        # check without claims
        cap.render_safe(
            {"work": WORK, "action": "check"},
            tmp_path,
            duration=1.0,
            aspect="16:9",
            seed=1,
        )
    with pytest.raises(CapabilityError):
        # claim missing its value
        cap.render_safe(
            {"work": WORK, "action": "check", "claims": [{"subject": "s", "attribute": "a"}]},
            tmp_path,
            duration=1.0,
            aspect="16:9",
            seed=1,
        )


# ---------------------------------------------------------------------------
# Foreshadowing flows
# ---------------------------------------------------------------------------


def test_foreshadow_plant_payoff_flow(tmp_path: Path) -> None:
    base = tmp_path / "bible"
    out = tmp_path / "out"

    _plant_knife(out, base)

    listed = _render(
        "story.foreshadow",
        {"work": WORK, "action": "list", "base_dir": str(base)},
        out,
    )
    assert listed.qa["count"] == 1
    entry = listed.qa["entries"][0]
    assert entry["id"] == "fs-knife"
    assert entry["status"] == "planted"
    assert entry["expected_start"] == 8 and entry["expected_end"] == 10

    result = _render(
        "story.foreshadow",
        {
            "work": WORK,
            "action": "payoff",
            "base_dir": str(base),
            "entry_id": "fs-knife",
            "chapter": 9,
        },
        out,
    )
    assert result.qa["entry"]["status"] == "paid_off"
    assert result.qa["entry"]["payoff_chapter"] == 9

    # The report artefact is real, fingerprinted, and verifiable on disk.
    report = Path(result.qa["report_json"])
    assert report.is_file()
    assert result.sha256 == compute_sha256(report)
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["action"] == "payoff"
    assert payload["entry"]["id"] == "fs-knife"

    # The ledger itself persisted the payoff (fresh instance, same files).
    reloaded = ForeshadowLedger(WORK, base_dir=base)
    assert reloaded.get("fs-knife").status == "paid_off"

    # A paid-off setup cannot pay off twice; unknown ids fail loudly.
    with pytest.raises(CapabilityError):
        _render(
            "story.foreshadow",
            {"work": WORK, "action": "payoff", "base_dir": str(base),
             "entry_id": "fs-knife", "chapter": 10},
            out,
        )
    with pytest.raises(CapabilityError):
        _render(
            "story.foreshadow",
            {"work": WORK, "action": "payoff", "base_dir": str(base),
             "entry_id": "fs-nope", "chapter": 10},
            out,
        )

    report.unlink()
    assert not report.exists()
    with pytest.raises(CapabilityError):
        compute_sha256(report)  # contract: deleting the artifact breaks verification


def test_foreshadow_overdue_alarm(tmp_path: Path) -> None:
    base = tmp_path / "bible"
    out = tmp_path / "out"
    _render(
        "story.foreshadow",
        {"work": WORK, "action": "plant", "base_dir": str(base),
         "entry_id": "fs-bell", "description": "桥头铜铃无风自响",
         "planted_chapter": 1, "expected_start": 3, "expected_end": 5},
        out,
    )
    _render(
        "story.foreshadow",
        {"work": WORK, "action": "plant", "base_dir": str(base),
         "entry_id": "fs-map", "description": "半张河道图藏在族谱夹层",
         "planted_chapter": 2, "expected_start": 10, "expected_end": 12},
        out,
    )

    # Chapter 4: still inside both windows — no alarm.
    early = _render(
        "story.foreshadow",
        {"work": WORK, "action": "check_overdue", "base_dir": str(base), "current_chapter": 4},
        out,
    )
    assert early.qa["count"] == 0

    # Chapter 7: the bell's window (ends 5) has passed, the map's has not.
    alarm = _render(
        "story.foreshadow",
        {"work": WORK, "action": "check_overdue", "base_dir": str(base), "current_chapter": 7},
        out,
    )
    assert alarm.qa["count"] == 1
    assert alarm.qa["overdue"][0]["id"] == "fs-bell"
    assert alarm.qa["overdue"][0]["status"] == "overdue"

    # The alarm state is persisted, and a late payoff still closes the setup.
    reloaded = ForeshadowLedger(WORK, base_dir=base)
    assert reloaded.get("fs-bell").status == "overdue"
    late = _render(
        "story.foreshadow",
        {"work": WORK, "action": "payoff", "base_dir": str(base),
         "entry_id": "fs-bell", "chapter": 8},
        out,
    )
    assert late.qa["entry"]["status"] == "paid_off"
    assert late.qa["entry"]["payoff_chapter"] == 8


def test_foreshadow_abandon_flow(tmp_path: Path) -> None:
    base = tmp_path / "bible"
    out = tmp_path / "out"
    _plant_knife(out, base)

    result = _render(
        "story.foreshadow",
        {"work": WORK, "action": "abandon", "base_dir": str(base),
         "entry_id": "fs-knife", "note": "改线：守桥人支线整体删除"},
        out,
    )
    assert result.qa["entry"]["status"] == "abandoned"

    listed = _render(
        "story.foreshadow",
        {"work": WORK, "action": "list", "base_dir": str(base), "status": "abandoned"},
        out,
    )
    assert listed.qa["count"] == 1

    with pytest.raises(CapabilityError):
        _render(
            "story.foreshadow",
            {"work": WORK, "action": "payoff", "base_dir": str(base),
             "entry_id": "fs-knife", "chapter": 9},
            out,
        )


def test_foreshadow_invalid_window_rejected(tmp_path: Path) -> None:
    out = tmp_path / "out"
    with pytest.raises(CapabilityError):
        # window starts before the setup is even planted
        _render(
            "story.foreshadow",
            {"work": WORK, "action": "plant", "base_dir": str(tmp_path),
             "description": "x", "planted_chapter": 5,
             "expected_start": 3, "expected_end": 6},
            out,
        )
    with pytest.raises(CapabilityError):
        # window end before window start
        _render(
            "story.foreshadow",
            {"work": WORK, "action": "plant", "base_dir": str(tmp_path),
             "description": "x", "planted_chapter": 1,
             "expected_start": 6, "expected_end": 4},
            out,
        )


# ---------------------------------------------------------------------------
# Canon flows
# ---------------------------------------------------------------------------


def _add_weapon_fact(out_dir: Path, base: Path) -> None:
    _render(
        "story.canon_check",
        {
            "work": WORK,
            "action": "add_fact",
            "base_dir": str(base),
            "fact_id": "fact-knife",
            "fact": "林雾惯用一把祖传短刀，从不离身",
            "subject": "林雾",
            "attribute": "惯用武器",
            "value": "短刀",
            "source_chapter": 3,
            "tags": ["人物", "武器"],
        },
        out_dir,
    )


def test_canon_check_detects_contradiction_and_passes_clean(tmp_path: Path) -> None:
    base = tmp_path / "bible"
    out = tmp_path / "out"
    _add_weapon_fact(out, base)

    bad = _render(
        "story.canon_check",
        {"work": WORK, "action": "check", "base_dir": str(base),
         "claims": [{"subject": "林雾", "attribute": "惯用武器", "value": "长剑"}]},
        out,
    )
    assert bad.qa["ok"] is False
    assert bad.qa["checked"] == 1
    contradiction = bad.qa["contradictions"][0]
    assert contradiction["canon_value"] == "短刀"
    assert contradiction["claimed_value"] == "长剑"
    assert contradiction["canon_fact_id"] == "fact-knife"
    assert contradiction["source_chapter"] == 3
    assert contradiction["reason"] == "rule"

    good = _render(
        "story.canon_check",
        {"work": WORK, "action": "check", "base_dir": str(base),
         "claims": [
             {"subject": "林雾", "attribute": "惯用武器", "value": "短刀"},
             {"subject": "林雾", "attribute": "籍贯", "value": "雾桥镇"},  # not in canon yet
         ]},
        out,
    )
    assert good.qa["ok"] is True
    assert good.qa["checked"] == 2
    assert good.qa["contradictions"] == []

    report = Path(good.qa["report_json"])
    assert report.is_file()
    assert good.sha256 == compute_sha256(report)
    report.unlink()
    with pytest.raises(CapabilityError):
        compute_sha256(report)  # contract: deleting the artifact breaks verification


def test_canon_add_fact_conflict_rejected_and_idempotent(tmp_path: Path) -> None:
    base = tmp_path / "bible"
    out = tmp_path / "out"
    _add_weapon_fact(out, base)

    # Same subject/attribute/value again: idempotent, still one fact.
    again = _render(
        "story.canon_check",
        {"work": WORK, "action": "add_fact", "base_dir": str(base),
         "fact": "林雾惯用一把祖传短刀，从不离身", "subject": "林雾",
         "attribute": "惯用武器", "value": "短刀", "source_chapter": 3},
        out,
    )
    assert again.qa["fact"]["id"] == "fact-knife"
    listed = _render(
        "story.canon_check",
        {"work": WORK, "action": "list", "base_dir": str(base)},
        out,
    )
    assert listed.qa["count"] == 1

    # Same subject/attribute, different value: canon conflict, refused.
    with pytest.raises(CapabilityError):
        _render(
            "story.canon_check",
            {"work": WORK, "action": "add_fact", "base_dir": str(base),
             "fact": "林雾改用长剑", "subject": "林雾",
             "attribute": "惯用武器", "value": "长剑", "source_chapter": 9},
            out,
        )


# ---------------------------------------------------------------------------
# Ledger-level logic (injected semantic checker, atomic writes)
# ---------------------------------------------------------------------------


def test_check_claims_checker_fn_overrides_rule(tmp_path: Path) -> None:
    ledger = CanonLedger(WORK, base_dir=tmp_path)
    ledger.add_fact(
        fact="林雾惯用一把祖传短刀",
        subject="林雾",
        attribute="惯用武器",
        value="短刀",
        source_chapter=3,
    )
    claim = {"subject": "林雾", "attribute": "惯用武器", "value": "短刀（祖传）"}

    # The bare rule sees a different value string and flags it...
    bare = check_claims_against_canon([claim], ledger)
    assert bare["ok"] is False
    assert bare["contradictions"][0]["reason"] == "rule"

    # ...but an injected semantic checker can clear the pair.
    def semantic(c: dict, fact) -> bool | None:
        return False if c["value"].startswith(fact.value) else None

    cleared = check_claims_against_canon([claim], ledger, checker_fn=semantic)
    assert cleared["ok"] is True

    # And it can flag a pair the rule considers identical.
    def paranoid(c: dict, fact) -> bool | None:
        return True

    flagged = check_claims_against_canon(
        [{"subject": "林雾", "attribute": "惯用武器", "value": "短刀"}],
        ledger,
        checker_fn=paranoid,
    )
    assert flagged["ok"] is False
    assert flagged["contradictions"][0]["reason"] == "checker"


def test_ledger_writes_are_atomic_and_persistent(tmp_path: Path) -> None:
    fore = ForeshadowLedger(WORK, base_dir=tmp_path)
    fore.plant("桥洞刻痕", 2, 8, 10, entry_id="fs-1")
    fore.payoff("fs-1", 9)
    canon = CanonLedger(WORK, base_dir=tmp_path)
    canon.add_fact(
        fact="雾桥镇每年汛期封桥",
        subject="雾桥镇",
        attribute="汛期习俗",
        value="封桥",
        source_chapter=1,
    )

    # Atomic writes leave exactly the two ledger files — no temp residue.
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["雾桥长篇.canon.json", "雾桥长篇.foreshadow.json"]

    # A fresh instance reads back exactly what was written.
    fore2 = ForeshadowLedger(WORK, base_dir=tmp_path)
    entry = fore2.get("fs-1")
    assert entry is not None and entry.status == "paid_off" and entry.payoff_chapter == 9
    canon2 = CanonLedger(WORK, base_dir=tmp_path)
    assert canon2.find("雾桥镇", "汛期习俗")[0].value == "封桥"
