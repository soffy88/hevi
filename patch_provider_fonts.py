import re

with open('hevi/providers/hyperframes/provider.py', 'r') as f:
    content = f.read()

replacement = """
    # 3. run story.py
    env = os.environ.copy()
    env["PATH"] = f"/home/soffy/.local/bin:{env['PATH']}"
    env.pop("HTTP_PROXY", None)
    env.pop("HTTPS_PROXY", None)
    env.pop("http_proxy", None)
    env.pop("https_proxy", None)
    env.pop("ALL_PROXY", None)
    env.pop("all_proxy", None)
    
    subprocess.run([sys.executable, "/data/soffy/projects/hevi-omrender/third_party/lanshu_explainer/tools/story.py", str(work_dir)], env=env, check=True)
    
    # 4. run sync.sh
    style = config.get("style", "v6-cinematic") if config else "v6-cinematic"
    subprocess.run(["bash", "/data/soffy/projects/hevi-omrender/third_party/lanshu_explainer/tools/sync.sh", str(work_dir), style, str(work_dir)], check=True)
    
    # run fonts.py to subset fonts
    subprocess.run([sys.executable, "/data/soffy/projects/hevi-omrender/third_party/lanshu_explainer/tools/fonts.py", str(work_dir)], env=env, check=True)
"""

content = re.sub(r'# 3\. run story\.py.*?# 4\. run sync\.sh\n.*?subprocess\.run\(\["bash".*?check=True\)', replacement.strip(), content, flags=re.DOTALL)

with open('hevi/providers/hyperframes/provider.py', 'w') as f:
    f.write(content)
