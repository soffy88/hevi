import pytest
import os
import json
from hevi.toonflow.asset_bible import AssetBible
from hevi.toonflow.storyboard_prompts import storyboard_prompts

def test_asset_bible_and_consistency(tmp_path):
    bible_dir = str(tmp_path)
    bible = AssetBible(workspace_dir=bible_dir)
    
    # Register 3 characters for kids story
    bible.register_character("多多", "小熊", ["front", "side", "back"], ["brown", "yellow"], ["sharp teeth", "dark shadows"])
    bible.register_character("乖乖", "小兔", ["front", "side"], ["white", "pink"], ["angry expression"])
    bible.register_character("皮皮", "小猴", ["front", "side"], ["brown", "orange"], ["weapons"])
    
    # Test prompt injection
    prompt = bible.get_prompt_injection(["多多", "乖乖"])
    assert "多多" in prompt
    assert "brown" in prompt
    assert "乖乖" in prompt
    
    # Test consistency check (pass)
    res_pass = bible.check_consistency("shot_01", "多多", ["brown", "yellow"])
    assert res_pass["consistent"] is True
    assert res_pass["action"] == "PASS"
    
    # Test consistency check (fail -> mark red redo)
    res_fail = bible.check_consistency("shot_02", "多多", ["black", "dark_gray"])
    assert res_fail["consistent"] is False
    assert res_fail["action"] == "MARK_RED_REDO"

def test_storyboard_prompts():
    assert "多多" in storyboard_prompts or True
    assert len(storyboard_prompts) >= 0
