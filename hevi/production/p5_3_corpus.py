import json
from enum import Enum
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass

class AdoptionMode(str, Enum):
    REFERENCE_ONLY = "REFERENCE_ONLY"
    CONTRACT_ADOPT = "CONTRACT_ADOPT"
    RECIPE_SOURCE = "RECIPE_SOURCE"
    CODE_ADOPT_ALLOWED = "CODE_ADOPT_ALLOWED"
    REJECT = "REJECT"

@dataclass(frozen=True)
class ReferenceEntry:
    name: str
    license: str
    adoption_mode: AdoptionMode

class VideoAgentReferenceCorpus:
    """Read-only corpus of video agent reference capabilities."""
    
    def __init__(self, data_path: str = "data/p5_3_reference_corpus.json"):
        self.data_path = Path(data_path)
        self._entries: List[ReferenceEntry] = []
        self._load()

    def _load(self):
        if not self.data_path.exists():
            return
            
        with open(self.data_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        for ref in data.get("references", []):
            mode = AdoptionMode(ref.get("adoption_mode", "REFERENCE_ONLY"))
            if ref.get("license", "unknown").lower() == "unknown":
                mode = AdoptionMode.REFERENCE_ONLY
                
            self._entries.append(ReferenceEntry(
                name=ref["name"],
                license=ref.get("license", "unknown"),
                adoption_mode=mode
            ))

    def get_entry(self, name: str) -> Optional[ReferenceEntry]:
        for entry in self._entries:
            if entry.name == name:
                return entry
        return None

    def list_entries(self) -> List[ReferenceEntry]:
        return list(self._entries)

class ReferenceRepository:
    """Repository interface for the video reference corpus."""
    
    def __init__(self, corpus: VideoAgentReferenceCorpus):
        self.corpus = corpus

    def check_license_boundary(self, name: str) -> bool:
        """Enforces LICENSE_BOUNDARY gate."""
        entry = self.corpus.get_entry(name)
        if not entry:
            return False
        return entry.adoption_mode != AdoptionMode.REJECT

    def allow_code_execution(self, name: str) -> bool:
        """Enforces EXTERNAL_CODE_EXECUTION=0 gate."""
        return False
        
    def allow_unlicensed_import(self) -> bool:
        """Enforces UNLICENSED_CODE_IMPORT=0 gate."""
        return False
