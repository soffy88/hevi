#!/usr/bin/env python3
"""
End-to-End Demo Runner
Runs the complete video production pipeline as a demonstration.
"""
import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from hevi.skills.production-director import production_director_skill_execute

async def run_demo():
    """Run the complete end-to-end demo."""
    print("🚀 Starting Hevi End-to-End Demo...")
    print("📋 This demo will execute the complete video production pipeline:")
    print("   1. Audio generation (local TTS only)")
    print("   2. Video rendering")
    print("   3. Subtitle generation (from real audio)")
    print("   4. Final quality control")
    print()
    
    try:
        # Validate TTS provider first
        print("🔍 Validating TTS provider configuration...")
        from hevi.scripts.validate_tts_provider import validate_tts_provider
        validate_tts_provider()
        print("✅ TTS provider validation passed")
        print()
        
        # Define paths
        handover_file = project_root / "hevi/examples/end-to-end-demo/example_handover.md"
        output_dir = project_root / "outputs/demo_run"
        
        print(f"📝 Using handover file: {handover_file}")
        print(f"💾 Output directory: {output_dir}")
        print()
        
        print("🎬 Starting production pipeline...")
        result = await production_director_skill_execute(
            handover_file=str(handover_file),
            output_dir=str(output_dir)
        )
        
        print("🎉 Pipeline completed successfully!")
        print()
        print("📊 Results:")
        for key, value in result.items():
            if key != 'output_files':  # Print output_files separately
                print(f"   {key}: {value}")
        
        print("📁 Output files:")
        for file_type, file_path in result.get('output_files', {}).items():
            print(f"   {file_type}: {file_path}")
        
        print()
        print("✅ Demo completed successfully!")
        return result
        
    except Exception as e:
        print(f"❌ Demo failed: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(run_demo())