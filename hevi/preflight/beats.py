"""preflight.beats —— 分镜节拍与模型规格。

一个 beat 是生成前门禁与编译器的最小输入单位：场景、人物、对白、
首帧、时长、段型。段型沿用通鉴五段法枚举（narration / dialogue /
commentary / modern_echo），因为现代词黑名单的作用域按段型豁免。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 失败原因分类（一次通过率统计用；人工归因时只许选其一，other 兜底）。
FAILURE_CATEGORIES = (
    "face_drift",       # 脸／人物与定妆漂移
    "pseudo_text",      # 伪文字（牌匾／题字／招牌上的无意义字形）
    "dialogue_garbled", # 对白含糊／转写错误（语速过快常是诱因）
    "timeout",          # 生成超时／高峰不可用
    "model_refusal",    # 模型拒答／内容审核
    "other",            # 其他（须在 notes 里写清）
)


@dataclass
class CharacterRef:
    """人物引用：定妆图路径与／或可执行文字描述，至少其一在位。"""

    char_id: str
    sheet_path: str | Path | None = None
    description: str = ""


@dataclass
class DialogueLine:
    speaker: str
    text: str


@dataclass
class Beat:
    """一个待生成的分镜节拍。"""

    beat_id: str
    kind: str = "dialogue"  # narration | dialogue | commentary | modern_echo
    scene: str = ""
    text: str = ""  # 对白（dialogue）或讲解词（narration/commentary）
    characters: list[CharacterRef] = field(default_factory=list)
    dialogue_lines: list[DialogueLine] = field(default_factory=list)
    first_frame: str | Path | None = None
    duration_s: float = 8.0
    aspect: str = "16:9"
    style_lock: str = ""
    on_screen_text: bool = False  # 明确要求画面出现文字时才为 True

    @property
    def dialogue_text(self) -> str:
        if self.dialogue_lines:
            return "".join(ln.text for ln in self.dialogue_lines)
        return self.text

    @classmethod
    def from_preproduction(cls, raw: dict[str, Any]) -> "Beat":
        """从通鉴 preproduction.json 的 storyboard 行转换。

        preproduction 行字段：beat / section / kind / scene / speaker / text。
        speaker 是 C_wei 这类 character_id；定妆与首帧由调用方另行补齐，
        这里不猜路径。
        """
        kind = str(raw.get("kind") or "dialogue")
        speaker = str(raw.get("speaker") or "")
        chars: list[CharacterRef] = []
        if speaker and speaker != "NARRATOR":
            chars.append(CharacterRef(char_id=speaker))
        return cls(
            beat_id=str(raw.get("beat", raw.get("beat_id", ""))),
            kind=kind,
            scene=str(raw.get("scene") or ""),
            text=str(raw.get("text") or ""),
            characters=chars,
        )


@dataclass(frozen=True)
class ModelSpec:
    """模型窗口与计价（2026-10-24 实测口径，见 README）。"""

    name: str
    window_s: float | None  # 单条生成窗口秒数；None = 按秒计价或本地
    credits_per_clip: int | None  # 窗口内单条 credits；None = 非 credits 计价
    currency: str  # credits | USD | local-gpu
    usd_per_s: float | None = None
    note: str = ""


MODEL_SPECS: dict[str, ModelSpec] = {
    "veo_fast": ModelSpec("veo_fast", 8.0, 20, "credits",
                          note="Veo 3.1 Fast，8 秒，Flow 非 Ultra 价"),
    "veo_lite": ModelSpec("veo_lite", 8.0, 10, "credits",
                          note="Veo 3.1 Lite，8 秒"),
    "veo_quality": ModelSpec("veo_quality", 8.0, 100, "credits",
                             note="Veo 3.1 Quality，8 秒"),
    "omni_flash": ModelSpec("omni_flash", 10.0, 15, "credits",
                            note="Gemini Omni Flash，10 秒约 15 credits"),
    "pixstag": ModelSpec("pixstag", None, None, "USD", usd_per_s=0.015,
                         note="PixStag 自托管 MiniMax-H3，约 $0.015/秒 720P"),
    "svi_film": ModelSpec("svi_film", None, None, "local-gpu",
                          note="SVI-Film 本地 LoRA，credits 为 0，成本为 GPU 机时（未定价）"),
}


def get_model_spec(name: str) -> ModelSpec:
    try:
        return MODEL_SPECS[name]
    except KeyError:
        raise ValueError(
            f"unknown preflight model: {name!r} "
            f"(want one of {', '.join(MODEL_SPECS)})"
        ) from None
