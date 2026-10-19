from pydantic import BaseModel, Field
from typing import List, Optional

class ContinuityCard(BaseModel):
    project_id: str = "default_project"
    characters: List[str] = Field(default_factory=list)
    clothing: List[str] = Field(default_factory=list)
    props: List[str] = Field(default_factory=list)
    seating_and_direction: str = ""
    axis_rule: str = "180-degree axis respected"
    light_direction: str = "Consistent window side light"

class ShotLangSpec(BaseModel):
    shot_id: str
    task: str
    framing: str  # e.g., "中景 (Medium Shot - 腰部以上，手与炸鸡入画)"
    camera_position_and_angle: str  # e.g., "过肩镜头 (Over-the-shoulder)"
    composition_and_negative_space: str
    focus_and_depth: str
    lighting: str
    camera_movement: str  # e.g., "相对车内固定 (Static relative to interior)"
    start_state: str
    end_state: str
    continuity_rules: ContinuityCard = Field(default_factory=ContinuityCard)
    acceptance_criteria: str = ""
