"""
Digital Twin Guard Skill
Ensures digital person generation only proceeds after audition confirmation.
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

class DigitalTwinGuardSkill:
    """
    Digital Twin Guard Skill - ensures digital person generation follows proper approval workflow.
    
    Input: Digital person request parameters
    Output: Approval status or rejection with reason
    """
    
    def __init__(self):
        # In a real implementation, this would connect to a persistent storage
        # For demo, we'll use a simple in-memory store
        self.audition_approvals = {}
    
    async def execute(self, *, voice_sample_path: str, 
                     digital_person_params: Dict[str, Any], 
                     skip_audition_check: bool = False) -> Dict[str, Any]:
        """
        Check if digital person generation is approved.
        
        Args:
            voice_sample_path: Path to the voice sample used for cloning
            digital_person_params: Parameters for digital person generation
            skip_audition_check: Whether to skip audition check (for testing)
            
        Returns:
            Dictionary containing approval status and details
        """
        try:
            # Extract the voice sample identifier (could be hash, filename, etc.)
            voice_identifier = self._extract_voice_identifier(voice_sample_path)
            
            if skip_audition_check:
                logger.warning("Audition check skipped - only for testing purposes")
                return {
                    "status": "approved",
                    "reason": "skipped_for_testing",
                    "voice_identifier": voice_identifier,
                    "params": digital_person_params
                }
            
            # Check if this voice sample has been approved
            if voice_identifier in self.audition_approvals:
                approval_record = self.audition_approvals[voice_identifier]
                if approval_record.get("approved", False):
                    logger.info(f"Digital person generation approved for voice: {voice_identifier}")
                    return {
                        "status": "approved",
                        "reason": "audition_confirmed",
                        "voice_identifier": voice_identifier,
                        "approval_timestamp": approval_record.get("timestamp"),
                        "approver": approval_record.get("approver"),
                        "params": digital_person_params
                    }
                else:
                    logger.error(f"Audition not approved for voice: {voice_identifier}")
                    raise RuntimeError(f"Digtal person generation denied: audition not approved for {voice_identifier}")
            else:
                logger.error(f"No audition confirmation found for voice: {voice_identifier}")
                raise RuntimeError(f"Digital person generation blocked: no audition confirmation for {voice_identifier}")
                
        except Exception as e:
            logger.error(f"Digital twin guard check failed: {str(e)}")
            raise RuntimeError(f"Digital twin guard skill failed: {str(e)}")
    
    def _extract_voice_identifier(self, voice_path: str) -> str:
        """Extract a unique identifier from the voice sample path."""
        # In a real implementation, this might calculate a hash of the audio file
        # For demo, we'll use the filename or path
        path = Path(voice_path)
        return str(path.name) if path.name != '.' else str(path.absolute())
    
    async def register_audition_approval(self, voice_sample_path: str, approver: str = "system") -> Dict[str, Any]:
        """Register an audition as approved (typically called by admin interface)."""
        voice_identifier = self._extract_voice_identifier(voice_sample_path)
        
        self.audition_approvals[voice_identifier] = {
            "approved": True,
            "timestamp": asyncio.get_event_loop().time(),
            "approver": approver
        }
        
        logger.info(f"Audition approved for voice: {voice_identifier} by {approver}")
        
        return {
            "status": "registered",
            "voice_identifier": voice_identifier,
            "approver": approver,
            "timestamp": self.audition_approvals[voice_identifier]["timestamp"]
        }


# Convenience function for direct execution
async def digital_twin_guard_skill_execute(*, voice_sample_path: str, 
                                        digital_person_params: Dict[str, Any], 
                                        skip_audition_check: bool = False) -> Dict[str, Any]:
    """
    Direct execution function for the digital twin guard skill.
    """
    skill = DigitalTwinGuardSkill()
    return await skill.execute(voice_sample_path=voice_sample_path, 
                             digital_person_params=digital_person_params,
                             skip_audition_check=skip_audition_check)