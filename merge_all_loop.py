import subprocess

def run_cmd(cmd):
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return res.returncode, res.stdout.strip(), res.stderr.strip()

with open("MERGE_PLAN.md", "r", encoding="utf-8") as f:
    content = f.read()

lines = content.splitlines()
header_lines = []
branch_rows = []

for line in lines:
    if line.startswith("| `"):
        parts = [p.strip() for p in line.split("|")]
        bname = parts[1].strip("`")
        branch_rows.append((line, bname, parts))
    else:
        header_lines.append(line)

print(f"Total branches: {len(branch_rows)}")

def write_plan(current_rows):
    # current_rows is list of full markdown table rows
    plan_lines = header_lines[:5] + [
        "| 分支名 | 最近提交时间 | 分叉提交数 | 改动文件数 | 状态 | 备注 |",
        "|---|---|---|---|---|---|"
    ] + current_rows
    with open("MERGE_PLAN.md", "w", encoding="utf-8") as f:
        f.write("\n".join(plan_lines) + "\n")

processed_table_rows = []

for i, (orig_line, bname, parts) in enumerate(branch_rows):
    total_len = len(branch_rows)
    print(f"\n[{i+1}/{total_len}] Processing branch: {bname}")
    
    # Check if ancestor
    rc, out, err = run_cmd(f"git merge-base --is-ancestor {bname} HEAD")
    if rc == 0:
        print(f"-> Already ancestor / up to date.")
        parts[5] = "MERGED"
        parts[6] = "Already ancestor"
        row_str = " | ".join(parts)
        processed_table_rows.append(row_str)
        continue

    # Try merge --no-ff
    rc, out, err = run_cmd(f"git merge --no-ff {bname} -m 'merge: merge branch {bname} into integration/mergeall-1017'")
    if rc == 0:
        print(f"-> Merged successfully.")
        parts[5] = "MERGED"
        parts[6] = "Clean merge"
        row_str = " | ".join(parts)
        processed_table_rows.append(row_str)
        
        # Commit plan and changes
        write_plan(processed_table_rows + [r[0] for r in branch_rows[i+1:]])
        run_cmd("git add . && git commit -m 'merge: integrate " + bname + "'")
    else:
        print(f"-> Merge conflict/error:\n{err or out}")
        run_cmd("git merge --abort")
        parts[5] = "SKIPPED"
        note_text = (err or out).replace('\n', ' ')[:60]
        parts[6] = f"Conflict: {note_text}"
        row_str = " | ".join(parts)
        processed_table_rows.append(row_str)
        
        write_plan(processed_table_rows + [r[0] for r in branch_rows[i+1:]])
        run_cmd("git add MERGE_PLAN.md && git commit -m 'docs: update MERGE_PLAN.md for skipped " + bname + "'")

print("All branches processed.")
