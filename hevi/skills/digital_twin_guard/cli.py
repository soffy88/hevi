#!/usr/bin/env python3
"""
CLI Tool for Digital Twin Management
Allows administrators to approve voice samples for digital person generation.
"""
import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from hevi.skills.digital_twin_guard import DigitalTwinGuardSkill

async def approve_voice_sample(voice_path: str, approver: str):
    """Approve a voice sample for digital person generation."""
    skill = DigitalTwinGuardSkill()
    result = await skill.register_audition_approval(voice_path, approver)
    print(f"✅ Voice sample approved: {result['voice_identifier']}")
    print(f"   Approved by: {result['approver']}")
    print(f"   Timestamp: {result['timestamp']}")

def main():
    parser = argparse.ArgumentParser(description="Digital Twin Management CLI")
    parser.add_argument("command", choices=["approve"], help="Management command")
    parser.add_argument("--voice-path", required=True, help="Path to voice sample file")
    parser.add_argument("--approver", default="admin", help="Name of approving user")
    
    args = parser.parse_args()
    
    if args.command == "approve":
        print(f"Approving voice sample: {args.voice_path}")
        print(f"Approver: {args.approver}")
        
        try:
            asyncio.run(approve_voice_sample(args.voice_path, args.approver))
            print("Voice sample successfully approved for digital person generation.")
        except Exception as e:
            print(f"❌ Error approving voice sample: {e}")
            sys.exit(1)

if __name__ == "__main__":
    main()