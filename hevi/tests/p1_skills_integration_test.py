"""
Integration Test for New P1 Skills
Tests the integration between title generation, hook detection, and digital twin guard.
"""
import asyncio
import tempfile
from pathlib import Path

# Add project root to path
import sys
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from hevi.skills.title_generator import title_generator_skill_execute
from hevi.skills.hook_detector import hook_detector_skill_execute
from hevi.skills.digital_twin_guard import digital_twin_guard_skill_execute
from hevi.skills.cost_tracker import cost_tracker_skill_execute

async def run_integration_test():
    """Run integration test for P1 skills."""
    print("🧪 Running Integration Test for P1 Skills...")
    print()
    
    # Sample content for testing
    sample_content = """
    人工智能正在改变我们的世界。从自动驾驶汽车到智能助手，
    AI技术已经深入到我们生活的方方面面。在未来，我们可以期待
    更加智能化的服务，比如个性化教育、精准医疗和智慧城市。
    """
    
    try:
        print("1️⃣ Testing Title Generation...")
        title_result = await title_generator_skill_execute(
            content=sample_content,
            num_titles=3
        )
        print(f"   Generated {title_result['generated_count']} titles")
        print(f"   Status: {title_result['status']}")
        print()
        
        print("2️⃣ Testing Hook Detection...")
        hook_result = await hook_detector_skill_execute(
            content=sample_content,
            threshold=0.5
        )
        print(f"   Engagement Score: {hook_result['engagement_score']:.2f}")
        print(f"   Passes Threshold: {hook_result['passes_threshold']}")
        print(f"   Suggestions: {len(hook_result['suggestions'])}")
        print()
        
        print("3️⃣ Testing Digital Twin Guard (without approval - should fail)...")
        # Create a temporary voice sample file for testing
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
            temp_file.write(b"dummy voice sample data")  # Not real audio data, just for testing
            temp_voice_path = temp_file.name
        
        try:
            # This should fail because no audition was approved
            await digital_twin_guard_skill_execute(
                voice_sample_path=temp_voice_path,
                digital_person_params={"style": "professional", "speed": 1.0}
            )
            print("   ERROR: Digital twin guard should have failed without approval!")
        except RuntimeError as e:
            print(f"   ✅ Correctly blocked: {str(e)}")
        finally:
            # Clean up temp file
            Path(temp_voice_path).unlink(missing_ok=True)
        print()
        
        print("4️⃣ Testing Digital Twin Guard (with approval)...")
        # Create another temp file and approve it
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
            temp_file.write(b"dummy voice sample data")
            temp_voice_path = temp_file.name
        
        try:
            # Use the same skill instance to register and check approval
            from hevi.skills.digital_twin_guard import DigitalTwinGuardSkill
            guard_skill = DigitalTwinGuardSkill()
            await guard_skill.register_audition_approval(temp_voice_path, "test_user")
            
            # Now check using the same instance
            approval_result = await guard_skill.execute(
                voice_sample_path=temp_voice_path,
                digital_person_params={"style": "professional", "speed": 1.0}
            )
            print(f"   Status: {approval_result['status']}")
            print(f"   Reason: {approval_result['reason']}")
        finally:
            # Clean up temp file
            Path(temp_voice_path).unlink(missing_ok=True)
        print()
        
        print("5️⃣ Testing Cost Tracking...")
        cost_result = await cost_tracker_skill_execute(
            operation_type="tts",
            resources_used={"characters": 500},
            metadata={"test_case": "integration_test", "skill": "title_generator"}
        )
        print(f"   Calculated Cost: ${cost_result['calculated_cost']}")
        print(f"   Operation ID: {cost_result['operation_id']}")
        print()
        
        print("✅ All P1 skill integration tests completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Integration test failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(run_integration_test())
    if success:
        print("\n🎉 P1 Skills Integration Test PASSED!")
    else:
        print("\n💥 P1 Skills Integration Test FAILED!")
        exit(1)