cd /data/soffy/projects/platform/3O
mkdir -p /tmp/r3m; P=""
for d in obase oprim oskill omodul; do git -C $d worktree add -f --detach /tmp/r3m/$d main >/dev/null 2>&1; P=$P:/tmp/r3m/$d; done
export PYTHONPATH=${P#:}
for d in obase oprim oskill omodul; do echo "## $d main=$(git -C $d rev-parse --short main) merged=$(git -C $d merge-base --is-ancestor feat/repo3o-intake main && echo yes || echo no)"; git -C $d log --oneline -1 main
 T=$(cd $d; git log feat/repo3o-intake --name-only --format= --grep=repo3o | grep -E "^tests/.*\.py$" | sort -u); (cd /tmp/r3m/$d; timeout 200 python3 -m pytest -q -p no:cacheprovider $T 2>&1 | tail -1); done
for d in obase oprim oskill omodul; do git -C $d worktree remove --force /tmp/r3m/$d; done
git -C oservi worktree remove oservi-repo3o 2>&1 | tail -1 || true; git -C oservi worktree remove ../oservi-repo3o 2>&1|tail -1; ls -d *-repo3o 2>/dev/null
git -C oprim log -1 --format=%h HEAD; git -C oprim stash list | head -3
