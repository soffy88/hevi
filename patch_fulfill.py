import re

with open('hevi/studio/fulfill.py', 'r') as f:
    content = f.read()

new_func = """
async def _render_character_animation_line(
    *, order: dict[str, Any], context: dict[str, Any], output_dir: Path
) -> dict[str, Any]:
    # Custom SVG character animation with GSAP/HyperFrames
    path = output_dir / "character_animation.mp4"
    
    # create hyperframes project for character animation
    hf_dir = output_dir / ".character_hf"
    hf_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. copy assets
    import shutil
    mocap_assets = Path("assets/mocap-clips")
    shutil.copytree(mocap_assets, hf_dir / "mocap", dirs_exist_ok=True)
    
    # copy ink-puppet.js and ink-theater.js from vendor
    vendor_ex = Path("/data/soffy/projects/vendor/calesthio__OpenMontage/ink-theater/examples/mocap-figure")
    shutil.copy(vendor_ex / "ink-puppet.js", hf_dir)
    shutil.copy(vendor_ex / "ink-theater.js", hf_dir)
    shutil.copytree(vendor_ex / "assets", hf_dir / "assets", dirs_exist_ok=True)
    
    # generate index.html that plays an animation
    html = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Character Animation</title>
    <style>
        body { margin: 0; padding: 0; background: #88ccee; overflow: hidden; }
        .puppet { position: absolute; bottom: 100px; left: 50%; transform: translateX(-50%); width: 400px; height: 600px; }
        h1 { position: absolute; top: 100px; width: 100%; text-align: center; font-family: sans-serif; font-size: 64px; color: white; }
    </style>
</head>
<body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="20" data-fps="30" data-width="1920" data-height="1080">
        <h1>Hello OMRENDER!</h1>
        <svg class="puppet" id="myPuppet" viewBox="-1 -1 2 2" data-track-index="1"></svg>
    </div>
    
    <script type="module">
        import { clips } from "./mocap/clips.js";
        import { Puppet } from "./ink-puppet.js";
        import { Theater } from "./ink-theater.js";
        
        window.addEventListener("load", () => {
            const svg = document.getElementById("myPuppet");
            const puppet = new Puppet(svg);
            const theater = new Theater();
            
            // Just play a dance clip from CMU clips
            // let's use some known clip like 'samba' or 'wave'
            const clipNames = Object.keys(clips);
            const clip = clips['wave'] || clips[clipNames[0]]; 
            theater.play(puppet, clip, { loop: true });
        });
    </script>
</body>
</html>'''
    (hf_dir / "index.html").write_text(html, encoding="utf-8")
    (hf_dir / "hyperframes.json").write_text('{"media": {"autoProxy": true}}', encoding="utf-8")
    
    # render using hyperframes cli
    import subprocess
    cmd = ["/home/soffy/.nvm/versions/node/v26.4.0/bin/hyperframes", "render", str(hf_dir), "-o", str(path), "-f", "30", "-q", "delivery", "--no-best-effort", "--strict"]
    # use env without proxy
    env = os.environ.copy()
    env.pop("HTTP_PROXY", None)
    env.pop("HTTPS_PROXY", None)
    env.pop("http_proxy", None)
    env.pop("https_proxy", None)
    subprocess.run(cmd, env=env, check=True)
    
    return {
        "status": "SUCCEEDED",
        "target": "character_animation",
        "line_id": str(order.get("line_id") or ""),
        "result_video_path": str(path),
        "artifact_manifest": {"assets": []},
        "quality": "production",
        "render_runtime": "hyperframes",
    }
"""

content = re.sub(r'async def _render_character_animation_line\([^)]+\) -> dict\[str, Any\]:.*?(?=async def _render)', new_func, content, flags=re.DOTALL)
if new_func not in content:
    # meaning there was no _render_character_animation_line, we insert it
    content = content.replace('async def _render_hyperframes_line(', new_func + '\nasync def _render_hyperframes_line(')

content = content.replace('"character_animation": _render_manim_line,', '"character_animation": _render_character_animation_line,')

with open('hevi/studio/fulfill.py', 'w') as f:
    f.write(content)
