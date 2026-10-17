"""
Intelligent AI Model Routing Service for Hevi
"""
from typing import Dict, List, Optional, Any, Union
from enum import Enum
import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..services.base import BaseService
from .orchestrator import AIModelOrchestrator, ModelType
from ..cost.estimator import estimate_cost
from ..resilience.live_state import provider_routable
from ..providers.registry import ProviderRegistry


class RoutingStrategy(Enum):
    COST_OPTIMIZED = "cost_optimized"
    QUALITY_PRIORITIZED = "quality_prioritized"
    BALANCED = "balanced"
    PERFORMANCE_FOCUSED = "performance_focused"
    FAULT_TOLERANT = "fault_tolerant"


@dataclass
class RoutingDecision:
    provider: str
    confidence: float  # 0.0 to 1.0
    estimated_cost: Optional[float]
    estimated_time: Optional[float]
    strategy_used: RoutingStrategy
    fallback_options: List[str]


class IntelligentRoutingService(BaseService):
    """
    Intelligent routing service that selects optimal AI models based on various factors
    """
    
    def __init__(self, orchestrator: AIModelOrchestrator):
        super().__init__()
        self.orchestrator = orchestrator
        self.provider_registry = ProviderRegistry
        self.routing_history = []
        self.failure_cache = {}  # Track recent failures to avoid retrying failed providers
        self.failure_timeout = 300  # 5 minutes timeout for failed providers
    
    async def route_request(
        self,
        model_type: ModelType,
        payload: Dict[str, Any],
        strategy: RoutingStrategy = RoutingStrategy.BALANCED,
        quality_threshold: int = 5,
        budget_limit: Optional[float] = None,
        timeout_preference: Optional[float] = None
    ) -> RoutingDecision:
        """
        Route a request using intelligent routing strategy
        """
        start_time = time.time()
        
        # Get eligible providers
        eligible_providers = await self._get_eligible_providers(
            model_type, 
            payload, 
            quality_threshold, 
            budget_limit
        )
        
        if not eligible_providers:
            return RoutingDecision(
                provider="",
                confidence=0.0,
                estimated_cost=None,
                estimated_time=None,
                strategy_used=strategy,
                fallback_options=[]
            )
        
        # Apply routing strategy
        best_provider = await self._apply_routing_strategy(
            strategy,
            model_type,
            eligible_providers,
            payload,
            budget_limit
        )
        
        # Calculate metrics
        estimated_cost = await self._estimate_cost(best_provider, payload, model_type)
        estimated_time = await self._estimate_response_time(best_provider)
        
        # Log the routing decision
        decision = RoutingDecision(
            provider=best_provider,
            confidence=0.8,  # Placeholder - in a real implementation this would be calculated
            estimated_cost=estimated_cost,
            estimated_time=estimated_time,
            strategy_used=strategy,
            fallback_options=[p for p in eligible_providers if p != best_provider][:3]
        )
        
        self._log_routing_decision(decision, time.time() - start_time)
        
        return decision
    
    async def _get_eligible_providers(
        self,
        model_type: ModelType,
        payload: Dict[str, Any],
        quality_threshold: int,
        budget_limit: Optional[float]
    ) -> List[str]:
        """Get list of eligible providers for the request"""
        all_providers = []
        
        # Get providers from registry
        registry_providers = self.provider_registry.list(model_type.value) or []
        for provider in registry_providers:
            # Check if provider is routable
            if not provider_routable(provider):
                continue
            
            # Check quality threshold
            from ..cost.selector import PROVIDER_QUALITY
            quality = PROVIDER_QUALITY.get(provider, 0)
            if quality < quality_threshold:
                continue
            
            # Check if provider recently failed
            if self._is_recently_failed(provider):
                continue
            
            all_providers.append(provider)
        
        # Filter based on payload requirements
        requirements = self._analyze_payload_requirements(payload, model_type)
        filtered_providers = []
        
        for provider in all_providers:
            if await self._meets_requirements(provider, model_type, requirements):
                filtered_providers.append(provider)
        
        return filtered_providers
    
    def _analyze_payload_requirements(self, payload: Dict[str, Any], model_type: ModelType) -> Dict[str, Any]:
        """Analyze payload to determine specific requirements"""
        requirements = {}
        
        if model_type == ModelType.VLM:
            # VLM might need multimodal support
            if "image_urls" in payload or "image_paths" in payload:
                requirements["multimodal"] = True
        
        elif model_type == ModelType.LLM:
            # Check token requirements
            if "max_tokens" in payload:
                requirements["min_tokens"] = payload["max_tokens"]
        
        elif model_type == ModelType.VIDEO:
            # Video generation might have specific quality requirements
            requirements["quality_focused"] = payload.get("quality_focused", True)
        
        return requirements
    
    async def _meets_requirements(self, provider: str, model_type: ModelType, requirements: Dict[str, Any]) -> bool:
        """Check if a provider meets specific requirements"""
        # For now, we'll use basic checks - in a full implementation, this would check
        # detailed capability matrices
        return True  # Simplified for now
    
    async def _apply_routing_strategy(
        self,
        strategy: RoutingStrategy,
        model_type: ModelType,
        providers: List[str],
        payload: Dict[str, Any],
        budget_limit: Optional[float]
    ) -> str:
        """Apply the selected routing strategy to choose the best provider"""
        
        if strategy == RoutingStrategy.COST_OPTIMIZED:
            return await self._select_lowest_cost_provider(model_type, providers, payload)
        
        elif strategy == RoutingStrategy.QUALITY_PRIORITIZED:
            return await self._select_highest_quality_provider(providers)
        
        elif strategy == RoutingStrategy.PERFORMANCE_FOCUSED:
            return await self._select_fastest_provider(providers)
        
        elif strategy == RoutingStrategy.FAULT_TOLERANT:
            return await self._select_most_reliable_provider(providers)
        
        else:  # BALANCED
            return await self._select_balanced_provider(model_type, providers, payload, budget_limit)
    
    async def _select_lowest_cost_provider(
        self, 
        model_type: ModelType, 
        providers: List[str], 
        payload: Dict[str, Any]
    ) -> str:
        """Select the lowest cost provider among eligible ones"""
        costs = []
        
        for provider in providers:
            try:
                cost_estimate = await estimate_cost(
                    duration_archetype=payload.get("duration_archetype", "standard"),
                    video_provider=provider if model_type == ModelType.VIDEO else "default",
                    audio_provider=provider if model_type == ModelType.AUDIO else "default"
                )
                costs.append((provider, cost_estimate.total_usd))
            except:
                # If cost estimation fails, assign a high cost
                costs.append((provider, float('inf')))
        
        # Sort by cost and return the cheapest
        costs.sort(key=lambda x: x[1])
        return costs[0][0] if costs else providers[0] if providers else ""
    
    async def _select_highest_quality_provider(self, providers: List[str]) -> str:
        """Select the highest quality provider based on quality scores"""
        from ..cost.selector import PROVIDER_QUALITY
        
        quality_scores = [(p, PROVIDER_QUALITY.get(p, 0)) for p in providers]
        quality_scores.sort(key=lambda x: x[1], reverse=True)
        return quality_scores[0][0] if quality_scores else providers[0] if providers else ""
    
    async def _select_fastest_provider(self, providers: List[str]) -> str:
        """Select the fastest provider based on performance metrics"""
        # In a real implementation, this would use actual performance data
        # For now, we'll use a simple heuristic based on quality and provider status
        return await self._select_highest_quality_provider(providers)
    
    async def _select_most_reliable_provider(self, providers: List[str]) -> str:
        """Select the most reliable provider considering recent failures"""
        # Filter out providers that recently failed
        safe_providers = [p for p in providers if not self._is_recently_failed(p)]
        
        if not safe_providers:
            # If all providers failed recently, return the first one
            return providers[0] if providers else ""
        
        # Among safe providers, select the highest quality one
        from ..cost.selector import PROVIDER_QUALITY
        quality_scores = [(p, PROVIDER_QUALITY.get(p, 0)) for p in safe_providers]
        quality_scores.sort(key=lambda x: x[1], reverse=True)
        return quality_scores[0][0] if quality_scores else safe_providers[0]
    
    async def _select_balanced_provider(
        self, 
        model_type: ModelType, 
        providers: List[str], 
        payload: Dict[str, Any], 
        budget_limit: Optional[float]
    ) -> str:
        """Select a balanced provider considering cost, quality, and performance"""
        from ..cost.selector import PROVIDER_QUALITY
        
        scores = []
        for provider in providers:
            # Get quality score
            quality = PROVIDER_QUALITY.get(provider, 0)
            
            # Estimate cost
            try:
                cost_estimate = await estimate_cost(
                    duration_archetype=payload.get("duration_archetype", "standard"),
                    video_provider=provider if model_type == ModelType.VIDEO else "default",
                    audio_provider=provider if model_type == ModelType.AUDIO else "default"
                )
                cost = cost_estimate.total_usd
            except:
                cost = float('inf')
            
            # Calculate a composite score (higher is better)
            # Normalize quality to 0-1 scale, invert cost so lower cost is better
            normalized_quality = quality / 10.0
            normalized_cost = 1.0 / (1.0 + cost)  # Higher value for lower cost
            
            # Apply budget constraint if specified
            if budget_limit and cost > budget_limit:
                composite_score = -float('inf')  # Penalize providers exceeding budget
            else:
                # Weight quality more heavily than cost in balanced mode
                composite_score = 0.7 * normalized_quality + 0.3 * normalized_cost
            
            scores.append((provider, composite_score))
        
        # Sort by composite score (descending)
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[0][0] if scores else providers[0] if providers else ""
    
    async def _estimate_cost(self, provider: str, payload: Dict[str, Any], model_type: ModelType) -> Optional[float]:
        """Estimate the cost of using a specific provider"""
        try:
            cost_estimate = await estimate_cost(
                duration_archetype=payload.get("duration_archetype", "standard"),
                video_provider=provider if model_type == ModelType.VIDEO else "default",
                audio_provider=provider if model_type == ModelType.AUDIO else "default"
            )
            return cost_estimate.total_usd
        except:
            return None
    
    async def _estimate_response_time(self, provider: str) -> Optional[float]:
        """Estimate the response time for a provider"""
        # In a real implementation, this would use historical performance data
        return None  # Placeholder
    
    def _is_recently_failed(self, provider: str) -> bool:
        """Check if a provider recently failed"""
        if provider not in self.failure_cache:
            return False
        
        failure_time = self.failure_cache[provider]
        return (datetime.now() - failure_time).total_seconds() < self.failure_timeout
    
    def _log_routing_decision(self, decision: RoutingDecision, processing_time: float):
        """Log the routing decision for analytics"""
        self.routing_history.append({
            "timestamp": datetime.now(),
            "decision": decision,
            "processing_time": processing_time
        })
        
        # Keep only recent history (last 1000 decisions)
        if len(self.routing_history) > 1000:
            self.routing_history = self.routing_history[-1000:]
    
    async def record_failure(self, provider: str):
        """Record a provider failure to avoid routing to it temporarily"""
        self.failure_cache[provider] = datetime.now()
        self.logger.warning(f"Recorded failure for provider: {provider}")
    
    async def get_routing_analytics(self) -> Dict[str, Any]:
        """Get analytics about routing decisions"""
        if not self.routing_history:
            return {"message": "No routing history available"}
        
        # Count provider selections
        provider_counts = {}
        total_decisions = len(self.routing_history)
        
        for record in self.routing_history:
            provider = record["decision"].provider
            if provider:
                provider_counts[provider] = provider_counts.get(provider, 0) + 1
        
        return {
            "total_decisions": total_decisions,
            "provider_distribution": provider_counts,
            "recent_failures": list(self.failure_cache.keys()),
            "active_strategies": [record["decision"].strategy_used.value for record in self.routing_history[-10:]]
        }


# Singleton instance
intelligent_router = IntelligentRoutingService(AIModelOrchestrator())