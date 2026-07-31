"""
Adaptive Learning Service for AI Model Selection in Hevi
"""
from typing import Dict, List, Optional, Any, Tuple
import asyncio
import logging
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass
import json
import pickle
from pathlib import Path

from ..services.base import BaseService
from .orchestrator import AIModelOrchestrator, ModelType
from .routing_service import IntelligentRoutingService, RoutingDecision


@dataclass
class PerformanceRecord:
    provider: str
    model_type: ModelType
    timestamp: datetime
    response_time: float
    cost: float
    quality_score: float  # 0-1 scale
    success: bool
    error_type: Optional[str] = None


class AdaptiveLearningService(BaseService):
    """
    Service that learns from past performance to improve AI model selection
    """
    
    def __init__(self, orchestrator: AIModelOrchestrator, router: IntelligentRoutingService):
        super().__init__()
        self.orchestrator = orchestrator
        self.router = router
        self.performance_records: List[PerformanceRecord] = []
        self.learning_weights = {
            "response_time": 0.3,
            "cost": 0.3,
            "quality": 0.3,
            "reliability": 0.1
        }
        self.model_preference_matrix = {}  # Maps request patterns to preferred models
        self.feedback_buffer = []  # Buffer for incoming feedback
        self.learning_rate = 0.1
        self.performance_window = timedelta(hours=24)  # Consider last 24 hours of data
        self.q_table = {}  # For reinforcement learning-based selection
        self.state_space = {}  # State representation for RL
    
    def record_interaction(
        self, 
        provider: str, 
        model_type: ModelType, 
        payload: Dict[str, Any], 
        response_time: float, 
        cost: float, 
        quality_score: float, 
        success: bool,
        error_type: Optional[str] = None
    ):
        """
        Record an interaction for learning purposes
        """
        record = PerformanceRecord(
            provider=provider,
            model_type=model_type,
            timestamp=datetime.now(),
            response_time=response_time,
            cost=cost,
            quality_score=quality_score,
            success=success,
            error_type=error_type
        )
        
        self.performance_records.append(record)
        
        # Keep only recent records
        cutoff_time = datetime.now() - self.performance_window
        self.performance_records = [
            r for r in self.performance_records 
            if r.timestamp > cutoff_time
        ]
        
        # Update model preference matrix based on request patterns
        request_signature = self._get_request_signature(payload, model_type)
        self._update_preference_matrix(request_signature, provider, quality_score, success)
    
    def _get_request_signature(self, payload: Dict[str, Any], model_type: ModelType) -> str:
        """
        Create a signature for the request to identify similar patterns
        """
        # Extract key features from the payload
        features = {
            "model_type": model_type.value,
            "payload_size": len(str(payload)),  # Approximate size
            "requires_multimodal": "image_urls" in payload or "image_paths" in payload,
            "quality_focused": payload.get("quality_focused", False),
            "max_tokens": payload.get("max_tokens", 0),
            "duration_archetype": payload.get("duration_archetype", "standard")
        }
        
        return json.dumps(features, sort_keys=True)
    
    def _update_preference_matrix(self, signature: str, provider: str, quality_score: float, success: bool):
        """
        Update the preference matrix based on performance
        """
        if signature not in self.model_preference_matrix:
            self.model_preference_matrix[signature] = {}
        
        if provider not in self.model_preference_matrix[signature]:
            self.model_preference_matrix[signature][provider] = {
                "total_weight": 0,
                "success_count": 0,
                "total_interactions": 0,
                "avg_quality": 0
            }
        
        # Update statistics
        stats = self.model_preference_matrix[signature][provider]
        stats["total_interactions"] += 1
        
        if success:
            stats["success_count"] += 1
            # Update average quality with exponential moving average
            stats["avg_quality"] = (
                self.learning_rate * quality_score + 
                (1 - self.learning_rate) * stats["avg_quality"]
            )
        
        # Calculate weighted preference score
        success_rate = stats["success_count"] / stats["total_interactions"]
        preference_score = success_rate * stats["avg_quality"]
        stats["total_weight"] = preference_score
    
    async def suggest_best_provider(
        self, 
        model_type: ModelType, 
        payload: Dict[str, Any], 
        fallback_providers: List[str] = None
    ) -> Tuple[str, float]:
        """
        Suggest the best provider based on learned patterns
        """
        fallback_providers = fallback_providers or []
        
        # Get request signature
        signature = self._get_request_signature(payload, model_type)
        
        # Check if we have learned preferences for this signature
        if signature in self.model_preference_matrix:
            provider_preferences = self.model_preference_matrix[signature]
            
            # Sort providers by preference weight
            sorted_providers = sorted(
                provider_preferences.items(),
                key=lambda x: x[1]["total_weight"],
                reverse=True
            )
            
            if sorted_providers:
                best_provider = sorted_providers[0][0]
                confidence = sorted_providers[0][1]["total_weight"]
                return best_provider, min(confidence, 1.0)
        
        # If no specific learning, fall back to general performance
        return await self._suggest_from_general_performance(model_type, payload, fallback_providers)
    
    async def _suggest_from_general_performance(
        self, 
        model_type: ModelType, 
        payload: Dict[str, Any], 
        fallback_providers: List[str]
    ) -> Tuple[str, float]:
        """
        Suggest provider based on general performance patterns
        """
        if not self.performance_records:
            # No learning data yet, return first fallback provider
            return fallback_providers[0] if fallback_providers else "default", 0.5
        
        # Filter records by model type
        relevant_records = [
            r for r in self.performance_records 
            if r.model_type == model_type
        ]
        
        if not relevant_records:
            return fallback_providers[0] if fallback_providers else "default", 0.5
        
        # Calculate provider scores based on multiple factors
        provider_scores = {}
        
        for record in relevant_records:
            if record.provider not in provider_scores:
                provider_scores[record.provider] = {
                    "response_times": [],
                    "costs": [],
                    "qualities": [],
                    "successes": 0,
                    "total_attempts": 0
                }
            
            stats = provider_scores[record.provider]
            stats["response_times"].append(record.response_time)
            stats["costs"].append(record.cost)
            stats["qualities"].append(record.quality_score)
            stats["total_attempts"] += 1
            if record.success:
                stats["successes"] += 1
        
        # Calculate composite scores
        scored_providers = []
        for provider, stats in provider_scores.items():
            if not stats["response_times"]:
                continue
            
            # Calculate averages
            avg_response_time = sum(stats["response_times"]) / len(stats["response_times"])
            avg_cost = sum(stats["costs"]) / len(stats["costs"])
            avg_quality = sum(stats["qualities"]) / len(stats["qualities"])
            success_rate = stats["successes"] / stats["total_attempts"]
            
            # Normalize scores (lower is better for time and cost, higher is better for quality)
            norm_response_time = 1.0 / (1.0 + avg_response_time)  # Higher is better
            norm_cost = 1.0 / (1.0 + avg_cost)  # Higher is better
            norm_quality = avg_quality  # Already 0-1
            norm_reliability = success_rate  # Success rate
            
            # Apply weights
            composite_score = (
                self.learning_weights["response_time"] * norm_response_time +
                self.learning_weights["cost"] * norm_cost +
                self.learning_weights["quality"] * norm_quality +
                self.learning_weights["reliability"] * norm_reliability
            )
            
            scored_providers.append((provider, composite_score))
        
        # Sort by composite score
        scored_providers.sort(key=lambda x: x[1], reverse=True)
        
        if scored_providers:
            best_provider, confidence = scored_providers[0]
            return best_provider, min(confidence, 1.0)
        
        # Fallback
        return fallback_providers[0] if fallback_providers else "default", 0.5
    
    async def update_weights_based_on_feedback(self, provider: str, feedback_score: float):
        """
        Update learning weights based on external feedback
        """
        # Feedback score should be -1 to 1, where positive is good and negative is bad
        adjustment = feedback_score * self.learning_rate
        
        # Adjust weights based on feedback
        # If feedback is positive, increase quality/reliability weights
        # If feedback is negative, decrease them
        if feedback_score > 0:
            self.learning_weights["quality"] = min(1.0, self.learning_weights["quality"] + adjustment * 0.3)
            self.learning_weights["reliability"] = min(1.0, self.learning_weights["reliability"] + adjustment * 0.3)
        else:
            self.learning_weights["quality"] = max(0.0, self.learning_weights["quality"] + adjustment * 0.3)
            self.learning_weights["reliability"] = max(0.0, self.learning_weights["reliability"] + adjustment * 0.3)
    
    async def get_learning_insights(self) -> Dict[str, Any]:
        """
        Get insights about the learning process
        """
        if not self.performance_records:
            return {"message": "No performance data collected yet"}
        
        # Calculate overall statistics
        total_interactions = len(self.performance_records)
        successful_interactions = sum(1 for r in self.performance_records if r.success)
        avg_response_time = np.mean([r.response_time for r in self.performance_records])
        avg_cost = np.mean([r.cost for r in self.performance_records if r.cost])
        avg_quality = np.mean([r.quality_score for r in self.performance_records])
        
        # Provider performance overview
        provider_stats = {}
        for record in self.performance_records:
            if record.provider not in provider_stats:
                provider_stats[record.provider] = {
                    "total": 0,
                    "successes": 0,
                    "avg_response_time": 0,
                    "avg_cost": 0,
                    "avg_quality": 0
                }
            
            stats = provider_stats[record.provider]
            stats["total"] += 1
            if record.success:
                stats["successes"] += 1
            stats["avg_response_time"] += record.response_time
            if record.cost:
                stats["avg_cost"] += record.cost
            stats["avg_quality"] += record.quality_score
        
        # Finalize averages
        for provider, stats in provider_stats.items():
            stats["success_rate"] = stats["successes"] / stats["total"]
            stats["avg_response_time"] /= stats["total"]
            stats["avg_cost"] /= stats["total"] if stats["avg_cost"] > 0 else stats["total"]
            stats["avg_quality"] /= stats["total"]
        
        return {
            "total_interactions": total_interactions,
            "overall_success_rate": successful_interactions / total_interactions if total_interactions > 0 else 0,
            "average_response_time": avg_response_time,
            "average_cost": avg_cost,
            "average_quality": avg_quality,
            "provider_performance": provider_stats,
            "learning_weights": self.learning_weights,
            "preference_matrix_size": len(self.model_preference_matrix)
        }
    
    async def save_learning_state(self, filepath: str):
        """
        Save the current learning state to a file
        """
        state = {
            "performance_records": self.performance_records,
            "learning_weights": self.learning_weights,
            "model_preference_matrix": self.model_preference_matrix,
            "q_table": self.q_table,
            "state_space": self.state_space
        }
        
        with open(filepath, 'wb') as f:
            pickle.dump(state, f)
        
        self.logger.info(f"Learning state saved to {filepath}")
    
    async def load_learning_state(self, filepath: str):
        """
        Load the learning state from a file
        """
        if not Path(filepath).exists():
            self.logger.warning(f"Learning state file does not exist: {filepath}")
            return
        
        with open(filepath, 'rb') as f:
            state = pickle.load(f)
        
        self.performance_records = state.get("performance_records", [])
        self.learning_weights = state.get("learning_weights", self.learning_weights)
        self.model_preference_matrix = state.get("model_preference_matrix", {})
        self.q_table = state.get("q_table", {})
        self.state_space = state.get("state_space", {})
        
        self.logger.info(f"Learning state loaded from {filepath}")
    
    async def reset_learning_state(self):
        """
        Reset all learning state
        """
        self.performance_records = []
        self.model_preference_matrix = {}
        self.q_table = {}
        self.state_space = {}
        
        # Keep default weights
        self.learning_weights = {
            "response_time": 0.3,
            "cost": 0.3,
            "quality": 0.3,
            "reliability": 0.1
        }
        
        self.logger.info("Learning state has been reset")


# Singleton instance
adaptive_learner = AdaptiveLearningService(AIModelOrchestrator(), IntelligentRoutingService(AIModelOrchestrator()))