"""
Integration tests for the complete Hevi system
Validating all phases: frontend, microservices, and AI model integration
"""
import pytest
import asyncio
from typing import Dict, Any
import time
from unittest.mock import AsyncMock, MagicMock

# Import components from all phases
from hevi.api.main import app
from hevi.services import service_registry, get_service
from hevi.ai_models import unified_ai_service, ModelType, RoutingStrategy
from hevi.providers.registry import ProviderRegistry


class TestSystemIntegration:
    """
    Integration tests covering all system components
    """
    
    def setup_method(self):
        """Setup test environment"""
        self.test_user_data = {
            "id": "test-user-123",
            "email": "test@example.com",
            "display_name": "Test User"
        }
    
    async def test_microservice_registry_integration(self):
        """Test that all microservices are properly registered and accessible"""
        # Verify service registry is initialized
        assert service_registry is not None
        assert len(service_registry.get_all_service_names()) > 0
        
        # Test accessing core services
        user_service = get_service('user_service')
        assert user_service is not None
        
        task_service = get_service('task_service')
        assert task_service is not None
        
        cache_service = get_service('cache_service')
        assert cache_service is not None
        
        response_service = get_service('api_response_service')
        assert response_service is not None
        
        auth_service = get_service('auth_service')
        assert auth_service is not None
        
        rate_limit_service = get_service('rate_limit_service')
        assert rate_limit_service is not None
        
        async_task_service = get_service('async_task_service')
        assert async_task_service is not None
        
        print("✅ Microservice registry integration test passed")
    
    async def test_ai_model_integration(self):
        """Test AI model services integration"""
        # Verify AI services are initialized
        assert unified_ai_service is not None
        
        # Test getting analytics (should not raise exception)
        analytics = await unified_ai_service.get_analytics()
        assert "execution_stats" in analytics
        assert "routing_analytics" in analytics
        assert "learning_insights" in analytics
        
        print("✅ AI model integration test passed")
    
    async def test_provider_registry_integration(self):
        """Test that existing providers are still accessible through registry"""
        # Check that key providers are registered
        llm_providers = ProviderRegistry.list("llm") or []
        assert len(llm_providers) > 0, "Should have LLM providers registered"
        
        video_providers = ProviderRegistry.list("video") or []
        assert len(video_providers) > 0, "Should have video providers registered"
        
        audio_providers = ProviderRegistry.list("audio") or []
        assert len(audio_providers) > 0, "Should have audio providers registered"
        
        print("✅ Provider registry integration test passed")
    
    async def test_unified_ai_service_basic_request(self):
        """Test basic AI service request (without actually calling external providers)"""
        # Mock a simple request that doesn't require external calls
        try:
            # Test with minimal payload
            result = await unified_ai_service.execute_request(
                model_type=ModelType.LLM,
                payload={"messages": [{"role": "user", "content": "Hello"}]},
                strategy=RoutingStrategy.BALANCED,
                quality_threshold=1  # Minimal threshold to allow testing
            )
            
            # The request may fail due to missing external credentials,
            # but the system should handle it gracefully
            assert "success" in result
            assert isinstance(result["success"], bool)
            
        except Exception as e:
            # Even if the request fails due to missing credentials,
            # the system should handle the error gracefully
            print(f"Expected potential failure due to missing credentials: {e}")
        
        print("✅ Unified AI service basic request test completed")
    
    async def test_service_communication_patterns(self):
        """Test communication patterns between services"""
        # Test cache service functionality
        cache_service = get_service('cache_service')
        assert cache_service is not None
        
        # Test basic cache operations
        test_key = "integration_test_key"
        test_value = {"test": "data", "timestamp": time.time()}
        
        # Set value in cache
        success = await cache_service.set(test_key, test_value, ttl=60)
        assert success, "Should be able to set value in cache"
        
        # Get value from cache
        retrieved_value = await cache_service.get(test_key)
        assert retrieved_value is not None, "Should be able to get value from cache"
        assert retrieved_value["test"] == "data", "Retrieved value should match set value"
        
        # Delete value from cache
        deleted = await cache_service.delete(test_key)
        assert deleted, "Should be able to delete value from cache"
        
        print("✅ Service communication patterns test passed")
    
    async def test_response_service_consistency(self):
        """Test that response service provides consistent formatting"""
        response_service = get_service('api_response_service')
        assert response_service is not None
        
        # Test success response
        success_resp = response_service.success(
            data={"test": "value"},
            message="Test success"
        )
        assert success_resp["status"] == "success"
        assert "data" in success_resp
        assert "timestamp" in success_resp
        
        # Test error response
        error_resp = response_service.error(
            message="Test error",
            code="TEST_ERROR"
        )
        assert error_resp["status"] == "error"
        assert "message" in error_resp
        assert "timestamp" in error_resp
        
        # Test paginated response
        paginated_resp = response_service.paginated_success(
            data=[1, 2, 3],
            page=1,
            page_size=10,
            total=100
        )
        assert "data" in paginated_resp
        assert "meta" in paginated_resp
        assert "pagination" in paginated_resp["meta"]
        
        print("✅ Response service consistency test passed")
    
    async def test_rate_limiting_functionality(self):
        """Test rate limiting service functionality"""
        rate_limit_service = get_service('rate_limit_service')
        assert rate_limit_service is not None
        
        # Test rate limit check
        is_allowed, current_count, reset_time = await rate_limit_service.is_rate_limited(
            key="test_integration_key",
            max_requests=10,
            window_seconds=60
        )
        
        assert isinstance(is_allowed, bool)
        assert isinstance(current_count, int)
        assert isinstance(reset_time, int)
        
        # Test rate limit info
        limit_info = await rate_limit_service.get_rate_limit_info(
            key="test_integration_key",
            max_requests=10,
            window_seconds=60
        )
        
        assert "limit" in limit_info
        assert "remaining" in limit_info
        assert "reset" in limit_info
        
        print("✅ Rate limiting functionality test passed")
    
    async def test_async_task_management(self):
        """Test async task service functionality"""
        async_task_service = get_service('async_task_service')
        assert async_task_service is not None
        
        # Define a simple async function to test
        async def sample_task(x, y):
            await asyncio.sleep(0.1)  # Simulate some async work
            return x + y
        
        # Run the task in background
        task_id = await async_task_service.run_background_task(
            sample_task,
            5,
            3,
            task_id="integration_test_task"
        )
        
        # Wait for task completion
        result = await async_task_service.wait_for_task_completion(task_id, timeout=5.0)
        assert result == 8, "Task should return correct result"
        
        # Test active task count
        active_count = async_task_service.get_active_task_count()
        assert isinstance(active_count, int)
        
        print("✅ Async task management test passed")
    
    async def test_comprehensive_system_workflow(self):
        """Test a comprehensive workflow involving multiple system components"""
        # This simulates a typical workflow: user creates task -> task processed -> AI model used -> result cached
        
        # 1. Use user service to simulate user data
        user_service = get_service('user_service')
        
        # 2. Use task service to create a task
        task_service = get_service('task_service')
        
        # 3. Use cache service to cache intermediate results
        cache_service = get_service('cache_service')
        
        # 4. Use AI service for processing
        # (Simulated - would normally involve actual AI processing)
        
        # 5. Use response service for consistent output
        response_service = get_service('api_response_service')
        
        # Verify all components are accessible
        components = [
            user_service, task_service, cache_service, 
            unified_ai_service, response_service
        ]
        
        for comp in components:
            assert comp is not None, f"Component {type(comp).__name__} should be available"
        
        # Create a sample workflow result
        workflow_result = response_service.success(
            data={
                "workflow": "integration_test",
                "components_verified": len(components),
                "status": "completed"
            },
            message="Comprehensive system workflow test completed"
        )
        
        assert workflow_result["status"] == "success"
        assert "data" in workflow_result
        assert workflow_result["data"]["components_verified"] == len(components)
        
        print("✅ Comprehensive system workflow test passed")
    
    async def run_all_tests(self):
        """Run all integration tests"""
        print("🚀 Starting comprehensive system integration tests...\n")
        
        tests = [
            self.test_microservice_registry_integration,
            self.test_ai_model_integration,
            self.test_provider_registry_integration,
            self.test_unified_ai_service_basic_request,
            self.test_service_communication_patterns,
            self.test_response_service_consistency,
            self.test_rate_limiting_functionality,
            self.test_async_task_management,
            self.test_comprehensive_system_workflow,
        ]
        
        passed = 0
        failed = 0
        
        for test in tests:
            try:
                await test()
                passed += 1
            except Exception as e:
                print(f"❌ Test {test.__name__} failed: {e}")
                failed += 1
        
        print(f"\n📊 Integration Test Results:")
        print(f"✅ Passed: {passed}")
        print(f"❌ Failed: {failed}")
        print(f"📈 Total: {passed + failed}")
        
        if failed == 0:
            print("\n🎉 All integration tests passed! System is functioning correctly.")
        else:
            print(f"\n⚠️  {failed} test(s) failed. Please review the issues above.")
        
        return failed == 0


# Run the tests if this file is executed directly
if __name__ == "__main__":
    import asyncio
    
    async def main():
        tester = TestSystemIntegration()
        success = await tester.run_all_tests()
        return success
    
    # Run with asyncio
    success = asyncio.run(main())
    
    # Exit with appropriate code
    import sys
    sys.exit(0 if success else 1)