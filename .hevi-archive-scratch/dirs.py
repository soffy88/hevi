import os, collections

BASE = "/data/soffy/projects/hevi"
src = "/data/soffy/projects/hevi/.veya/worktrees/task-remote-f6a5c69f516233eb7e20/.hevi-archive-scratch/all_videos.txt"

counts = collections.Counter()
bytes_ = collections.Counter()

def topdir(p, depth):
    rel = os.path.relpath(p, BASE)
    parts = rel.split(os.sep)
    return os.sep.join(parts[:depth])

for line in open(src, encoding="utf-8", errors="replace"):
    parts = line.split(None, 2)
    if len(parts) < 3:
        continue
    sz, mt, path = parts[0], parts[1], parts[2].strip()
    if sz == "0" and not path:
        continue
    try:
        size = int(sz) if sz.lstrip("-").isdigit() else int(mt)
    except ValueError:
        continue
    d = topdir(path, 3)
    counts[d] += 1
    bytes_[d] += size

print(f"{'files':>6} {'bytes':>15}  dir(3)")
for d in sorted(bytes_, key=lambda x: -bytes_[x]):
    print(f"{counts[d]:>6} {bytes_[d]:>15}  {d}")

print()
print("TOTAL files:", sum(counts.values()), "TOTAL bytes:", sum(bytes_.values()))
