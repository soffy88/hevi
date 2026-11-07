"""ShotSpec —— 单镜规格(模板/入场转场/特效/风格/音效/运镜/字幕样式/时长)。

GAP_PLAN §2 W1:此前每个镜头的"怎么接、加什么效果、配什么音效"散落在各处调用参数
里,没有统一可持久化、可校验的单镜规格。本模块定义 ``ShotSpec`` 模型,并把所有取值
收敛到既有注册表做校验:

  - ``template``       → T1 FX 注册表 ``hevi/fx/registry.py`` 的模板 id
  - ``transition_in``  → T2 xfade 注册表 ``hevi/assembly/xfade_transitions.py`` 的 id
                         (``cut`` = 硬切;第 1 镜忽略)
  - ``effect``         → 内置 5 种(warm/cool/mono/vignette/sharpen)+ 注册表里
                         style 类条目(能映射成 ffmpeg 滤镜的尽力而为)
  - ``style``          → 若 ``hevi/layer4_legacy/dirstyle`` 已合并则校验其风格 id;
                         否则自由字符串
  - ``sfx``            → ``assets/audio/sfx/library/manifest.json`` 里的音效 id
  - ``camera`` / ``subtitle_style`` / ``duration`` → 自由/数值字段

未知取值一律让 pydantic 抛 ``ValidationError``(FastAPI 转 422),绝不静默放行。
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

# ── 内置特效名 ────────────────────────────────────────────────────────
# 这些名字直接映射到 shot_spec_render 里的 ffmpeg 滤镜链。
BUILTIN_EFFECTS: frozenset[str] = frozenset({"warm", "cool", "mono", "vignette", "sharpen"})

# ── 合法 style 枚举 ───────────────────────────────────────────────────
# dirstyle 未合并期间,style 只接受有 ffmpeg 映射的枚举值,其它值一律 422。
# 复用 effect 色调集 + 典型视觉风格滤镜。
# TODO(dirstyle): validate once feat/director-styles merges
STYLE_FILTERS: dict[str, str] = {
    "warm": "colortemperature=temperature=4000",
    "cool": "colortemperature=temperature=9500",
    "mono": "hue=s=0",
    "noir": "hue=s=0,eq=contrast=1.3",
    "vignette": "vignette=PI/5",
    "sharpen": "unsharp=5:5:1.2:5:5:0.0",
    "blur": "gblur=sigma=6",
    "soft": "gblur=sigma=2",
    "sketch": "edgedetect=low=0.05:high=0.2",
    "sepia": "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131",
}

VALID_STYLES: frozenset[str] = frozenset(STYLE_FILTERS.keys())


def valid_style_ids() -> frozenset[str]:
    """返回当前合法的 style 枚举 id 集合。"""
    mod = _dirstyle_module()
    if mod is not None:
        ids = getattr(mod, "valid_style_ids", None)
        if callable(ids):
            return frozenset(ids())
    return VALID_STYLES

#: ``transition_in`` 的特殊值:硬切(不重叠,由 build_xfade_chain 的 concat 分支处理)。
CUT = "cut"


def _repo_root() -> Path:
    """仓库根(hevi/production/shot_spec.py 往上三层)。"""
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def _registry():
    """惰性单例 FX 注册表(不扫预览,只取 id 集合做校验)。"""
    from hevi.fx.loader import load_all

    return load_all(sync_previews=False)


@lru_cache(maxsize=1)
def _manifest_ids() -> frozenset[str]:
    """sfx manifest 里的全部音效 id(70 条,含 library/ 子目录资产)。"""
    manifest = _repo_root() / "assets" / "audio" / "sfx" / "library" / "manifest.json"
    if not manifest.exists():
        return frozenset()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    return frozenset(a["id"] for a in data.get("assets", []) if a.get("id"))


def valid_sfx_ids() -> frozenset[str]:
    """合法音效 id 集合 = 注册表 sfx 源 + manifest 资产 id(二者取并)。"""
    from hevi.fx.registry import Source

    reg_ids = {t.source_ref for t in _registry().list_all() if t.source == Source.SFX}
    return frozenset(reg_ids | set(_manifest_ids()))


def sfx_asset_path(sfx_id: str) -> Path:
    """按 id 解析音效文件路径(manifest 的 ``file`` 字段,仓库相对)。"""
    manifest = _repo_root() / "assets" / "audio" / "sfx" / "library" / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    for a in data.get("assets", []):
        if a.get("id") == sfx_id:
            return _repo_root() / a["file"]
    # 退化:顶层 sfx/<id>.wav(注册表 sfx 源对应)
    return _repo_root() / "assets" / "audio" / "sfx" / f"{sfx_id}.wav"


def valid_template_ids() -> frozenset[str]:
    """FX 注册表里的全部模板 id。"""
    return frozenset(t.id for t in _registry().list_all())


def template_render_supported(template_id: str) -> bool:
    """FX 注册表模板在装配期是否支持渲染。

    仅 TEMPLATE_RENDER_MAP 中拥有明确装配期动作 (71 个接缝转场或 8 种画面滤镜) 的模板被支持。
    文字动画、图表、数字计数、UI剧场、标注引导、角色类及 SFX 模板等装配期均不可渲染,
    由 ShotSpec 校验拒绝 -> 422「装配期不可渲染」。
    """
    from hevi.production.shot_spec_render import TEMPLATE_RENDER_MAP

    return template_id in TEMPLATE_RENDER_MAP


def rejected(template_id: str) -> bool:
    """FX 注册表模板是否在 ShotSpec 校验中被拒绝 (422: 装配期不可渲染)。"""
    return not template_render_supported(template_id)


def valid_style_effect_ids() -> frozenset[str]:
    """effect 字段可接受的注册表 style 模板 id(仅显式语义映射的, 其余 422)。"""
    from hevi.production.shot_spec_render import EFFECT_REGISTRY_FILTERS

    return frozenset(EFFECT_REGISTRY_FILTERS.keys())


def valid_transition_ids() -> frozenset[str]:
    """xfade 注册表里的全部转场 id(不含 ``cut``)。"""
    from hevi.assembly.xfade_transitions import ALL_TRANSITIONS

    return frozenset(t.id for t in ALL_TRANSITIONS)


def _dirstyle_module():
    """dirstyle 模块(未合并时为 None)。"""
    try:
        from hevi.layer4_legacy import dirstyle  # type: ignore[attr-defined]

        return dirstyle
    except Exception:  # 模块未合并/导入失败都视作不可用
        return None


class SFXCue(BaseModel):
    """一条音效提示:音效 id + 相对本镜起点的偏移秒数。"""

    id: str
    offset: float = 0.0

    @field_validator("offset")
    @classmethod
    def _offset_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"sfx offset must be >= 0, got {v}")
        return v


class ShotSpec(BaseModel):
    """单镜规格。所有字段可选;未知取值由校验器拒绝(→ 422)。"""

    template: str | None = None
    transition_in: str | None = None
    effect: str | None = None
    # TODO(dirstyle): validate once feat/director-styles merges —— 目前 dirstyle 未合并,
    # 该字段是自由字符串;合并后改为校验 dirstyle 风格 id。
    style: str | None = None
    sfx: list[SFXCue] = Field(default_factory=list)
    camera: str | None = None
    subtitle_style: str | None = None
    duration: float | None = None
    # 素材余量(handles):采用时长(duration)之外、生成时多要的首/尾余量,
    # 供生成端多拍一点、装配时按 in 点裁切。默认 0.0 = 旧行为(不带余量)。
    handle_head_s: float = 0.0
    handle_tail_s: float = 0.0

    @field_validator("handle_head_s", "handle_tail_s")
    @classmethod
    def _handles_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"handle must be >= 0, got {v}")
        return v

    def requested_generation_duration_s(
        self, use_duration_s: float | None = None
    ) -> float | None:
        """请求生成时长 = 采用时长 + handle_head_s + handle_tail_s。

        采用时长默认取 ``duration``;显式传 ``use_duration_s`` 时用它
        (调用方采用时长与 spec.duration 不一致时)。采用时长未知(None)
        时返回 None,不臆造时长。
        """
        use = self.duration if use_duration_s is None else use_duration_s
        if use is None:
            return None
        if use <= 0:
            raise ValueError(f"use duration must be > 0, got {use}")
        return float(use) + self.handle_head_s + self.handle_tail_s

    @field_validator("duration")
    @classmethod
    def _duration_positive(cls, v: float | None) -> float | None:
        if v is not None and v <= 0:
            raise ValueError(f"duration must be > 0, got {v}")
        return v

    @field_validator("template")
    @classmethod
    def _template_known(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in valid_template_ids():
            raise ValueError(f"unknown template id '{v}' (not in FX registry)")
        if not template_render_supported(v):
            raise ValueError(
                f"template '{v}' is not supported at assembly time (装配期不可渲染)"
            )
        return v

    @field_validator("transition_in")
    @classmethod
    def _transition_known(cls, v: str | None) -> str | None:
        if v is None or v == CUT:
            return v
        if v not in valid_transition_ids():
            raise ValueError(f"unknown transition id '{v}' (not in xfade registry)")
        return v

    @field_validator("effect")
    @classmethod
    def _effect_known(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v in BUILTIN_EFFECTS:
            return v
        # 注册表 style 类条目:尽力而为映射成 ffmpeg 滤镜(见 shot_spec_render)。
        if v in valid_style_effect_ids():
            return v
        raise ValueError(
            f"unknown effect '{v}' (must be one of {sorted(BUILTIN_EFFECTS)} "
            "or a registry style id with an explicit assembly-time mapping)"
        )

    @field_validator("style")
    @classmethod
    def _style_known(cls, v: str | None) -> str | None:
        if v is None:
            return v
        mod = _dirstyle_module()
        if mod is not None:
            # TODO(dirstyle): feat/director-styles 已合并时走 dirstyle 的校验器
            ids = getattr(mod, "valid_style_ids", None)
            if callable(ids) and v not in ids():
                raise ValueError(f"unknown dirstyle id '{v}'")
            return v
        # TODO(dirstyle): validate once feat/director-styles merges
        # dirstyle 未合并期间,仅允许有 ffmpeg 映射的合法 style 枚举,其它一律 422
        if v not in VALID_STYLES:
            raise ValueError(
                f"unknown style '{v}' (dirstyle unmerged: must be one of {sorted(VALID_STYLES)})"
            )
        return v

    @model_validator(mode="after")
    def _sfx_valid(self) -> ShotSpec:
        known = valid_sfx_ids()
        for cue in self.sfx:
            if cue.id not in known:
                raise ValueError(f"unknown sfx id '{cue.id}' (not in sfx manifest/registry)")
            if self.duration is not None and cue.offset >= self.duration:
                raise ValueError(f"sfx offset {cue.offset} must be < duration {self.duration}")
        return self

    def to_dict(self) -> dict[str, Any]:
        """JSON 安全 dict(落库/响应共用)。"""
        return self.model_dump(exclude_none=False)


def validate_specs(specs: list[dict[str, Any]]) -> list[ShotSpec]:
    """批量校验:任一非法整体抛 ``ValidationError``(调用方转 422)。"""
    return [ShotSpec.model_validate(s) for s in specs]


# ── 持久化(挂在 shot_states.selection_json["shot_spec"],零迁移)──────────
# 与 hevi.season_planner.preparation 同构:跟随任务现有 shot 存储,不新建库表。

SPEC_KEY = "shot_spec"

# ── 任务镜规格跨重建内存缓存 (保证即使 delete_shots 先行执行，随后的 persist 仍能找回 spec) ──
# 键为 (task_id, shot_index)。有界 LRU 风格 dict，避免长期运行无限增长。
_TASK_SPEC_CACHE: dict[tuple[str, int], dict[str, Any]] = {}
_TASK_SPEC_CACHE_MAX = 4096


def cache_task_spec(task_id: Any, shot_index: int, spec_dict: dict[str, Any]) -> None:
    """按 (task_id, shot_index) 缓存已配置的规格 dict。"""
    key = (str(task_id), shot_index)
    if len(_TASK_SPEC_CACHE) >= _TASK_SPEC_CACHE_MAX and key not in _TASK_SPEC_CACHE:
        # 简单的 FIFO 淘汰:丢掉最早插入的一项
        _TASK_SPEC_CACHE.pop(next(iter(_TASK_SPEC_CACHE)), None)
    _TASK_SPEC_CACHE[key] = spec_dict


def get_cached_task_spec(task_id: Any, shot_index: int) -> dict[str, Any] | None:
    """读取 (task_id, shot_index) 对应的规格 dict (无则 None)。"""
    return _TASK_SPEC_CACHE.get((str(task_id), shot_index))


def clear_cached_task_spec(task_id: Any, shot_index: int) -> None:
    """清理单个镜头的规格缓存。"""
    _TASK_SPEC_CACHE.pop((str(task_id), shot_index), None)


def clear_task_specs_cache(task_id: Any) -> None:
    """清理指定任务的所有镜头规格缓存。"""
    prefix = str(task_id)
    keys_to_remove = [k for k in _TASK_SPEC_CACHE if k[0] == prefix]
    for k in keys_to_remove:
        _TASK_SPEC_CACHE.pop(k, None)


def upsert_spec(shot_row: dict[str, Any], spec: ShotSpec) -> dict[str, Any]:
    """把规格写回 shot_states 行(selection_json.shot_spec)。"""
    sel = dict(shot_row.get("selection_json") or {})
    spec_dict = spec.to_dict()
    sel[SPEC_KEY] = spec_dict
    shot_row["selection_json"] = sel
    tid = shot_row.get("task_id")
    idx = shot_row.get("shot_index")
    if tid is not None and idx is not None and isinstance(idx, int):
        cache_task_spec(tid, idx, spec_dict)
    return shot_row


def read_spec(shot_row: dict[str, Any]) -> ShotSpec | None:
    """从 shot_states 行读取规格(无则 None)。读到后同步写回内存缓存。"""
    raw = (shot_row.get("selection_json") or {}).get(SPEC_KEY)
    if not raw:
        return None
    spec = ShotSpec.model_validate(raw)
    tid = shot_row.get("task_id")
    idx = shot_row.get("shot_index")
    if tid is not None and isinstance(idx, int):
        cache_task_spec(tid, idx, spec.to_dict())
    return spec


def merge_patch(base: ShotSpec, patch: dict[str, Any]) -> ShotSpec:
    """部分更新:只覆盖 ``patch`` 里显式给出的键,未给字段保留 ``base`` 的值。

    ``patch`` 应为 ``model_dump(exclude_unset=True)`` 的结果——区分"显式传 null"
    (清空该字段)与"没传"(保留)。
    """
    merged = base.model_dump()
    merged.update(patch)
    return ShotSpec.model_validate(merged)


_SHOT_INDEX_RE = re.compile(r"shot_(\d+)")


async def load_shot_specs_for_task(
    repo: Any,
    task_id: Any,
    shot_count: int | None = None,
    ordered_paths: list[Path] | None = None,
) -> list[ShotSpec | None] | None:
    """从任务存储 (shot_states.selection_json["shot_spec"]) 读取指定任务各镜的 ShotSpec 列表。

    - 若提供 ordered_paths,按路径里的 shot index (shot_XXXX) 对齐;
    - 否则若提供 shot_count,按 shot_index 0..shot_count-1 顺序对齐;
    - 若该任务没有镜头或没有任何镜设置 spec,返回 None(保持旧调用行为逐字不变)。
    """
    if repo is None or task_id is None:
        return None
    try:
        raw_shots = await repo.get_shots(task_id)
    except Exception:
        return None
    if not raw_shots:
        return None

    spec_by_idx: dict[int, ShotSpec] = {}
    for row in raw_shots:
        idx = row.get("shot_index")
        if idx is not None and isinstance(idx, int):
            sp = read_spec(row)
            if sp is not None:
                spec_by_idx[idx] = sp

    if not spec_by_idx:
        return None

    if ordered_paths is not None:
        specs: list[ShotSpec | None] = []
        for i, p in enumerate(ordered_paths):
            m = _SHOT_INDEX_RE.search(p.name)
            idx = int(m.group(1)) if m else i
            specs.append(spec_by_idx.get(idx))
        return specs

    if shot_count is not None:
        return [spec_by_idx.get(i) for i in range(shot_count)]

    max_idx = max(spec_by_idx.keys()) if spec_by_idx else -1
    return [spec_by_idx.get(i) for i in range(max_idx + 1)]
