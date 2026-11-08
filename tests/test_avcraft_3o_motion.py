"""avcraft 3O · Motion Prompt 接入测试：词条库、检索、术语注入、ffmpeg 动效映射、标题卡、分镜充实。
CPU + ffmpeg；不联网、不调模型。词条：showheyohtaki/motion-prompt（MIT (c) 2026 Shohei Ohtaki）。"""

import json
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("hevi.avcraft.oskill.shotprompt")  # deferred at admission 2026-11-04 (origin/main)

from hevi.avcraft.obase.media import ffmpeg_bin, probe_duration
from hevi.avcraft.obase.motion_catalog import CREDIT, motion_catalog_load, motion_get
from hevi.avcraft.obase.text_layer import render_text_png
from hevi.avcraft.omodul.storyboard_enrich import storyboard_enrich
from hevi.avcraft.omodul.title_card import title_card_compose
from hevi.avcraft.oskill.motion import (
    SUPPORTED,
    motion_search,
    motion_spec_to_ffmpeg,
    shot_vocab_inject,
    vocab_line,
)
from hevi.avcraft.oskill.shotprompt import compile_shot_prompt

ROOT = Path(__file__).resolve().parents[1]
SHOT_TABLE = ROOT / "output" / "avcraft_p1" / "seq" / "shot_table.json"


@pytest.fixture(scope="module")
def cat():
    return motion_catalog_load()


def test_catalog_loads_with_credit_and_license(cat):
    assert len(cat["elements"]) >= 100 and cat["credit"] == CREDIT
    assert "MIT" in CREDIT
    base = Path(cat["base"])
    assert (base / "LICENSE").exists() and "Shohei Ohtaki" in (base / "LICENSE").read_text()
    for key in ("027", "27", "#027", "dolly-in"):
        e = motion_get(cat, key)
        assert e and e["id"] == "027"


def test_search_zh_en_and_packs(cat):
    r = motion_search(cat, "慢推 dolly in", packs=["camera"], k=3)
    assert r and r[0]["id"] == "027" and all(x["pack"] == "camera" for x in r)
    assert motion_search(cat, "", k=3) == []
    assert any(x["id"] == "118" for x in motion_search(cat, "35mm film grain", packs=["photo"], k=3))


def test_vocab_inject_dedup_and_prompt_terms(cat):
    shot = {"id": "s1", "duration_s": 4, "camera": {"size": "WS", "move": "push-in"}, "characters": [],
            "action": "a cup on a table", "end_frame": "cup centered"}
    s = shot_vocab_inject(shot, ["027", "dolly-in", "118"], cat)
    assert [v["id"] for v in s["vocab"]] == ["027", "118"] and "vocab" not in shot
    assert vocab_line(s["vocab"]).startswith("Terms:")
    r = compile_shot_prompt(s, {"aspect": "9:16", "characters": {}, "locations": {}}, None, prescreen=False)
    assert "Terms:" in r["prompt"] and "Dolly" in r["prompt"]
    r0 = compile_shot_prompt(shot, {"aspect": "9:16", "characters": {}, "locations": {}}, None, prescreen=False)
    assert "Terms:" not in r0["prompt"]  # 向后兼容


def test_spec_mapping_kinds_and_errors():
    kinds = {k: motion_spec_to_ffmpeg(k, duration=2)["kind"] for k in SUPPORTED}
    assert kinds["001"] == kinds["005"] == kinds["006"] == "title"
    assert kinds["112"] == "vf" and kinds["044"] == "xfade"
    x = motion_spec_to_ffmpeg("cross-dissolve", duration=0.5, a_duration=3)
    assert "xfade" in x["filter"] and "Shohei Ohtaki" in x["credit"]
    with pytest.raises(KeyError):
        motion_spec_to_ffmpeg("no-such-motion")


def test_text_layer_char_x_monotonic(tmp_path):
    t = render_text_png("春日 ABC", tmp_path / "t.png", fontsize=48)
    assert Path(t["path"]).exists() and len(t["char_x"]) == 6
    assert t["char_x"] == sorted(t["char_x"]) and t["char_x"][-1] <= t["w"]


def _ymax(mp4, ts):
    out = subprocess.run([ffmpeg_bin(), "-hide_banner", "-ss", str(ts), "-i", str(mp4), "-frames:v", "1",
                          "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YMAX:file=-", "-f", "null", "-"],
                         capture_output=True, text=True).stdout
    return max([int(float(l.split("=")[1])) for l in out.splitlines() if "YMAX=" in l] or [0])


@pytest.mark.parametrize("m", ["pop-in", "typewriter", "mask-reveal"])
def test_title_card_motions_render(tmp_path, m):
    r = title_card_compose("新品上市", tmp_path / f"{m}.mp4", motion=m, w=360, h=640, duration=1.6,
                           start=0.1, fade_out=0.2, workdir=tmp_path / "w")
    assert Path(r["out"]).stat().st_size > 1000 and r["motion"] == m
    assert abs(probe_duration(r["out"]) - 1.6) < 0.2
    assert len(r["credits"]) == 2  # 动效 + vignette
    assert _ymax(r["out"], 1.1) > 150  # 文字已出现（白字）


def test_title_card_rejects_non_title():
    with pytest.raises(ValueError):
        title_card_compose("x", "/tmp/_never.mp4", motion="vignette")


@pytest.mark.skipif(not SHOT_TABLE.exists(), reason="no P1 shot_table sample")
def test_storyboard_enrich_p1_table(cat):
    table = json.loads(SHOT_TABLE.read_text(encoding="utf-8"))
    res = storyboard_enrich(table, catalog=cat)
    assert len(res["shots"]) == len(table["shots"]) and res["credit"] == CREDIT
    assert all(row["vocab"] for row in res["shots"])
    assert all("Terms:" in row["prompt"] for row in res["shots"])
    assert "Motion Prompt" in res["markdown"]
    assert "vocab" not in table["shots"][0]  # 不改原表
