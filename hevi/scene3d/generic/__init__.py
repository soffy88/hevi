"""Generic data-driven Three.js scene line (3O layout).

* ``camera_path`` (oskill) - pure CatmullRom camera path baking (pos/look/fov/roll per frame)
* ``spec``        (oskill) - scene JSON schema, normalisation, prompt 3-part gate
* ``html``        (oskill) - scene JSON + baked camera -> self-contained Three.js page
* ``browser_render`` (obase) - Playwright/SwiftShader deterministic frame capture + ffmpeg
* ``templates``   (oskill) - presets are just template JSON for this interface
* ``pipeline``    (omodul) - load -> validate -> bake -> render -> verify
"""
from .camera_path import CatmullRom3, bake_camera, sample_camera
from .spec import SceneError, normalize_scene, check_prompt, load_scene_json
from .templates import list_templates, expand_template
from .pipeline import render_scene

__all__ = [
    "CatmullRom3", "bake_camera", "sample_camera", "SceneError", "normalize_scene",
    "check_prompt", "load_scene_json", "list_templates", "expand_template", "render_scene",
]
