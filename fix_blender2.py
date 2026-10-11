import re
with open('hevi/creative/layer4/blender_workflow.py', 'r') as f:
    c = f.read()

# find and replace using regex
c = re.sub(r'"bpy\.context\.scene\.render\.engine = "CYCLES"\nbpy\.context\.scene\.cycles\.device = "CPU"\nbpy\.context\.scene\.cycles\.samples = 16\ncam = bpy\.data\.objects\.new\(\'Camera\', bpy\.data\.cameras\.new\(\'Cam\'\)\)",',
           '"bpy.context.scene.render.engine = \'CYCLES\'",\n        "bpy.context.scene.cycles.device = \'CPU\'",\n        "bpy.context.scene.cycles.samples = 16",\n        "cam = bpy.data.objects.new(\'Camera\', bpy.data.cameras.new(\'Cam\'))",', c)

with open('hevi/creative/layer4/blender_workflow.py', 'w') as f:
    f.write(c)
