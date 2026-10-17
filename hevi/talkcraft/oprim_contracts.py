from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass(kw_only=True)
class WordTimestamp:
    text: str
    start: float
    end: float

@dataclass(kw_only=True)
class SentenceTimestamp:
    i: int
    text: str
    start: float
    end: float
    asr: str
    match: float
    ok: bool
    words: List[WordTimestamp]

@dataclass(kw_only=True)
class AlignmentResult:
    sr: int
    total: float
    sentences: List[SentenceTimestamp]

@dataclass(kw_only=True)
class Beat:
    start: float
    end: float
    type: str

@dataclass(kw_only=True)
class ShotSpec:
    id: str
    start: float
    end: float
    props: Dict[str, Any]

@dataclass(kw_only=True)
class Shotbook:
    shots: List[ShotSpec]

@dataclass(kw_only=True)
class TalkcraftRenderRequest:
    shotbook: Shotbook
    timing: Any
    output_path: str
    resolution: str
    fps: int
    audio_sfx: List[Dict[str, Any]]

@dataclass(kw_only=True)
class TalkcraftRenderResult:
    path: str
    duration: float
    sha256: str
    qa_records: Dict[str, Any]

