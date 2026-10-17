"""
Production Director Skill
Orchestrates the entire production pipeline: audio -> render -> subtitles -> QC.
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict

from hevi.skills.tts_skill import tts_skill_execute
from hevi.skills.caption_from_audio import caption_from_audio_skill_execute
from hevi.skills.final_qc import final_qc_skill_execute

logger = logging.getLogger(__name__)

class ProductionDirectorSkill:
    """
    Production Director Skill - orchestrates the complete video production pipeline.
    
    Input: Handover document with frontmatter
    Output: Complete video with all stages processed
    """
    
    async def execute(self, *, handover_file: str, output_dir: str = "outputs") -> Dict[str, Any]:
        """
        Execute the complete production pipeline.
        
        Args:
            handover_file: Path to the handover document
            output_dir: Directory for output files
            
        Returns:
            Dictionary containing pipeline results
        """
        try:
            # Read handover file
            with open(handover_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Extract frontmatter and content (simplified - real implementation would parse properly)
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    frontmatter_str = parts[1]
                    script_content = parts[2].strip()
                    
                    # Parse frontmatter (simplified)
                    frontmatter = self._parse_frontmatter(frontmatter_str)
                else:
                    raise ValueError("Invalid handover file format - missing proper frontmatter")
            else:
                # If no frontmatter, treat entire content as script
                script_content = content
                frontmatter = {
                    "title": "Untitled",
                    "production_requirements": {
                        "tts_provider": "local-indextts2"
                    }
                }
            
            # Validate production requirements
            reqs = frontmatter.get("production_requirements", {})
            if reqs.get("tts_provider") != "local-indextts2":
                raise RuntimeError(f"Production requires local TTS, got: {reqs.get('tts_provider')}")
            
            # Ensure output directory exists
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            
            # Stage 1: Audio generation
            logger.info("Starting audio generation stage...")
            audio_output = await tts_skill_execute(
                text=script_content,
                output_path=str(output_path / "audio_output.wav")
            )
            
            if audio_output["status"] != "success":
                raise RuntimeError("Audio generation failed")
            
            # Stage 2: Rendering (placeholder - would integrate with actual renderer)
            logger.info("Starting rendering stage...")
            rendered_video = await self._render_video(
                audio_file=audio_output["audio_file"],
                output_path=str(output_path / "rendered_video.mp4")
            )
            
            # Stage 3: Subtitles from real audio (not estimated!)
            logger.info("Generating subtitles from real audio...")
            subtitle_result = await caption_from_audio_skill_execute(
                audio_file=audio_output["audio_file"],
                output_path=str(output_path / "subtitles.srt")
            )
            
            if subtitle_result["status"] != "success":
                raise RuntimeError("Subtitle generation failed")
            
            # Stage 4: Final QC
            logger.info("Performing final QC...")
            qc_result = await final_qc_skill_execute(
                video_file=rendered_video,
                audio_file=audio_output["audio_file"],
                subtitle_file=subtitle_result["subtitle_file"]
            )
            
            if not qc_result.get("passed", False):
                raise RuntimeError(f"Final QC failed: {qc_result.get('issues', [])}")
            
            logger.info("Production pipeline completed successfully!")
            
            return {
                "status": "success",
                "stages_completed": [
                    "audio_generation",
                    "rendering", 
                    "subtitle_generation",
                    "final_qc"
                ],
                "output_files": {
                    "audio": audio_output["audio_file"],
                    "video": rendered_video,
                    "subtitles": subtitle_result["subtitle_file"],
                    "qc_report": qc_result.get("report_file")
                },
                "pipeline_passed": True
            }
            
        except Exception as e:
            logger.error(f"Production pipeline failed: {str(e)}")
            raise RuntimeError(f"Production director skill failed: {str(e)}")
    
    def _parse_frontmatter(self, frontmatter_str: str) -> Dict[str, Any]:
        """Parse frontmatter from YAML-like format (simplified)."""
        # Simplified parser - real implementation would use proper YAML
        result = {}
        for line in frontmatter_str.strip().split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()
                
                # Try to parse value appropriately
                if value.lower() in ['true', 'false']:
                    value = value.lower() == 'true'
                elif value.isdigit():
                    value = int(value)
                elif value.startswith('"') and value.endswith('"'):
                    value = value.strip('"')
                
                result[key] = value
        
        return result
    
    async def _render_video(self, audio_file: str, output_path: str) -> str:
        """Placeholder for video rendering - would integrate with actual renderer."""
        # In a real implementation, this would call the video renderer
        # For now, we'll just copy the audio to simulate a video file
        import shutil
        
        # Create a dummy video file with audio (just copy audio file for simulation)
        src_path = Path(audio_file)
        dst_path = Path(output_path)
        
        # Copy audio file to simulate video file for demo purposes
        shutil.copy2(src_path, dst_path)
        
        logger.info(f"Video rendering simulated: {dst_path}")
        return str(dst_path)


# Convenience function for direct execution
async def production_director_skill_execute(*, handover_file: str, output_dir: str = "outputs") -> Dict[str, Any]:
    """
    Direct execution function for the production director skill.
    """
    skill = ProductionDirectorSkill()
    return await skill.execute(handover_file=handover_file, output_dir=output_dir)