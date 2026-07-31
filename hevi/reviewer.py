"""結構化 reviewer 技能 —— OpenMontage 風格的自審系統。

對標 OpenMontage 的 skills/meta/reviewer.md + 每個 pipeline 的 review_focus 字段。
Hevi 目前有 L5 終審，但缺少結構化的 checklist 式自審。

實現：
1. 通用 reviewer 引擎
2. 按階段劃分的審查重點 (research/script/scene_plan/assets/edit/compose)
3. 問題分類和建議
4. 審查報告生成

用法:
    from hevi.reviewer import PipelineReviewer
    reviewer = PipelineReviewer()
    report = await reviewer.review_stage("script", content=script_content, context=context)
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ReviewCategory(Enum):
    """審查類別"""
    CONTENT = "content"
    TECHNICAL = "technical"
    CONSISTENCY = "consistency"
    QUALITY = "quality"
    COST = "cost"
    COMPLIANCE = "compliance"


class Severity(Enum):
    """嚴重程度"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ReviewFinding:
    """審查發現"""
    category: ReviewCategory
    severity: Severity
    title: str
    description: str
    suggestions: List[str]
    affected_elements: List[str]
    confidence: float  # 0.0-1.0


@dataclass
class ReviewReport:
    """審查報告"""
    stage: str
    findings: List[ReviewFinding]
    score: float  # 0.0-1.0
    summary: str
    recommendations: List[str]
    metadata: Dict[str, Any]


