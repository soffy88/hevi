"""Runs INSIDE Blender:  blender -b --factory-startup --python bpy_runtime.py -- ops.json result.json
Executes a validated JSON op list. No hevi imports (Blender's Python)."""
import json
import math
import os
import sys
import time
import traceback

import bpy
from mathutils import Vector

RES = {"ok": True, "outputs": [], "objects": [], "timings": {}, "log": []}


def obj(name):
    o = bpy.data.objects.get(name)
    if o is None:
        raise KeyError(f"object {name!r} not found; have {[x.name for x in bpy.data.objects]}")
    return o


def look_at(o, target):
    d = Vector(target) - o.location
    o.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def deg(v):
    return [math.radians(x) for x in v]


def clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.lights, bpy.data.cameras, bpy.data.curves):
        for b in list(coll):
            coll.remove(b)


def op_scene(o):
    sc = bpy.context.scene
    if "engine" in o:
        eng = o["engine"]
        if eng == "BLENDER_EEVEE_NEXT" and bpy.app.version < (4, 2, 0):
            eng = "BLENDER_EEVEE"
        sc.render.engine = eng
    if sc.render.engine == "CYCLES":
        sc.cycles.device = "CPU"
        sc.cycles.samples = int(o.get("samples", sc.cycles.samples))
        sc.cycles.use_denoising = bool(o.get("denoise", True))
        for attr, val in (("denoiser", "OPENIMAGEDENOISE"), ("denoising_prefilter", o.get("denoise_prefilter", "FAST")),
                          ("denoising_quality", o.get("denoise_quality", "FAST")), ("denoising_input_passes", "RGB_ALBEDO")):
            try:
                setattr(sc.cycles, attr, val)
            except Exception:
                pass
        sc.cycles.adaptive_threshold = float(o.get("adaptive_threshold", 0.05))
        sc.cycles.use_light_tree = False
        sc.cycles.caustics_reflective = sc.cycles.caustics_refractive = False
        sc.render.use_persistent_data = True
        sc.cycles.use_adaptive_sampling = True
        sc.cycles.max_bounces = int(o.get("bounces", 4))
        sc.render.threads_mode = "AUTO"
    elif sc.render.engine.startswith("BLENDER_EEVEE"):
        sc.eevee.taa_render_samples = int(o.get("samples", 16))
        for attr in ("use_shadows", "use_gtao", "use_raytracing"):
            if hasattr(sc.eevee, attr) and attr != "use_raytracing":
                setattr(sc.eevee, attr, True)
    elif sc.render.engine == "BLENDER_WORKBENCH":
        sc.display.shading.light = "STUDIO"
        sc.display.shading.color_type = "MATERIAL"
        sc.display.shading.show_shadows = True
        sc.display.shading.background_type = "WORLD"
    if "resolution" in o:
        sc.render.resolution_x, sc.render.resolution_y = o["resolution"]
        sc.render.resolution_percentage = 100
    if "fps" in o:
        sc.render.fps = int(o["fps"])
    if "frame_start" in o:
        sc.frame_start = int(o["frame_start"])
    if "frame_end" in o:
        sc.frame_end = int(o["frame_end"])
    sc.view_settings.view_transform = o.get("view_transform", "Standard")
    if "background" in o:
        w = sc.world or bpy.data.worlds.new("World")
        sc.world = w
        w.use_nodes = True
        bg = w.node_tree.nodes.get("Background")
        bg.inputs[0].default_value = (*o["background"], 1)
        bg.inputs[1].default_value = float(o.get("background_strength", 1.0))
        w.color = o["background"]  # workbench uses world colour


