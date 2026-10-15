import sys, json
sys.path.insert(0,"/data/soffy/projects/hevi-storyplan")
from hevi.storyplan.autofill import autofill_story_plan
from hevi.storyplan.check import run_story_check

for topic in ["小水滴去哪儿了","小熊为什么洗手"]:
    plan = autofill_story_plan(topic)
    rep = run_story_check(plan)
    # build a genuine no-structure baseline: minimal plan without hook/end_state
    bad = autofill_story_plan(topic)
    bad.narrative.hook.text=""
    for sc in bad.shots.sequences[0].scenes:
        for sh in sc.shots: sh.end_state=""
    rb = run_story_check(bad)
    fails_bad=[c.check_id for c in rb.checks if c.status=="FAIL"]
    fails_ok=[c.check_id for c in rep.checks if c.status=="FAIL"]
    print(topic, "| planned.passed=",rep.passed,"| baseline.passed=",rb.passed,"| baseline FAILs=",fails_bad,"| planned FAILs=",fails_ok)
