import re

with open('hevi/providers/hyperframes/provider.py', 'r') as f:
    content = f.read()

# Add styled_explainer capability and a new provider
cap = """
HYPERFRAMES_STYLED_CAPABILITY = {
    "id": "hyperframes_styled",
    "capabilities": ["t2v", "styled_explainer", "zh_prompt"],
    "prompt_language": "zh",
    "max_duration_sec": 90,
    "resolution": ["1080"],
    "ref_image": False,
    "cost_per_sec": 0,
    "health": "local_cli",
    "entrypoint": "hyperframes_styled",
    "vram_profile": "cpu",
    "notes": "Lanshu styled explainer wrapper.",
}

async def hyperframes_styled_generate(*, prompt="", output_path, config=None, **kwargs):
    # For styled_explainer, we expect the prompt to be the topic name, or it has script_lines.
    import os
    import subprocess
    import shutil
    
    output_path = Path(output_path)
    topic = str(prompt) if not isinstance(prompt, dict) else str(prompt.get("topic", "test"))
    
    # 1. Create a workspace
    work_dir = output_path.parent / f"{output_path.stem}_styled"
    work_dir.mkdir(parents=True, exist_ok=True)
    
    # 2. Write script.md if script_lines provided
    if isinstance(prompt, dict) and prompt.get("script_lines"):
        lines = prompt["script_lines"]
        script_path = work_dir / "script.md"
        with open(script_path, "w") as f:
            f.write(f"# {topic}\\n\\n")
            f.write("## Chapter 1\\n\\n")
            for line in lines:
                text = line.get("text", line) if isinstance(line, dict) else line
                f.write(f"- {text}\\n")
    else:
        # Default script
        with open(work_dir / "script.md", "w") as f:
            f.write(f"# {topic}\\n\\n## Chapter 1\\n\\n- Hello world, this is a default style test.\\n")

    # 3. run story.py
    env = os.environ.copy()
    env["PATH"] = f"/home/soffy/.local/bin:{env['PATH']}"
    subprocess.run([sys.executable, "/data/soffy/projects/hevi-omrender/third_party/lanshu_explainer/tools/story.py", str(work_dir)], env=env, check=True)
    
    # 4. run sync.sh
    style = config.get("style", "v6-cinematic") if config else "v6-cinematic"
    subprocess.run(["bash", "/data/soffy/projects/hevi-omrender/third_party/lanshu_explainer/tools/sync.sh", str(work_dir), style, str(work_dir)], check=True)
    
    # 5. run render.sh
    subprocess.run(["bash", "/data/soffy/projects/hevi-omrender/third_party/lanshu_explainer/tools/render.sh", str(work_dir), output_path.stem, str(output_path.parent)], check=True)
    
    # render.sh puts it in output_path.parent / output_path.stem-master.mp4 or something?
    # wait, render.sh says: ffmpeg -i "$OUT/$NAME-master.mp4"
    # Wait, render.sh runs finalize_delivery.sh which generates `-master.mp4`.
    # Let's check finalize_delivery.sh
    
    result_mp4 = output_path.parent / f"{output_path.stem}-master.mp4"
    if result_mp4.exists():
        shutil.copy(result_mp4, output_path)
    else:
        # maybe it failed to finalize, try just .mp4
        shutil.copy(work_dir / "renders" / f"{output_path.stem}.mp4", output_path)

    return output_path
"""

# append this and register it
content = content.replace("def register_hyperframes() -> None:", cap + "\ndef register_hyperframes() -> None:")
content = content.replace("ProviderRegistry.register(\"video\", \"hyperframes\", hyperframes_generate, replace=True)", "ProviderRegistry.register(\"video\", \"hyperframes\", hyperframes_generate, replace=True)\n    ProviderRegistry.register(\"video\", \"hyperframes_styled\", hyperframes_styled_generate, replace=True)")

with open('hevi/providers/hyperframes/provider.py', 'w') as f:
    f.write(content)
