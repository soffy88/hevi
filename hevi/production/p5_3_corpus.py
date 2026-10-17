import json
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass

class AdoptionMode(str, Enum):
    REFERENCE_ONLY = "REFERENCE_ONLY"
    CONTRACT_ADOPT = "CONTRACT_ADOPT"
    RECIPE_SOURCE = "RECIPE_SOURCE"
    CODE_ADOPT_ALLOWED = "CODE_ADOPT_ALLOWED"
    REJECT = "REJECT"

@dataclass
class ReferenceEntry:
    name: str
    verifiable: bool
    license: str
    description: str
    adoption_mode: AdoptionMode

class VideoAgentReferenceCorpus:
    def __init__(self, data_path: Optional[Path] = None):
        if data_path is None:
            data_path = Path(__file__).parent.parent.parent / "data" / "p5_3_reference_corpus.json"
        
        self.data_path = data_path
        self._entries: Dict[str, ReferenceEntry] = {}
        self._load()

    def _load(self) -> None:
        if not self.data_path.exists():
            return
            
        with open(self.data_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        for item in data.get("seed_references", []):
            mode = item.get("adoption_mode", "REFERENCE_ONLY")
            if item.get("license", "Unknown") == "Unknown":
                mode = "REFERENCE_ONLY"
                
            entry = ReferenceEntry(
                name=item["name"],
                verifiable=item.get("verifiable", False),
                license=item.get("license", "Unknown"),
                description=item.get("description", ""),
                adoption_mode=AdoptionMode(mode)
            )
            self._entries[entry.name] = entry

    def get_reference(self, name: str) -> Optional[ReferenceEntry]:
        return self._entries.get(name)

    def list_references(self) -> List[ReferenceEntry]:
        return list(self._entries.values())
