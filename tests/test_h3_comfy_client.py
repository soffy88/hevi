"""h3_local comfy_client / 适配器单测 —— 占位符填参、ref 裁剪、Subject 适配(无网络)。"""

from __future__ import annotations

from pathlib import Path

from hevi.adapters.subject_to_h3_ref import subject_master_path, to_h3_refs
from hevi.providers.h3_local.comfy_client import ComfyClient

# ── 占位符填参 ─────────────────────────────────────────────────────────────


def _template() -> dict:
    return {
        "load": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "__UNET_GGUF__"}},
        "ref_0": {"class_type": "LoadImage", "inputs": {"image": "__REF_0__"}},
        "ref_1": {"class_type": "LoadImage", "inputs": {"image": "__REF_1__"}},
        "h3": {
            "class_type": "MiniMaxH3ReferenceToVideo",
            "inputs": {
                "prompt": "__PROMPT__",
                "length": "__LENGTH__",
                "seed": "__SEED__",
                "ref_image_0": ["ref_0", 0],
                "ref_image_1": ["ref_1", 0],
            },
        },
    }


def test_build_workflow_fills_placeholders_and_types() -> None:
    client = ComfyClient(base_url="http://127.0.0.1:1", serial=False)  # 无网络,只测纯函数
    wf = client.build_workflow(
        _template(),
        prompt="【场景】雨夜。",
        length=124,
        width=768,
        height=1344,
        seed=42,
        output_prefix="shot_001_v0",
        ref_images=[Path("/tmp/a.png"), Path("/tmp/b.png")],
        extra_fills={"__UNET_GGUF__": "minimax_h3_fl2va_pruned_w4a8_mixed.safetensors"},
    )
    assert wf["h3"]["inputs"]["prompt"] == "【场景】雨夜。"
    assert wf["h3"]["inputs"]["length"] == 124
    assert wf["h3"]["inputs"]["seed"] == 42
    assert wf["load"]["inputs"]["unet_name"] == "minimax_h3_fl2va_pruned_w4a8_mixed.safetensors"
    # 两张参考图 → 两个 LoadImage 都保留、链接都在
    assert "ref_0" in wf and "ref_1" in wf
    assert wf["h3"]["inputs"]["ref_image_1"] == ["ref_1", 0]


def test_build_workflow_trims_unused_refs() -> None:
    client = ComfyClient(base_url="http://127.0.0.1:1", serial=False)
    wf = client.build_workflow(
        _template(),
        prompt="p",
        ref_images=[Path("/tmp/only_one.png")],  # 只有 1 张 → ref_1 节点与链接应被裁掉
    )
    assert "ref_0" in wf
    assert "ref_1" not in wf
    assert "ref_image_1" not in wf["h3"]["inputs"]
    assert wf["h3"]["inputs"]["ref_image_0"] == ["ref_0", 0]


def test_build_workflow_zero_refs_t2v() -> None:
    client = ComfyClient(base_url="http://127.0.0.1:1", serial=False)
    wf = client.build_workflow(_template(), prompt="纯文生视频")
    assert "ref_0" not in wf
    assert all(not k.startswith("ref_image_") for k in wf["h3"]["inputs"])


def test_build_workflow_random_seed_when_absent() -> None:
    client = ComfyClient(base_url="http://127.0.0.1:1", serial=False)
    wf = client.build_workflow(_template(), prompt="p", ref_images=[])
    seed = wf["h3"]["inputs"]["seed"]
    assert isinstance(seed, int) and 0 <= seed < 2**32


def test_workflow_template_file_is_api_format() -> None:
    """仓库里自带模板必须能被 load_workflow 接受(API 格式校验)。"""
    client = ComfyClient(base_url="http://127.0.0.1:1", serial=False)
    wf = client.load_workflow("h3_w4a8_zh.json")
    assert "h3" in wf
    assert wf["h3"]["class_type"] == "MiniMaxH3ReferenceToVideo"
    assert wf["save"]["class_type"] == "SaveVideo"


# ── Subject → H3 ref 适配 ──────────────────────────────────────────────────


class FakeShot:
    def __init__(
        self,
        *,
        primary_speaker: str = "林晚",
        scene_id: str = "",
        ref_strategy: str = "A",
        secondary_speakers: list[str] | None = None,
        character_names: list[str] | None = None,
    ) -> None:
        self.primary_speaker = primary_speaker
        self.scene_id = scene_id
        self.ref_strategy = ref_strategy
        self.secondary_speakers = secondary_speakers or []
        self.character_names = character_names or [primary_speaker, *self.secondary_speakers]


def _subject(subject_id: str, name: str, master: str, anchor: str = "") -> tuple[str, dict]:
    return subject_id, {
        "id": subject_id,
        "name": name,
        "reference_images": [master],
        "metadata_json": {"prompt_anchor": anchor, "master_path": master},
    }


def test_to_h3_refs_primary_scene_and_anchor() -> None:
    sid, sub = _subject("char_001", "林晚", "/data/refs/linwan.png", "黑长直,红围巾")
    scene_sid, scene = _subject("loc_001", "雨夜街口", "/data/refs/rain_street.png")
    shot = FakeShot(primary_speaker="林晚", scene_id=scene_sid)
    refs = to_h3_refs(
        shot=shot,
        cast_map={"林晚": "char_001@v001"},
        subjects={sid: sub},
        scenes={scene_sid: scene},
    )
    assert refs.primary_ref == Path("/data/refs/linwan.png")
    assert refs.ref_images == [
        Path("/data/refs/linwan.png"),
        Path("/data/refs/rain_street.png"),
    ]
    assert refs.prompt_anchor == "黑长直,红围巾"
    assert refs.cast == {"林晚": 1}  # 主说话人恒 S1


def test_to_h3_refs_strategy_c_appends_prev_end_frame() -> None:
    sid, sub = _subject("char_001", "林晚", "/data/refs/linwan.png")
    shot = FakeShot(primary_speaker="林晚", ref_strategy="C")
    refs = to_h3_refs(
        shot=shot,
        cast_map={"林晚": "char_001"},
        subjects={sid: sub},
        scenes={},
        prev_end_frame="/data/shots/002/final.mp4",  # verdict 接受后的真实末帧
    )
    assert Path("/data/shots/002/final.mp4") in refs.ref_images


def test_to_h3_refs_double_shot_and_secondary() -> None:
    a_id, a = _subject("char_001", "林晚", "/data/refs/a.png")
    b_id, b = _subject("char_002", "阿泽", "/data/refs/b.png")
    shot = FakeShot(primary_speaker="林晚", secondary_speakers=["阿泽"])
    refs = to_h3_refs(
        shot=shot,
        cast_map={"林晚": "char_001", "阿泽": "char_002"},
        subjects={a_id: a, b_id: b},
        scenes={},
    )
    assert refs.cast == {"林晚": 1, "阿泽": 2}
    assert refs.ref_images == [Path("/data/refs/a.png"), Path("/data/refs/b.png")]


def test_to_h3_refs_unknown_subject_degrades() -> None:
    shot = FakeShot(primary_speaker="不存在的人")
    refs = to_h3_refs(
        shot=shot, cast_map={"不存在的人": "char_999"}, subjects={}, scenes={}
    )
    assert refs.primary_ref is None
    assert refs.ref_images == []


def test_subject_master_path_prefers_metadata() -> None:
    sub = {
        "reference_images": ["/data/refs/old.png"],
        "metadata_json": {"master_path": "/data/refs/locked.png"},
    }
    assert subject_master_path(sub) == Path("/data/refs/locked.png")
    assert subject_master_path(None) is None
