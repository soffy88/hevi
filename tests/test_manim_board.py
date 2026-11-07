"""Manim 数学板书:MathTex / 曲线 / TransformMatchingTex —— 编译单测 + 真实渲染。"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from hevi.explainer.contracts import ExplainerCue
from hevi.explainer.manim_scene import attach_manim_scenes
from hevi.prompt.manim_compiler import ManimSceneIR, compile_manim_source, safe_func_expr
from hevi.providers.manim.provider import detect_manim_bin, latex_available
from hevi.providers.manim.sandbox import validate_manim_source

DERIVE = ["(a+b)^2", "(a+b)(a+b)", "a^2 + 2ab + b^2"]


def test_safe_func_expr_whitelist():
    assert safe_func_expr("sin(x)*exp(-x^2/4)") == "np.sin(x)*np.exp(-x**2/4)"
    assert safe_func_expr("x^2 - 1") == "x**2 - 1"
    for bad in ("__import__('os')", "open(x)", "x; 1", "os.system(x)", "x" * 200, ""):
        assert safe_func_expr(bad) == ""


def test_derivation_uses_transform_matching_tex():
    ir = ManimSceneIR(recipe="derivation", steps=DERIVE, use_mathtex=True, duration_s=4)
    src = compile_manim_source(ir)
    validate_manim_source(src)
    assert src.count("MathTex(") == 3
    assert src.count("TransformMatchingTex(") == 2


def test_transform_falls_back_without_mathtex():
    ir = ManimSceneIR(recipe="transform", tex="a", tex_to="b")
    src = compile_manim_source(ir)
    assert "TransformMatchingTex" not in src and "Transform(src, dst)" in src


def test_curve_plot_compiles_and_rejects_bad_func():
    ir = ManimSceneIR.from_dict(
        {"recipe": "curve_plot", "func": "sin(x)", "tex": r"y=\sin x", "use_mathtex": True}
    )
    src = compile_manim_source(ir)
    validate_manim_source(src)
    assert "axes.plot(lambda x: np.sin(x)" in src and "Create(curve)" in src
    bad = compile_manim_source(ManimSceneIR(recipe="curve_plot", func="__import__('os')"))
    assert "__import__" not in bad and "np.sin(x)" in bad


def test_ir_roundtrip_new_fields():
    ir = ManimSceneIR(recipe="derivation", steps=DERIVE, func="x^2", x_range=[-2, 2])
    back = ManimSceneIR.from_dict(ir.to_dict())
    assert back.steps == DERIVE and back.func == "x^2" and back.x_range == [-2.0, 2.0]
    assert ManimSceneIR.from_dict({"x_range": [3, 1]}).x_range == [-3.0, 3.0]


needs_real = pytest.mark.skipif(
    not (detect_manim_bin("ce") and latex_available() and shutil.which("ffprobe")),
    reason="需要 manim CLI + LaTeX + ffprobe",
)


def _probe(path: Path) -> tuple[int, int, float]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "csv=p=0:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    return int(out[0].split(",")[0]), int(out[0].split(",")[1]), float(out[-1])


@needs_real
def test_real_render_board(tmp_path, monkeypatch, caplog):
    """真实 manim CLI + LaTeX 渲染三镜(公式写出/曲线/符号变换),走 attach_manim_scenes。"""
    monkeypatch.setenv("MANIM_USE_MATHTEX", "auto")
    caplog.set_level("INFO")
    cues = [
        ExplainerCue(text="勾股", visual_type="manim_scene", time_estimate_s=2.0,
                     visual_config={"recipe": "equation", "tex": r"a^2 + b^2 = c^2"}),
        ExplainerCue(text="曲线", visual_type="manim_scene", time_estimate_s=2.0,
                     visual_config={"recipe": "curve_plot", "func": "sin(x)*exp(-x^2/8)",
                                    "tex": r"y = \sin x \, e^{-x^2/8}",
                                    "x_range": [-6, 6], "y_range": [-1.2, 1.2]}),
        ExplainerCue(text="展开", visual_type="manim_scene", time_estimate_s=3.0,
                     visual_config={"recipe": "derivation", "steps": DERIVE}),
    ]
    out = asyncio.run(attach_manim_scenes(
        cues, tmp_path, width=640, height=360, quality="low", fps=15
    ))
    for cue in out:
        assert cue.visual_type == "manim_scene", "降级了=没真实渲染"
        assert cue.visual_config["manim_engine"] == "manim"
        mp4 = Path(cue.visual_config["assetUrl"])
        w, h, dur = _probe(mp4)
        assert (w, h) == (640, 360) and dur > 0.8
    logs = caplog.text
    assert logs.count("manim cli:") == 3
    assert "回退" not in logs, logs[-1500:]
