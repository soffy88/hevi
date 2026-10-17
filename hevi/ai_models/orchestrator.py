"""
Advanced AI Model Orchestration Service for Hevi
"""
from typing import Dict, List, Optional, Any, Callable, Union
from enum import Enum
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
import time

from ..providers.registry import ProviderRegistry
from ..cost.selector import PROVIDER_QUALITY
from ..cost.estimator import estimate_cost
from ..resilience.live_state import provider_routable
from ..services.base import BaseService
from ..services.registry import service_registry


class ModelType(Enum):
    LLM = "llm"
    VLM = "vlm"
    AUDIO = "audio"
    VIDEO = "video"
    IMAGE_GEN = "image_gen"


@dataclass
class ModelCapability:
    """Describes the capabilities of an AI model"""
    supports_streaming: bool = False
    max_tokens: Optional[int] = None
    max_input_length: Optional[int] = None
    supports_multimodal: bool = False
    response_time_range: tuple = (0.5, 10.0)  # (min, max) in seconds
    cost_per_token: Optional[float] = None
    quality_score: int = 5  # 1-10 scale


@dataclass
class ModelInfo:
    """Information about a specific AI model"""
    name: str
    provider: str
    model_type: ModelType
    version: str
    capabilities: ModelCapability
    is_active: bool = True
    last_tested: Optional[datetime] = None
    performance_metrics: Dict[str, float] = field(default_factory=dict)


