#!/usr/bin/env python3
"""Replace byte-identical files under the given roots with hard links.

Used when flattening an image: several Python environments carry identical
copies of the same wheels (e.g. the same CPU torch in four venvs). Hard links
inside one layer are stored once, and the files read exactly the same, so
nothing changes for the code that imports them. Only regular files with the
same size, mode, uid and gid are linked.
Usage: dedup-hardlink.py ROOT [ROOT ...]
"""
import hashlib, os, sys
from collections import defaultdict

MIN = 4096
by_key = defaultdict(list)
for root in sys.argv[1:]:
    for dp, dns, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if not os.path.isfile(p) or os.path.islink(p) or st.st_size < MIN:
                continue
            by_key[(st.st_size, st.st_mode, st.st_uid, st.st_gid)].append((p, st.st_dev, st.st_ino))

def digest(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.digest()

saved = linked = 0
for key, files in by_key.items():
    if len(files) < 2:
        continue
    by_hash = defaultdict(list)
    seen = set()
    for p, dev, ino in files:
        if (dev, ino) in seen:
            continue
        seen.add((dev, ino))
        by_hash[digest(p)].append((p, dev))
    for group in by_hash.values():
        if len(group) < 2:
            continue
        src, sdev = group[0]
        for p, dev in group[1:]:
            if dev != sdev:
                continue
            tmp = p + '.dedup-tmp'
            os.link(src, tmp)
            os.replace(tmp, p)
            saved += key[0]; linked += 1
print(f"dedup: linked {linked} files, saved {saved/1e9:.2f} GB")
