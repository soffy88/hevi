import os
import json
import pytest

from hevi.video.talkedit_clean import generate_clean_recipe
from hevi.video.talkedit_herk import export_herk_pkg
from hevi.video.talkedit_ghost import generate_ghost_spec
from hevi.workflows.talkedit_oneprompt import run_one_prompt_pipeline
from hevi.video.talkedit_talkcraft import generate_talkcraft_config

def test_full_talkedit_pipeline(tmp_path):
    out_dir = str(tmp_path / "output")
    os.makedirs(out_dir, exist_ok=True)
    
    # 1. Clean test
    clean_recipe_path = os.path.join(out_dir, "clean_recipe.json")
    recipe = generate_clean_recipe("nonexistent.json", clean_recipe_path)
    assert recipe["status"] == "ready"
    assert len(recipe["segments"]) == 3  # Filler removed and duplicate resolved
    
    # 2. Herk test
    herk_path = os.path.join(out_dir, "herk_pkg.json")
    plan = export_herk_pkg(clean_recipe_path, herk_path)
    assert plan["aspect_ratio"] == "9:16"
    
    # 3. Ghost test
    ghost_path = os.path.join(out_dir, "ghost_spec.json")
    spec = generate_ghost_spec(clean_recipe_path, ghost_path)
    assert len(spec["matchings"]) == 3
    assert spec["matchings"][0]["subtitle_position"]["avoid_face_region"] is True
    
    # 4. One-prompt workflow test
    workflow_res = run_one_prompt_pipeline("Python高级异步编程", os.path.join(out_dir, "oneprompt"))
    assert workflow_res["status"] == "success"
    
    # 5. Talkcraft test
    talkcraft_path = os.path.join(out_dir, "talkcraft_config.json")
    tc_config = generate_talkcraft_config("精通Python视频剪辑与自动化", talkcraft_path)
    assert len(tc_config["timed_words"]) > 0
    
    print("All Talkedit pipeline components tested successfully!")
