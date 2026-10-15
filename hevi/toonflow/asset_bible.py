# Asset Bible (资产圣经)
import json
import os
from typing import Dict, Any, List, Optional

class AssetBible:
    def __init__(self, workspace_dir: str = "."):
        self.workspace_dir = workspace_dir
        self.bible_path = os.path.join(workspace_dir, "asset_bible.json")
        self.data: Dict[str, Any] = {"characters": {}, "scenes": {}, "props": {}}
        self.load()

    def load(self):
        if os.path.exists(self.bible_path):
            try:
                with open(self.bible_path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                pass

    def save(self):
        os.makedirs(self.workspace_dir, exist_ok=True)
        with open(self.bible_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def register_character(self, name: str, appearance: str, views: List[str], palette: List[str], taboos: List[str]):
        self.data["characters"][name] = {
            "name": name,
            "appearance": appearance,
            "views": views,
            "palette": palette,
            "taboos": taboos
        }
        self.save()

    def register_scene(self, name: str, description: str, lighting: str):
        self.data["scenes"][name] = {
            "name": name,
            "description": description,
            "lighting": lighting
        }
        self.save()

    def register_prop(self, name: str, description: str):
        self.data["props"][name] = {
            "name": name,
            "description": description
        }
        self.save()

    def get_prompt_injection(self, character_names: List[str]) -> str:
        parts = []
        for name in character_names:
            if name in self.data["characters"]:
                c = self.data["characters"][name]
                parts.append(f"[Character: {name}] Appearance: {c['appearance']}. Palette: {', '.join(c['palette'])}. Taboos: {', '.join(c['taboos'])}.")
        return " ".join(parts)

    def check_consistency(self, shot_id: str, character_name: str, observed_palette: List[str]) -> Dict[str, Any]:
        if character_name not in self.data["characters"]:
            return {"consistent": True, "reason": "Unknown character"}
        expected = set(self.data["characters"][character_name]["palette"])
        observed = set(observed_palette)
        # Check overlap
        intersection = expected.intersection(observed)
        consistent = len(intersection) > 0 or not expected
        return {
            "shot_id": shot_id,
            "character": character_name,
            "consistent": consistent,
            "expected_palette": list(expected),
            "observed_palette": list(observed),
            "action": "PASS" if consistent else "MARK_RED_REDO"
        }
