"""Manim SceneIR 编译器单测 —— 纯逻辑,不调 CLI。"""

from __future__ import annotations

from hevi.explainer.contracts import ExplainerCue
from hevi.prompt.manim_compiler import (
    ManimSceneIR,
    compile_manim_source,
    draft_scene_ir,
    resolve_scene_ir,
)
from hevi.providers.manim.sandbox import (
    ManimSandboxError,
    scene_class_name,
    validate_manim_source,
)


def test_draft_picks_equation_from_latex() -> None:
    ir = draft_scene_ir("能量公式是 $E = mc^2$，这改变了物理。")
    assert ir.recipe == "equation"
    assert ir.tex == "E = mc^2"


def test_draft_picks_transform_from_two_formulas() -> None:
    ir = draft_scene_ir("从 $F=ma$ 到 $F=dp/dt$")
    assert ir.recipe == "transform"
    assert ir.tex == "F=ma"
    assert ir.tex_to == "F=dp/dt"


def test_draft_picks_list_from_bullets() -> None:
    ir = draft_scene_ir("步骤:\n1. 定义问题\n2. 写出方程\n3. 求解")
    assert ir.recipe == "list_reveal"
    assert ir.bullets == ["定义问题", "写出方程", "求解"]


def test_compile_is_sandbox_clean() -> None:
    source = compile_manim_source(
        ManimSceneIR(recipe="equation", title="能量", tex="E = mc^2")
    )
    tree = validate_manim_source(source)
    assert tree is not None
    assert "from manim import *" in source
    assert "class HeviScene(Scene):" in source
    assert "Write(" in source
    assert scene_class_name(source) == "HeviScene"


def test_compile_gl_uses_manimlib() -> None:
    source = compile_manim_source(ManimSceneIR(tex="x"), engine="gl")
    assert source.startswith("from manimlib import *")
    validate_manim_source(source)


def test_sandbox_rejects_os_import() -> None:
    try:
        validate_manim_source("import os\nclass HeviScene:\n    pass\n")
    except ManimSandboxError as exc:
        assert "os" in str(exc)
    else:
        raise AssertionError("expected sandbox reject")


def test_sandbox_rejects_eval() -> None:
    try:
        validate_manim_source("from manim import *\neval('1')\n")
    except ManimSandboxError as exc:
        assert "eval" in str(exc)
    else:
        raise AssertionError("expected sandbox reject")


def test_resolve_from_cue_visual_config() -> None:
    cue = ExplainerCue(
        visual_type="manim_scene",
        text="旁白不该覆盖配方",
        time_estimate_s=8,
        visual_config={"recipe": "transform", "tex": "A", "tex_to": "B"},
    )
    ir = resolve_scene_ir(cue)
    assert ir.recipe == "transform"
    assert ir.tex == "A"
    assert ir.tex_to == "B"
    assert ir.duration_s == 8.0


def test_resolve_provider_dict() -> None:
    ir = resolve_scene_ir({"recipe": "equation", "tex": "F=ma", "duration_s": 4})
    assert ir.recipe == "equation"
    assert ir.tex == "F=ma"
    assert ir.duration_s == 4.0


def test_from_dict_unknown_recipe_falls_back() -> None:
    ir = ManimSceneIR.from_dict({"recipe": "flying_cow", "tex": "x"})
    assert ir.recipe == "equation"
