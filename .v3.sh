cd /data/soffy/projects/platform/3O
export PYTHONPATH=$PWD/obase:$PWD/oprim:$PWD/oskill:$PWD/omodul
for d in obase oprim oskill omodul; do echo "## $d branch=$(git -C $d branch --show-current) feat-merged=$(git -C $d merge-base --is-ancestor feat/repo3o-intake HEAD && echo yes || echo no) UU=$(git -C $d status --short | grep -c '^UU\|^AA\|^DU\|^UD')"; git -C $d log --oneline -1
 T=$(cd $d; git log feat/repo3o-intake --name-only --format= --grep=repo3o | grep -E "^tests/.*\.py$" | sort -u); (cd $d; timeout 200 python3 -m pytest -q -p no:cacheprovider $(ls $T 2>/dev/null) 2>&1 | tail -1); done
diff <(sort ~/projects/hevi/.repo3o_backup/oprim/status.txt) <(git -C oprim status --short | sort)
git worktree list 2>/dev/null | grep repo3o; ls -d *-repo3o 2>/dev/null
