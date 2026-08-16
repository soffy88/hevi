"""Subject → H3 Ref 适配器(L2 资产层,不重做资产库,只加导出适配)。

hevi 资产继续走 Subject / 挂载树:本模块只做一件事 —— 把**已锁定**的
Subject(角色/场景)+ cast 映射 + 观察态末帧,导出成 H3 需要的 ref 集合:

    cast_map[shot.primary_speaker]  → primary_ref(锁脸/锁身份的母卡)
    ref_images = [primary_ref, 场景母卡, (策略 C) 上一镜合格末帧, …]
    prompt_anchor                     → 写进【人物】短锚点

纪律:
  - 只消费 locked 资产(version 钉死),不在此处生成/修改资产。
  - 与 hevi「观察态」对齐:ref_strategy == "C" 时,prev_end_frame 必须是 verdict
    接受后的**真实末帧**,不是分镜计划帧——调用方(导演流水线)负责传入真实末帧路径。
  - S 编号全片稳定:按 cast_map 键序分配(S1 = primary_speaker),同一角色编号不变。
  - 纯函数、无 IO(路径字符串不做 exists 校验,交给下游 provider 与 verdict)。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class H3Refs:
    """H3 一镜的 ref 集合 + S 编号表。"""

    primary_ref: Path | None
    ref_images: list[Path] = field(default_factory=list)
    prompt_anchor: str = ""
    #: 角色名 → S 号(1 基,全片稳定)。喂 compile_h3_prompt 的 cast 参数。
    cast: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_ref": str(self.primary_ref) if self.primary_ref else None,
            "ref_images": [str(p) for p in self.ref_images],
            "prompt_anchor": self.prompt_anchor,
            "cast": self.cast,
        }


def subject_master_path(subject: dict[str, Any] | None) -> Path | None:
    """Subject(库行 dict 或同构对象)→ 母卡路径。

    优先级:metadata_json.master_path > reference_images[0](首个参考图即锁脸/锁身份的
    封面,hevi 既定行为)。无图/无元数据 → None(调用方降级为 t2v 或跳过该 ref)。
    """
    if not subject:
        return None
    meta = subject.get("metadata_json") or subject.get("metadata") or {}
    master = meta.get("master_path") or meta.get("primary_ref")
    if master:
        return Path(str(master))
    refs = subject.get("reference_images") or []
    if refs and str(refs[0]).strip():
        return Path(str(refs[0]))
    return None


def subject_prompt_anchor(subject: dict[str, Any] | None) -> str:
    """Subject → prompt_anchor(【人物】短锚点)。空则回退名字。"""
    if not subject:
        return ""
    meta = subject.get("metadata_json") or subject.get("metadata") or {}
    anchor = meta.get("prompt_anchor") or ""
    if anchor:
        return str(anchor)
    name = subject.get("name") or ""
    return str(name) if name else ""


def to_h3_refs(
    *,
    shot: Any,
    cast_map: dict[str, str],
    subjects: dict[str, Any],
    scenes: dict[str, Any],
    prev_end_frame: Path | str | None = None,
) -> H3Refs:
    """镜头契约 + cast 映射 + 资产字典 → H3Refs。

    Args:
        shot: 镜头契约(鸭子类型)。读取:
            - primary_speaker: 本镜主说话人角色名(cast_map 的键)
            - scene_id: 场景 Subject id(可空)
            - ref_strategy: "A"/"B"/"C"(C = 接上一镜真实末帧)
            - secondary_speakers: 本镜其他出场角色名(可空,双人镜用)
        cast_map: 角色名 → Subject id(如 {"林晚": "char_001@v001"} 的 id 部分)。
            真实路径由 subjects 字典解析;@版本后缀在此剥掉(版本钉死在 Subject 行内)。
        subjects: subject_id → Subject 行(库行 dict,含 reference_images/metadata_json)。
        scenes: scene_id → 场景 Subject 行(可空)。
        prev_end_frame: 策略 C 的上一镜**合格**末帧(verdict 接受后的真实末帧)。
    """
    primary_name = getattr(shot, "primary_speaker", "") or ""
    scene_id = getattr(shot, "scene_id", "") or ""
    strategy = getattr(shot, "ref_strategy", "") or "A"
    secondary = list(getattr(shot, "secondary_speakers", None) or [])

    # cast_map: 角色名 → subject_id(剥 @version 后缀)。
    def _sid(name: str) -> str:
        raw = cast_map.get(name, "")
        return str(raw).split("@", 1)[0] if raw else ""

    primary_sid = _sid(primary_name)
    primary = subjects.get(primary_sid) if primary_sid else None
    primary_path = subject_master_path(primary)

    refs: list[Path] = []
    if primary_path:
        refs.append(primary_path)

    # 场景母卡(有则追加;主角色在前,主体权重更高)。
    scene_path = subject_master_path(scenes.get(scene_id)) if scene_id else None
    if scene_path and scene_path not in refs:
        refs.append(scene_path)

    # 双人镜:第二角色母卡(同样按 cast 解析)。
    for name in secondary:
        sid = _sid(name)
        sub = subjects.get(sid)
        p = subject_master_path(sub)
        if p and p not in refs:
            refs.append(p)

    # 观察态末帧:策略 C 且给了真实末帧。
    if strategy.upper() == "C" and prev_end_frame:
        frame = Path(str(prev_end_frame))
        if frame not in refs:
            refs.append(frame)

    # S 编号:主说话人恒为 S1,其余按出场顺序(全片稳定,调用方保证 cast_map 稳定)。
    cast: dict[str, int] = {}
    if primary_name:
        cast[primary_name] = 1
    for i, name in enumerate(secondary, start=2):
        if name not in cast:
            cast[name] = i
    # 镜头契约里出现但 cast_map 没配的角色也进 cast(按出现顺序续号),编译器
    # 拿到 0 号会告警 —— 这里直接给号,避免 S0 进 prompt。
    for n in getattr(shot, "character_names", None) or []:
        if n not in cast:
            cast[n] = len(cast) + 1
            logger.warning(
                "to_h3_refs: 角色 %r 未出现在 cast_map,自动续 S%d(建议在 cast_map 显式配置)",
                n,
                cast[n],
            )

    return H3Refs(
        primary_ref=primary_path,
        ref_images=refs,
        prompt_anchor=subject_prompt_anchor(primary),
        cast=cast,
    )
