import re

with open('hevi/studio/fulfill.py', 'r') as f:
    content = f.read()

html = '''<!doctype html>
<html lang="en" data-resolution="landscape">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1920, height=1080" />
    <script src="../../../../hevi/providers/hyperframes/lanshu_assets/node_modules/gsap/dist/gsap.min.js"></script>
    <script src="ink-theater.js"></script>
    <script src="ink-puppet.js"></script>
    <script src="clips.js"></script>
    <style>
      * { margin: 0; padding: 0; box-sizing: border-box; }
      @font-face { font-family: "InkHand"; src: url("assets/patrickhand.ttf") format("truetype"); font-display: block; }
      html, body { width: 1920px; height: 1080px; overflow: hidden; background: #fcfbf8; }
      #root { position: relative; width: 1920px; height: 1080px; overflow: hidden; }
      .stage { position: absolute; inset: 0; background: #fcfbf8; }
      .stage svg { position: absolute; inset: 0; display: block; width: 1920px; height: 1080px; }
      .cap { position: absolute; left: 0; width: 1920px; text-align: center; font-family: "InkHand", cursive; opacity: 0; }
      #opening { top: 200px; font-size: 66px; color: #333; }
      #action { top: 210px; font-size: 92px; color: #333; }
      #credit { bottom: 70px; font-size: 40px; color: #8a857a; }
      #endcap { top: 205px; font-size: 70px; color: #333; }
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="21" data-width="1920" data-height="1080">
      <section id="scene" class="clip" data-start="0" data-duration="21" data-track-index="1">
        <div class="stage">
          <svg viewBox="0 0 1920 1080" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <filter id="boil" x="-20%" y="-20%" width="140%" height="140%">
                <feTurbulence id="boilTurb" type="fractalNoise" baseFrequency="0.013" numOctaves="1" seed="1" result="n"/>
                <feDisplacementMap in="SourceGraphic" in2="n" scale="2.8"/>
              </filter>
            </defs>
            <path id="ground" d="" fill="none" stroke="#c3bdb0" stroke-width="3" stroke-linecap="round" opacity="0"/>
            <g id="mount"></g>
          </svg>
          <div id="opening" class="cap">watch a line become a character</div>
          <div id="action" class="cap">wave</div>
          <div id="endcap" class="cap">real motion capture &middot; zero hand-tuning</div>
          <div id="credit" class="cap">ink&nbsp;puppet &middot; the agent just chooses the moves</div>
        </div>
      </section>
    </div>

    <script>
      window.__timelines = window.__timelines || {};
      if (document.fonts && document.fonts.load) { document.fonts.load("90px InkHand"); }
      var tl = gsap.timeline({ paused: true });
      var GROUND = 902, CX = 960;

      document.getElementById("ground").setAttribute("d",
        window.InkTheater.inkPath([[640, GROUND], [960, GROUND + 4], [1280, GROUND]], { wobble: 1.6, step: 60 }));

      var pup = window.InkPuppet.create(document.getElementById("mount"), { cx: CX, ground: GROUND, boil: "boil", headR: 48, strokeWidth: 6 });

      // 1) the pencil draws the figure
      pup.drawIn(tl, { start: 0.4, each: 0.5 });
      tl.fromTo("#ground", { opacity: 0 }, { opacity: 1, duration: 0.6 }, 2.4);
      tl.fromTo("#opening", { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: 0.6 }, 1.0);
      tl.to("#opening", { opacity: 0, duration: 0.4 }, 3.2);

      // 2) it comes alive and performs — real mocap, chosen by name
      var segs = [
        { clip: "walk", dur: 2.6, label: "it walks" },
        { clip: "run", dur: 2.6, label: "it runs" },
        { clip: "dance_spin", dur: 3.4, label: "it dances" },
        { clip: "kick", dur: 2.6, label: "it kicks" },
        { clip: "sit", dur: 3.4, label: "it sits" },
        { clip: "wave", dur: 2.6, label: "it waves" }
      ];
      window.InkPuppet.choreograph(tl, pup, segs, { start: 3.7 });

      // action labels (one HTML div per move) + persistent credit
      tl.fromTo("#credit", { opacity: 0 }, { opacity: 1, duration: 0.6 }, 3.7);
      var stage = document.querySelector(".stage");
      var t = 3.7;
      segs.forEach(function (s) {
        var d = document.createElement("div");
        d.className = "cap"; d.textContent = s.label;
        d.style.top = "208px"; d.style.fontSize = "94px"; d.style.color = "#333";
        stage.appendChild(d);
        tl.fromTo(d, { opacity: 0 }, { opacity: 1, duration: 0.4 }, t + 0.2);
        tl.to(d, { opacity: 0, duration: 0.35 }, t + s.dur - 0.4);
        t += s.dur;
      });

      // 3) close
      tl.to("#credit", { opacity: 0, duration: 0.4 }, t + 0.1);
      tl.fromTo("#endcap", { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: 0.7 }, t + 0.2);

      window.InkTheater.boil(document.getElementById("boilTurb"), tl, { duration: 21, fps: 10 });
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>'''

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
    import os
    import subprocess
    
    vendor_ex = Path("/data/soffy/projects/vendor/calesthio__OpenMontage/ink-theater/examples/mocap-figure")
    shutil.copy(vendor_ex / "ink-puppet.js", hf_dir)
    shutil.copy(vendor_ex / "ink-theater.js", hf_dir)
    shutil.copy(vendor_ex / "clips.js", hf_dir)
    shutil.copytree(vendor_ex / "assets", hf_dir / "assets", dirs_exist_ok=True)
    
    # Write the html
    html = \"\"\"""" + html + """\"\"\"
    (hf_dir / "index.html").write_text(html, encoding="utf-8")
    (hf_dir / "hyperframes.json").write_text('{"media": {"autoProxy": true}}', encoding="utf-8")
    
    # render using hyperframes cli
    cmd = ["/home/soffy/.nvm/versions/node/v26.4.0/bin/hyperframes", "render", str(hf_dir), "-o", str(path), "-f", "30", "-q", "delivery", "--no-best-effort", "--strict"]
    env = os.environ.copy()
    env.pop("HTTP_PROXY", None)
    env.pop("HTTPS_PROXY", None)
    env.pop("http_proxy", None)
    env.pop("https_proxy", None)
    env["PATH"] = f"/home/soffy/.local/bin:{env['PATH']}"
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

with open('hevi/studio/fulfill.py', 'w') as f:
    f.write(content)
