import re
with open('scripts/om_render_e2e.py', 'r') as f:
    c = f.read()

c = c.replace('import subprocess', 'import subprocess\nimport os\nenv = os.environ.copy()\nenv["PATH"] = f"/home/soffy/.local/bin:{env.get(\'PATH\', \'\')}"')
c = c.replace('subprocess.run(["ffmpeg"', 'subprocess.run(["ffmpeg"]', 1)
c = c.replace('subprocess.run(["ffmpeg"', 'subprocess.run(["ffmpeg"', 1)
c = c.replace('subprocess.run([', 'subprocess.run([')
# just replace all subprocess.run to add env=env
c = re.sub(r'subprocess\.run\((.*?)(?:,\s*check=(True|False))?\)', r'subprocess.run(\1, env=env, check=\2)', c)

with open('scripts/om_render_e2e.py', 'w') as f:
    f.write(c)
