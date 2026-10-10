"""CosyVoice 三模式解析 + CosyVoice3 <|endofprompt|> 前缀。

对齐 Voice-Pro `abus_tts_cosyvoice`:Zero-Shot / Cross-Lingual / Instruct。
CV3 缺系统提示词时 LLM 线程静默死亡、产出空音频。
3O 归属(待上游): `oprim.cosy_mode`。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hevi.voicepro.schemas import CosyInferenceMode

CV3_SYSTEM_PROMPT = "You are a helpful assistant.<|endofprompt|>"

_ALIASES: dict[str, CosyInferenceMode] = {
    "zero_shot": "zero_shot",
    "zero-shot": "zero_shot",
    "zeroshot": "zero_shot",
    "cross_lingual": "cross_lingual",
    "cross-lingual": "cross_lingual",
    "crosslingual": "cross_lingual",
    "instruct": "instruct",
    "instruct2": "instruct",
    "sft": "sft",
}

#: 仓库内置默认参考音 —— 线协议用 ``builtin:<name>``, 由 GPU 引擎解析为
#: ``services/gen_engine/assets/voice_refs/<name>.wav``(引擎镜像 COPY 了
#: services/gen_engine/, 跨容器可见)。zh_default 取自 FunAudioLLM/CosyVoice
#: 官方 asset/zero_shot_prompt.wav(Apache-2.0), 16 kHz mono, 3.48 s。
BUILTIN_VOICE_REF_PREFIX = "builtin:"
DEFAULT_BUILTIN_VOICE = "zh_default"
BUILTIN_VOICE_REFS: dict[str, dict[str, str]] = {
    "zh_default": {
        "file": "zh_default.wav",
        "transcript": "希望你以后能够做的比我还好呦。",
        "language": "zh",
    },
}
#: 这些音色名都表示"用默认参考音"(explainer voice_profile 默认值等)。
DEFAULT_VOICE_ALIASES = frozenset({"", "default", "builtin", "cosyvoice_default", "cosy_default"})


def normalize_mode(raw: str | None) -> CosyInferenceMode | None:
    if raw is None:
        return None
    key = str(raw).strip().lower().replace(" ", "_")
    return _ALIASES.get(key)


def detect_family(model_name: str | None) -> str:
    name = (model_name or "").lower()
    if "cosyvoice3" in name or name in {"cv3", "fun-cosyvoice3-0.5b"}:
        return "cosyvoice3"
    return "cosyvoice2"


def needs_cv3_prefix(family: str) -> bool:
    return family == "cosyvoice3"


def is_default_voice_alias(name: str | None) -> bool:
    """voice 名是否等价于"默认参考音"。"""
    return (name or "").strip().lower() in DEFAULT_VOICE_ALIASES


def builtin_voice_name(ref: str | None) -> str | None:
    """``builtin:<name>`` → ``<name>``(未知内置名返回 None);非 builtin URI 返回 None。"""
    raw = (ref or "").strip()
    if not raw.startswith(BUILTIN_VOICE_REF_PREFIX):
        return None
    name = raw[len(BUILTIN_VOICE_REF_PREFIX) :].strip() or DEFAULT_BUILTIN_VOICE
    return name if name in BUILTIN_VOICE_REFS else None


def builtin_voice_ref(name: str | None = None) -> tuple[str, str] | None:
    """返回 (``builtin:<name>`` URI, 参考转录);未知名返回 None。"""
    key = (name or DEFAULT_BUILTIN_VOICE).strip()
    if key.startswith(BUILTIN_VOICE_REF_PREFIX):
        key = key[len(BUILTIN_VOICE_REF_PREFIX) :] or DEFAULT_BUILTIN_VOICE
    spec = BUILTIN_VOICE_REFS.get(key)
    if spec is None:
        return None
    return f"{BUILTIN_VOICE_REF_PREFIX}{key}", spec["transcript"]


def mode_requires_voice_ref(mode: str | None) -> bool:
    """zero_shot / cross_lingual / instruct 都以参考音定音色;只有 sft 不需要。"""
    return normalize_mode(mode) != "sft"


def mode_requires_prompt_text(mode: str | None) -> bool:
    """zero_shot 额外需要参考音转录(prompt_text / ref_text)。"""
    return normalize_mode(mode) == "zero_shot"


def validate_cosy_row(row: Mapping[str, Any]) -> list[str]:
    """按 cosy-ref-v1 契约校验一行引擎 payload, 返回问题列表(空 = 合法)。"""
    problems: list[str] = []
    text = str(row.get("text") or "").strip()
    if not text:
        problems.append("text 为空")
    raw_mode = row.get("inference_mode")
    mode = normalize_mode(raw_mode) if raw_mode else None
    if raw_mode and mode is None:
        problems.append(f"未知 inference_mode: {raw_mode}")
        return problems
    if mode is None:
        problems.append("inference_mode 未解析(契约要求客户端显式给出)")
        return problems
    voice_ref = str(row.get("voice_ref") or "").strip()
    ref_text = str(row.get("ref_text") or row.get("prompt_text") or "").strip()
    if mode_requires_voice_ref(mode) and not voice_ref:
        problems.append(f"{mode} 模式缺 voice_ref(参考音)")
    if voice_ref.startswith(BUILTIN_VOICE_REF_PREFIX) and builtin_voice_name(voice_ref) is None:
        problems.append(f"未知内置参考音: {voice_ref}")
    if mode_requires_prompt_text(mode) and not ref_text:
        problems.append("zero_shot 模式缺 ref_text/prompt_text(参考音转录)")
    if mode == "sft" and not str(row.get("spk_id") or "").strip():
        problems.append("sft 模式缺 spk_id(CosyVoice 内置说话人)")
    return problems


def resolve_inference_mode(
    *,
    requested: str | None = None,
    ref_text: str | None = None,
    instruct_text: str | None = None,
) -> CosyInferenceMode:
    explicit = normalize_mode(requested)
    if explicit is not None:
        return explicit
    if instruct_text and str(instruct_text).strip():
        return "instruct"
    if ref_text and str(ref_text).strip():
        return "zero_shot"
    return "cross_lingual"


def apply_cv3_prefix(
    text: str,
    *,
    family: str,
    mode: CosyInferenceMode,
) -> str:
    """按模式给 CV3 加系统前缀。CV2 原样返回。"""
    body = text or ""
    if not needs_cv3_prefix(family):
        return body
    if body.startswith(CV3_SYSTEM_PROMPT):
        return body
    return CV3_SYSTEM_PROMPT + body


def cv3_fields_for_mode(
    *,
    family: str,
    mode: CosyInferenceMode,
    tts_text: str,
    ref_text: str | None,
    instruct_text: str | None,
) -> tuple[str, str, str]:
    """返回 (prompt_text, tts_text_out, instruct_out)。

    Voice-Pro:zero_shot 前缀加在 ref_text;cross_lingual 加在 tts_text;
    instruct 的 instruct_text 为系统提示(CV3)或空(CV2)。
    """
    if mode == "zero_shot":
        prompt = apply_cv3_prefix(ref_text or "", family=family, mode=mode)
        return prompt, tts_text, ""
    if mode == "cross_lingual":
        return "", apply_cv3_prefix(tts_text, family=family, mode=mode), ""
    if mode == "sft":
        return "", tts_text, ""
    instruct = instruct_text or ""
    if needs_cv3_prefix(family) and not instruct:
        instruct = CV3_SYSTEM_PROMPT
    elif needs_cv3_prefix(family):
        instruct = apply_cv3_prefix(instruct, family=family, mode=mode)
    return "", tts_text, instruct
