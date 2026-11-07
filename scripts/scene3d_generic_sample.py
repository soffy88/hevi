"""Render the boat/sea/islands sample (template + a local GLTF tree) to output/codevideo/threejs/."""
import json, sys
from pathlib import Path
from hevi.scene3d.generic import render_scene
from hevi.scene3d.generic.templates import load_template

REPO = Path(__file__).resolve().parents[1] if (Path(__file__).resolve().parents[1] / "hevi").is_dir() else Path("/data/soffy/projects/hevi")
out = REPO / "output" / "codevideo" / "threejs"
doc = load_template("boat_sea_islands")
doc["name"] = "boat_sea_islands_sample"
glb = REPO / "assets" / "scene3d" / "source" / "tree-01-plane-green.glb"
doc["objects"].append({"id": "gltf_tree", "type": "gltf", "src": str(glb), "fit_height": 3.2,
                       "tags": ["GLTF树", "树"], "position": [12.2, 1.5, -11.0]})
doc["prompt"]["must_have"].append("GLTF树")
out.mkdir(parents=True, exist_ok=True)
(out / "sample_scene.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
r = render_scene(doc, out, keep_frames=False)
print(json.dumps({k: v for k, v in r.items() if k != "prompt_report"}, ensure_ascii=False))
print("prompt_ok", r["prompt_report"]["ok"])
