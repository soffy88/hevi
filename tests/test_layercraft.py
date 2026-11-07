import math, shutil
import numpy as np
import pytest
from PIL import Image, ImageDraw

from hevi.layercraft.oskill import svg_path as sp, timing as tm, paper_cut as pc
from hevi.layercraft.omodul import render as R


def test_rect_and_line_length():
    shapes, size = sp.parse_svg('<svg viewBox="0 0 100 50" width="100" height="50"><rect x="10" y="10" width="20" height="10"/><line x1="0" y1="0" x2="30" y2="40" stroke="#000"/></svg>')
    assert size == (100, 50)
    assert shapes[0].length == pytest.approx(60)
    assert shapes[1].length == pytest.approx(50)


def test_viewbox_scaling():
    shapes, size = sp.parse_svg('<svg viewBox="0 0 100 100"><line x1="0" y1="0" x2="100" y2="0"/></svg>', (200, 200))
    assert shapes[0].length == pytest.approx(200)


def test_circle_and_arc_length():
    shapes, _ = sp.parse_svg('<svg viewBox="0 0 200 200"><circle cx="100" cy="100" r="50"/></svg>')
    assert shapes[0].length == pytest.approx(2 * math.pi * 50, rel=0.01)
    (pts, _c), = sp.parse_path_d("M 0 0 A 50 50 0 0 1 100 0")
    assert sp.polyline_length(pts) == pytest.approx(math.pi * 50, rel=0.01)
    assert pts[-1] == (100, 0)


def test_relative_cubic_and_close():
    subs = sp.parse_path_d("m10 10 h20 v20 h-20 z M0 0 c 0 0 10 0 10 10")
    assert subs[0][1] is True and sp.polyline_length(subs[0][0]) == pytest.approx(80)
    assert subs[1][0][-1] == pytest.approx((10, 10))


def test_smooth_quadratic_T():
    (pts, _), = sp.parse_path_d("M0 0 Q 10 10 20 0 T 40 0")
    assert pts[-1] == pytest.approx((40, 0))
    assert min(y for _, y in pts) < -1  # reflected control goes the other way


def test_bad_path_raises():
    with pytest.raises(ValueError):
        sp.parse_path_d("M 0 0 L 10")


def test_trim_and_dash_state():
    pts = [(0, 0), (10, 0), (10, 10)]
    assert sp.trim_polyline(pts, 15)[-1] == pytest.approx((10, 5))
    assert sp.trim_polyline(pts, 99) == pts
    assert len(sp.trim_polyline(pts, 0)) == 1
    s0, s1 = sp.dash_state(20, 0), sp.dash_state(20, 1)
    assert s0["dashoffset"] == 20 and s0["visible"] == 0
    assert s1["dashoffset"] == 0 and s1["visible"] == 20


def test_transform_translate_scale():
    shapes, _ = sp.parse_svg('<svg viewBox="0 0 100 100"><g transform="translate(10,0) scale(2)"><line x1="0" y1="0" x2="10" y2="0"/></g></svg>')
    p = shapes[0].subpaths[0][0]
    assert p[0] == pytest.approx((10, 0)) and p[-1] == pytest.approx((30, 0))


def test_stagger_half_beat():
    assert tm.stagger_starts(6, bpm=120) == pytest.approx([0, .25, .5, .75, 1.0, 1.25])
    s = tm.layer_enter_state(0.0, 0.5)
    assert s["alpha"] == 0 and s["dy"] == pytest.approx(40)
    e = tm.layer_enter_state(5.0, 0.5)
    assert e["alpha"] == 1 and e["dy"] == 0 and e["stroke"] == 1


def test_boil_seed():
    seeds = [tm.boil_seed(f, 7, 3) for f in range(7)]
    assert seeds == [7, 7, 7, 8, 8, 8, 9]
    with pytest.raises(ValueError):
        tm.boil_seed(0, 0, 0)


def test_boiling_passes_change_every_hold_and_deterministic():
    pl = [[[0, 0], [100, 0], [100, 100]]]
    a0 = R.boiling_passes(pl, 0, hold=2); a1 = R.boiling_passes(pl, 1, hold=2); a2 = R.boiling_passes(pl, 2, hold=2)
    assert a0 == a1 and a0 != a2
    assert R.boiling_passes(pl, 2, hold=2) == a2


def _blocks():
    im = Image.new("RGB", (120, 80), (230, 230, 240))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 50, 120, 80], fill=(40, 120, 60)); d.ellipse([70, 5, 105, 40], fill=(240, 150, 40))
    return im


def test_paper_split_layers_deterministic_and_stacked():
    im = _blocks()
    L1, L2 = pc.split_layers(im, 3, seed=1), pc.split_layers(im, 3, seed=1)
    assert len(L1) == 3 and [l.color for l in L1] == [l.color for l in L2]
    assert np.asarray(L1[0].mask).min() == 255  # back sheet full
    # lower sheets cover the sheets above them (no gaps)
    assert (np.asarray(L1[1].mask) >= np.asarray(L1[2].mask)).all()
    with pytest.raises(ValueError):
        pc.split_layers(im, 1)


def test_paper_sheet_has_white_rim_and_shadow():
    m = Image.new("L", (60, 60), 0); ImageDraw.Draw(m).rectangle([20, 20, 40, 40], fill=255)
    sh = pc.paper_sheet(m, (200, 30, 30), border=4, grain=pc.paper_grain((60, 60), seed=0))
    a = np.asarray(sh)
    assert a[30, 30, 0] > 150 and a[30, 30, 1] < 80        # coloured core
    assert a[30, 18, 3] > 200 and a[30, 18, :3].min() > 220  # white rim outside the cut
    assert a[2, 2, 3] == 0
    assert np.asarray(pc.drop_shadow(sh))[30, 30, 3] > 0


def test_frames_render_progressively():
    svg = '<svg viewBox="0 0 64 36"><path d="M2 18 L62 18" stroke="#000" stroke-width="3" fill="none"/></svg>'
    fr = list(R.svg_draw_on_frames(svg, size=(64, 36), fps=10, duration=1.0, fill_fade=0.1))
    ink = [int((np.asarray(f.convert("L")) < 128).sum()) for f in fr]
    assert ink[0] < ink[len(ink) // 2] < ink[-1] or ink[-1] > ink[0]
    assert ink == sorted(ink)


def test_layered_reveal_layers_enter_in_order():
    svg = R.default_landscape_svg("T")
    assert [l[0] for l in R.split_svg_layers(svg)] == ["sky", "sun", "far_hills", "near_hills", "trees", "text"]
    fr = list(R.layered_reveal_frames(svg, size=(96, 54), fps=8, duration=2.5, bpm=120))
    diffs = [float(np.abs(np.asarray(fr[i + 1], float) - np.asarray(fr[i], float)).mean()) for i in range(len(fr) - 1)]
    assert diffs[-1] < max(diffs)  # settles at the end
    assert np.asarray(fr[0]).std() < np.asarray(fr[-1]).std()


def test_paper_cut_frames():
    fr = list(R.paper_cut_frames(_blocks(), k=3, size=(96, 54), fps=8, duration=2.0))
    assert len(fr) == 16 and fr[-1].size == (96, 54)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="no ffmpeg")
def test_encode_mp4(tmp_path):
    out = R.boiling_lines([[[10, 10], [80, 40]]], tmp_path / "b.mp4", size=(96, 54), fps=8, duration=0.5)
    assert out.stat().st_size > 500
