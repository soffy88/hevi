"""
AI Model Service API Router for Hevi
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any, List
from pydantic import BaseModel

from hevi.ai_models import unified_ai_service, ModelType, RoutingStrategy
from hevi.auth.dependencies import get_current_user

router = APIRouter(prefix="/ai-models", tags=["ai-models"])


class AIRequest(BaseModel):
    model_type: str  # Should be a valid ModelType value
    payload: Dict[str, Any]
    strategy: str = "balanced"  # Should be a valid RoutingStrategy value
    quality_threshold: int = 5
    budget_limit: float = None


class ModelEvaluationRequest(BaseModel):
    provider: str
    model_type: str  # Should be a valid ModelType value
    test_cases: List[Dict[str, Any]]


class OptimizationRequest(BaseModel):
    request_pattern: Dict[str, Any]
    optimization_target: str = "balanced"  # cost, quality, speed, balanced


@router.post("/execute")
async def execute_ai_request(
    request: AIRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Execute an AI request using the unified AI service with intelligent routing
    and adaptive learning
    """
    try:
        # Validate model type
        try:
            model_type = ModelType(request.model_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid model type: {request.model_type}")
        
        # Validate strategy
        try:
            strategy = RoutingStrategy(request.strategy)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid routing strategy: {request.strategy}")
        
        result = await unified_ai_service.execute_request(
            model_type=model_type,
            payload=request.payload,
            strategy=strategy,
            quality_threshold=request.quality_threshold,
            budget_limit=request.budget_limit
        )
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI request execution failed: {str(e)}")


@router.get("/analytics")
async def get_ai_analytics(
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get analytics about AI model usage, performance, and learning insights
    """
    try:
        analytics = await unified_ai_service.get_analytics()
        return analytics
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve analytics: {str(e)}")


@router.post("/evaluate-model")
async def evaluate_model_quality(
    eval_request: ModelEvaluationRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Evaluate the quality of a specific AI model with test cases
    """
    try:
        # Validate model type
        try:
            model_type = ModelType(eval_request.model_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid model type: {eval_request.model_type}")
        
        result = await unified_ai_service.evaluate_model_quality(
            provider=eval_request.provider,
            model_type=model_type,
            test_cases=eval_request.test_cases
        )
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Model evaluation failed: {str(e)}")


@router.post("/optimize-request")
async def optimize_request_pattern(
    optimization_request: OptimizationRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Optimize model selection for a specific request pattern
    """
    try:
        result = await unified_ai_service.optimize_for_request_pattern(
            request_pattern=optimization_request.request_pattern,
            optimization_target=optimization_request.optimization_target
        )
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Request optimization failed: {str(e)}")


@router.get("/health")
async def ai_service_health():
    """
    Health check for the AI model services
    """
    try:
        # Test basic functionality
        analytics = await unified_ai_service.get_analytics()
        
        return {
            "status": "healthy",
            "service": "ai-model-integration",
            "analytics_available": analytics is not None,
            "total_executions": analytics.get("execution_stats", {}).get("total_executions", 0)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")