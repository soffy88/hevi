with open('hevi/studio/fulfill.py', 'r') as f:
    c = f.read()
c = c.replace('env.pop("https_proxy", None)', 'env.pop("https_proxy", None)\n    env["PATH"] = f"/home/soffy/.local/bin:{env[\'PATH\']}"')
with open('hevi/studio/fulfill.py', 'w') as f:
    f.write(c)
