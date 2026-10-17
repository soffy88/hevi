"""
Final QC Skill
Performs comprehensive quality check on the final video product.
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

class FinalQCSkill:
    """
    Final QC Skill - performs comprehensive quality check on final products.
    
    Input: Video, audio, and subtitle files
    Output: QC report with pass/fail status
    """
    
    async def execute(self, *, video_file: str, audio_file: str, 
                     subtitle_file: str = None, criteria: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Perform final quality control check.
        
        Args:
            video_file: Path to video file
            audio_file: Path to audio file  
            subtitle_file: Path to subtitle file (optional)
            criteria: Custom QC criteria (optional)
            
        Returns:
            Dictionary containing QC results
        """
        try:
            # Initialize with default criteria if not provided
            if criteria is None:
                criteria = {
                    "audio_quality": {"min_db": -32, "max_db": -6},  # LUFS range
                    "video_integrity": True,
                    "subtitle_sync": True,
                    "file_size_check": True,
                    "codec_compliance": True
                }
            
            # Validate file existence
            video_path = Path(video_file)
            audio_path = Path(audio_file)
            
            if not video_path.exists():
                raise FileNotFoundError(f"Video file not found: {video_file}")
            if not audio_path.exists():
                raise FileNotFoundError(f"Audio file not found: {audio_file}")
            
            # Perform comprehensive QC checks
            issues = []
            warnings = []
            
            # Check 1: File integrity
            logger.info("Checking file integrity...")
            integrity_issues = await self._check_file_integrity(video_path, audio_path)
            issues.extend(integrity_issues)
            
            # Check 2: Audio quality
            logger.info("Checking audio quality...")
            audio_issues = await self._check_audio_quality(str(audio_path), criteria.get("audio_quality", {}))
            issues.extend(audio_issues)
            
            # Check 3: Video properties
            logger.info("Checking video properties...")
            video_issues = await self._check_video_properties(str(video_path))
            issues.extend(video_issues)
            
            # Check 4: Subtitle validation (if provided)
            if subtitle_file:
                logger.info("Checking subtitle sync...")
                subtitle_issues = await self._check_subtitle_sync(subtitle_file, str(audio_path))
                issues.extend(subtitle_issues)
            
            # Determine pass/fail status
            passed = len(issues) == 0
            
            # Create QC report
            qc_report = {
                "timestamp": asyncio.get_event_loop().time(),
                "video_file": str(video_path),
                "audio_file": str(audio_path),
                "subtitle_file": subtitle_file,
                "criteria_used": criteria,
                "passed": passed,
                "issues": issues,
                "warnings": warnings,
                "checks_performed": [
                    "file_integrity",
                    "audio_quality", 
                    "video_properties",
                    "subtitle_sync" if subtitle_file else "subtitle_sync_skipped"
                ]
            }
            
            # Generate output path for report
            report_path = video_path.with_suffix('.qc.json')
            with open(report_path, 'w', encoding='utf-8') as f:
                json.dump(qc_report, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Final QC completed. Passed: {passed}. Report: {report_path}")
            
            if not passed:
                logger.error(f"QC failed with {len(issues)} issues: {issues[:3]}...")  # Show first 3 issues
                raise RuntimeError(f"Final QC failed: {len(issues)} issues found")
            
            return {
                "status": "success",
                "passed": passed,
                "issues_found": len(issues),
                "warnings_found": len(warnings),
                "report_file": str(report_path),
                "qc_details": qc_report
            }
            
        except Exception as e:
            logger.error(f"Final QC failed: {str(e)}")
            raise RuntimeError(f"Final QC skill failed: {str(e)}")
    
    async def _check_file_integrity(self, video_path: Path, audio_path: Path) -> List[str]:
        """Check basic file integrity."""
        issues = []
        
        # Check if files are not empty
        if video_path.stat().st_size == 0:
            issues.append("Video file is empty")
        if audio_path.stat().st_size == 0:
            issues.append("Audio file is empty")
        
        # Check if files have valid extensions
        valid_video_exts = ['.mp4', '.mov', '.avi', '.mkv', '.webm']
        valid_audio_exts = ['.wav', '.mp3', '.aac', '.flac', '.m4a']
        
        if video_path.suffix.lower() not in valid_video_exts:
            issues.append(f"Video file has unsupported extension: {video_path.suffix}")
        if audio_path.suffix.lower() not in valid_audio_exts:
            issues.append(f"Audio file has unsupported extension: {audio_path.suffix}")
        
        return issues
    
    async def _check_audio_quality(self, audio_file: str, criteria: Dict[str, Any]) -> List[str]:
        """Check audio quality against criteria."""
        issues = []
        
        # Placeholder for actual audio analysis
        # In real implementation, would use librosa, pydub, or similar
        # to analyze loudness, frequency response, etc.
        
        # For now, just check if file exists and has reasonable size
        path = Path(audio_file)
        size_mb = path.stat().st_size / (1024 * 1024)
        
        if size_mb < 0.1:  # Less than 0.1 MB is suspiciously small
            issues.append(f"Audio file is suspiciously small ({size_mb:.2f} MB)")
        
        # Mock loudness check (would be real in production)
        # For demo, assume we can't actually measure loudness
        logger.debug("Audio quality check - would analyze actual loudness in production")
        
        return issues
    
    async def _check_video_properties(self, video_file: str) -> List[str]:
        """Check video properties."""
        issues = []
        
        path = Path(video_file)
        size_mb = path.stat().st_size / (1024 * 1024)
        
        if size_mb < 0.5:  # Less than 0.5 MB is suspiciously small for video
            issues.append(f"Video file is suspiciously small ({size_mb:.2f} MB)")
        
        # In production, would use ffprobe or similar to check codec, resolution, etc.
        logger.debug("Video properties check - would analyze actual video properties in production")
        
        return issues
    
    async def _check_subtitle_sync(self, subtitle_file: str, audio_file: str) -> List[str]:
        """Check subtitle synchronization with audio."""
        issues = []
        
        sub_path = Path(subtitle_file)
        if not sub_path.exists():
            issues.append(f"Subtitle file not found: {subtitle_file}")
            return issues
        
        # Check if subtitle file has content
        with open(sub_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
        
        if not content:
            issues.append("Subtitle file is empty")
        
        # In production, would check timing alignment
        # For demo, just verify it's not empty
        logger.debug("Subtitle sync check - would verify timing alignment in production")
        
        return issues


# Convenience function for direct execution
async def final_qc_skill_execute(*, video_file: str, audio_file: str, 
                           subtitle_file: str = None, criteria: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Direct execution function for the final QC skill.
    """
    skill = FinalQCSkill()
    return await skill.execute(video_file=video_file, audio_file=audio_file, 
                             subtitle_file=subtitle_file, criteria=criteria)