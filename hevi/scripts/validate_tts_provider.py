#!/usr/bin/env python3
"""
TTS Provider Validation Script
Validates that the TTS provider configuration is set to local for production environments.
"""
import json
import os
import sys
from pathlib import Path

def validate_tts_provider():
    """Validate TTS provider configuration at startup."""
    config_path = Path("hevi/configs/tts_routing.json")
    
    if not config_path.exists():
        print("ERROR: TTS routing configuration not found at hevi/configs/tts_routing.json", file=sys.stderr)
        sys.exit(1)
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in TTS routing configuration: {e}", file=sys.stderr)
        sys.exit(1)
    
    production_provider = config.get("production_provider")
    allowed_providers = config.get("allowed_providers", [])
    fallback_enabled = config.get("fallback_enabled", True)
    
    # Check if provider is set to local
    if production_provider != "local-indextts2":
        print(f"ERROR: Production TTS provider must be 'local-indextts2', got '{production_provider}'", file=sys.stderr)
        print("Refusing to start - cloud TTS not allowed in production", file=sys.stderr)
        sys.exit(1)
    
    # Check if only local provider is allowed
    if "local-indextts2" not in allowed_providers:
        print(f"ERROR: Local TTS provider 'local-indextts2' not in allowed providers: {allowed_providers}", file=sys.stderr)
        sys.exit(1)
    
    # Check if fallback is disabled (no cloud fallback allowed)
    if fallback_enabled:
        print("ERROR: Fallback to cloud TTS is enabled, which is not allowed in production", file=sys.stderr)
        print("Set 'fallback_enabled': false in TTS routing configuration", file=sys.stderr)
        sys.exit(1)
    
    # Validate voice reference hash if provided
    voice_hash = config.get("voice_reference_sha256", "")
    if voice_hash:
        # Check if voice reference file exists and matches the hash
        voice_file_path = config.get("voice_reference_path", "voice_reference.wav")
        if os.path.exists(voice_file_path):
            import hashlib
            with open(voice_file_path, 'rb') as vf:
                calculated_hash = hashlib.sha256(vf.read()).hexdigest()
            if calculated_hash != voice_hash:
                print(f"ERROR: Voice reference file hash mismatch!", file=sys.stderr)
                print(f"Expected: {voice_hash}", file=sys.stderr)
                print(f"Actual:   {calculated_hash}", file=sys.stderr)
                sys.exit(1)
        else:
            print(f"WARNING: Voice reference file {voice_file_path} not found for validation", file=sys.stderr)
    
    print("TTS Provider validation passed - using local provider only")
    return True

if __name__ == "__main__":
    validate_tts_provider()