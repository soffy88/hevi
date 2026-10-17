"""镜头配方卡库 + 场景尺度规则测试(2026-07-26)。"""

from __future__ import annotations

from hevi.director.multirole_reference import _reverse_shot_directive
from hevi.director.pipeline_schemas import SceneScriptDialogueLine, SceneScriptSegment
from hevi.director.shot_recipes import (
    RECIPES,
    ots_directive,
    palace_scale_directive,
)


def test_recipe_registry_has_first_batch() -> None:
    for name in ("廷议过肩反打", "君主御座裁决", "宫殿纵深仰拍", "城门市井全景", "文物道具特写"):
        assert name in RECIPES
        r = RECIPES[name]
        assert r.applies_to and r.framing and r.composition  # 卡有元数据


def test_master_directive_carries_palace_scale() -> None:
    # ★ 宫殿纵深仰拍进 master 建立镜(治"大殿不宏伟")
    d = _reverse_shot_directive(SceneScriptSegment(shot_type="master"))
    scale = palace_scale_directive()
    assert "低机位仰拍" in d and "纵深" in d
    assert scale in d  # master 叠加了尺度卡


def test_reverse_directives_sourced_from_recipes() -> None:
    seg = SceneScriptSegment(
        shot_type="ots",
        speaker_side="画左",
        foreground_character="李斯",
        dialogue=[SceneScriptDialogueLine(character_name="王绾", text="x")],
    )
    # multirole 的指令 == 配方卡函数产的(卡是唯一真源)
    assert _reverse_shot_directive(seg) == ots_directive(
        speaker="王绾", speaker_side="画左", foreground="李斯"
    )


def test_palace_scale_directive_content() -> None:
    d = palace_scale_directive()
    assert "广角" in d and "仰拍" in d and "纵深" in d and "占比不大" in d
