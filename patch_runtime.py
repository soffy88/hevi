import re
with open('hevi/studio/runtime.py', 'r') as f:
    content = f.read()

content = content.replace('RUNTIMES = ("remotion", "hyperframes", "manim", "ffmpeg")', 'RUNTIMES = ("remotion", "hyperframes", "hyperframes_styled", "manim", "ffmpeg")')
content = content.replace('_HYPER_HINTS = (', '_STYLED_HINTS = ("style", "explainer", "风格", "讲解")\n_HYPER_HINTS = (')

new_sel = """    if any(h in blob for h in _STYLED_HINTS):
        return {"runtime": "hyperframes_styled", "locked": False, "reason": "intent.styled"}
    if any(h in blob for h in _HYPER_HINTS):"""
content = content.replace('    if any(h in blob for h in _HYPER_HINTS):', new_sel)

with open('hevi/studio/runtime.py', 'w') as f:
    f.write(content)
