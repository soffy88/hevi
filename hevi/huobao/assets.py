"""Asset registry with cross-episode deduplication and alias merging.

Supports:
- Character, Scene, and Prop asset models.
- Name normalization removing parenthetical tags (e.g. "林小雨（主角）" -> "林小雨").
- Alias merging across episodes (different titles/aliases map to single canonical asset).
- Strict 3-question prop filtering (pushes plot, standalone item, not common daily/furniture; max 3/ep).
- Pure-background scene prompt enforcement (no humans).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_PAREN_PATTERN = re.compile(r"[（(【\[][^）)\]】]+[）)\]】]$")
_DISALLOWED_PROP_SUBSTRINGS = (
    "桌",
    "椅",
    "凳",
    "门",
    "窗",
    "杯",
    "碗",
    "筷",
    "烟",
    "雨伞",
    "手机",
    "衣服",
    "鞋",
    "床",
    "灯",
    "墙",
    "地毯",
)
_HIGH_VALUE_PROP_KEYWORDS = (
    "玉玦",
    "玉佩",
    "密信",
    "信物",
    "宝剑",
    "佩剑",
    "令牌",
    "锦囊",
    "印章",
    "虎符",
    "秘籍",
    "解药",
    "短匕",
    "凶器",
    "玉簪",
    "残卷",
    "兵符",
    "古卷",
    "账本",
    "金钗",
    "图谱",
)


def normalize_name(name: str) -> str:
    """Normalize asset name by stripping whitespace and trailing parenthetical tags.

    Example:
        '林小雨（主角）' -> '林小雨'
        '沈砚之(少爷)' -> '沈砚之'
        '  苏晚 [妹妹] ' -> '苏晚'
    """
    clean = (name or "").strip()
    # Iteratively strip trailing parenthetical labels
    while True:
        m = _PAREN_PATTERN.search(clean)
        if m:
            clean = clean[: m.start()].strip()
        else:
            break
    return clean


def clean_scene_prompt(prompt: str) -> str:
    """Enforce pure-background rule: strip human mentions and ensure empty scene."""
    text = (prompt or "").strip()
    # Strip common character action phrases from scene description
    text = re.sub(r"角色|人物|男女|侍从|众人|围观|有人|立于|站立|坐着", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if "空镜" not in text and "纯背景" not in text:
        text = f"{text}，纯背景无人物空镜，传统国风场景"
    return text


def is_valid_prop(name: str, description: str = "") -> bool:
    """Validate candidate prop against Huobao's 3-question filter.

    Q1: Directly pushes plot (token, weapon, critical letter, evidence).
    Q2: Deserves standalone generation (close-up reference card).
    Q3: Not an everyday disposable item (cup, cigarette, chopsticks) and not furniture.
    """
    norm = normalize_name(name)
    if not norm:
        return False

    # Check against disallowed common furniture / everyday items
    if any(bad in norm for bad in _DISALLOWED_PROP_SUBSTRINGS):
        # Unless explicitly recognized as a high-value narrative token (e.g. 密信)
        if not any(good in norm for good in _HIGH_VALUE_PROP_KEYWORDS):
            return False

    # High value keywords always pass
    if any(kw in norm for kw in _HIGH_VALUE_PROP_KEYWORDS):
        return True

    # Description indicates high-stakes narrative weight
    desc_clean = description.lower()
    high_stakes_words = ("信物", "证物", "凶器", "线索", "关键", "保命", "遗物", "机密", "誓言")
    if any(w in desc_clean for w in high_stakes_words):
        return True

    return False


@dataclass
class CharacterAsset:
    id: str
    name: str
    aliases: list[str] = field(default_factory=list)
    role: str = "supporting"  # protagonist | antagonist | supporting
    appearance: str = ""
    styling: str = ""
    description: str = ""
    seed: int = 1000
    ref_image_path: str = ""
    episodes: list[int] = field(default_factory=list)

    @property
    def normalized_name(self) -> str:
        return normalize_name(self.name)

    def all_known_names(self) -> set[str]:
        names = {self.normalized_name, self.name.strip()}
        for a in self.aliases:
            names.add(a.strip())
            names.add(normalize_name(a))
        return {n for n in names if n}

    def merge_with(self, other: CharacterAsset) -> None:
        """Merge another character asset representation into this canonical record."""
        # Add new aliases
        existing_names = self.all_known_names()
        for a in [other.name, *other.aliases]:
            norm_a = normalize_name(a)
            if norm_a and norm_a not in existing_names:
                self.aliases.append(norm_a)
                existing_names.add(norm_a)

        # Merge appearance if other provides longer/richer description
        if len(other.appearance) > len(self.appearance):
            self.appearance = other.appearance
        elif other.appearance and other.appearance not in self.appearance:
            self.appearance = f"{self.appearance}；{other.appearance}".strip("；")

        # Merge styling
        if len(other.styling) > len(self.styling):
            self.styling = other.styling
        elif other.styling and other.styling not in self.styling:
            self.styling = f"{self.styling}；{other.styling}".strip("；")

        # Merge episodes
        for ep in other.episodes:
            if ep not in self.episodes:
                self.episodes.append(ep)
        self.episodes.sort()


@dataclass
class SceneAsset:
    id: str
    location: str
    time: str = "白天"
    prompt: str = ""
    lighting: str = ""
    seed: int = 2000
    ref_image_path: str = ""
    episodes: list[int] = field(default_factory=list)

    @property
    def normalized_location(self) -> str:
        return normalize_name(self.location).strip()

    @property
    def normalized_time(self) -> str:
        return self.time.strip()

    @property
    def scene_key(self) -> tuple[str, str]:
        return (self.normalized_location.lower(), self.normalized_time.lower())

    def merge_with(self, other: SceneAsset) -> None:
        if len(other.prompt) > len(self.prompt):
            self.prompt = other.prompt
        if len(other.lighting) > len(self.lighting):
            self.lighting = other.lighting
        for ep in other.episodes:
            if ep not in self.episodes:
                self.episodes.append(ep)
        self.episodes.sort()


@dataclass
class PropAsset:
    id: str
    name: str
    type: str = "信物"
    description: str = ""
    seed: int = 3000
    ref_image_path: str = ""
    episodes: list[int] = field(default_factory=list)

    @property
    def normalized_name(self) -> str:
        return normalize_name(self.name)

    def merge_with(self, other: PropAsset) -> None:
        if len(other.description) > len(self.description):
            self.description = other.description
        for ep in other.episodes:
            if ep not in self.episodes:
                self.episodes.append(ep)
        self.episodes.sort()


class AssetRegistry:
    """Unified repository for Character, Scene, and Prop assets with cross-episode dedup."""

    def __init__(self, base_seed: int = 42) -> None:
        self.base_seed = base_seed
        self.characters: dict[str, CharacterAsset] = {}  # id -> asset
        self.scenes: dict[str, SceneAsset] = {}  # id -> asset
        self.props: dict[str, PropAsset] = {}  # id -> asset

    def _next_char_id(self) -> str:
        return f"C{len(self.characters) + 1:03d}"

    def _next_scene_id(self) -> str:
        return f"S{len(self.scenes) + 1:03d}"

    def _next_prop_id(self) -> str:
        return f"P{len(self.props) + 1:03d}"

    def _deterministic_seed(self, prefix: str, key: str) -> int:
        h = hashlib.sha256(f"{prefix}:{key}".encode("utf-8")).hexdigest()
        return self.base_seed + (int(h[:8], 16) % 10000)

    # ── Character Management ──

    def find_character(self, name_or_alias: str) -> CharacterAsset | None:
        clean = normalize_name(name_or_alias)
        if not clean:
            return None
        for char in self.characters.values():
            if clean in char.all_known_names():
                return char
        return None

    def register_character(
        self,
        name: str,
        *,
        aliases: list[str] | None = None,
        role: str = "supporting",
        appearance: str = "",
        styling: str = "",
        description: str = "",
        episode: int = 1,
    ) -> CharacterAsset:
        norm = normalize_name(name)
        existing = self.find_character(norm)
        if existing is not None:
            candidate = CharacterAsset(
                id=existing.id,
                name=norm,
                aliases=aliases or [],
                role=role,
                appearance=appearance,
                styling=styling,
                description=description,
                episodes=[episode],
            )
            existing.merge_with(candidate)
            return existing

        # Check aliases
        candidate_aliases = [normalize_name(a) for a in (aliases or []) if normalize_name(a)]
        for a in candidate_aliases:
            existing = self.find_character(a)
            if existing is not None:
                candidate = CharacterAsset(
                    id=existing.id,
                    name=norm,
                    aliases=candidate_aliases,
                    role=role,
                    appearance=appearance,
                    styling=styling,
                    description=description,
                    episodes=[episode],
                )
                existing.merge_with(candidate)
                return existing

        cid = self._next_char_id()
        seed = self._deterministic_seed("char", norm)
        asset = CharacterAsset(
            id=cid,
            name=norm,
            aliases=candidate_aliases,
            role=role,
            appearance=appearance,
            styling=styling,
            description=description,
            seed=seed,
            episodes=[episode],
        )
        self.characters[cid] = asset
        return asset

    # ── Scene Management ──

    def find_scene(self, location: str, time: str = "白天") -> SceneAsset | None:
        key = (normalize_name(location).lower(), time.strip().lower())
        for scene in self.scenes.values():
            if scene.scene_key == key:
                return scene
        return None

    def register_scene(
        self,
        location: str,
        time: str = "白天",
        *,
        prompt: str = "",
        lighting: str = "",
        episode: int = 1,
    ) -> SceneAsset:
        norm_loc = normalize_name(location)
        clean_p = clean_scene_prompt(prompt)
        existing = self.find_scene(norm_loc, time)
        if existing is not None:
            candidate = SceneAsset(
                id=existing.id,
                location=norm_loc,
                time=time.strip(),
                prompt=clean_p,
                lighting=lighting,
                episodes=[episode],
            )
            existing.merge_with(candidate)
            return existing

        sid = self._next_scene_id()
        seed = self._deterministic_seed("scene", f"{norm_loc}_{time}")
        asset = SceneAsset(
            id=sid,
            location=norm_loc,
            time=time.strip(),
            prompt=clean_p,
            lighting=lighting,
            seed=seed,
            episodes=[episode],
        )
        self.scenes[sid] = asset
        return asset

    # ── Prop Management ──

    def find_prop(self, name: str) -> PropAsset | None:
        norm = normalize_name(name)
        if not norm:
            return None
        for prop in self.props.values():
            if prop.normalized_name == norm:
                return prop
        return None

    def register_prop(
        self,
        name: str,
        *,
        prop_type: str = "信物",
        description: str = "",
        episode: int = 1,
        force: bool = False,
    ) -> PropAsset | None:
        norm = normalize_name(name)
        if not force and not is_valid_prop(norm, description):
            return None

        # Check existing
        existing = self.find_prop(norm)
        if existing is not None:
            candidate = PropAsset(
                id=existing.id,
                name=norm,
                type=prop_type,
                description=description,
                episodes=[episode],
            )
            existing.merge_with(candidate)
            return existing

        # Enforce maximum 3 props per episode limit
        ep_props = [p for p in self.props.values() if episode in p.episodes]
        if not force and len(ep_props) >= 3:
            return None

        pid = self._next_prop_id()
        seed = self._deterministic_seed("prop", norm)
        asset = PropAsset(
            id=pid,
            name=norm,
            type=prop_type,
            description=description,
            seed=seed,
            episodes=[episode],
        )
        self.props[pid] = asset
        return asset

    # ── Export & Import ──

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_seed": self.base_seed,
            "characters": [asdict(c) for c in self.characters.values()],
            "scenes": [asdict(s) for s in self.scenes.values()],
            "props": [asdict(p) for p in self.props.values()],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AssetRegistry:
        reg = cls(base_seed=int(data.get("base_seed", 42)))
        for c_data in data.get("characters", []):
            char = CharacterAsset(**c_data)
            reg.characters[char.id] = char
        for s_data in data.get("scenes", []):
            scene = SceneAsset(**s_data)
            reg.scenes[scene.id] = scene
        for p_data in data.get("props", []):
            prop = PropAsset(**p_data)
            reg.props[prop.id] = prop
        return reg

    def save_json(self, path: Path | str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load_json(cls, path: Path | str) -> AssetRegistry:
        p = Path(path)
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls.from_dict(data)
