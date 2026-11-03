"""Tests for the open-3d B2 browser check executor (clean-room).

Real Playwright runs against local fixture pages only: a clean
fixture must pass the full Chromium + WebKit x 1440/768/390
matrix with exit code 0, and a fixture with a blank canvas, a
wide overflowing element, and a 404 fetch must fail every shot
with exit code 1. Browser runs are skipped, with the reason
stated, when either matrix browser cannot launch on the host;
the plan-validation negatives always run. No URL outside the
loopback fixture server is ever requested.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.capabilities import get as _get_capability
from hevi.capabilities.browser_check_executor import (
    browsers_available,
    run_browser_check,
)
from hevi.capabilities.browser_check_matrix import check_browser_check_report
from hevi.capabilities.errors import CapabilityError

_AVAILABILITY = browsers_available()
BROWSERS_OK = all(_AVAILABILITY.values())

_CLEAN_INDEX = """<!doctype html><html><head><meta charset="utf-8">
<style>body{margin:0;font-family:sans-serif}h1{font-size:20px}</style>
</head><body><h1>clean fixture</h1>
<canvas id="c" width="200" height="100"></canvas>
<script>
window.__ready = true;
const ctx = document.getElementById('c').getContext('2d');
ctx.fillStyle = '#224466'; ctx.fillRect(0, 0, 100, 100);
ctx.fillStyle = '#cc8833'; ctx.fillRect(100, 0, 100, 100);
</script></body></html>"""

_CLEAN_SECOND = """<!doctype html><html><head><meta charset="utf-8"></head>
<body><h1>second fixture</h1>
<script>window.__ready = true;</script></body></html>"""

_BAD_INDEX = """<!doctype html><html><head><meta charset="utf-8">
<style>body{margin:0}.wide{width:2000px;height:20px;background:#333}</style>
</head><body><div class="wide"></div>
<canvas id="c" width="200" height="100"></canvas>
<script>
window.__ready = true;
const ctx = document.getElementById('c').getContext('2d');
ctx.fillStyle = '#aa2222'; ctx.fillRect(0, 0, 200, 100);
fetch('/missing.json').catch(() => {});
</script></body></html>"""

_NEVER_READY = """<!doctype html><html><head><meta charset="utf-8"></head>
<body><h1>never ready</h1></body></html>"""


def _plan(deep_links):
    return {
        "matrix": {
            "browsers": ["chromium", "webkit"],
            "widths": [1440, 768, 390],
            "deep_links": deep_links,
            "ready": "window.__ready === true",
            "wait_ms": 200,
        },
        "unexamined": ["reduced-motion pass", "seam/loop checks", "long sessions"],
        "failure": {
            "exit_code_on_failure": 1,
            "conditions": [
                "page_error", "http_4xx", "http_5xx",
                "blank_canvas", "horizontal_overflow",
            ],
        },
    }


def _clean_fixtures():
    return {"/": _CLEAN_INDEX, "/second": _CLEAN_SECOND}


@pytest.mark.skipif(not BROWSERS_OK, reason=f"matrix browsers unavailable: {_AVAILABILITY}")
def test_b2_clean_fixture_passes_full_matrix(tmp_path):
    report = run_browser_check(
        _plan(["/", "/second"]), _clean_fixtures(), out_dir=tmp_path
    )
    assert report["verdict"] == "pass", report["shot_detail"]
    assert report["exit_code"] == 0
    assert report["shots_checked"] == 12
    assert report["saw_failure"] is False
    assert report["local_only"] is True
    assert set(report["browser_executables"]) == {"chromium", "webkit"}
    assert report["unexamined"] == [
        "reduced-motion pass", "seam/loop checks", "long sessions",
    ]
    for shot in report["shots"]:
        assert shot["failures"] == []
        assert Path(shot["screenshot"]).is_file()
    assert Path(report["contact_sheet"]).is_file()
    gate = check_browser_check_report(
        {"shots": report["shots"], "exit_code": report["exit_code"]}
    )
    assert gate["verdict"] == "pass", gate["issues"]


@pytest.mark.skipif(not BROWSERS_OK, reason=f"matrix browsers unavailable: {_AVAILABILITY}")
def test_b2_bad_fixture_fails_every_shot_with_exit_1(tmp_path):
    report = run_browser_check(
        _plan(["/"]), {"/": _BAD_INDEX}, out_dir=tmp_path
    )
    assert report["verdict"] == "fail"
    assert report["exit_code"] == 1
    assert report["shots_checked"] == 6
    for shot in report["shots"]:
        assert "blank_canvas" in shot["failures"], shot
        assert "horizontal_overflow" in shot["failures"], shot
        assert "http_4xx" in shot["failures"], shot
    assert Path(report["contact_sheet"]).is_file()


@pytest.mark.skipif(not BROWSERS_OK, reason=f"matrix browsers unavailable: {_AVAILABILITY}")
def test_b2_ready_timeout_fails_closed_without_report(tmp_path):
    with pytest.raises(CapabilityError, match="ready expression"):
        run_browser_check(_plan(["/"]), {"/": _NEVER_READY}, out_dir=tmp_path)


def test_b2_registered_on_the_registry():
    capability = _get_capability("qa.browser_check_executor")
    assert capability.name == "qa.browser_check_executor"


def test_b2_non_local_deep_link_fails_closed(tmp_path):
    plan = _plan(["https://example.com/"])
    with pytest.raises(CapabilityError, match="local"):
        run_browser_check(plan, _clean_fixtures(), out_dir=tmp_path)


def test_b2_deep_link_without_fixture_fails_closed(tmp_path):
    with pytest.raises(CapabilityError, match="no fixture page"):
        run_browser_check(_plan(["/absent"]), _clean_fixtures(), out_dir=tmp_path)


def test_b2_plan_missing_webkit_fails_closed(tmp_path):
    plan = _plan(["/"])
    plan["matrix"]["browsers"] = ["chromium"]
    with pytest.raises(CapabilityError, match="qa.browser_check_matrix"):
        run_browser_check(plan, _clean_fixtures(), out_dir=tmp_path)


def test_b2_empty_fixture_pages_fails_closed(tmp_path):
    with pytest.raises(CapabilityError, match="fixture_pages"):
        run_browser_check(_plan(["/"]), {}, out_dir=tmp_path)