def op_add(o):
    t = o["type"]
    loc = o.get("location", [0, 0, 0])
    r = float(o.get("radius", o.get("size", 1.0)))
    seg = int(o.get("segments", 32))
    A = bpy.ops.mesh
    if t == "sphere":
        A.primitive_uv_sphere_add(radius=r, segments=seg, ring_count=max(8, seg // 2), location=loc)
    elif t == "cube":
        A.primitive_cube_add(size=2 * r, location=loc)
        if o.get("bevel", 0.08):
            m = bpy.context.object.modifiers.new("Bevel", "BEVEL")
            m.width = float(o.get("bevel", 0.08)) * r
            m.segments = 3
    elif t == "cylinder":
        A.primitive_cylinder_add(radius=r, depth=float(o.get("depth", 2 * r)), vertices=seg, location=loc)
    elif t == "cone":
        A.primitive_cone_add(radius1=r, depth=float(o.get("depth", 2 * r)), vertices=seg, location=loc)
    elif t == "torus":
        A.primitive_torus_add(major_radius=r, minor_radius=float(o.get("minor_radius", r * 0.3)), location=loc)
    elif t == "plane":
        A.primitive_plane_add(size=2 * r, location=loc)
    elif t == "text":
        bpy.ops.object.text_add(location=loc)
        tx = bpy.context.object
        tx.data.body = str(o["text"])
        tx.data.size = r
        tx.data.extrude = float(o.get("extrude", 0.08 * r))
        tx.data.bevel_depth = float(o.get("bevel", 0.02 * r))
        tx.data.align_x = "CENTER"
        tx.data.align_y = "CENTER"
        if o.get("font") and os.path.exists(o["font"]):
            tx.data.font = bpy.data.fonts.load(o["font"])
    elif t == "import":
        p = os.path.expanduser(o["path"])
        before = set(bpy.data.objects)
        ext = os.path.splitext(p)[1].lower()
        if ext == ".obj":
            bpy.ops.wm.obj_import(filepath=p)
        elif ext in (".glb", ".gltf"):
            bpy.ops.import_scene.gltf(filepath=p)
        elif ext == ".fbx":
            bpy.ops.import_scene.fbx(filepath=p)
        elif ext == ".stl":
            bpy.ops.wm.stl_import(filepath=p)
        elif ext == ".ply":
            bpy.ops.wm.ply_import(filepath=p)
        new = [x for x in bpy.data.objects if x not in before]
        if not new:
            raise RuntimeError(f"import produced no objects: {p}")
        root = bpy.data.objects.new(o["name"], None)
        bpy.context.collection.objects.link(root)
        for x in new:
            if x.parent is None:
                x.parent = root
        root.location = loc
        if "rotation" in o:
            root.rotation_euler = deg(o["rotation"])
        if "scale" in o:
            root.scale = o["scale"]
        RES["log"].append(f"imported {len(new)} objects as {o['name']}")
        return
    ob = bpy.context.object
    ob.name = o["name"]
    if t in ("sphere", "cylinder", "cone", "torus") and o.get("smooth", True):
        bpy.ops.object.shade_smooth()
    if "rotation" in o:
        ob.rotation_euler = deg(o["rotation"])
    if "scale" in o:
        ob.scale = o["scale"]


def clay_material(name, rgb, rough):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = 0.0
    for k in ("Specular IOR Level", "Specular"):
        if k in b.inputs:
            b.inputs[k].default_value = 0.25
    m.diffuse_color = (*rgb, 1)  # workbench
    return m


def op_material(o):
    target = obj(o["target"])
    m = clay_material(o.get("name", f"clay_{o['target']}"), o["color"], float(o["roughness"]))
    targets = [target] + [c for c in target.children_recursive]
    n = 0
    for x in targets:
        if x.type in ("MESH", "FONT", "CURVE"):
            x.data.materials.clear()
            x.data.materials.append(m)
            n += 1
    if not n:
        raise RuntimeError(f"{o['target']} has no mesh to colour")


def op_light(o):
    ld = bpy.data.lights.new(o["name"], o["type"])
    ld.energy = float(o.get("energy", 500 if o["type"] in ("AREA", "POINT", "SPOT") else 2))
    if "color" in o:
        ld.color = o["color"]
    if o["type"] == "AREA":
        ld.size = float(o.get("size", 3))
    if hasattr(ld, "shadow_soft_size") and "soft" in o:
        ld.shadow_soft_size = float(o["soft"])
    lo = bpy.data.objects.get(o["name"])
    if lo is None:
        lo = bpy.data.objects.new(o["name"], ld)
        bpy.context.collection.objects.link(lo)
    else:
        lo.data = ld
    lo.location = o.get("location", [0, 0, 5])
    if "target" in o:
        look_at(lo, o["target"])
    elif "rotation" in o:
        lo.rotation_euler = deg(o["rotation"])


def op_camera(o):
    sc = bpy.context.scene
    cam = sc.camera
    if cam is None:
        cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
        bpy.context.collection.objects.link(cam)
        sc.camera = cam
    if "location" in o:
        cam.location = o["location"]
    cam.data.lens = float(o.get("lens", cam.data.lens))
    if "target" in o:
        look_at(cam, o["target"])
    elif "rotation" in o:
        cam.rotation_euler = deg(o["rotation"])
    if "frame" in o:  # camera move keyframe
        cam.keyframe_insert("location", frame=int(o["frame"]))
        cam.keyframe_insert("rotation_euler", frame=int(o["frame"]))


def op_keyframe(o):
    t = bpy.context.scene.camera if o["target"] == "Camera" else obj(o["target"])
    f = o["frame"]
    if "location" in o:
        t.location = o["location"]
        t.keyframe_insert("location", frame=f)
    if "rotation" in o:
        t.rotation_euler = deg(o["rotation"])
        t.keyframe_insert("rotation_euler", frame=f)
    if "scale" in o:
        t.scale = o["scale"]
        t.keyframe_insert("scale", frame=f)
    if t.animation_data and t.animation_data.action:
        interp = o.get("interpolation", "BEZIER")
        for fc in t.animation_data.action.fcurves:
            for kp in fc.keyframe_points:
                if int(kp.co[0]) == f:
                    kp.interpolation = interp


def op_delete(o):
    bpy.data.objects.remove(obj(o["target"]), do_unlink=True)


def _ensure_camera():
    if bpy.context.scene.camera is None:
        op_camera({"location": [0, -7, 3], "target": [0, 0, 0.8], "lens": 40})


def op_render_frame(o):
    _ensure_camera()
    sc = bpy.context.scene
    sc.frame_set(o["frame"])
    sc.render.image_settings.file_format = "PNG"
    sc.render.filepath = os.path.abspath(o["out"])
    t = time.time()
    bpy.ops.render.render(write_still=True)
    dt = time.time() - t
    RES["outputs"].append({"kind": "frame", "path": sc.render.filepath, "frame": o["frame"], "seconds": round(dt, 3)})


def op_render_animation(o):
    _ensure_camera()
    sc = bpy.context.scene
    out = os.path.abspath(o["out"])
    if out.lower().endswith(".mp4"):
        sc.render.image_settings.file_format = "FFMPEG"
        sc.render.ffmpeg.format = "MPEG4"
        sc.render.ffmpeg.codec = "H264"
        sc.render.ffmpeg.constant_rate_factor = "MEDIUM"
        sc.render.filepath = out
    else:  # png sequence directory
        os.makedirs(out, exist_ok=True)
        sc.render.image_settings.file_format = "PNG"
        sc.render.filepath = os.path.join(out, "frame_")
    sc.render.use_file_extension = not out.lower().endswith(".mp4")
    t = time.time()
    bpy.ops.render.render(animation=True)
    dt = time.time() - t
    nf = sc.frame_end - sc.frame_start + 1
    vid_s = nf / sc.render.fps
    RES["outputs"].append({"kind": "animation", "path": out, "frames": nf, "fps": sc.render.fps,
                           "engine": sc.render.engine, "seconds": round(dt, 2),
                           "sec_per_video_sec": round(dt / vid_s, 2),
                           "resolution": [sc.render.resolution_x, sc.render.resolution_y]})


def op_info(o):
    sc = bpy.context.scene
    RES["scene"] = {"engine": sc.render.engine, "frames": [sc.frame_start, sc.frame_end], "fps": sc.render.fps,
                    "resolution": [sc.render.resolution_x, sc.render.resolution_y]}


def op_save_blend(o):
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(o["out"]))
    RES["outputs"].append({"kind": "blend", "path": os.path.abspath(o["out"])})


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    ops_path, res_path = argv[0], argv[1]
    ops = json.load(open(ops_path))
    clear()
    bpy.context.scene.render.engine = "BLENDER_EEVEE_NEXT" if bpy.app.version >= (4, 2, 0) else "BLENDER_EEVEE"
    t0 = time.time()
    for i, o in enumerate(ops):
        try:
            globals()["op_" + o["op"]](o)
        except Exception as e:
            RES["ok"] = False
            RES["error"] = {"index": i, "op": o, "message": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}
            break
    RES["timings"]["total"] = round(time.time() - t0, 3)
    RES["objects"] = [{"name": x.name, "type": x.type, "location": [round(v, 3) for v in x.location]} for x in bpy.data.objects]
    RES["blender"] = bpy.app.version_string
    with open(res_path, "w") as f:
        json.dump(RES, f, indent=1)


main()
