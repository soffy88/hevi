"""组装 CosyVoice 引擎行:三模式 + CV3 前缀字段 + 参考音契约(cosy-ref-v1)。

组合: `resolve_inference_mode` + `cv3_fields_for_mode` + `detect_family`
      + `builtin_voice_ref` + `validate_cosy_row`。
3O 归属(待上游): `oskill.cosy_payload`。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from hevi.layer4_legacy.voicepro.oprim_impl.cosy_mode import (
    BUILTIN_VOICE_REF_PREFIX,
    builtin_voice_ref,
    cv3_fields_for_mode,
    detect_family,
    is_default_voice_alias,
    normalize_mode,
    resolve_inference_mode,
    validate_cosy_row,
)
from hevi.voicepro.schemas import CosyContractError, CosyLinePayload, CosyReference

#: voice_id → (参考音路径, 转录);未知返回 None;已知但不可用(未拉取)应抛
#: CosyContractError。由适配层注入(studio 音色目录), oskill 不直接依赖 studio。
CatalogLookup = Callable[[str], "tuple[str, str] | None"]


def build_cosy_line(
    *,
    text: str,
    voice_ref: str | None = None,
    ref_text: str | None = None,
    instruct_text: str | None = None,
    requested_mode: str | None = None,
    model_name: str | None = None,
    speed: float = 1.0,
    speaker_id: str = "host",
) -> CosyLinePayload:
    mode = resolve_inference_mode(
        requested=requested_mode,
        ref_text=ref_text,
        instruct_text=instruct_text,
    )
    family = detect_family(model_name)
    prompt, tts_out, instruct_out = cv3_fields_for_mode(
        family=family,
        mode=mode,
        tts_text=text,
        ref_text=ref_text,
        instruct_text=instruct_text,
    )
    return CosyLinePayload(
        text=tts_out,
        inference_mode=mode,
        prompt_text=prompt,
        instruct_text=instruct_out,
        voice_ref=voice_ref,
        ref_text=ref_text,
        speed=speed,
        speaker_id=speaker_id,
    )


def build_engine_script(lines: list[CosyLinePayload]) -> list[dict[str, Any]]:
    return [line.to_dict() for line in lines]


def _clean(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def resolve_cosy_reference(
    *,
    voice_ref: str | None = None,
    ref_text: str | None = None,
    voice_id: str | None = None,
    identity_voice: Mapping[str, Any] | None = None,
    catalog_lookup: CatalogLookup | None = None,
    env_default: tuple[str, str] | None = None,
    allow_builtin: bool = True,
    sft_speaker: str | None = None,
    requested_mode: str | None = None,
    strict_voice_id: bool = False,
) -> CosyReference:
    """按优先级为一行解析参考音, 解析不到时显式 sft 或抛 CosyContractError。

    优先级: 显式 voice_ref → voice_id(内置名/音色目录) → 身份包声线样本
    → 部署默认(env) → 仓库内置默认 builtin:zh_default → sft(spk_id) → 报错。
    """
    voice_ref = _clean(voice_ref)
    ref_text = _clean(ref_text)
    voice_id = _clean(voice_id)
    sft_speaker = _clean(sft_speaker)

    if normalize_mode(requested_mode) == "sft":
        if not sft_speaker:
            raise CosyContractError("inference_mode=sft 需要 spk_id(CosyVoice 内置说话人)")
        return CosyReference(source="sft", spk_id=sft_speaker)

    # 1) 调用方显式参考音(含 builtin:<name> URI)
    if voice_ref:
        if voice_ref.startswith(BUILTIN_VOICE_REF_PREFIX):
            hit = builtin_voice_ref(voice_ref)
            if hit is None:
                raise CosyContractError(f"未知内置参考音: {voice_ref}")
            return CosyReference(source="builtin", voice_ref=hit[0], ref_text=ref_text or hit[1])
        return CosyReference(source="request", voice_ref=voice_ref, ref_text=ref_text)

    # 2) 音色名: 默认别名跳过; builtin 名; 音色目录
    if voice_id and not is_default_voice_alias(voice_id):
        builtin = builtin_voice_ref(voice_id)
        if builtin is not None:
            return CosyReference(
                source="builtin", voice_ref=builtin[0], ref_text=ref_text or builtin[1]
            )
        hit = catalog_lookup(voice_id) if catalog_lookup is not None else None
        if hit is not None:
            path, transcript = hit
            return CosyReference(
                source="catalog", voice_ref=path, ref_text=ref_text or _clean(transcript)
            )
        if strict_voice_id:
            raise CosyContractError(f"未知 CosyVoice 音色: {voice_id}(不在内置参考音/音色目录中)")

    # 3) 身份包声线样本
    if identity_voice:
        path = _clean(identity_voice.get("voice_ref_audio") or identity_voice.get("voice_ref"))
        if path:
            text = ref_text or _clean(
                identity_voice.get("voice_ref_text") or identity_voice.get("ref_text")
            )
            return CosyReference(source="identity", voice_ref=path, ref_text=text)

    # 4) 部署级默认
    if env_default and _clean(env_default[0]):
        return CosyReference(
            source="env",
            voice_ref=env_default[0].strip(),
            ref_text=ref_text or _clean(env_default[1]),
        )

    # 5) 仓库内置默认
    if allow_builtin:
        hit = builtin_voice_ref(None)
        if hit is not None:
            return CosyReference(source="builtin", voice_ref=hit[0], ref_text=ref_text or hit[1])

    # 6) 无参考音: 显式 sft
    if sft_speaker:
        return CosyReference(source="sft", spk_id=sft_speaker)

    raise CosyContractError(
        "CosyVoice 需要参考音(voice_ref + ref_text)才能合成: 请求未给 voice_ref, "
        "音色目录/身份包/HEVI_COSY_DEFAULT_VOICE_REF 均无可用参考音, 内置默认参考音已禁用, "
        "且未配置 sft 说话人(HEVI_COSY_SFT_SPEAKER)。"
    )


def bind_cosy_reference(
    *,
    row: Mapping[str, Any],
    reference: CosyReference,
) -> dict[str, Any]:
    """把解析好的参考音绑定到一行引擎 payload, 解析推理模式并按契约校验。

    文本保持原样(CV3 系统前缀由引擎 worker 统一加, 避免双前缀)。
    """
    out: dict[str, Any] = dict(row)
    out.pop("voice_id", None)
    if reference.source == "sft":
        mode = "sft"
        out.pop("voice_ref", None)
        out.pop("ref_text", None)
        out.pop("prompt_text", None)
        out["spk_id"] = reference.spk_id
    else:
        mode = resolve_inference_mode(
            requested=out.get("inference_mode"),
            ref_text=reference.ref_text,
            instruct_text=out.get("instruct_text"),
        )
        if mode == "sft":
            raise CosyContractError("inference_mode=sft 需要 spk_id(CosyVoice 内置说话人)")
        out["voice_ref"] = reference.voice_ref
        if reference.ref_text:
            out["ref_text"] = reference.ref_text
            out["prompt_text"] = reference.ref_text
        else:
            out.pop("ref_text", None)
            out.pop("prompt_text", None)
    out["inference_mode"] = mode
    out["ref_source"] = reference.source
    problems = validate_cosy_row(out)
    if problems:
        raise CosyContractError(
            f"CosyVoice 契约校验失败(ref_source={reference.source}): " + "; ".join(problems)
        )
    return out
