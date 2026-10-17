import subprocess

def run_cmd(cmd):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()

wip_branches = [
    "wip/agentops-20261017",
    "wip/amfx-20261017",
    "wip/ff1017-20261017",
    "wip/fxreg-20261017",
    "wip/kidsmanifest-20261017",
    "wip/omfootage-20261017",
    "wip/sfxbad-20261017",
    "wip/slimimg-20261017",
    "wip/toonflow-20261017",
    "wip/shotspec-20261017",
    "wip/dirstyle-20261017",
    "wip/handdraw-20261017",
    "wip/kidsgate-20261017",
    "wip/scene3d-20261017",
    "wip/storyplan-20261017",
    "wip/xfadepack-20261017",
    "wip/amtpl-20261017",
    "wip/motiondir-20261017",
    "wip/storybook-20261017",
    "wip/v3-20261017",
    "wip/anatup-20261017",
    "wip/quoteimage-20261017",
    "wip/pubfix-baseline-20261017",
    "wip/pubfix-20261017",
    "wip/reviewsheet-20261017",
    "wip/stash-2-20261017",
    "wip/opuscar-20261017",
    "wip/stash-4-20261017",
    "wip/stash-1-20261017",
    "wip/stash-0-20261017",
    "wip/stash-3-20261017",
]

for b in wip_branches:
    rc, out, _ = run_cmd(f"git rev-list --count integration/mergeall-1017..{b}")
    if out == "0":
        print(f"{b} is already merged.")
        continue
    rc, out, err = run_cmd(f"git merge --no-ff {b} -m 'merge: merge {b} into integration/mergeall-1017'")
    if rc == 0:
        print(f"SUCCESS: {b} cleanly merged.")
    else:
        print(f"CONFLICT on {b}:\n{out}\n{err}")
        run_cmd("git merge --abort")
