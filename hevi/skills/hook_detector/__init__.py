"""
Hook Detector Skill
Analyzes video content for engagement hooks and suggests improvements.
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

class HookDetectorSkill:
    """
    Hook Detector Skill - analyzes content for engagement hooks.
    
    Input: Video script/content
    Output: Hook analysis and improvement suggestions
    """
    
    def __init__(self):
        # Define common hook patterns and anti-patterns
        self.strong_hooks = [
            "为什么", "真相", "秘密", "震惊", "颠覆", "首次", "独家", 
            "没想到", "竟然", "原来", "万万没想到", "太意外"
        ]
        self.weak_hooks = [
            "介绍", "概述", "讲解", "分析", "谈论", "讨论"
        ]
        self.engagement_patterns = [
            "提出问题", "制造悬念", "对比反差", "数据冲击", 
            "情感共鸣", "实用价值", "稀缺性", "权威背书"
        ]
    
    async def execute(self, *, content: str, threshold: float = 0.5) -> Dict[str, Any]:
        """
        Analyze content for engagement hooks and quality.
        
        Args:
            content: Video script or content to analyze
            threshold: Engagement quality threshold (0-1)
            
        Returns:
            Dictionary containing hook analysis and suggestions
        """
        try:
            logger.info(f"Analyzing content for engagement hooks: {content[:50]}...")
            
            # Analyze content for hook elements
            analysis = await self._analyze_hooks(content)
            
            # Calculate overall engagement score
            engagement_score = self._calculate_engagement_score(analysis)
            
            # Generate improvement suggestions
            suggestions = await self._generate_suggestions(analysis, content)
            
            # Determine if content passes engagement threshold
            passes_threshold = engagement_score >= threshold
            
            logger.info(f"Hook analysis complete. Score: {engagement_score:.2f}, Passes: {passes_threshold}")
            
            return {
                "status": "success",
                "engagement_score": engagement_score,
                "passes_threshold": passes_threshold,
                "analysis": analysis,
                "suggestions": suggestions,
                "content_length": len(content)
            }
            
        except Exception as e:
            logger.error(f"Hook detection failed: {str(e)}")
            raise RuntimeError(f"Hook detector skill failed: {str(e)}")
    
    async def _analyze_hooks(self, content: str) -> Dict[str, Any]:
        """Analyze content for various hook elements."""
        content_lower = content.lower()
        
        # Count strong hooks
        strong_matches = []
        for hook in self.strong_hooks:
            if hook.lower() in content_lower:
                strong_matches.append(hook)
        
        # Count weak hooks
        weak_matches = []
        for hook in self.weak_hooks:
            if hook.lower() in content_lower:
                weak_matches.append(hook)
        
        # Check for engagement patterns
        pattern_matches = []
        for pattern in self.engagement_patterns:
            if pattern.lower() in content_lower:
                pattern_matches.append(pattern)
        
        # Analyze content structure
        sentences = content.split('.')
        avg_sentence_length = sum(len(s) for s in sentences) / len(sentences) if sentences else 0
        
        # Count questions (good for engagement)
        question_count = content.count('?')
        
        return {
            "strong_hooks": strong_matches,
            "weak_hooks": weak_matches,
            "engagement_patterns": pattern_matches,
            "sentence_analysis": {
                "count": len(sentences),
                "avg_length": avg_sentence_length
            },
            "question_count": question_count,
            "has_power_words": len(strong_matches) > 0,
            "hook_density": len(strong_matches) / max(len(content), 1)
        }
    
    def _calculate_engagement_score(self, analysis: Dict[str, Any]) -> float:
        """Calculate overall engagement score based on analysis."""
        score = 0.0
        
        # Strong hooks contribute positively
        score += len(analysis["strong_hooks"]) * 0.15
        
        # Weak hooks contribute negatively
        score -= len(analysis["weak_hooks"]) * 0.1
        
        # Engagement patterns contribute positively
        score += len(analysis["engagement_patterns"]) * 0.1
        
        # Questions improve engagement
        score += min(analysis["question_count"] * 0.05, 0.1)  # Cap at 0.1
        
        # Hook density bonus
        if analysis["hook_density"] > 0.01:  # At least 1% hook density
            score += 0.1
        
        # Ensure score stays in 0-1 range
        return max(0.0, min(1.0, score + 0.3))  # Add baseline of 0.3
    
    async def _generate_suggestions(self, analysis: Dict[str, Any], content: str) -> List[Dict[str, str]]:
        """Generate improvement suggestions based on analysis."""
        suggestions = []
        
        if not analysis["strong_hooks"]:
            suggestions.append({
                "type": "hook_addition",
                "suggestion": "添加强有力的开头钩子词汇，如'为什么'、'真相'、'秘密'等",
                "priority": "high"
            })
        
        if analysis["question_count"] == 0:
            suggestions.append({
                "type": "engagement_increase",
                "suggestion": "在开头加入问题句式以提高参与度",
                "priority": "medium"
            })
        
        if len(analysis["engagement_patterns"]) < 2:
            suggestions.append({
                "type": "pattern_enhancement",
                "suggestion": "增加更多吸引人的元素，如数据对比、情感共鸣或实用价值",
                "priority": "medium"
            })
        
        if analysis["weak_hooks"]:
            suggestions.append({
                "type": "hook_improvement",
                "suggestion": f"减少使用较弱的词汇：{', '.join(analysis['weak_hooks'])}，改用更强的钩子词汇",
                "priority": "high"
            })
        
        if analysis["sentence_analysis"]["avg_length"] > 25:
            suggestions.append({
                "type": "readability",
                "suggestion": "考虑缩短句子长度以提高可读性和吸引力",
                "priority": "low"
            })
        
        return suggestions


# Convenience function for direct execution
async def hook_detector_skill_execute(*, content: str, threshold: float = 0.5) -> Dict[str, Any]:
    """
    Direct execution function for the hook detector skill.
    """
    skill = HookDetectorSkill()
    return await skill.execute(content=content, threshold=threshold)