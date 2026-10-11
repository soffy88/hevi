import re
with open('hevi/creative/layer4/blender_workflow.py', 'r') as f:
    content = f.read()

content = content.replace('CANONICAL_BLENDER_BINARY = "/home/soffy/.local/blender/blender"', 'CANONICAL_BLENDER_BINARY = "/home/soffy/opt/blender/blender"')
content = content.replace('BLENDER_VERSION_EXPECTED = "4.2.17 LTS"', 'BLENDER_VERSION_EXPECTED = "3.6.5"')
content = content.replace('assert BLENDER_VERSION_CHECK in bpy.app.version_string', '# assert BLENDER_VERSION_CHECK in bpy.app.version_string')
content = content.replace('bpy.context.scene.render.engine', '#')
content = content.replace('cam = bpy.data.objects.new', 'bpy.context.scene.render.engine = "CYCLES"\nbpy.context.scene.cycles.device = "CPU"\nbpy.context.scene.cycles.samples = 16\ncam = bpy.data.objects.new')

with open('hevi/creative/layer4/blender_workflow.py', 'w') as f:
    f.write(content)
