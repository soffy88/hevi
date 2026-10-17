import subprocess
import re

def run_cmd(cmd):
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return res.returncode, res.stdout.strip(), res.stderr.strip()

# Read MERGE_PLAN.md
with open("MERGE_PLAN.md", "r", encoding="utf-8") as f:
    content = f.read()

lines = content.splitlines()
branch_rows = []
for line in lines:
    if line.startswith("| `"):
        parts = [p.strip() for p in line.split("|")]
        # parts[1] is `branch_name`
        bname = parts[1].strip("`")
        status = parts[5]
        branch_rows.append((bname, status))

print(f"Total branches to process: {len(branch_rows)}")
for bname, status in branch_rows:
    print(f"Branch: {bname}, Status: {status}")
