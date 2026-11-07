"""HyperFrames GSAP 暂停时间轴逐帧驱动测试。"""
from __future__ import annotations

import asyncio
import re

import pytest

from hevi.video.hyperframes_seek import (
    EmbedLayer, build_seek_page, custom_layer, frame_times, p5_layer, required_vendor,
    rough_layer, sequence_digest, three_layer,
)
from hevi.video.hyperframes_capture import seek_capture_available, vendor_paths


# ── oskill 纯函数 ──────────────────────────────────────────────
def test_frame_times_exact():
    ts = frame_times(24, 2.0)
    assert len(ts) == 48 and ts[0] == 0.0 and ts[24] == 1.0 and ts[-1] == 47 / 24


def test_frame_times_invalid():
    with pytest.raises(ValueError):
        frame_times(0, 1)
    with pytest.raises(ValueError):
        frame_times(24, 0)


def test_layer_validation():
    with pytest.raises(ValueError):
        EmbedLayer("svg", "a", "")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        rough_layer("bad id!", "")
    with pytest.raises(ValueError):
        rough_layer("a", "", reseed_every=-1)
    with pytest.raises(ValueError):
        build_seek_page("", layers=[rough_layer("a", ""), p5_layer("a", "")])


def test_page_is_local_only_and_paused():
    page = build_seek_page("<h1>x</h1>", gsap_script="tl.to('h1',{x:10,duration:1})",
                           layers=[rough_layer("r", ""), three_layer("t", "return ()=>{}"), p5_layer("p", "")])
    srcs = re.findall(r'src="([^"]+)"', page)
    assert srcs and all(s.startswith("/vendor/") for s in srcs)
    assert "cdn" not in page.lower() and "https://" not in page
    assert "gsap.timeline({paused: true})" in page and "Math.random = function" in page
    assert '"three": "/vendor/three.module.js"' in page
    assert 'data-composition-id="root"' in page


def test_page_deterministic_text():
    a = build_seek_page("<p>a</p>", layers=[custom_layer("c", "HF.registerLayer({seek(){}})")])
    b = build_seek_page("<p>a</p>", layers=[custom_layer("c", "HF.registerLayer({seek(){}})")])
    assert a == b


def test_required_vendor_and_files_present():
    assert required_vendor([three_layer("t", ""), rough_layer("r", "")]) == ["gsap", "three", "rough"]
    for name, p in vendor_paths().items():
        assert p.is_file(), name


def test_sequence_digest():
    assert sequence_digest(["a", "b"]) != sequence_digest(["b", "a"])


def test_legacy_unknown_driver(tmp_path):
    from hevi.video.hyperframes_service import render_html_video
    with pytest.raises(ValueError):
        asyncio.run(render_html_video("<p/>", tmp_path / "x.mp4", driver="nope"))


# ── 真实渲染（需 Playwright Chromium + ffmpeg）─────────────────
needs_browser = pytest.mark.skipif(not seek_capture_available(), reason="playwright chromium unavailable")

HTML = '<div id="b" style="position:absolute;left:0;top:20px;width:20px;height:20px;background:#f00"></div>' \
       '<div id="c" style="position:absolute;left:0;top:50px;width:10px;height:10px;background:#0f0;' \
       'animation:mv 1s linear forwards"></div><style>@keyframes mv{to{transform:translateX(100px)}}</style>'
GSAP = "tl.to('#b', {x: 120, rotation: 90, duration: 1, ease: 'power1.inOut'});"


def _render(tmp_path, name, fps, layers=()):
    from hevi.video.hyperframes_service import render_gsap_video
    return asyncio.run(render_gsap_video(HTML, tmp_path / f"{name}.mp4", width=160, height=90, fps=fps,
                                         duration=1.0, gsap_script=GSAP, layers=layers, crf=30))


@needs_browser
def test_gsap_seek_deterministic_and_time_exact(tmp_path):
    a = _render(tmp_path, "a", 6)
    b = _render(tmp_path, "b", 6)
    c = _render(tmp_path, "c", 12)
    assert a.success and b.success and c.success, (a.error, b.error, c.error)
    assert a.driver == "gsap" and a.frame_count == 6 and (tmp_path / "a.mp4").stat().st_size > 0
    assert a.frame_hashes == b.frame_hashes and a.sequence_hash == b.sequence_hash
    # 同一时刻 t=k/6 == 2k/12 → 同帧（证明是按时间 seek，而不是实时播放）
    assert all(a.frame_hashes[k] == c.frame_hashes[2 * k] for k in range(6))
    assert len(set(a.frame_hashes)) == 6  # 每帧都在动


@needs_browser
def test_embedded_layers_deterministic(tmp_path):
    layers = [
        rough_layer("r", "rc.rectangle(10,10,80,50,{seed: seed, stroke:'#fff'});", reseed_every=2),
        p5_layer("p", "p.clear(); p.fill(0,128,255); p.circle(20 + t*100, 60, 12 + p.random(4));"),
        three_layer("t", "const m=new THREE.Mesh(new THREE.BoxGeometry(1,1,1), new THREE.MeshNormalMaterial());"
                         "ctx.scene.add(m); return t=>{m.rotation.y=t*3;};"),
    ]
    a = _render(tmp_path, "la", 4, layers)
    b = _render(tmp_path, "lb", 4, layers)
    assert a.success and b.success, (a.error, b.error)
    assert a.frame_hashes == b.frame_hashes
    assert len(set(a.frame_hashes)) == 4


@needs_browser
def test_render_html_video_gsap_driver(tmp_path):
    from hevi.video.hyperframes_service import render_html_video
    r = asyncio.run(render_html_video(HTML, tmp_path / "d.mp4", width=160, height=90, fps=4, duration=0.5,
                                      gsap_script=GSAP, driver="gsap"))
    assert r.success and r.driver == "gsap" and r.frame_count == 2