class AIModelOrchestrator(BaseService):
    """
    Advanced orchestration service for managing multiple AI providers and models
    """
    
    def __init__(self):
        super().__init__()
        self.models: Dict[str, ModelInfo] = {}
        self.provider_registry = ProviderRegistry
        self.performance_cache = {}
        self.last_selection_cache = {}
        
        # Initialize with known providers from the existing registry
        self._discover_existing_providers()
    
    def _discover_existing_providers(self):
        """Discover and register existing providers from the registry"""
        for model_type in ModelType:
            providers = self.provider_registry.list(model_type.value) or []
            for provider_name in providers:
                try:
                    # Get quality score from existing mapping
                    quality_score = PROVIDER_QUALITY.get(provider_name, 5)
                    
                    # Create basic capability info based on model type
                    capability = self._get_capability_template(model_type, quality_score)
                    
                    model_info = ModelInfo(
                        name=f"{model_type.value}_{provider_name}",
                        provider=provider_name,
                        model_type=model_type,
                        version="unknown",  # Will be updated during testing
                        capabilities=capability,
                        is_active=provider_routable(provider_name),
                        performance_metrics={}
                    )
                    
                    self.models[f"{model_type.value}:{provider_name}"] = model_info
                except Exception as e:
                    self.logger.warning(f"Failed to register provider {provider_name}: {e}")
    
    def _get_capability_template(self, model_type: ModelType, quality_score: int) -> ModelCapability:
        """Get a template capability based on model type and quality"""
        base_caps = {
            ModelType.LLM: ModelCapability(
                supports_streaming=True,
                max_tokens=4096,
                max_input_length=32768,
                response_time_range=(0.2, 5.0),
                quality_score=quality_score
            ),
            ModelType.VLM: ModelCapability(
                supports_multimodal=True,
                max_tokens=2048,
                max_input_length=16384,
                response_time_range=(1.0, 15.0),
                quality_score=quality_score
            ),
            ModelType.AUDIO: ModelCapability(
                response_time_range=(0.5, 10.0),
                quality_score=quality_score
            ),
            ModelType.VIDEO: ModelCapability(
                response_time_range=(5.0, 120.0),  # Video generation takes longer
                quality_score=quality_score
            ),
            ModelType.IMAGE_GEN: ModelCapability(
                response_time_range=(1.0, 30.0),
                quality_score=quality_score
            )
        }
        return base_caps.get(model_type, ModelCapability(quality_score=quality_score))
    
    async def register_model(self, model_info: ModelInfo) -> bool:
        """Register a new AI model with the orchestrator"""
        try:
            key = f"{model_info.model_type.value}:{model_info.provider}"
            self.models[key] = model_info
            self.logger.info(f"Registered model: {key}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to register model {model_info.name}: {e}")
            return False
    
    async def get_best_model(
        self, 
        model_type: ModelType, 
        requirements: Dict[str, Any] = None,
        quality_threshold: int = 5,
        exclude_providers: List[str] = None
    ) -> Optional[ModelInfo]:
        """Select the best model based on requirements and constraints"""
        requirements = requirements or {}
        exclude_providers = exclude_providers or []
        
        # Filter models by type, quality threshold, and exclusions
        eligible_models = []
        for key, model in self.models.items():
            if (model.model_type == model_type and 
                model.is_active and
                model.capabilities.quality_score >= quality_threshold and
                model.provider not in exclude_providers):
                
                # Check additional requirements
                meets_requirements = True
                if requirements.get("supports_streaming") and not model.capabilities.supports_streaming:
                    meets_requirements = False
                elif requirements.get("supports_multimodal") and not model.capabilities.supports_multimodal:
                    meets_requirements = False
                elif requirements.get("max_tokens") and model.capabilities.max_tokens:
                    if requirements["max_tokens"] > model.capabilities.max_tokens:
                        meets_requirements = False
                
                if meets_requirements:
                    eligible_models.append(model)
        
        if not eligible_models:
            return None
        
        # Sort by quality score (descending) and then by performance metrics if available
        eligible_models.sort(
            key=lambda m: (
                m.capabilities.quality_score,
                m.performance_metrics.get("avg_response_time", float('inf'))
            ),
            reverse=True
        )
        
        return eligible_models[0]
    
    async def route_request_intelligently(
        self,
        model_type: ModelType,
        payload: Dict[str, Any],
        quality_threshold: int = 5,
        budget_limit: Optional[float] = None
    ) -> tuple[Optional[str], Dict[str, Any]]:
        """
        Route a request to the most appropriate provider based on intelligent criteria
        """
        start_time = time.time()
        
        # Determine requirements from payload
        requirements = self._analyze_payload_requirements(payload, model_type)
        
        # Get the best model for this request
        best_model = await self.get_best_model(
            model_type=model_type,
            requirements=requirements,
            quality_threshold=quality_threshold
        )
        
        if not best_model:
            return None, {"error": "No suitable model found"}
        
        # Estimate cost if budget limit is set
        if budget_limit:
            try:
                cost_estimate = await estimate_cost(
                    duration_archetype=payload.get("duration_archetype", "standard"),
                    video_provider=best_model.provider if model_type == ModelType.VIDEO else "default",
                    audio_provider=best_model.provider if model_type == ModelType.AUDIO else "default"
                )
                
                if cost_estimate.total_usd > budget_limit:
                    return None, {"error": f"Cost estimate ({cost_estimate.total_usd}) exceeds budget limit ({budget_limit})"}
            except Exception as e:
                self.logger.warning(f"Cost estimation failed: {e}")
        
        # Track performance
        duration = time.time() - start_time
        await self._track_performance(best_model.provider, duration, payload, success=True)
        
        return best_model.provider, {"selected_model": best_model.name, "routing_time": duration}
    
    def _analyze_payload_requirements(self, payload: Dict[str, Any], model_type: ModelType) -> Dict[str, Any]:
        """Analyze payload to determine specific requirements"""
        requirements = {}
        
        if model_type == ModelType.VLM:
            # VLM might need multimodal support
            if "image_urls" in payload or "image_paths" in payload:
                requirements["supports_multimodal"] = True
        
        elif model_type == ModelType.LLM:
            # LLM might need streaming for large responses
            if payload.get("stream", False):
                requirements["supports_streaming"] = True
            
            # Check token requirements
            if "max_tokens" in payload:
                requirements["max_tokens"] = payload["max_tokens"]
        
        elif model_type == ModelType.VIDEO:
            # Video generation might have specific quality requirements
            requirements["quality_focused"] = payload.get("quality_focused", True)
        
        return requirements
    
    async def _track_performance(self, provider: str, duration: float, payload: Dict[str, Any], success: bool):
        """Track performance metrics for a provider"""
        key = provider
        if key not in self.performance_cache:
            self.performance_cache[key] = {
                "total_calls": 0,
                "successful_calls": 0,
                "avg_response_time": 0.0,
                "last_called": None
            }
        
        cache = self.performance_cache[key]
        cache["total_calls"] += 1
        if success:
            cache["successful_calls"] += 1
            # Update average response time with exponential moving average
            alpha = 0.1  # Smoothing factor
            cache["avg_response_time"] = (
                alpha * duration + 
                (1 - alpha) * cache["avg_response_time"]
            )
        cache["last_called"] = datetime.now()
    
    async def benchmark_model(self, provider: str, model_type: ModelType, test_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Benchmark a specific model with a test payload"""
        try:
            start_time = time.time()
            
            # Get the provider function
            provider_func = self.provider_registry.get(model_type.value, provider)
            if not provider_func:
                return {"error": f"Provider {provider} not found for {model_type.value}"}
            
            # Execute the test
            result = provider_func(**test_payload)
            if asyncio.iscoroutine(result):
                result = await result
            
            duration = time.time() - start_time
            
            # Update model info with benchmark results
            model_key = f"{model_type.value}:{provider}"
            if model_key in self.models:
                model_info = self.models[model_key]
                model_info.last_tested = datetime.now()
                model_info.performance_metrics.update({
                    "last_response_time": duration,
                    "last_success": True
                })
            
            return {
                "provider": provider,
                "model_type": model_type.value,
                "response_time": duration,
                "success": True,
                "result_preview": str(result)[:200] + "..." if len(str(result)) > 200 else str(result)
            }
        except Exception as e:
            self.logger.error(f"Benchmark failed for {provider}: {e}")
            
            # Update model info with failure
            model_key = f"{model_type.value}:{provider}"
            if model_key in self.models:
                model_info = self.models[model_key]
                model_info.performance_metrics["last_success"] = False
                model_info.performance_metrics["last_error"] = str(e)
            
            return {
                "provider": provider,
                "model_type": model_type.value,
                "success": False,
                "error": str(e)
            }
    
    async def get_model_health_status(self) -> Dict[str, Any]:
        """Get overall health status of all registered models"""
        health_status = {
            "total_models": len(self.models),
            "active_models": 0,
            "performance_summary": {},
            "provider_status": {}
        }
        
        for key, model in self.models.items():
            if model.is_active:
                health_status["active_models"] += 1
            
            # Add performance info if available
            perf = model.performance_metrics
            health_status["performance_summary"][key] = {
                "quality_score": model.capabilities.quality_score,
                "avg_response_time": perf.get("avg_response_time", "N/A"),
                "success_rate": (
                    f"{perf.get('successful_calls', 0)}/{perf.get('total_calls', 0)}"
                    if perf.get("total_calls", 0) > 0 else "N/A"
                )
            }
            
            # Check provider routability
            health_status["provider_status"][model.provider] = {
                "is_routable": provider_routable(model.provider),
                "is_registered": self.provider_registry.get(model.model_type.value, model.provider) is not None
            }
        
        return health_status


# Singleton instance
ai_orchestrator = AIModelOrchestrator()