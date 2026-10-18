import pytest
from hevi.stickman.proposal import (
    DirectorProposal,
    create_proposal_from_script,
    ProposalNotApprovedError,
    ProposalModificationError,
    ProposalError,
)


def _sample_script_data():
    return {
        "topic": "为什么冰块放水里浮起来，放油里却沉下去？",
        "stages": [
            {"stage_name": "悬念追问", "narration": "同样是冰块，为什么扔进水里浮，扔进油里沉底？"},
            {"stage_name": "常识铺垫", "narration": "常识告诉我们水结冰变轻。"},
            {"stage_name": "反转", "narration": "但食用油密度其实比水更轻！"},
            {"stage_name": "揭秘", "narration": "揭秘：冰密度0.917，油只有0.91！比油重自然沉底！"},
            {"stage_name": "互动收尾", "narration": "如果南极变成油海冰山会沉吗？请在下方给出推论！"},
        ],
    }


def test_proposal_lifecycle_and_invariants():
    script = _sample_script_data()
    prop = create_proposal_from_script(script, aspect_ratio="16:9", art_style="classic_minimalist")

    # 1. Initial state is draft
    assert prop.status == "draft"
    assert prop.total_duration == 60.0
    assert len(prop.storyboard) == 6

    # 2. In draft stage, modifying aspect_ratio & art_style is allowed
    prop.update_settings(aspect_ratio="9:16", art_style="color_story")
    assert prop.aspect_ratio == "9:16"
    assert prop.art_style == "color_story"

    # 3. In draft stage, attempting to render or generate prompts MUST FAIL
    with pytest.raises(ProposalNotApprovedError):
        prop.assert_can_render()

    with pytest.raises(ProposalNotApprovedError):
        prop.assert_can_generate_prompts()

    # 4. Approve proposal
    prop.approve()
    assert prop.status == "approved"

    # Now rendering and prompt generation are authorized
    prop.assert_can_render()
    prop.assert_can_generate_prompts()

    # 5. In approved stage, modifying aspect_ratio or art_style MUST FAIL
    with pytest.raises(ProposalModificationError) as exc_ratio:
        prop.update_settings(aspect_ratio="16:9")
    assert "画幅与画风只能在提案草稿阶段" in str(exc_ratio.value)

    with pytest.raises(ProposalModificationError) as exc_style:
        prop.update_settings(art_style="classic_minimalist")
    assert "画幅与画风只能在提案草稿阶段" in str(exc_style.value)

    # 6. Reopen to draft allows modifications again
    prop.reopen()
    assert prop.status == "draft"
    prop.update_settings(aspect_ratio="16:9", art_style="classic_minimalist")
    assert prop.aspect_ratio == "16:9"
    assert prop.art_style == "classic_minimalist"
