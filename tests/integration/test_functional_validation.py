#!/usr/bin/env python3
"""
Functional validation of Hevi system components
"""
import sys
import os
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
project_root = '/data/soffy/projects/hevi'
sys.path.insert(0, project_root)

def test_service_creation():
    """Test creating service instances without database connections"""
    print("Testing service creation...")
    
    # Test base service creation
    from hevi.services.base import BaseService
    base_service = BaseService()
    assert base_service is not None
    print("  ✅ BaseService created successfully")
    
    # Test response service (doesn't need database)
    from hevi.services.response_service import ApiResponseService
    response_service = ApiResponseService()
    assert response_service is not None
    print("  ✅ ApiResponseService created successfully")
    
    # Test response formatting
    success_resp = response_service.success({"test": "data"}, "Test message")
    assert success_resp["status"] == "success"
    assert "data" in success_resp
    print("  ✅ ApiResponseService formatting works")
    
    error_resp = response_service.error("Test error", "TEST_ERR")
    assert error_resp["status"] == "error"
    assert "message" in error_resp
    print("  ✅ ApiResponseService error handling works")
    
    return True

def test_ai_model_enums():
    """Test AI model enums and data structures"""
    print("Testing AI model enums and data structures...")
    
    from hevi.ai_models.orchestrator import ModelType, ModelCapability, ModelInfo
    
    # Test ModelType enum
    assert ModelType.LLM.value == "llm"
    assert ModelType.VIDEO.value == "video"
    print("  ✅ ModelType enum works correctly")
    
    # Test ModelCapability creation
    capability = ModelCapability(
        supports_streaming=True,
        max_tokens=4096,
        quality_score=8
    )
    assert capability.supports_streaming == True
    assert capability.max_tokens == 4096
    assert capability.quality_score == 8
    print("  ✅ ModelCapability created and works correctly")
    
    # Test ModelInfo creation
    model_info = ModelInfo(
        name="test_model",
        provider="test_provider",
        model_type=ModelType.LLM,
        version="1.0",
        capabilities=capability
    )
    assert model_info.name == "test_model"
    assert model_info.model_type == ModelType.LLM
    print("  ✅ ModelInfo created and works correctly")
    
    return True

def test_routing_strategy_enum():
    """Test routing strategy enum"""
    print("Testing routing strategy enum...")
    
    from hevi.ai_models.routing_service import RoutingStrategy
    
    assert RoutingStrategy.COST_OPTIMIZED.value == "cost_optimized"
    assert RoutingStrategy.QUALITY_PRIORITIZED.value == "quality_prioritized"
    assert RoutingStrategy.BALANCED.value == "balanced"
    print("  ✅ RoutingStrategy enum works correctly")
    
    return True

def test_routing_decision():
    """Test routing decision data structure"""
    print("Testing routing decision structure...")
    
    from hevi.ai_models.routing_service import RoutingDecision, RoutingStrategy
    
    decision = RoutingDecision(
        provider="test_provider",
        confidence=0.8,
        estimated_cost=0.05,
        estimated_time=2.5,
        strategy_used=RoutingStrategy.BALANCED,
        fallback_options=["fallback1", "fallback2"]
    )
    
    assert decision.provider == "test_provider"
    assert decision.confidence == 0.8
    assert decision.strategy_used == RoutingStrategy.BALANCED
    assert len(decision.fallback_options) == 2
    print("  ✅ RoutingDecision created and works correctly")
    
    return True

async def test_mocked_ai_orchestrator():
    """Test AI orchestrator with mocked dependencies"""
    print("Testing AI orchestrator with mocked dependencies...")
    
    from hevi.ai_models.orchestrator import AIModelOrchestrator, ModelType, ModelInfo, ModelCapability
    
    # Create orchestrator
    orchestrator = AIModelOrchestrator()
    
    # Test model registration
    test_capability = ModelCapability(quality_score=8)
    test_model = ModelInfo(
        name="test_llm_model",
        provider="test_provider",
        model_type=ModelType.LLM,
        version="1.0",
        capabilities=test_capability
    )
    
    # Register the model
    result = await orchestrator.register_model(test_model)
    assert result == True
    print("  ✅ Model registration works")
    
    # Check that model was registered
    model_key = f"{ModelType.LLM.value}:{test_model.provider}"
    assert model_key in orchestrator.models
    print("  ✅ Model found in registry")
    
    # Test getting best model (with mocked requirements)
    best_model = await orchestrator.get_best_model(
        model_type=ModelType.LLM,
        requirements={},
        quality_threshold=5
    )
    # Since we only have one model and it meets the threshold, it should be returned
    assert best_model is not None
    assert best_model.name == "test_llm_model"
    print("  ✅ Best model selection works")
    
    return True