class PipelineReviewer:
    """流水線審查器"""
    
    def __init__(self):
        self.review_templates = self._load_review_templates()
    
    def _load_review_templates(self) -> Dict[str, Dict[str, Any]]:
        """加載各階段的審查模板"""
        return {
            "research": {
                "focus": [
                    {"category": "content", "aspect": "topic_coverage", "weight": 0.3},
                    {"category": "content", "aspect": "audience_fit", "weight": 0.25},
                    {"category": "technical", "aspect": "feasibility", "weight": 0.2},
                    {"category": "cost", "aspect": "budget_alignment", "weight": 0.15},
                    {"category": "compliance", "aspect": "copyright", "weight": 0.1}
                ],
                "checklist": [
                    {"id": "topic_comprehensiveness", "prompt": "Does the research cover all important aspects of the topic?"},
                    {"id": "source_credibility", "prompt": "Are the sources credible and up-to-date?"},
                    {"id": "audience_analysis", "prompt": "Is the target audience clearly defined and understood?"},
                    {"id": "delivery_feasibility", "prompt": "Is the proposed delivery method technically feasible?"},
                    {"id": "budget_realism", "prompt": "Is the estimated budget realistic for the scope?"},
                    {"id": "copyright_clearance", "prompt": "Are all referenced materials copyright cleared?"}
                ]
            },
            "script": {
                "focus": [
                    {"category": "content", "aspect": "narrative_flow", "weight": 0.3},
                    {"category": "content", "aspect": "engagement", "weight": 0.25},
                    {"category": "technical", "aspect": "production_feasibility", "weight": 0.2},
                    {"category": "quality", "aspect": "clarity", "weight": 0.15},
                    {"category": "compliance", "aspect": "appropriateness", "weight": 0.1}
                ],
                "checklist": [
                    {"id": "narrative_coherence", "prompt": "Does the story flow logically from beginning to end?"},
                    {"id": "hook_effectiveness", "prompt": "Does the opening effectively grab attention?"},
                    {"id": "pacing_balance", "prompt": "Is the pacing balanced throughout?"},
                    {"id": "production_clarity", "prompt": "Are production requirements clearly specified?"},
                    {"id": "target_duration", "prompt": "Does the script length match the target duration?"},
                    {"id": "tone_consistency", "prompt": "Is the tone consistent throughout?"}
                ]
            },
            "scene_plan": {
                "focus": [
                    {"category": "technical", "aspect": "shot_variety", "weight": 0.3},
                    {"category": "content", "aspect": "story_flow", "weight": 0.25},
                    {"category": "cost", "aspect": "efficiency", "weight": 0.2},
                    {"category": "quality", "aspect": "visual_interest", "weight": 0.15},
                    {"category": "consistency", "aspect": "continuity", "weight": 0.1}
                ],
                "checklist": [
                    {"id": "shot_diversity", "prompt": "Do shots provide sufficient variety in angle/composition?"},
                    {"id": "scene_transitions", "prompt": "Do scene transitions flow naturally?"},
                    {"id": "coverage_completeness", "prompt": "Are all story points covered visually?"},
                    {"id": "cost_optimization", "prompt": "Are shots designed for cost efficiency?"},
                    {"id": "continuity_preservation", "prompt": "Will continuity be maintained across shots?"},
                    {"id": "technical_feasibility", "prompt": "Are all shots technically achievable?"},
                ]
            },
            "assets": {
                "focus": [
                    {"category": "quality", "aspect": "resolution", "weight": 0.25},
                    {"category": "consistency", "aspect": "brand_aligment", "weight": 0.25},
                    {"category": "technical", "aspect": "compatibility", "weight": 0.2},
                    {"category": "cost", "aspect": "generation_efficiency", "weight": 0.2},
                    {"category": "compliance", "aspect": "rights_clearance", "weight": 0.1}
                ],
                "checklist": [
                    {"id": "resolution_adquacy", "prompt": "Do assets meet minimum resolution requirements?"},
                    {"id": "style_consistency", "prompt": "Do all assets follow the established style?"},
                    {"id": "format_compatibility", "prompt": "Are asset formats compatible with pipeline?"},
                    {"id": "generation_efficiency", "prompt": "Were assets generated efficiently?"},
                    {"id": "rights_verification", "prompt": "Are all asset rights verified and cleared?"},
                    {"id": "backup_availability", "prompt": "Are backup assets available if needed?"}
                ]
            },
            "edit": {
                "focus": [
                    {"category": "content", "aspect": "story_clarity", "weight": 0.3},
                    {"category": "technical", "aspect": "timing_precision", "weight": 0.25},
                    {"category": "quality", "aspect": "audio_sync", "weight": 0.2},
                    {"category": "consistency", "aspect": "color_grading", "weight": 0.15},
                    {"category": "quality", "aspect": "transitions", "weight": 0.1}
                ],
                "checklist": [
                    {"id": "story_coherence", "prompt": "Does the edited sequence tell a coherent story?"},
                    {"id": "timing_accuracy", "prompt": "Are cuts timed precisely to the beat/motion?"},
                    {"id": "audio_visual_sync", "prompt": "Is audio synchronized with visual elements?"},
                    {"id": "color_consistency", "prompt": "Is color grading consistent across clips?"},
                    {"id": "transition_smoothness", "prompt": "Do transitions flow smoothly?"},
                    {"id": "pacing_effectiveness", "prompt": "Does the pacing maintain engagement?"}
                ]
            },
            "compose": {
                "focus": [
                    {"category": "technical", "aspect": "render_quality", "weight": 0.3},
                    {"category": "quality", "aspect": "final_appearance", "weight": 0.25},
                    {"category": "technical", "aspect": "format_compliance", "weight": 0.2},
                    {"category": "quality", "aspect": "audio_mixed", "weight": 0.15},
                    {"category": "technical", "aspect": "file_integrity", "weight": 0.1}
                ],
                "checklist": [
                    {"id": "render_settings", "prompt": "Are render settings optimized for target platform?"},
                    {"id": "visual_polish", "prompt": "Does the final video look professionally polished?"},
                    {"id": "format_compliance", "prompt": "Does the output meet platform specifications?"},
                    {"id": "audio_mixed", "prompt": "Is audio properly mixed and leveled?"},
                    {"id": "file_integrity", "prompt": "Is the output file complete and playable?"},
                    {"id": "delivery_readiness", "prompt": "Is the video ready for delivery?"},
                ]
            }
        }
    
    async def review_stage(self, stage: str, content: Any, context: Dict[str, Any] | None = None) -> ReviewReport:
        """審查特定階段的內容"""
        if stage not in self.review_templates:
            raise ValueError(f"Unknown stage: {stage}. Available: {list(self.review_templates.keys())}")
        
        template = self.review_templates[stage]
        checklist = template["checklist"]
        focus_areas = template["focus"]
        
        findings = []
        
        # 根據檢查清單執行審查
        for check in checklist:
            result = await self._perform_check(check["id"], check["prompt"], content, context or {})
            if result:
                findings.extend(result)
        
        # 計算分數
        score = self._calculate_score(findings, focus_areas)
        
        # 生成摘要和建議
        summary = self._generate_summary(findings, score)
        recommendations = self._generate_recommendations(findings)
        
        return ReviewReport(
            stage=stage,
            findings=findings,
            score=score,
            summary=summary,
            recommendations=recommendations,
            metadata={
                "reviewed_at": asyncio.get_event_loop().time(),
                "content_type": type(content).__name__,
                "context_keys": list(context.keys()) if context else []
            }
        )
    
    async def _perform_check(self, check_id: str, prompt: str, content: Any, context: Dict[str, Any]) -> List[ReviewFinding]:
        """執行單個檢查項"""
        # 這個方法在實際實現中會調用 LLM 或規則引擎來評估內容
        # 這裡提供一個簡化的實現
        
        findings = []
        
        # 基於內容類型執行不同檢查
        content_str = str(content)
        
        # 示例檢查邏輯
        if check_id == "narrative_coherence":
            if "script" in content_str.lower():
                if "beginning" in content_str.lower() and "end" in content_str.lower():
                    # 簡單檢查是否有開頭和結尾
                    pass
                else:
                    findings.append(ReviewFinding(
                        category=ReviewCategory.CONTENT,
                        severity=Severity.WARNING,
                        title="Narrative Incompleteness",
                        description="The script may be missing clear beginning or ending structure",
                        suggestions=["Add clear opening hook", "Ensure satisfying conclusion"],
                        affected_elements=["script_structure"],
                        confidence=0.7
                    ))
        
        elif check_id == "target_duration":
            # 檢查腳本長度是否符合目標時長
            if isinstance(content, str):
                word_count = len(content.split())
                estimated_duration = word_count / 150  # 假設 150 字/分鐘
                target_duration = context.get("target_duration_minutes", 3)
                
                if abs(estimated_duration - target_duration) > target_duration * 0.2:  # 20% 容差
                    findings.append(ReviewFinding(
                        category=ReviewCategory.CONTENT,
                        severity=Severity.INFO,
                        title="Duration Mismatch",
                        description=f"Estimated duration {estimated_duration:.1f}min differs significantly from target {target_duration}min",
                        suggestions=[
                            f"Adjust content to match target duration of {target_duration} minutes",
                            f"Aim for approximately {int(target_duration * 150)} words"
                        ],
                        affected_elements=["script_length"],
                        confidence=0.8
                    ))
        
        elif check_id == "resolution_adquacy":
            # 檢查資源是否符合解析度要求
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and "resolution" in item:
                        res = item["resolution"]
                        if isinstance(res, tuple) and res[0] < 1280:  # 低於 720p
                            findings.append(ReviewFinding(
                                category=ReviewCategory.QUALITY,
                                severity=Severity.WARNING,
                                title="Low Resolution Asset",
                                description=f"Asset resolution {res} may be too low for quality output",
                                suggestions=["Use assets with at least 720p resolution", "Consider upscaling if source permits"],
                                affected_elements=[str(item.get("id", "unknown"))],
                                confidence=0.9
                            ))
        
        # 針對不同檢查類型的通用檢查
        if "copyright" in check_id.lower() and "©" not in content_str and "trademark" not in content_str.lower():
            findings.append(ReviewFinding(
                category=ReviewCategory.COMPLIANCE,
                severity=Severity.INFO,
                title="Copyright Review Needed",
                description="No explicit copyright notices found, manual review recommended",
                suggestions=["Verify all content is properly licensed", "Add copyright notices where appropriate"],
                affected_elements=["compliance"],
                confidence=0.6
            ))
        
        return findings
    
    def _calculate_score(self, findings: List[ReviewFinding], focus_areas: List[Dict[str, Any]]) -> float:
        """計算審查分數"""
        if not findings:
            return 1.0  # 無問題 = 完美分數
        
        # 按嚴重程度計算扣分
        severity_weights = {
            Severity.CRITICAL: 0.4,   # 致命問題扣 40%
            Severity.ERROR: 0.2,      # 錎誤扣 20%
            Severity.WARNING: 0.1,    # 警告扣 10%
            Severity.INFO: 0.02       # 信息扣 2%
        }
        
        total_deduction = 0.0
        for finding in findings:
            deduction = severity_weights.get(finding.severity, 0.0)
            # 根據關注領域權重調整
            area_weight = next((area["weight"] for area in focus_areas if area["category"] == finding.category.value), 0.1)
            total_deduction += deduction * area_weight
        
        # 確保分數在 0-1 之間
        score = max(0.0, min(1.0, 1.0 - total_deduction))
        return round(score, 2)
    
    def _generate_summary(self, findings: List[ReviewFinding], score: float) -> str:
        """生成審查摘要"""
        if not findings:
            return f"✅ Clean: No issues found. Overall score: {score:.2f}"
        
        categories = {}
        severities = {}
        
        for finding in findings:
            cat = finding.category.value
            sev = finding.severity.value
            categories[cat] = categories.get(cat, 0) + 1
            severities[sev] = severities.get(sev, 0) + 1
        
        summary_parts = [f"📊 Review completed with score: {score:.2f}"]
        
        if severities.get("critical", 0) > 0:
            summary_parts.append(f"🚨 {severities['critical']} critical issues")
        if severities.get("error", 0) > 0:
            summary_parts.append(f"❌ {severities['error']} errors")
        if severities.get("warning", 0) > 0:
            summary_parts.append(f"⚠️ {severities['warning']} warnings")
        if severities.get("info", 0) > 0:
            summary_parts.append(f"ℹ️ {severities['info']} info items")
        
        return ". ".join(summary_parts)
    
    def _generate_recommendations(self, findings: List[ReviewFinding]) -> List[str]:
        """生成建議"""
        recommendations = set()
        
        for finding in findings:
            for suggestion in finding.suggestions:
                recommendations.add(suggestion)
        
        return list(recommendations)[:5]  # 最多返回 5 個建議
    
    async def review_multiple_stages(self, reviews: List[Dict[str, Any]]) -> Dict[str, ReviewReport]:
        """批量審查多個階段"""
        results = {}
        
        for review_request in reviews:
            stage = review_request["stage"]
            content = review_request["content"]
            context = review_request.get("context", {})
            
            report = await self.review_stage(stage, content, context)
            results[stage] = report
        
        return results
    
    def export_report(self, report: ReviewReport, output_path: Path) -> None:
        """導出審查報告為 JSON"""
        report_data = {
            "stage": report.stage,
            "score": report.score,
            "summary": report.summary,
            "recommendations": report.recommendations,
            "findings": [
                {
                    "category": f.value,
                    "severity": s.value,
                    "title": t,
                    "description": d,
                    "suggestions": sug,
                    "affected_elements": aff,
                    "confidence": conf
                }
                for f, s, t, d, sug, aff, conf in [
                    (finding.category, finding.severity, finding.title, finding.description,
                     finding.suggestions, finding.affected_elements, finding.confidence)
                    for finding in report.findings
                ]
            ],
            "metadata": report.metadata
        }
        
        output_path.write_text(json.dumps(report_data, ensure_ascii=False, indent=2), encoding='utf-8')


# 預定義的審查器實例
_default_reviewer: PipelineReviewer | None = None


async def get_default_reviewer() -> PipelineReviewer:
    """獲取默認審查器實例"""
    global _default_reviewer
    if _default_reviewer is None:
        _default_reviewer = PipelineReviewer()
    return _default_reviewer


async def review_content(stage: str, content: Any, context: Dict[str, Any] | None = None) -> ReviewReport:
    """便捷函數：直接審查內容"""
    reviewer = await get_default_reviewer()
    return await reviewer.review_stage(stage, content, context)