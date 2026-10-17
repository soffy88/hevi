"""
Script to Handover Skill
Converts raw text/script to standardized handover format with frontmatter.
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

class ScriptToHandoverSkill:
    """
    Script to Handover Skill - converts text to standardized format with frontmatter.
    
    Input: Raw script/text content
    Output: Standardized handover file with frontmatter
    """
    
    async def execute(self, *, input_content: str, title: str = "Untitled", 
                     content_type: str = "video_script", metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Convert input content to standardized handover format.
        
        Args:
            input_content: Raw script/text content
            title: Title for the handover document
            content_type: Type of content ('video_script', 'podcast', etc.)
            metadata: Additional metadata to include in frontmatter
            
        Returns:
            Dictionary containing result information
        """
        try:
            # Create standardized frontmatter
            frontmatter = {
                "title": title,
                "type": content_type,
                "created_at": datetime.now().isoformat(),
                "version": "1.0",
                "status": "ready_for_production",
                "production_requirements": {
                    "tts_provider": "local-indextts2",
                    "quality_gates": ["audio_qc", "visual_qc", "final_approval"]
                },
                "metadata": metadata or {},
                "handover_schema": "hevi-v1-standard"
            }
            
            # Combine frontmatter and content
            yaml_frontmatter = self._dict_to_yaml(frontmatter)
            handover_content = f"---\n{yaml_frontmatter}---\n\n{input_content}"
            
            # Generate output filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"{title.replace(' ', '_')}_{timestamp}_handover.md"
            
            # Write to file
            output_path = Path("outputs") / output_filename
            output_path.parent.mkdir(exist_ok=True)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(handover_content)
            
            logger.info(f"Script converted to handover format: {output_path}")
            
            return {
                "status": "success",
                "handover_file": str(output_path),
                "frontmatter": frontmatter,
                "content_length": len(input_content)
            }
            
        except Exception as e:
            logger.error(f"Script to handover conversion failed: {str(e)}")
            raise RuntimeError(f"Script to handover skill failed: {str(e)}")
    
    def _dict_to_yaml(self, data: Dict[str, Any], indent: int = 0) -> str:
        """Convert dictionary to YAML-like format."""
        yaml_str = ""
        for key, value in data.items():
            spaces = "  " * indent
            if isinstance(value, dict):
                yaml_str += f"{spaces}{key}:\n{self._dict_to_yaml(value, indent + 1)}"
            elif isinstance(value, list):
                yaml_str += f"{spaces}{key}:\n"
                for item in value:
                    if isinstance(item, dict):
                        yaml_str += f"{spaces}  - {self._dict_to_yaml(item, indent + 2).lstrip()}"
                    else:
                        yaml_str += f"{spaces}  - {item}\n"
            else:
                yaml_str += f"{spaces}{key}: {value}\n"
        return yaml_str


# Convenience function for direct execution
async def script_to_handover_skill_execute(*, input_content: str, title: str = "Untitled", 
                                         content_type: str = "video_script", metadata: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Direct execution function for the script to handover skill.
    """
    skill = ScriptToHandoverSkill()
    return await skill.execute(input_content=input_content, title=title, 
                             content_type=content_type, metadata=metadata)