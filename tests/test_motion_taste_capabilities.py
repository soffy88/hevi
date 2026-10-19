"""Tests for motion.review / motion.audit_plan / motion.perfcheck per CAPABILITY_CONTRACT.md.

契约要求：
- 注册后能被 list 查到；
- 用 schema 校验非法参数，必须报错；
- 渲染 2 秒的产物要通过 ffprobe 检查；
- 删除产物后，测试必须失败。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import hevi.capabilities  # noqa: F401 — importing registers motion.* capabilities
from hevi.capabilities.registry import CapabilityError, get, list_capabilities, resolve
from hevi.renderers.ffmpeg import resolve_ffprobe_bin

CAP_NAMES = ["motion.review", "motion.audit_plan", "motion.perfcheck"]

BAD_CODE = """
.card {
  transition: all 300ms ease-in;
  transform: scale(0);
}
.card:hover { transform: translateX(10px); }
"""

CLEAN_CODE = """
.card {
  transition: transform 200ms cubic-bezier(0.23, 1, 0.32, 1), opacity 200ms ease;
}
.card:active { transform: scale(0.97); }
@media (prefers-reduced-motion: reduce) {
  .card { transition: opacity 200ms ease; }
}
@media (hover: hover) and (pointer: fine) {
  .card:hover { transform: translateY(-2px); }
}
"""


def _params(name: str, tmp_path: Path) -> dict:
    if name == "motion.audit_plan":
        fixture = tmp_path / "fixture_src"
        fixture.mkdir(exist_ok=True)
        (fixture / "bad.css").write_text(BAD_CODE, encoding="utf-8")
        (fixture / "clean.css").write_text(CLEAN_CODE, encoding="utf-8")
        return {"repo_path": str(fixture), "effort": "quick"}
    return {"code": BAD_CODE, "language": "css", "context": "card"}


@pytest.mark.parametrize("name", CAP_NAMES)
def test_capability_registered_and_discoverable(name: str) -> None:
    cap = get(name)
    assert cap.name == name
    assert cap.kind == "line"
    assert "9:16" in cap.aspects and "16:9" in cap.aspects
    assert resolve(name).name == cap.name
    assert any(c.name == name for c in list_capabilities())
    assert cap.line == "motion_taste"


@pytest.mark.parametrize("name", CAP_NAMES)
def test_capability_schema_validation_rejects_invalid_params(name: str, tmp_path: Path) -> None:
    cap = get(name)
    # 合法参数通过
    assert cap.validate_params(_params(name, tmp_path)) == _params(name, tmp_path)

    # 非法枚举值报错
    bad = dict(_params(name, tmp_path))
    if name == "motion.audit_plan":
        bad["effort"] = "ultra"
        with pytest.raises(CapabilityError, match="ultra"):
            cap.validate_params(bad)
    else:
        bad["language"] = "cobol"
        with pytest.raises(CapabilityError, match="cobol"):
            cap.validate_params(bad)

    # 多余未知参数报错
    with pytest.raises(CapabilityError, match="Additional properties are not allowed"):
        cap.validate_params({**_params(name, tmp_path), "bogus_key": 123})

    # 缺失必填参数报错
    with pytest.raises(CapabilityError):
        cap.validate_params({})


@pytest.mark.parametrize("name", CAP_NAMES)
def test_capability_render_2s_product_and_ffprobe_check(name: str, tmp_path: Path) -> None:
    cap = get(name)
    out_dir = tmp_path / "cap_render"

    res = cap.render(_params(name, tmp_path), out_dir, duration=2.0, aspect="9:16", seed=7)

    assert res.duration_s == 2.0
    assert res.mp4 is not None
    mp4_file = Path(res.mp4)
    assert mp4_file.is_file() and mp4_file.stat().st_size > 0
    assert len(res.sha256) == 64
    assert res.qa["rules_version"] == "taste-r1"
    assert Path(res.qa["report_md"]).is_file()
    assert Path(res.qa["report_json"]).is_file()

    # ffprobe 检查时长（2.00s ± 0.1s）与分辨率 (320x568)
    probe_cmd = [
        resolve_ffprobe_bin(), "-v", "error",
        "-show_entries", "format=duration:stream=width,height",
        "-of", "json", str(mp4_file),
    ]
    probe_res = subprocess.run(probe_cmd, check=True, capture_output=True, text=True)
    probe_data = json.loads(probe_res.stdout)
    assert abs(float(probe_data["format"]["duration"]) - 2.0) <= 0.1
    video_stream = next(s for s in probe_data["streams"] if "width" in s)
    assert (video_stream["width"], video_stream["height"]) == (320, 568)

    # 删除产物后，检验必须失败
    mp4_file.unlink()
    assert not mp4_file.exists()
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.run(probe_cmd, check=True, capture_output=True, text=True)


def test_review_blocks_bad_code_and_approves_clean(tmp_path: Path) -> None:
    cap = get("motion.review")
    bad = cap.render({"code": BAD_CODE, "language": "css"},
                     tmp_path / "bad", duration=2.0, aspect="16:9", seed=1)
    assert bad.qa["verdict"] == "Block"
    rules = {f["rule"] for f in json.loads(Path(bad.qa["report_json"]).read_text())["findings"]}
    assert {"transition_all", "scale_zero", "ease_in"} <= rules

    good = cap.render({"code": CLEAN_CODE, "language": "css"},
                      tmp_path / "good", duration=2.0, aspect="16:9", seed=1)
    assert good.qa["verdict"] == "Approve"
    assert good.qa["findings_count"] == 0


def test_perfcheck_diagnoses_causes(tmp_path: Path) -> None:
    cap = get("motion.perfcheck")
    code = ".box { transition: all 200ms; }\n.list { width: 100px; transition: width 300ms; }"
    res = cap.render({"code": code, "language": "css"}, tmp_path / "p",
                     duration=2.0, aspect="16:9", seed=1)
    rules = {d["rule"] for d in
             json.loads(Path(res.qa["report_json"]).read_text())["diagnoses"]}
    assert "transition_all" in rules and "layout_props" in rules


def test_audit_writes_plans(tmp_path: Path) -> None:
    cap = get("motion.audit_plan")
    out_dir = tmp_path / "audit"
    res = cap.render(_params("motion.audit_plan", tmp_path), out_dir,
                     duration=2.0, aspect="16:9", seed=1)
    assert res.qa["files_scanned"] == 2
    assert res.qa["findings_total"] > 0
    plans = res.qa["plans"]
    assert plans, "expected at least one implementation plan"
    for p in plans:
        assert (out_dir / p).is_file()
    assert (out_dir / "plans" / "README.md").is_file()


def test_render_is_deterministic_for_same_seed(tmp_path: Path) -> None:
    cap = get("motion.review")
    params = {"code": BAD_CODE, "language": "css"}
    r1 = cap.render(params, tmp_path / "a", duration=2.0, aspect="16:9", seed=42)
    r2 = cap.render(params, tmp_path / "b", duration=2.0, aspect="16:9", seed=42)
    j1 = json.loads(Path(r1.qa["report_json"]).read_text())["findings"]
    j2 = json.loads(Path(r2.qa["report_json"]).read_text())["findings"]
    assert j1 == j2
    assert r1.qa["verdict"] == r2.qa["verdict"]
