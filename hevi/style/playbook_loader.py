"""StylePack Playbook 运行时 —— YAML 加载 + 三张查找表 + 根变量 + schema 验证。

对标 OpenMontage 的 styles/playbook_loader.py(YAML playbook + JSON Schema 验证),
但 Hevi 的 StylePack 设计更深(架构文档 §5.3):三张正交查找表 × 根变量因果推导。

三张查找表:
  1. device_pack(设备包):capture_source → 画面特征/操作特征/负面约束
  2. atmosphere_dict(氛围词典):抽象词 → 可拍摄物理现象(全局单例)
  3. provider_defaults(provider 默认行为对照表):每个 provider 一份

根变量:`capture_source` —— 派生一切(camera/lighting/negative),兼作真实感/完美感总开关。

用法:
    playbook = load_playbook(Path("styles/cinematic.yaml"))
    compiled = compile_prompt(playbook, provider="happyhorse", genre="historical")
    available = list_playbooks()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


# ── 数据模型 ──────────────────────────────────────────────────────────────────

@dataclass
class DevicePack:
    """设备包 —— 内容无关的可替换槽位(§5.3.2)。"""
    id: str
    capture_source: str          # 根变量:"2000年代DV" / "35mm电影感" / ...
    visual_features: str         # 画面特征描述
    operation_features: str      # 操作特征(手持/三脚架/...)
    negative_constraints: str    # 负面约束(不该出现什么)
    imperfections: bool = False  # 是否启用非完美事件(verité 家族)


@dataclass
class AtmosphereEntry:
    """氛围词典条目 —— 抽象词 → 物理现象(§5.3.3,全局单例)。"""
    abstract_word: str           # "温馨"
    physical_phenomena: list[str]  # ["树影在地面移动", "陶瓷杯冒热气"]


@dataclass
class ProviderDefault:
    """Provider 默认行为对照表条目(§5.3.4)。"""
    provider: str
    prompt_language: str         # "zh" / "en" / "any"
    default_bias: str            # "往电影感走" / "往丝滑运镜走"
    negative_overrides: str      # 针对性负向词
    last_verified: str = ""      # ISO 日期,过期条目降权


@dataclass
class GenrePreset:
    """Genre Router 预设(§5.3.4b)。"""
    genre: str                   # "historical" / "product" / "lifestyle" / ...
    shot_duration_default: float
    camera_tendency: str         # "slow_push" / "static" / "fast_cut"
    transition_style: str        # "dissolve" / "cut" / "wipe"


@dataclass
class Playbook:
    """完整的 StylePack Playbook。"""
    id: str
    version: str
    name: str
    capture_source: str          # 根变量
    device_pack: DevicePack
    atmosphere: list[AtmosphereEntry]
    provider_defaults: dict[str, ProviderDefault]
    genre_router: dict[str, GenrePreset] = field(default_factory=dict)
    color_baseline: str = ""     # 调色基准(供 L1 跨 provider 归一化)
    imperfection_library: dict[str, list[str]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


# ── 内置设备包(§5.3.2 起步 8 种) ─────────────────────────────────────────────

_BUILTIN_DEVICE_PACKS: dict[str, DevicePack] = {
    "dv_2000s": DevicePack(
        id="dv_2000s", capture_source="2000年代DV家庭录像",
        visual_features="低分辨率、色彩偏移、自动白平衡波动、4:3画幅",
        operation_features="手持不稳、偶尔失焦、自动对焦搜索",
        negative_constraints="4K画质、电影感景深、稳定运镜",
        imperfections=True,
    ),
    "cinema_35mm": DevicePack(
        id="cinema_35mm", capture_source="35mm电影感变形宽银幕",
        visual_features="变形宽银幕镜头光晕、浅景深、胶片颗粒、2.39:1画幅",
        operation_features="斯坦尼康、轨道推、稳定手持",
        negative_constraints="数字锐利感、过度HDR、竖屏",
    ),
    "vhs_home": DevicePack(
        id="vhs_home", capture_source="VHS家用摄像机",
        visual_features="磁带噪点、色彩溢出、扫描线、tracking glitch",
        operation_features="固定机位、偶尔zoom、手动对焦",
        negative_constraints="高清画质、数字特效",
        imperfections=True,
    ),
    "8mm_film": DevicePack(
        id="8mm_film", capture_source="8mm胶片",
        visual_features="胶片颗粒、闪烁、色彩褪色、暗角",
        operation_features="手摇变速、跳帧",
        negative_constraints="数字画质、平滑运镜",
        imperfections=True,
    ),
    "phone_vertical": DevicePack(
        id="phone_vertical", capture_source="手机竖屏",
        visual_features="9:16画幅、HDR自动处理、锐化",
        operation_features="竖持、偶尔横转、电子防抖",
        negative_constraints="电影感、宽银幕",
    ),
    "gopro_action": DevicePack(
        id="gopro_action", capture_source="GoPro运动相机",
        visual_features="超广角畸变、高饱和度、高帧率",
        operation_features="第一人称、极端角度、防水",
        negative_constraints="浅景深、长焦",
    ),
    "cctv": DevicePack(
        id="cctv", capture_source="监控摄像头",
        visual_features="低帧率、广角畸变、时间戳叠加、夜间红外",
        operation_features="固定机位、自动切换日/夜",
        negative_constraints="美学构图、运镜",
        imperfections=True,
    ),
    "documentary_pro": DevicePack(
        id="documentary_pro", capture_source="专业纪录片",
        visual_features="自然光为主、采访构图、B-roll丰富",
        operation_features="肩扛、手持跟拍、固定采访",
        negative_constraints="过度调色、CGI特效",
    ),
    "historical_epic": DevicePack(
        id="historical_epic", capture_source="历史正剧(火把/烛火光源)",
        visual_features="青灰赭褐palette、低饱和、厚重感、实景建筑",
        operation_features="慢推、固定大全景、正反打",
        negative_constraints="浅景深糖水、现代建筑、LED光源",
    ),
}

# ── 内置氛围词典(全局单例,§5.3.3) ─────────────────────────────────────────────

_BUILTIN_ATMOSPHERE: list[AtmosphereEntry] = [
    AtmosphereEntry("温馨", ["树影在地面移动", "晾衣绳织物摇曳", "陶瓷杯冒热气", "猫慵懒靠近"]),
    AtmosphereEntry("紧张", ["手指无意识敲击", "咽口水声放大", "目光游移不定", "呼吸节奏变化"]),
    AtmosphereEntry("孤独", ["空荡走廊回响", "窗外远处车声", "单人餐具", "灯光只开一盏"]),
    AtmosphereEntry("庄严", ["旗帜缓慢飘动", "人群屏息静立", "钟鼓余音回荡", "光线从高窗倾泻"]),
    AtmosphereEntry("悲壮", ["风卷尘土飞扬", "残破旌旗猎猎", "远处号角低沉", "火把光摇曳不定"]),
    AtmosphereEntry(
        "欢快", ["脚步轻快节奏", "笑声在空间回荡", "色彩鲜艳的物件", "阳光穿过树叶缝隙"],
    ),
    AtmosphereEntry("神秘", ["雾气缓慢流动", "光影在地面游移", "远处不明声响", "门缝透入一束光"]),
    AtmosphereEntry("压抑", ["天花板低矮", "灯光昏暗闪烁", "墙壁水渍斑驳", "空气凝滞不动"]),
]

# ── 内置 Genre 预设(§5.3.4b) ────────────────────────────────────────────────

_BUILTIN_GENRES: dict[str, GenrePreset] = {
    "historical": GenrePreset("historical", shot_duration_default=6.0,
                               camera_tendency="slow_push", transition_style="dissolve"),
    "drama": GenrePreset("drama", shot_duration_default=5.0,
                          camera_tendency="slow_push", transition_style="cut"),
    "product": GenrePreset("product", shot_duration_default=2.5,
                            camera_tendency="fast_cut", transition_style="cut"),
    "lifestyle": GenrePreset("lifestyle", shot_duration_default=3.5,
                              camera_tendency="handheld", transition_style="dissolve"),
    "mv": GenrePreset("mv", shot_duration_default=2.0,
                       camera_tendency="dynamic", transition_style="beat_sync"),
    "landscape": GenrePreset("landscape", shot_duration_default=8.0,
                              camera_tendency="slow_pan", transition_style="dissolve"),
    "documentary": GenrePreset("documentary", shot_duration_default=5.0,
                                camera_tendency="handheld", transition_style="cut"),
    "animation": GenrePreset("animation", shot_duration_default=3.0,
                              camera_tendency="dynamic", transition_style="cut"),
}


# ── YAML 加载 + 验证 ────────────────────────────────────────────────────────

def load_playbook(path: Path) -> Playbook:
    """从 YAML 文件加载 Playbook,验证 schema 完整性。

    YAML 结构:
        id: my-style
        version: "1.0"
        name: "我的风格"
        capture_source: "35mm电影感"
        device_pack: cinema_35mm  # 引用内置 或 内联定义
        atmosphere: [{ abstract_word: "...", phenomena: [...] }]  # 可覆盖/扩展内置
        provider_defaults:
            happyhorse: { prompt_language: zh, default_bias: "..." }
        genre_router:
            historical: { shot_duration_default: 6.0, camera_tendency: "slow_push" }
        color_baseline: "青灰赭褐"
    """
    with open(path) as f:
        data = yaml.safe_load(f)

    return _parse_playbook(data, source=str(path))


def load_playbook_from_dict(data: dict[str, Any]) -> Playbook:
    """从 dict 加载 Playbook(用于 API 传入或测试)。"""
    return _parse_playbook(data, source="dict")


def _parse_playbook(data: dict[str, Any], *, source: str) -> Playbook:
    """解析 + 验证 playbook 数据。"""
    _validate_required(data, source)

    pb_id = data.get("id", data.get("name", "unnamed"))
    version = str(data.get("version", "1.0"))
    name = data.get("name", pb_id)
    capture_source = data["capture_source"]

    # 设备包:引用内置 或 内联
    dp_ref = data.get("device_pack", "")
    if isinstance(dp_ref, str) and dp_ref in _BUILTIN_DEVICE_PACKS:
        device_pack = _BUILTIN_DEVICE_PACKS[dp_ref]
    elif isinstance(dp_ref, dict):
        device_pack = DevicePack(
            id=dp_ref.get("id", pb_id),
            capture_source=capture_source,
            visual_features=dp_ref.get("visual_features", ""),
            operation_features=dp_ref.get("operation_features", ""),
            negative_constraints=dp_ref.get("negative_constraints", ""),
            imperfections=dp_ref.get("imperfections", False),
        )
    else:
        device_pack = DevicePack(
            id=pb_id, capture_source=capture_source,
            visual_features="", operation_features="", negative_constraints="",
        )

    # 氛围词典:内置 + 覆盖/扩展
    atmosphere = list(_BUILTIN_ATMOSPHERE)
    new_entries = [
        AtmosphereEntry(
            abstract_word=e.get("abstract_word", ""),
            physical_phenomena=e.get("phenomena", e.get("physical_phenomena", [])),
        )
        for e in data.get("atmosphere", [])
        if isinstance(e, dict)
    ]
    atmosphere.extend(new_entries)

    # Provider 默认行为
    provider_defaults: dict[str, ProviderDefault] = {}
    for prov, cfg in data.get("provider_defaults", {}).items():
        if isinstance(cfg, dict):
            provider_defaults[prov] = ProviderDefault(
                provider=prov,
                prompt_language=cfg.get("prompt_language", "any"),
                default_bias=cfg.get("default_bias", ""),
                negative_overrides=cfg.get("negative_overrides", ""),
                last_verified=cfg.get("last_verified", ""),
            )

    # Genre Router
    genre_router: dict[str, GenrePreset] = dict(_BUILTIN_GENRES)
    for genre, cfg in data.get("genre_router", {}).items():
        if isinstance(cfg, dict):
            genre_router[genre] = GenrePreset(
                genre=genre,
                shot_duration_default=cfg.get("shot_duration_default", 4.0),
                camera_tendency=cfg.get("camera_tendency", "static"),
                transition_style=cfg.get("transition_style", "cut"),
            )

    return Playbook(
        id=pb_id,
        version=version,
        name=name,
        capture_source=capture_source,
        device_pack=device_pack,
        atmosphere=atmosphere,
        provider_defaults=provider_defaults,
        genre_router=genre_router,
        color_baseline=data.get("color_baseline", ""),
        imperfection_library=data.get("imperfection_library", {}),
        metadata=data.get("metadata", {}),
    )


def _validate_required(data: dict[str, Any], source: str) -> None:
    """验证必填字段。"""
    required = ["capture_source"]
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(
            f"Playbook from {source} missing required fields: {missing}. "
            f"'capture_source' is the root variable that derives everything."
        )


# ── Prompt 编译 ──────────────────────────────────────────────────────────────

def compile_prompt(
    playbook: Playbook,
    *,
    provider: str = "",
    genre: str = "drama",
    scene_description: str = "",
) -> dict[str, str]:
    """将 Playbook 编译成 provider 适配的 prompt 组件。

    返回 dict:
        visual_style: 视觉风格描述
        camera_style: 运镜风格描述
        negative_prompt: 负面约束
        atmosphere_hints: 氛围物理现象提示
    """
    dp = playbook.device_pack
    fallback_genre = _BUILTIN_GENRES["drama"]
    genre_p = playbook.genre_router.get(genre, fallback_genre)

    if playbook.color_baseline:
        visual = f"{dp.visual_features}. {playbook.color_baseline}"
    else:
        visual = dp.visual_features
    camera = (
        f"{dp.operation_features}. {genre_p.camera_tendency} camera, "
        f"{genre_p.shot_duration_default}s avg shots"
    )

    # 负面约束 = 设备包负面 + provider 对照表针对性负向
    negative_parts = [dp.negative_constraints]
    if provider in playbook.provider_defaults:
        pd = playbook.provider_defaults[provider]
        if pd.negative_overrides:
            negative_parts.append(pd.negative_overrides)
    negative = ", ".join(p for p in negative_parts if p)

    # 氛围:将抽象词翻译成物理现象
    atmosphere_hints = []
    for entry in playbook.atmosphere:
        if scene_description and entry.abstract_word in scene_description:
            atmosphere_hints.extend(entry.physical_phenomena[:2])

    return {
        "visual_style": visual,
        "camera_style": camera,
        "negative_prompt": negative,
        "atmosphere_hints": "; ".join(atmosphere_hints) if atmosphere_hints else "",
        "genre": genre,
        "capture_source": playbook.capture_source,
    }


# ── 发现 ─────────────────────────────────────────────────────────────────────

_STYLES_DIR = Path(__file__).resolve().parent.parent.parent / "styles"


def list_playbooks() -> list[dict[str, str]]:
    """列出所有可用 playbook(YAML 文件 + 内置设备包)。"""
    result = []

    # 内置设备包
    for dp_id, dp in _BUILTIN_DEVICE_PACKS.items():
        result.append({
            "id": dp_id,
            "name": dp.capture_source,
            "type": "builtin_device_pack",
            "imperfections": str(dp.imperfections),
        })

    # YAML playbook 文件
    if _STYLES_DIR.exists():
        for yf in sorted(_STYLES_DIR.glob("*.yaml")):
            try:
                with open(yf) as f:
                    data = yaml.safe_load(f) or {}
                result.append({
                    "id": data.get("id", yf.stem),
                    "name": data.get("name", yf.stem),
                    "type": "yaml_playbook",
                    "path": str(yf),
                })
            except Exception:
                result.append({"id": yf.stem, "name": yf.stem, "type": "yaml_error"})

    return result
