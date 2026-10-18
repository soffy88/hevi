import pytest
from hevi.stickman.structure_clone import (
    clone_structure,
    scale_durations,
    check_ngram_overlap,
    CopyViolationError,
    STAGES,
)


def test_scale_durations_proportional():
    # 5 ref segments totaling 50 seconds: [5, 10, 10, 15, 10]
    ref_durs = [5.0, 10.0, 10.0, 15.0, 10.0]
    # Scale to 60.0 seconds
    scaled = scale_durations(ref_durs, 60.0)
    assert len(scaled) == 5
    assert sum(scaled) == pytest.approx(60.0)
    assert scaled[0] == pytest.approx(6.0)
    assert scaled[1] == pytest.approx(12.0)
    assert scaled[2] == pytest.approx(12.0)
    assert scaled[3] == pytest.approx(18.0)
    assert scaled[4] == pytest.approx(12.0)


def test_clone_structure_success():
    ref_subtitles = [
        {"start": 0.0, "end": 6.0, "text": "为什么飞机飞得那么高，客舱里的人却不会缺氧？"},
        {"start": 6.0, "end": 18.0, "text": "大家都以为万米高空空气稀薄，常人上去就无法呼吸。"},
        {"start": 18.0, "end": 30.0, "text": "但飞机上根本没有供几百人呼吸的巨大氧气瓶！"},
        {"start": 30.0, "end": 48.0, "text": "真正奥秘是喷气发动机把冷空气压缩增温后直接送入机舱循环。"},
        {"start": 48.0, "end": 60.0, "text": "下次登机你敢大口呼吸吗？评论区留下你的看法！"},
    ]

    result = clone_structure(
        reference_script=ref_subtitles,
        new_topic="为什么冰块放水里浮起来，放油里却沉下去？",
        target_duration=60.0,
        enforce_anti_copy=True,
    )

    assert result["total_duration"] == 60.0
    assert len(result["stages"]) == 5
    stage_names = [s["stage_name"] for s in result["stages"]]
    assert stage_names == STAGES

    # Check fact-checking list
    assert "fact_check_list" in result
    assert len(result["fact_check_list"]) >= 2
    for item in result["fact_check_list"]:
        assert item["verified"] is True
        assert "source" in item


def test_ngram_overlap_detects_plagiarism():
    ref = "常识告诉我们水结冰体积会膨胀密度变小，我们总想当然地认为冰比所有液体都要轻。"
    # Directly copied identical sentence
    copied = "常识告诉我们水结冰体积会膨胀密度变小，我们总想当然地认为冰比所有液体都要轻。"
    audit = check_ngram_overlap(ref, copied)
    assert audit["is_violation"] is True
    assert audit["overlap_ratio"] > 0.8
    assert audit["longest_match_len"] >= 15

    # Completely different text
    different = "食用油的物理特性取决于脂肪酸分子的交织结构与表面张力变化。"
    audit2 = check_ngram_overlap(ref, different)
    assert audit2["is_violation"] is False
    assert audit2["overlap_ratio"] < 0.1


def test_clone_structure_raises_on_copy():
    # If the reference text is identical to what the generator produces, it must raise CopyViolationError
    identical_ref = [
        {"start": 0.0, "end": 10.0, "text": "同样是一块纯净冰块，为什么扔进水里欢快漂浮，扔进食用油里却瞬间直坠沉底？"},
        {"start": 10.0, "end": 20.0, "text": "常识告诉我们水结冰体积会膨胀、密度变小，所以我们总想当然地认为冰比所有液体都要轻。"},
        {"start": 20.0, "end": 30.0, "text": "但常识在这里骗了你！液体的密度千差万别，大家天天吃的植物油，密度其实比水还要轻得多！"},
        {"start": 30.0, "end": 45.0, "text": "揭开物理铁律：水密度是1.0，冰密度是0.917，而食用油密度只有0.91左右！比油重当然只能沉底！"},
        {"start": 45.0, "end": 60.0, "text": "设想一下，如果南极的海洋全部变成食用油，冰川还会浮在海面上吗？评论区留下你的硬核推论！"},
    ]

    with pytest.raises(CopyViolationError) as exc_info:
        clone_structure(
            reference_script=identical_ref,
            new_topic="为什么冰块放水里浮起来，放油里却沉下去？",
            target_duration=60.0,
            enforce_anti_copy=True,
        )
    assert "抄袭检测未通过" in str(exc_info.value)
