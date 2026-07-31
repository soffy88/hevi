"""
Caption from Audio Skill
Generates accurate timestamps from real audio using ASR (not estimation).
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict

from hevi.analysis.transcribe import transcribe_video

logger = logging.getLogger(__name__)

class CaptionFromAudioSkill:
    """
    Caption from Audio Skill - generates accurate captions from real audio using ASR.
    
    Input: Audio file
    Output: Time-stamped captions (SRT/VTT format)
    """
    
    async def execute(self, *, audio_file: str, output_path: str, 
                     language: str = "auto", format_type: str = "srt") -> Dict[str, Any]:
        """
        Generate captions from real audio using ASR.
        
        Args:
            audio_file: Path to audio file
            output_path: Where to save the caption file
            language: Language for transcription ('auto', 'zh', 'en', etc.)
            format_type: Output format ('srt', 'vtt', 'txt')
            
        Returns:
            Dictionary containing result information
        """
        try:
            # Validate that we're working with real audio, not estimating
            audio_path = Path(audio_file)
            if not audio_path.exists():
                raise FileNotFoundError(f"Audio file not found: {audio_file}")
            
            # Use real ASR to generate accurate timestamps (not estimation!)
            logger.info(f"Starting ASR transcription for {audio_file}")
            
            # Use hevi.analysis.transcribe which has better fallback handling
            import tempfile
            import shutil
            from hevi.analysis.transcribe import transcribe_video
            
            output_dir = Path(output_path).parent
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Create temp video file (transcribe_video expects video)
            temp_video_dir = Path(tempfile.mkdtemp())
            temp_video_path = temp_video_dir / "temp_video.mp4"
            shutil.copy2(audio_path, temp_video_path)
            
            try:
                transcription_result = transcribe_video(
                    video_path=temp_video_path,
                    output_dir=output_dir,
                    model_size="base",
                    language=language if language != "auto" else None,
                    word_timestamps=True
                )
                
                transcript_dict = {
                    "segments": [
                        {"start": seg.start, "end": seg.end, "text": seg.text}
                        for seg in transcription_result.segments
                    ]
                }
            finally:
                if temp_video_dir.exists():
                    shutil.rmtree(temp_video_dir, ignore_errors=True)
            
            # Generate appropriate caption format
            if format_type.lower() == 'srt':
                caption_content = self._transcript_to_srt(transcript_dict)
            elif format_type.lower() == 'vtt':
                caption_content = self._transcript_to_vtt(transcript_dict)
            else:
                caption_content = self._transcript_to_txt(transcript_dict)
            
            # Write caption file
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(caption_content)
            
            logger.info(f"Captions generated from real audio: {output_file}")
            
            return {
                "status": "success",
                "subtitle_file": str(output_file),
                "word_count": len(transcript_dict.get('segments', [])),
                "source": "real_audio_asr",  # Critical: confirms it's from real audio, not estimation
                "format": format_type
            }
            
        except Exception as e:
            logger.error(f"Caption generation from audio failed: {str(e)}")
            raise RuntimeError(f"Caption from audio skill failed: {str(e)}")
    
    def _transcript_to_srt(self, transcript: Dict[str, Any]) -> str:
        """Convert transcript to SRT format."""
        segments = transcript.get('segments', [])
        srt_lines = []
        
        for i, segment in enumerate(segments, 1):
            start_time = segment.get('start', 0)
            end_time = segment.get('end', 0)
            text = segment.get('text', '').strip()
            
            # Format time as HH:MM:SS,mmm
            start_formatted = self._format_time(start_time)
            end_formatted = self._format_time(end_time)
            
            srt_lines.extend([
                str(i),
                f"{start_formatted} --> {end_formatted}",
                text,
                ""  # Empty line between entries
            ])
        
        return '\n'.join(srt_lines)
    
    def _transcript_to_vtt(self, transcript: Dict[str, Any]) -> str:
        """Convert transcript to WebVTT format."""
        segments = transcript.get('segments', [])
        vtt_lines = ["WEBVTT", ""]  # WebVTT header
        
        for segment in segments:
            start_time = segment.get('start', 0)
            end_time = segment.get('end', 0)
            text = segment.get('text', '').strip()
            
            start_formatted = self._format_time_vtt(start_time)
            end_formatted = self._format_time_vtt(end_time)
            
            vtt_lines.extend([
                f"{start_formatted} --> {end_formatted}",
                text,
                ""  # Empty line between entries
            ])
        
        return '\n'.join(vtt_lines)
    
    def _transcript_to_txt(self, transcript: Dict[str, Any]) -> str:
        """Convert transcript to plain text with timestamps."""
        segments = transcript.get('segments', [])
        txt_lines = []
        
        for segment in segments:
            start_time = segment.get('start', 0)
            text = segment.get('text', '').strip()
            formatted_time = self._format_time(start_time)
            
            txt_lines.append(f"[{formatted_time}] {text}")
        
        return '\n'.join(txt_lines)
    
    def _format_time(self, seconds: float) -> str:
        """Format time in seconds to HH:MM:SS,mmm format."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millisecs = int((seconds - int(seconds)) * 1000)
        
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millisecs:03d}"
    
    def _format_time_vtt(self, seconds: float) -> str:
        """Format time in seconds to HH:MM:SS.mmm format for VTT."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millisecs = int((seconds - int(seconds)) * 1000)
        
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millisecs:03d}"


# Convenience function for direct execution
async def caption_from_audio_skill_execute(*, audio_file: str, output_path: str, 
                                       language: str = "auto", format_type: str = "srt") -> Dict[str, Any]:
    """
    Direct execution function for the caption from audio skill.
    """
    skill = CaptionFromAudioSkill()
    return await skill.execute(audio_file=audio_file, output_path=output_path, 
                              language=language, format_type=format_type)