async def test_mocked_intelligent_router():
    """Test intelligent router with mocked dependencies"""
    print("Testing intelligent router with mocked dependencies...")
    
    from hevi.ai_models.orchestrator import AIModelOrchestrator, ModelType
    from hevi.ai_models.routing_service import IntelligentRoutingService, RoutingStrategy
    
    # Create orchestrator and router
    orchestrator = AIModelOrchestrator()
    router = IntelligentRoutingService(orchestrator)
    
    # Test routing request with mocked provider availability
    with patch('hevi.ai_models.routing_service.provider_routable', return_value=True):
        with patch('hevi.ai_models.routing_service.estimate_cost') as mock_cost:
            from hevi.cost.estimator import estimate_cost
            from unittest.mock import AsyncMock
            mock_cost.return_value = AsyncMock()
            mock_cost.return_value.total_usd = 0.05
            
            decision = await router.route_request(
                model_type=ModelType.LLM,
                payload={"messages": [{"role": "user", "content": "hello"}]},
                strategy=RoutingStrategy.BALANCED,
                quality_threshold=1
            )
            
            # Decision should be created even if no providers are available in real system
            assert hasattr(decision, 'strategy_used')
            print("  ✅ Routing decision created successfully")
    
    return True

async def test_mocked_adaptive_learner():
    """Test adaptive learner with mocked dependencies"""
    print("Testing adaptive learner with mocked dependencies...")
    
    from hevi.ai_models.orchestrator import AIModelOrchestrator, ModelType
    from hevi.ai_models.routing_service import IntelligentRoutingService
    from hevi.ai_models.adaptive_learning import AdaptiveLearningService
    
    # Create components
    orchestrator = AIModelOrchestrator()
    router = IntelligentRoutingService(orchestrator)
    learner = AdaptiveLearningService(orchestrator, router)
    
    # Test recording an interaction
    learner.record_interaction(
        provider="test_provider",
        model_type=ModelType.LLM,
        payload={"test": "data"},
        response_time=0.5,
        cost=0.01,
        quality_score=0.8,
        success=True
    )
    
    assert len(learner.performance_records) == 1
    print("  ✅ Interaction recorded successfully")
    
    # Test suggesting best provider
    suggested_provider, confidence = await learner.suggest_best_provider(
        model_type=ModelType.LLM,
        payload={"test": "data"},
        fallback_providers=["fallback1", "fallback2"]
    )
    
    # Should return a provider and confidence value
    assert isinstance(confidence, float)
    assert 0.0 <= confidence <= 1.0
    print("  ✅ Provider suggestion works")
    
    # Test getting learning insights
    insights = await learner.get_learning_insights()
    assert "total_interactions" in insights
    assert "provider_performance" in insights
    print("  ✅ Learning insights retrieval works")
    
    return True

async def test_unified_ai_service_structure():
    """Test unified AI service structure"""
    print("Testing unified AI service structure...")
    
    from hevi.ai_models.unified_service import UnifiedAIService
    
    # Create unified service
    unified_service = UnifiedAIService()
    
    # Verify components exist
    assert unified_service.orchestrator is not None
    assert unified_service.router is not None
    assert unified_service.learner is not None
    print("  ✅ Unified service components initialized")
    
    # Test analytics retrieval
    analytics = await unified_service.get_analytics()
    assert "execution_stats" in analytics
    assert "provider_performance" in analytics
    assert "routing_analytics" in analytics
    assert "learning_insights" in analytics
    print("  ✅ Analytics retrieval works")
    
    return True

async def run_all_functional_tests():
    """Run all functional tests"""
    print("🔍 Starting functional validation of Hevi system components...\n")
    
    tests = [
        ("Service Creation", test_service_creation),
        ("AI Model Enums", test_ai_model_enums),
        ("Routing Strategy Enum", test_routing_strategy_enum),
        ("Routing Decision Structure", test_routing_decision),
        ("AI Orchestrator", test_mocked_ai_orchestrator),
        ("Intelligent Router", test_mocked_intelligent_router),
        ("Adaptive Learner", test_mocked_adaptive_learner),
        ("Unified AI Service", test_unified_ai_service_structure),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        print(f"🧪 Running {test_name} test...")
        try:
            if asyncio.iscoroutinefunction(test_func):
                result = await test_func()
            else:
                result = test_func()
            
            if result:
                print(f"  ✅ {test_name} test PASSED\n")
                passed += 1
            else:
                print(f"  ❌ {test_name} test FAILED\n")
                failed += 1
        except Exception as e:
            print(f"  ❌ {test_name} test ERROR: {e}\n")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print(f"📊 Functional Test Results:")
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")
    print(f"📈 Total: {passed + failed}")
    
    overall_success = failed == 0
    
    if overall_success:
        print(f"\n🎉 All functional tests passed! System components are working correctly.")
    else:
        print(f"\n⚠️  {failed} functional test(s) failed. Please review the issues above.")
    
    return overall_success

if __name__ == "__main__":
    success = asyncio.run(run_all_functional_tests())
    sys.exit(0 if success else 1)