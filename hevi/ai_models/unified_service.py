"""
Unified AI Model Service for Hevi - Integrates orchestration, routing, and adaptive learning
"""
from typing import Dict, Any, Optional, List
import asyncio
import logging
from datetime import datetime
import time

from ..services.base import BaseService
from .orchestrator import AIModelOrchestrator, ModelType
from .routing_service import IntelligentRoutingService, RoutingDecision, RoutingStrategy
from .adaptive_learning import AdaptiveLearningService


class UnifiedAIService(BaseService):
    """
    Unified service that combines orchestration, intelligent routing, and adaptive learning
    for optimal AI model selection and usage
    """
    
    def __init__(self):
        super().__init__()
        self.orchestrator = AIModelOrchestrator()
        self.router = IntelligentRoutingService(self.orchestrator)
        self.learner = AdaptiveLearningService(self.orchestrator, self.router)
        self.execution_history = []
    
    async def execute_request(
        self,
        model_type: ModelType,
        payload: Dict[str, Any],
        strategy: RoutingStrategy = RoutingStrategy.BALANCED,
        quality_threshold: int = 5,
        budget_limit: Optional[float] = None,
        timeout: float = 300.0  # 5 minute default timeout
    ) -> Dict[str, Any]:
        """
        Execute an AI request using the unified service
        """
        start_time = time.time()
        
        try:
            # Step 1: Get intelligent routing decision
            routing_decision = await self.router.route_request(
                model_type=model_type,
                payload=payload,
                strategy=strategy,
                quality_threshold=quality_threshold,
                budget_limit=budget_limit
            )
            
            if not routing_decision.provider:
                return {
                    "success": False,
                    "error": "No suitable provider found",
                    "routing_decision": routing_decision
                }
            
            # Step 2: Use adaptive learning to potentially refine the choice
            suggested_provider, confidence = await self.learner.suggest_best_provider(
                model_type=model_type,
                payload=payload,
                fallback_providers=[routing_decision.provider] + routing_decision.fallback_options
            )
            
            # Use the suggested provider if it has higher confidence than routing
            final_provider = suggested_provider if confidence > routing_decision.confidence else routing_decision.provider
            
            # Step 3: Execute the actual request through the provider registry
            result = await self._execute_with_provider(final_provider, model_type, payload, timeout)
            
            # Step 4: Record the interaction for learning
            execution_time = time.time() - start_time
            await self._record_execution(
                provider=final_provider,
                model_type=model_type,
                payload=payload,
                result=result,
                execution_time=execution_time,
                routing_decision=routing_decision
            )
            
            return {
                "success": True,
                "result": result,
                "provider_used": final_provider,
                "confidence": confidence,
                "execution_time": execution_time,
                "routing_decision": routing_decision
            }
            
        except Exception as e:
            execution_time = time.time() - start_time
            error_result = {
                "success": False,
                "error": str(e),
                "execution_time": execution_time
            }
            
            # Record the failure for learning
            await self._record_execution(
                provider="unknown",
                model_type=model_type,
                payload=payload,
                result=error_result,
                execution_time=execution_time,
                routing_decision=None,
                success=False,
                error=str(e)
            )
            
            return error_result
    
    async def _execute_with_provider(
        self, 
        provider: str, 
        model_type: ModelType, 
        payload: Dict[str, Any], 
        timeout: float
    ) -> Any:
        """
        Execute a request with a specific provider
        """
        from ..providers.registry import ProviderRegistry
        
        provider_func = ProviderRegistry.get(model_type.value, provider)
        if not provider_func:
            raise ValueError(f"Provider '{provider}' not found for model type '{model_type.value}'")
        
        # Execute with timeout
        try:
            result = provider_func(**payload)
            if asyncio.iscoroutine(result):
                result = await asyncio.wait_for(result, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            raise TimeoutError(f"Provider '{provider}' timed out after {timeout} seconds")
        except Exception as e:
            # Mark provider as failed for routing
            await self.router.record_failure(provider)
            raise e
    
    async def _record_execution(
        self,
        provider: str,
        model_type: ModelType,
        payload: Dict[str, Any],
        result: Any,
        execution_time: float,
        routing_decision: Optional[RoutingDecision],
        success: bool = True,
        error: Optional[str] = None
    ):
        """
        Record the execution for learning and analytics
        """
        # Determine cost (if available)
        cost = None
        try:
            from ..cost.estimator import estimate_cost
            cost_estimate = await estimate_cost(
                duration_archetype=payload.get("duration_archetype", "standard"),
                video_provider=provider if model_type == ModelType.VIDEO else "default",
                audio_provider=provider if model_type == ModelType.AUDIO else "default"
            )
            cost = cost_estimate.total_usd
        except:
            pass  # Cost estimation failed, continue with cost=None
        
        # Determine quality score (simplified - in reality this would come from evaluation)
        quality_score = 0.8 if success else 0.0  # Placeholder
        
        # Record interaction for learning
        self.learner.record_interaction(
            provider=provider,
            model_type=model_type,
            payload=payload,
            response_time=execution_time,
            cost=cost or 0.0,
            quality_score=quality_score,
            success=success,
            error_type=type(error).__name__ if error else None
        )
        
        # Store execution in history
        self.execution_history.append({
            "timestamp": datetime.now(),
            "provider": provider,
            "model_type": model_type.value,
            "payload_size": len(str(payload)),
            "execution_time": execution_time,
            "cost": cost,
            "success": success,
            "error": error,
            "routing_strategy": routing_decision.strategy_used.value if routing_decision else None
        })
        
        # Keep only recent history
        if len(self.execution_history) > 1000:
            self.execution_history = self.execution_history[-1000:]
    
    async def get_analytics(self) -> Dict[str, Any]:
        """
        Get comprehensive analytics about AI model usage
        """
        # Get routing analytics
        routing_analytics = await self.router.get_routing_analytics()
        
        # Get learning insights
        learning_insights = await self.learner.get_learning_insights()
        
        # Get execution statistics
        if self.execution_history:
            total_executions = len(self.execution_history)
            successful_executions = sum(1 for ex in self.execution_history if ex["success"])
            avg_execution_time = sum(ex["execution_time"] for ex in self.execution_history) / total_executions
            avg_cost = sum(ex["cost"] for ex in self.execution_history if ex["cost"] is not None) / total_executions if any(ex["cost"] for ex in self.execution_history) else 0
            
            provider_stats = {}
            for ex in self.execution_history:
                provider = ex["provider"]
                if provider not in provider_stats:
                    provider_stats[provider] = {"total": 0, "success": 0, "avg_time": 0, "total_cost": 0}
                
                stats = provider_stats[provider]
                stats["total"] += 1
                if ex["success"]:
                    stats["success"] += 1
                stats["avg_time"] += ex["execution_time"]
                if ex["cost"]:
                    stats["total_cost"] += ex["cost"]
            
            for provider, stats in provider_stats.items():
                stats["avg_time"] /= stats["total"]
                stats["success_rate"] = stats["success"] / stats["total"]
        else:
            total_executions = 0
            successful_executions = 0
            avg_execution_time = 0
            avg_cost = 0
            provider_stats = {}
        
        return {
            "execution_stats": {
                "total_executions": total_executions,
                "successful_executions": successful_executions,
                "success_rate": successful_executions / total_executions if total_executions > 0 else 0,
                "average_execution_time": avg_execution_time,
                "average_cost": avg_cost
            },
            "provider_performance": provider_stats,
            "routing_analytics": routing_analytics,
            "learning_insights": learning_insights
        }
    
    async def evaluate_model_quality(
        self,
        provider: str,
        model_type: ModelType,
        test_cases: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Evaluate the quality of a specific model with test cases
        """
        results = []
        total_score = 0
        
        for test_case in test_cases:
            try:
                # Execute the test case
                result = await self.execute_request(
                    model_type=model_type,
                    payload=test_case,
                    quality_threshold=1  # Allow any quality for testing
                )
                
                if result["success"]:
                    # Calculate a quality score based on the result
                    # This is a simplified approach - in practice, this would use more sophisticated evaluation
                    score = self._calculate_quality_score(result["result"], test_case.get("expected_output"))
                    total_score += score
                    results.append({
                        "test_case": test_case.get("description", "Unknown"),
                        "success": True,
                        "quality_score": score,
                        "provider": result["provider_used"]
                    })
                else:
                    results.append({
                        "test_case": test_case.get("description", "Unknown"),
                        "success": False,
                        "error": result.get("error"),
                        "quality_score": 0
                    })
            except Exception as e:
                results.append({
                    "test_case": test_case.get("description", "Unknown"),
                    "success": False,
                    "error": str(e),
                    "quality_score": 0
                })
        
        average_score = total_score / len(test_cases) if test_cases else 0
        
        return {
            "provider": provider,
            "model_type": model_type.value,
            "total_tests": len(test_cases),
            "passed_tests": len([r for r in results if r["success"]]),
            "average_quality_score": average_score,
            "test_results": results
        }
    
    def _calculate_quality_score(self, actual_output: Any, expected_output: Any) -> float:
        """
        Calculate a quality score comparing actual vs expected output
        This is a simplified implementation - in practice, this would use more sophisticated evaluation methods
        """
        if expected_output is None:
            # If no expected output, just give a medium score for successful generation
            return 0.6
        
        # Convert outputs to strings for comparison
        actual_str = str(actual_output) if actual_output else ""
        expected_str = str(expected_output) if expected_output else ""
        
        # Simple similarity check (in practice, this would use semantic similarity, BLEU, etc.)
        if actual_str and expected_str:
            # Calculate similarity as percentage of common substrings
            actual_words = set(actual_str.lower().split())
            expected_words = set(expected_str.lower().split())
            
            if expected_words:
                intersection = actual_words.intersection(expected_words)
                similarity = len(intersection) / len(expected_words)
                return min(similarity, 1.0)  # Cap at 1.0
            else:
                return 1.0 if not actual_words else 0.0
        else:
            # If either is empty, return low score unless both are empty
            return 1.0 if not actual_str and not expected_str else 0.0
    
    async def optimize_for_request_pattern(
        self,
        request_pattern: Dict[str, Any],
        optimization_target: str = "cost"  # "cost", "quality", "speed", or "balanced"
    ) -> Dict[str, Any]:
        """
        Optimize model selection for a specific request pattern
        """
        # Analyze the request pattern
        pattern_signature = self.learner._get_request_signature(request_pattern, ModelType.LLM)
        
        # Determine the best strategy based on target
        if optimization_target == "cost":
            strategy = RoutingStrategy.COST_OPTIMIZED
        elif optimization_target == "quality":
            strategy = RoutingStrategy.QUALITY_PRIORITIZED
        elif optimization_target == "speed":
            strategy = RoutingStrategy.PERFORMANCE_FOCUSED
        else:
            strategy = RoutingStrategy.BALANCED
        
        # Get the best provider for this pattern
        best_provider, confidence = await self.learner.suggest_best_provider(
            model_type=ModelType.LLM,  # Default type, could be inferred from pattern
            payload=request_pattern
        )
        
        return {
            "recommended_provider": best_provider,
            "confidence": confidence,
            "strategy": strategy.value,
            "pattern_signature": pattern_signature,
            "optimization_target": optimization_target
        }


# Singleton instance
unified_ai_service = UnifiedAIService()