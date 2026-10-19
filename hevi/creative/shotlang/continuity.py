from typing import Dict, Any
from hevi.creative.shotlang.schemas import ShotLangSpec, ContinuityCard

class ContinuityValidationResult:
    def __init__(self, valid: bool, errors: List[str] = None):
        self.valid = valid
        self.errors = errors or []

def validate_continuity(shot: ShotLangSpec, card: ContinuityCard) -> ContinuityValidationResult:
    errors = []
    if not shot.shot_id:
        errors.append("Missing shot_id")
    if not shot.task:
        errors.append("Missing viewing task description")
    if not shot.framing:
        errors.append("Missing framing specification")
    
    # Check consistency with card
    if card.project_id and shot.continuity_rules.project_id:
        if card.project_id != shot.continuity_rules.project_id:
            errors.append("Project ID mismatch in continuity rules")
            
    return ContinuityValidationResult(valid=len(errors) == 0, errors=errors)
