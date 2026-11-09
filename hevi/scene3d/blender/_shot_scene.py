"""Blender-side scene: a route shot, measured and rendered headless.

blender -b --factory-startup --python _shot_scene.py -- \
    --out DIR --width 720 --height 1280 --fps 24 --seconds 2 \
    --samples 16 [--glb asset.glb] [--angles 3]

No hevi imports (Blender runs its own Python).  The script writes
``frames/``, ``measured.json`` and ``angles/angle_*.png``.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--width", type=int, default=720)
ap.add_argument("--height", type=int, default=1280)
ap.add_argument("--fps", type=int, default=24)
ap.add_argument("--seconds", type=float, default=2.0)
ap.add_argument("--samples", type=int, default=16)
ap.add_argument("--glb", default="")
ap.add_argument("--angles", type=int, default=3)
args = ap.parse_args(argv)

OUT = Path(args.out)
OUT.mkdir(parents=True, exist_ok=True)
FRAMES = max(1, round(args.seconds * args.fps))

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = args.samples
scene.cycles.use_denoising = True
scene.cycles.use_adaptive_sampling = True
scene.cycles.max_bounces = 4
scene.render.resolution_x = args.width
scene.render.resolution_y = args.height
scene.render.resolution_percentage = 100
scene.render.fps = args.fps
scene.frame_start = 1
scene.frame_end = FRAMES
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = str(OUT / "frames" / "frame_")
scene.view_settings.view_transform = "Standard"


def mat(name, color, rough=0.65, metal=0.0):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    return material


WHITE = mat("city_white", (0.93, 0.93, 0.92), 0.75)
PALE = mat("city_pale", (0.86, 0.87, 0.86), 0.8)
GREEN = mat("park", (0.55, 0.72, 0.42), 0.85)
WATER = mat("water", (0.50, 0.70, 0.86), 0.25)
BLUE = mat("route_blue", (0.02, 0.20, 0.95), 0.3)
RED = mat("pin_red", (0.86, 0.09, 0.12), 0.4)
GROUND = mat("ground", (0.82, 0.83, 0.82), 0.9)

ground = bpy.ops.mesh.primitive_plane_add(size=120, location=(0, 0, -0.06))
ground_obj = bpy.context.object
ground_obj.name = "GROUND"
ground_obj.data.materials.append(GROUND)


def add_cube(name, loc, size, material, rot_z=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.scale = (size[0] / 2, size[1] / 2, size[2] / 2)
    obj.rotation_euler[2] = rot_z
    obj.data.materials.append(material)
    return obj


add_cube("RIVER", (0, -32, 0.005), (120, 12, 0.02), WATER)
add_cube("PARK_A", (-20, 10, 0.01), (12, 10, 0.03), GREEN)
add_cube("PARK_B", (20, 4, 0.01), (10, 12, 0.03), GREEN)

PTS = [(-30.0, -24.0), (-30.0, -6.0), (-6.0, -6.0), (-6.0, 18.0), (10.0, 18.0)]
PIN = (10.0, 18.0)


def seg_dist(px, py, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    t = 0.0 if length == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


rng = random.Random(7)
count = 0
for gx in range(-4, 5):
    for gy in range(-3, 4):
        x, y = gx * 12.0, gy * 12.0
        if abs(x) < 8 and abs(y) < 8:
            continue
        if y < -20:
            continue
        if min(seg_dist(x, y, PTS[i], PTS[i + 1]) for i in range(len(PTS) - 1)) < 4.5:
            continue
        if math.hypot(x - PIN[0], y - PIN[1]) < 10.0:
            continue
        w, d = rng.uniform(5.0, 8.4), rng.uniform(5.0, 8.4)
        h = rng.uniform(2.5, 9.0) if rng.random() > 0.18 else rng.uniform(11.0, 18.0)
        add_cube(f"BLOCK_{count:02d}", (x, y, h / 2), (w, d, h),
                 WHITE if rng.random() > 0.3 else PALE,
                 rot_z=rng.choice([0, 0, 0, 0.05]))
        count += 1

curve = bpy.data.curves.new("ROUTE", type="CURVE")
curve.dimensions = "3D"
curve.resolution_u = 16
curve.bevel_depth = 0.38
spline = curve.splines.new("POLY")
spline.points.add(len(PTS) - 1)
for point, (x, y) in zip(spline.points, PTS, strict=True):
    point.co = (x, y, 0.20, 1.0)
route = bpy.data.objects.new("ROUTE", curve)
scene.collection.objects.link(route)
route.data.materials.append(BLUE)
route.data.bevel_factor_end = 0.0
route.data.keyframe_insert("bevel_factor_end", frame=1)
route.data.bevel_factor_end = 1.0
route.data.keyframe_insert("bevel_factor_end", frame=max(2, int(FRAMES * 0.55)))

bpy.ops.mesh.primitive_uv_sphere_add(radius=1.15, segments=24, ring_count=12,
                                    location=(PIN[0], PIN[1], 3.4))
ball = bpy.context.object
ball.name = "PIN_BALL"
ball.data.materials.append(RED)
bpy.ops.mesh.primitive_cone_add(vertices=24, radius1=0.75, radius2=0.02, depth=2.4,
                                location=(PIN[0], PIN[1], 1.55))
cone = bpy.context.object
cone.name = "PIN_CONE"
cone.data.materials.append(RED)
for obj in (ball, cone):
    obj.location.z += 8.0
    obj.keyframe_insert("location", frame=max(1, int(FRAMES * 0.5)))
    obj.location.z -= 10.4
    obj.keyframe_insert("location", frame=max(2, int(FRAMES * 0.62)))

if args.glb:
    try:
        bpy.ops.import_scene.gltf(filepath=args.glb)
        imported = [o for o in bpy.context.selected_objects if o.type == "MESH"]
        for obj in imported:
            obj.name = "ASSET_" + obj.name
            obj.location = (PIN[0] + 2.6, PIN[1] - 1.2, obj.location.z)
            obj.rotation_euler[2] = math.radians(28)
        bpy.context.view_layer.update()
        if imported:
            low = min((obj.matrix_world @ Vector(c)).z for obj in imported for c in obj.bound_box)
            for obj in imported:
                obj.location.z -= low
    except Exception as exc:  # recorded, never silently ignored
        (OUT / "glb_import_error.txt").write_text(str(exc), encoding="utf-8")


def make_camera(name, location, look_at=(0, 0, 0)):
    bpy.ops.object.camera_add(location=location)
    cam = bpy.context.object
    cam.name = name
    target = bpy.data.objects.new(name + "_TARGET", None)
    scene.collection.objects.link(target)
    target.location = look_at
    constraint = cam.constraints.new("TRACK_TO")
    constraint.target = target
    constraint.track_axis = "TRACK_NEGATIVE_Z"
    constraint.up_axis = "UP_Y"
    cam.data.lens = 35
    return cam


main_cam = make_camera("CAMERA", (-34, -46, 26), (0, 0, 0))
scene.camera = main_cam

light_data = bpy.data.lights.new("SUN", type="SUN")
light_data.energy = 3.0
light = bpy.data.objects.new("SUN", light_data)
scene.collection.objects.link(light)
light.rotation_euler = (math.radians(38), math.radians(12), math.radians(-35))
world = scene.world or bpy.data.worlds.new("World")
scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes.get("Background")
bg.inputs[0].default_value = (0.86, 0.90, 0.95, 1)
bg.inputs[1].default_value = 0.6

# Render the animation.
bpy.ops.render.render(animation=True)

# Multi-angle stills (low-cost, for the node self-check contact sheet).
angles_dir = OUT / "angles"
angles_dir.mkdir(parents=True, exist_ok=True)
scene.render.image_settings.file_format = "PNG"
scene.render.resolution_percentage = 45
scene.cycles.samples = min(8, args.samples)
mid = max(1, FRAMES // 2)
scene.frame_set(mid)
spots = [
    ((10, -10, 6), (0, 0, 2)),
    ((40, -40, 40), (0, 0, 0)),
    ((0, 55, 28), (0, 0, 0)),
]
stills = []
for index, (loc, look) in enumerate(spots[: max(0, args.angles)]):
    cam = make_camera(f"ANGLE_{index}", loc, look)
    scene.camera = cam
    path = angles_dir / f"angle_{index + 1}.png"
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    stills.append(str(path))
scene.camera = main_cam
scene.render.resolution_percentage = 100

# Measure what is actually in the scene.
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
tris = 0
zero_area = []
non_manifold = {}
for obj in meshes:
    me = obj.data
    me.calc_loop_triangles()
    tris += len(me.loop_triangles)
    if any(poly.area < 1e-9 for poly in me.polygons):
        zero_area.append(obj.name)
    bm = bmesh.new()
    bm.from_mesh(me)
    edges = sum(1 for edge in bm.edges if not edge.is_manifold)
    bm.free()
    if edges:
        non_manifold[obj.name] = edges
corners = [obj.matrix_world @ Vector(c) for obj in meshes for c in obj.bound_box]
mn = [min(v[i] for v in corners) for i in range(3)] if corners else [0, 0, 0]
mx = [max(v[i] for v in corners) for i in range(3)] if corners else [0, 0, 0]
residual = [o.name for o in bpy.data.objects if o.name in {"Cube", "Sphere", "Camera.001"}]
measured = {
    "blender": bpy.app.version_string,
    "engine": scene.render.engine,
    "resolution": [scene.render.resolution_x, scene.render.resolution_y],
    "fps": scene.render.fps,
    "frame_range": [scene.frame_start, scene.frame_end],
    "duration_s": round((scene.frame_end - scene.frame_start + 1) / scene.render.fps, 3),
    "objects": len(bpy.data.objects),
    "mesh_objects": len(meshes),
    "triangles": tris,
    "bbox_min_m": [round(v, 4) for v in mn],
    "bbox_max_m": [round(v, 4) for v in mx],
    "bbox_size_m": [round(mx[i] - mn[i], 4) for i in range(3)],
    "origin": [0.0, 0.0, 0.0],
    "zero_area_objects": zero_area,
    "non_manifold": non_manifold,
    "no_material_objects": [o.name for o in meshes if not o.data.materials],
    "duplicate_suffix_objects": [o.name for o in bpy.data.objects if ".001" in o.name],
    "residual_objects": residual,
    "materials": len(bpy.data.materials),
    "angles": stills,
}
(OUT / "measured.json").write_text(json.dumps(measured, ensure_ascii=False, indent=2), encoding="utf-8")
print("SCENE_JSON " + json.dumps(measured, ensure_ascii=False))
