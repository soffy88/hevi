"""Unit tests for explainer.script capability and oral script pipeline."""

import pytest
from pathlib import Path

from hevi.capabilities import get
from hevi.explainer.script import (
    OralScript,
    compute_script_diff,
    create_oral_script,
    edit_section,
    extract_key_terms,
    load_script,
    oralize_text,
    register_explainer_script_capability,
    save_script,
)


@pytest.fixture(autouse=True)
def ensure_capability():
    register_explainer_script_capability()


def test_oralize_text_replacements():
    written = "众所周知，量子纠缠是一种非常奇特的微观物理现象。显而易见，因而它引起了广泛关注。例如在通信领域。"
    oral = oralize_text(written)
    assert "大家肯定经常听说" in oral
    assert "其实很明显" in oral
    assert "所以呢" in oral
    assert "比方说" in oral


def test_extract_key_terms():
    sample = "在量子计算中，“叠加态”和“量子纠缠”是两个核心概念，薛定谔的猫理论也是经典模型。"
    terms = extract_key_terms(sample, max_terms=4)
    assert any("叠加态" in t for t in terms)
    assert any("量子纠缠" in t for t in terms)


def test_create_oral_script_segmentation_and_duration():
    article = (
        "人工智能正在深刻改变世界。\n\n"
        "深度学习模型通过神经网络结构自主学习海量数据特征，从而展现出惊人的推理能力。\n\n"
        "然而，算法模型也面临着计算资源与可解释性的巨大挑战。\n\n"
        "总结而言，人机协同将成为未来科技发展的重要趋势。"
    )
    script = create_oral_script(article, title="AI变革")
    assert script.title == "AI变革"
    assert len(script.sections) >= 3
    assert script.revision == 1
    assert script.version_id.startswith("v1_")
    assert script.total_chars > 50
    assert script.total_estimated_duration_s > 10.0


def test_edit_section_versioning_and_diff():
    article = "第一段文字。\n\n第二段文字。\n\n第三段文字。"
    s1 = create_oral_script(article, title="版本测试")
    assert s1.revision == 1

    s2 = edit_section(
        s1,
        section_index=1,
        new_oral_text="第二段经过主播重点优化后的口播台词，更有节奏感！",
        new_key_terms=["优化", "口播台词"],
    )
    assert s2.revision == 2
    assert s2.parent_version_id == s1.version_id
    assert s2.version_id != s1.version_id
    assert s2.sections[1].oral_text == "第二段经过主播重点优化后的口播台词，更有节奏感！"
    assert s2.sections[0].oral_text == s1.sections[0].oral_text

    diff = compute_script_diff(s1, s2)
    assert diff["is_identical"] is False
    assert diff["modified_ids"] == ["sec_01"]
    assert diff["affected_section_ids"] == ["sec_01"]
    assert "sec_00" in diff["unchanged_ids"]


def test_save_and_load_script(tmp_path: Path):
    article = "测试保存与加载。\n\n第二段测试内容。"
    script = create_oral_script(article, title="持久化测试")
    out_file = save_script(script, tmp_path)
    assert out_file.exists()

    loaded = load_script(out_file)
    assert loaded.script_id == script.script_id
    assert loaded.version_id == script.version_id
    assert len(loaded.sections) == len(script.sections)
    assert loaded.sections[0].oral_text == script.sections[0].oral_text


def test_capability_explainer_script(tmp_path: Path):
    cap = get("explainer.script")
    assert cap is not None

    # Test create action
    res_create = cap.render(
        params={
            "action": "create",
            "text": "众所周知，光合作用是植物将光能转化为化学能的过程。\n\n其核心机制在于叶绿素吸收光子并分解水分子释放氧气。",
            "title": "光合作用的奥秘",
        },
        out_dir=tmp_path / "script_run",
        duration=15.0,
        aspect="16:9",
        seed=42,
    )
    assert res_create.duration_s > 5.0
    assert res_create.qa["action"] == "create"
    assert res_create.qa["section_count"] == 2
    script_dict = res_create.qa["script_dict"]

    # Test edit action
    res_edit = cap.render(
        params={
            "action": "edit",
            "script": script_dict,
            "section_index": 0,
            "new_oral_text": "大家肯定经常听说，植物之所以能生长全靠神奇的光合作用。",
        },
        out_dir=tmp_path / "script_run",
        duration=15.0,
        aspect="16:9",
        seed=42,
    )
    assert res_edit.qa["action"] == "edit"
    assert res_edit.qa["revision"] == 2
