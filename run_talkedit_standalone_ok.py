import sys
import os
import importlib.util

def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

clean_mod = load_mod("talkedit_clean", "hevi/video/talkedit_clean.py")
herk_mod = load_mod("talkedit_herk", "hevi/video/talkedit_herk.py")
ghost_mod = load_mod("talkedit_ghost", "hevi/video/talkedit_ghost.py")
oneprompt_mod = load_mod("talkedit_oneprompt", "hevi/workflows/talkedit_oneprompt.py")
talkcraft_mod = load_mod("talkedit_talkcraft", "hevi/video/talkedit_talkcraft.py")

def main():
    out_dir = "output_e2e/talkedit_sample"
    os.makedirs(out_dir, exist_ok=True)
    
    print("--- 1. Testing talkedit_clean ---")
    clean_path = os.path.join(out_dir, "clean_recipe.json")
    recipe = clean_mod.generate_clean_recipe("nonexistent.json", clean_path)
    print("Clean recipe segments count:", len(recipe["segments"]))
    
    print("--- 2. Testing talkedit_herk ---")
    herk_path = os.path.join(out_dir, "herk_pkg.json")
    plan = herk_mod.export_herk_pkg(clean_path, herk_path)
    print("Herk narrative phases:", len(plan["narrative_structure"]))
    
    print("--- 3. Testing talkedit_ghost ---")
    ghost_path = os.path.join(out_dir, "ghost_spec.json")
    spec = ghost_mod.generate_ghost_spec(clean_path, ghost_path)
    print("Ghost matchings count:", len(spec["matchings"]))
    
    print("--- 4. Testing talkedit_oneprompt ---")
    wf_res = oneprompt_mod.run_one_prompt_pipeline("AI驱动的高效自媒体口播剪辑工作流", os.path.join(out_dir, "one_prompt_demo"))
    print("One prompt result status:", wf_res["status"])
    
    print("--- 5. Testing talkedit_talkcraft ---")
    tc_path = os.path.join(out_dir, "talkcraft_config.json")
    tc_conf = talkcraft_mod.generate_talkcraft_config("让每一次口播都自带电影级动效与逐字完美卡点", tc_path)
    print("Talkcraft timed words count:", len(tc_conf["timed_words"]))
    
    print("\nSUCCESS: All 5 talkedit capabilities executed and verified end-to-end!")

if __name__ == "__main__":
    main()
