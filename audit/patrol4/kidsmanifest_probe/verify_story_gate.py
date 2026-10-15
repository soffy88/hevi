#!/usr/bin/env python3
"""PATROL4 independent check of the kidsmanifest story gate (A.2).

Task A.2 requires: 3 classes of bad sample MUST FAIL
  1. all AND-THEN (causal transition ratio < 30%)
  2. adjacent beats with the same emotion
  3. missing theme or missing fixed character
and a compliant sample MUST PASS.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

WORKTREE = Path("/data/soffy/projects/hevi-kidsmanifest")
PY = "/data/soffy/projects/hevi/.venv/bin/python"
KINDS = ["greeting", "problem", "attempt", "solution", "recap", "farewell"]

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}", flush=True)


def beat(kind: str, text: str, emotion: str, transition: str | None) -> dict:
    return {"kind": kind, "text": text, "emotion": emotion, "transition": transition}


def good_story() -> dict:
    return {
        "logline": "小狐狸学会刷牙，牙齿变得白白净净。",
        "theme": "刷牙护牙",
        "spoken_language": "zh-CN",
        "fixed_characters": ["小狐狸"],
        "characters": [{"id": "char_fox", "name": "小狐狸"}],
        "beats": [
            beat("greeting", "早上好呀，我是小狐狸。", "开心", None),
            beat("problem", "我的牙齿有点黄，怎么办呢。", "难过", "BUT"),
            beat("attempt", "我先用小手擦一擦，擦不干净。", "着急", "THEREFORE"),
            beat("solution", "于是我拿起小牙刷，认真刷干净了。", "开心", "THEREFORE"),
            beat("recap", "每天刷牙，牙齿白白的。", "骄傲", "THEREFORE"),
            beat("farewell", "你今天刷牙了吗？", "温暖", "THEREFORE"),
        ],
    }


def bad_and_then() -> dict:
    s = good_story()
    s["beats"] = [
        beat("greeting", "小狐狸起床了。", "开心", None),
        beat("problem", "然后他去洗脸。", "平静", "THEN"),
        beat("attempt", "然后他吃早饭。", "平静", "THEN"),
        beat("solution", "然后他出门玩。", "平静", "THEN"),
        beat("recap", "然后他回家了。", "平静", "THEN"),
        beat("farewell", "然后他睡觉了。", "平静", "THEN"),
    ]
    return s


def bad_same_emotion() -> dict:
    s = good_story()
    s["beats"][1]["emotion"] = s["beats"][2]["emotion"] = "开心"
    s["beats"][2]["emotion"] = s["beats"][1]["emotion"] = "开心"
    # make beats 2 and 3 (problem, attempt) share an emotion
    s["beats"][2] = dict(s["beats"][2], emotion="开心")
    s["beats"][1] = dict(s["beats"][1], emotion="开心")
    return s


def bad_no_theme() -> dict:
    s = good_story()
    s["theme"] = None
    return s


def bad_no_characters() -> dict:
    s = good_story()
    s["fixed_characters"] = []
    s["characters"] = []
    return s


CASES = [
    ("compliant -> must PASS", good_story(), "PASS"),
    ("all AND-THEN -> must FAIL", bad_and_then(), "FAIL"),
    ("adjacent same emotion -> must FAIL", bad_same_emotion(), "FAIL"),
    ("missing theme -> must FAIL", bad_no_theme(), "FAIL"),
    ("missing fixed character -> must FAIL", bad_no_characters(), "FAIL"),
]


def main() -> int:
    payload = json.dumps([[n, s] for n, s, _ in CASES], ensure_ascii=False)
    script = f"""
import sys, json
sys.path.insert(0, {str(WORKTREE)!r})
from hevi.kids.story_gate import kids_story_gate, StoryInput
cases = json.loads(sys.stdin.read())
out = []
for name, s in cases:
    rep = kids_story_gate(StoryInput.model_validate(s))
    d = rep.to_dict()
    fails = [f['rule'] for f in d['findings'] if f['severity'] == 'FAIL']
    out.append({{'name': name, 'status': d['status'], 'fails': fails,
                'causal_ratio': d['metrics'].get('causal_ratio')}})
print('GATE_JSON:' + json.dumps(out, ensure_ascii=False))
"""
    proc = subprocess.run([PY, "-c", script], cwd=str(WORKTREE), input=payload,
                          capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        print(proc.stderr[-3000:])
        return 2
    got = json.loads([l for l in proc.stdout.splitlines() if l.startswith("GATE_JSON:")][-1][len("GATE_JSON:"):])

    for (name, _, want), r in zip(CASES, got):
        ok = (r["status"] == want) if want == "PASS" else (r["status"] in ("FAIL", "WARN") and bool(r["fails"]))
        record(f"story gate: {name}",
               ok,
               f"got={r['status']} causal_ratio={r['causal_ratio']} fails={r['fails']}")

    # determinism of gate_json
    script2 = f"""
import sys, json, hashlib
sys.path.insert(0, {str(WORKTREE)!r})
from hevi.kids.story_gate import kids_story_gate, StoryInput
s = StoryInput.model_validate(json.loads(sys.stdin.read()))
h = hashlib.sha256(json.dumps(kids_story_gate(s).to_dict(), sort_keys=True,
                              ensure_ascii=False).encode()).hexdigest()
print('DET:' + h)
"""
    good = json.dumps(good_story(), ensure_ascii=False)
    hs = []
    for _ in range(2):
        p2 = subprocess.run([PY, "-c", script2], cwd=str(WORKTREE), input=good,
                            capture_output=True, text=True, timeout=300)
        hs.append([l for l in p2.stdout.splitlines() if l.startswith("DET:")][0][4:])
    record("story gate: deterministic (2 runs identical sha256)", hs[0] == hs[1], f"{hs[0][:24]}")

    npass = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n==== PATROL4 STORY GATE SUMMARY ====\n{npass}/{len(RESULTS)} checks passed")
    fails = [n for n, ok, _ in RESULTS if not ok]
    if fails:
        print("FAILED: " + "; ".join(fails))
    print("VERDICT: " + ("PASS" if npass == len(RESULTS) else "FAIL"))
    Path(__file__).parent.joinpath("story_gate_result.json").write_text(json.dumps(
        {"results": [{"check": n, "ok": o, "detail": d} for n, o, d in RESULTS],
         "gate": got, "pass": npass, "total": len(RESULTS)}, ensure_ascii=False, indent=2))
    return 0 if npass == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
