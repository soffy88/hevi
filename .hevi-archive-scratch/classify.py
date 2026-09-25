import os, re, json

BASE = "/data/soffy/projects/hevi"
TSV = "/data/soffy/projects/hevi/.veya/worktrees/task-remote-f6a5c69f516233eb7e20/.hevi-archive-scratch/videos.tsv"

EXCLUDE_DIR_PARTS = [
    "/.git/", "/.veya/worktrees/", "/node_modules/", "/third_party/", "/.venv",
    "/segs/", "/shots/", "/clips/", "/cache", "/.cache", "/smoke", "/test/",
    "/tests/", "/test_", "_test/", "/fixtures/", "/fixture", "/diagnostic",
    "/qualification/", "/.pytest_cache/", "/docs/ref-repos/",
]

rows = []
for line in open(TSV, encoding="utf-8", errors="replace"):
    p = line.rstrip("\n").split("\t")
    if len(p) != 3:
        continue
    sz, mt, path = int(p[0]), int(p[1]), p[2]
    rows.append((sz, mt, path))

def classify(path):
    low = "/" + os.path.relpath(path, BASE).lower() + "/"
    name = os.path.basename(path).lower()
    reasons = []
    for part in EXCLUDE_DIR_PARTS:
        if part in low:
            reasons.append(part)
    is_final_named = bool(re.search(r"(^|[/_-])(final|deliver|delivery|master|export)([-_]|\.|$)", name)) \
        or name.endswith("_final.mp4") or name.endswith("-final.mp4") or name == "final.mp4"
    return reasons, is_final_named

out = []
for sz, mt, path in rows:
    reasons, is_final = classify(path)
    out.append({"size": sz, "path": path, "excluded_dirs": reasons, "final_named": is_final})

print("=== FINAL-NAMED files that are NOT in excluded dirs ===")
cand = [o for o in out if o["final_named"] and not o["excluded_dirs"]]
for o in sorted(cand, key=lambda x: -x["size"]):
    print(f'{o["size"]:>12}  {os.path.relpath(o["path"], BASE)}')
print(f"\ncount={len(cand)}  bytes={sum(o['size'] for o in cand)}")

print("\n=== FINAL-NAMED files that ARE in excluded dirs (sample) ===")
exc = [o for o in out if o["final_named"] and o["excluded_dirs"]]
print(f"count={len(exc)} bytes={sum(o['size'] for o in exc)}")
for o in sorted(exc, key=lambda x: -x["size"])[:25]:
    print(f'{o["size"]:>12}  [{",".join(o["excluded_dirs"])}]  {os.path.relpath(o["path"], BASE)}')
