import re
with open('hevi/creative/layer4/blender_workflow.py', 'r') as f:
    c = f.read()

# fix the broken string literal
c = c.replace('"bpy.context.scene.render.engine = "CYCLES"\\nbpy.context.scene.cycles.device = "CPU"\\nbpy.context.scene.cycles.samples = 16\\ncam = bpy.data.objects.new',
              '"bpy.context.scene.render.engine = \'CYCLES\'",\n        "bpy.context.scene.cycles.device = \'CPU\'",\n        "bpy.context.scene.cycles.samples = 16",\n        "cam = bpy.data.objects.new')
with open('hevi/creative/layer4/blender_workflow.py', 'w') as f:
    f.write(c)
