"""
TTS Skill Implementation
Skill that handles local TTS generation with hard validation.
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List
import hashlib

from hevi.audio.tts_service import synthesize_dialogue
from hevi.scripts.validate_tts_provider import validate_tts_provider

logger = logging.getLogger(__name__)

class TTSSkill:
    """
    TTS Skill - generates audio from text using local TTS only.
    
    Input: Text content and voice reference
    Output: Audio file + voice_manifest.json
    """
    
    def __init__(self):
        # Validate provider at initialization
        validate_tts_provider()
    
    async def execute(self, *, text: str, voice_reference: str = None, output_path: str) -> Dict[str, Any]:
        """
        Execute TTS generation with local provider only.
        
        Args:
            text: Input text to convert to speech
            voice_reference: Path to voice reference file (optional)
            output_path: Where to save the output audio
            
        Returns:
            Dictionary containing result information
        """
        try:
            # Validate that we're using local provider
            config_path = Path("hevi/configs/tts_routing.json")
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            if config.get("production_provider") != "local-indextts2":
                raise RuntimeError("TTS provider validation failed - not using local provider")
            
            # Prepare the script for synthesis
            script_entry = {
                "speaker_id": "default",
                "text": text,
                "voice_ref": voice_reference if voice_reference else None
            }
            
            # Generate audio using local TTS service
            output_file = Path(output_path)
            result_path = await synthesize_dialogue(
                config={},
                script=[script_entry],
                output_path=output_file
            )
            
            # Create voice manifest
            manifest_data = {
                "provider": "local-indextts2",
                "input_text": text[:100] + "..." if len(text) > 100 else text,  # Truncate long texts
                "voice_reference": voice_reference,
                "output_file": str(result_path),
                "timestamp": asyncio.get_event_loop().time()
            }
            
            # Save manifest
            manifest_path = output_file.with_suffix('.json')
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(manifest_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"TTS generation completed: {result_path}")
            logger.info(f"Voice manifest saved: {manifest_path}")
            
            return {
                "status": "success",
                "audio_file": str(result_path),
                "voice_manifest": str(manifest_path),
                "provider": "local-indextts2"
            }
            
        except Exception as e:
            logger.error(f"TTS generation failed: {str(e)}")
            raise RuntimeError(f"TTS skill failed: {str(e)}")


# Convenience function for direct execution
async def tts_skill_execute(*, text: str, voice_reference: str = None, output_path: str) -> Dict[str, Any]:
    """
    Direct execution function for the TTS skill.
    """
    skill = TTSSkill()
    return await skill.execute(text=text, voice_reference=voice_reference, output_path=output_path)