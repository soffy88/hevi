#!/usr/bin/env python
"""DRAMAPLAN E2E —— 真实免费 LLM 跑通「章节事件图 → 改编大纲 → 三层审稿」。

不碰像素（本任务不产出视频）。真跑真模型，产物落
`output/dramaplan_e2e/<run_id>/`：event_graph.json、adaptation_outline.json、
episode_scripts/、review_log.json、record.json、qa.json。

用法：
    .venv/bin/python scripts/e2e/dramaplan_e2e.py \
        --env-file /data/soffy/projects/hevi/.env \
        --channel nim --episodes 3 --episode-duration 60

只用免费/本地通道（见 hevi/providers/free_llm.py），绝不调付费端点。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 自写原创 3 章短篇（无版权问题；任务允许自写原创）。含人物/事件/对白/因果。
SOURCE_TEXT = """第一章 夜奔
沈砚之在子夜翻出沈府后墙，怀里揣着那半块玉玦。他身后是燃着灯的祠堂，父亲沈崇山的怒喝穿过夜色：「你若踏出这门，就永远别回来！」沈砚之没有回头。他要去青州，找那个三年前救过他性命的女子。
巷口，老仆福伯提着一盏灯笼等他。「少爷，盘缠我备好了。」福伯把布包塞进他手里，又从袖中取出一封密信，「这是夫人临终前留给您的，她说，等您真正要走的时候再拆。」

第二章 青州雪
青州落了大雪。沈砚之在城西的绣坊找到了苏晚。苏晚正在灯下绣一幅寒梅图，见了他，手中的针顿了顿。「你终究还是来了。」她说。沈砚之取出那半块玉玦：「三年前你救我时，落下的是这个吧。」苏晚不答，只把另一块玉玦从怀中取出，两块严丝合缝。原来她是沈崇山当年失散的义女。密信里，母亲写着：「晚儿是你的妹妹，护好她。」沈砚之握信的手在发抖。

第三章 归途
沈砚之带着苏晚回沈府。沈崇山立在阶前，看见两块合璧的玉玦，老泪纵横。「是我对不住你们兄妹。」他颤声道。祠堂的灯一盏盏亮起，福伯在廊下悄悄抹泪。沈砚之扶起父亲，苏晚跪在母亲牌位前，轻声说：「娘，我回来了。」雪停了，东方既白。
"""


def _load_env_file(path: Path) -> int:
    if not path.is_file():
        return 0
    count = 0
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            count += 1
    return count


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _CountingLLM:
    """包一层真实 caller，统计调用次数/耗时/失败（用于 record.json）。"""

    def __init__(self, inner):
        self.inner = inner
        self.calls = 0
        self.failures = 0
        self.total_s = 0.0

    async def __call__(self, **kwargs):
        self.calls += 1
        start = time.monotonic()
        try:
            return await self.inner(**kwargs)
        except Exception:
            self.failures += 1
            raise
        finally:
            self.total_s += time.monotonic() - start


async def _main_async(args: argparse.Namespace) -> int:
    for env_file in args.env_file:
        n = _load_env_file(Path(env_file).expanduser())
        print(f"[env] {env_file}: loaded {n} keys")
    if args.nim_model:
        os.environ["HEVI_NIM_MODEL"] = args.nim_model

    from hevi.providers.free_llm import probe_channel, resolve_free_llm
    from hevi.storygraph.chapters import (
        build_adaptation_outline,
        build_book_event_graph,
        outline_to_story,
    )
    from hevi.storygraph.review import run_three_layer_review

    run_id = args.run_id or time.strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out_root) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "source.txt").write_text(SOURCE_TEXT, encoding="utf-8")

    started = time.monotonic()
    record: dict = {"run_id": run_id, "channel": args.channel or "auto", "steps": {}}

    # 0) 通道探测（真实一次调用）
    probe = await probe_channel(args.channel or "auto", timeout=args.timeout)
    (out_dir / "llm_probe.json").write_text(
        json.dumps(probe, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[probe] {probe}")
    if not probe.get("available"):
        print("[fatal] 通道不可用", file=sys.stderr)
        return 2

    channel_name, caller = resolve_free_llm(args.channel)
    record["channel"] = channel_name
    llm = _CountingLLM(caller)

    # 1) 章节事件图（真实 LLM 逐章抽取）
    t0 = time.monotonic()
    book = await build_book_event_graph(source_name="沈砚之与苏晚（原创）", raw_text=SOURCE_TEXT, llm=llm)
    record["steps"]["event_graph"] = {
        "elapsed_s": round(time.monotonic() - t0, 2),
        "chapters": len(book.chapters),
        "characters": len(book.characters),
        "events": len(book.events),
        "quotes": len(book.quotes),
    }
    (out_dir / "event_graph.json").write_text(
        book.model_dump_json(indent=2), encoding="utf-8"
    )
    print(f"[event_graph] chapters={len(book.chapters)} events={len(book.events)} chars={len(book.characters)}")

    # 2) 改编大纲（按集数 × 时长挑选/压缩事件）
    t0 = time.monotonic()
    outline = build_adaptation_outline(
        book, target_episodes=args.episodes, episode_duration_s=args.episode_duration
    )
    trimmed = outline_to_story(book, outline)
    record["steps"]["outline"] = {
        "elapsed_s": round(time.monotonic() - t0, 2),
        "episodes": len(outline.episodes),
        "total_shot_budget": outline.total_shot_budget,
        "compressed": outline.compressed,
        "dropped_events": len(outline.dropped_event_ids),
    }
    (out_dir / "adaptation_outline.json").write_text(
        outline.model_dump_json(indent=2), encoding="utf-8"
    )
    print(f"[outline] episodes={len(outline.episodes)} shot_budget={outline.total_shot_budget} compressed={outline.compressed}")

    # 3) 三层审稿（真实 LLM 执行 + 监督；至少一轮监督→返修）
    t0 = time.monotonic()
    log = await run_three_layer_review(
        trimmed, outline, llm=llm, max_rounds=args.max_rounds
    )
    record["steps"]["review"] = {
        "elapsed_s": round(time.monotonic() - t0, 2),
        "episodes": len(log.episodes),
        "passed": log.passed,
        "rounds": [len(e.rounds) for e in log.episodes],
        "revision_rounds": sum(1 for e in log.episodes for r in e.rounds if r.round_index > 0),
    }
    from hevi.storygraph.review import write_review_log

    write_review_log(log, out_dir / "review_log.json")
    scripts_dir = out_dir / "episode_scripts"
    scripts_dir.mkdir(exist_ok=True)
    for ep in log.episodes:
        if ep.script is not None:
            (scripts_dir / f"ep{ep.ep_number:02d}.json").write_text(
                ep.script.model_dump_json(indent=2), encoding="utf-8"
            )
    print(f"[review] passed={log.passed} rounds={record['steps']['review']['rounds']}")

    record["llm_calls"] = llm.calls
    record["llm_failures"] = llm.failures
    record["llm_total_s"] = round(llm.total_s, 2)
    record["elapsed_s"] = round(time.monotonic() - started, 2)

    # 4) QA：全部由脚本实测计算，不手写 passed
    review_has_revision = any(
        r.round_index > 0 for e in log.episodes for r in e.rounds
    )
    qa = {
        "chapters_ge_3": len(book.chapters) >= 3,
        "event_graph_nonempty": len(book.events) > 0,
        "characters_merged": len(book.characters) > 0,
        "outline_episodes_match": len(outline.episodes) == args.episodes,
        "all_episodes_have_scripts": all(e.script is not None for e in log.episodes),
        "review_has_revision_round": review_has_revision,
        "review_all_passed": log.passed,
        "llm_calls": llm.calls,
    }
    qa["passed"] = all(
        v for k, v in qa.items() if isinstance(v, bool) and k != "passed"
    )
    qa["artifacts"] = {}
    for name in ("event_graph.json", "adaptation_outline.json", "review_log.json"):
        p = out_dir / name
        if p.exists():
            qa["artifacts"][name] = {"sha256": _sha256(p), "bytes": p.stat().st_size}
    for p in sorted(scripts_dir.glob("*.json")):
        qa["artifacts"][f"episode_scripts/{p.name}"] = {
            "sha256": _sha256(p),
            "bytes": p.stat().st_size,
        }
    (out_dir / "qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    record["qa_passed"] = qa["passed"]
    (out_dir / "record.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[qa] passed={qa['passed']} revision_round={review_has_revision}")
    print(f"[out] {out_dir}")
    return 0 if qa["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", action="append", default=[])
    parser.add_argument("--run-id", default="")
    parser.add_argument("--out-root", default=str(ROOT / "output" / "dramaplan_e2e"))
    parser.add_argument("--channel", default="nim", help="免费通道名（默认 nim）")
    parser.add_argument("--nim-model", default="nvidia/nemotron-3-super-120b-a12b")
    parser.add_argument("--episodes", type=int, default=3)
    parser.add_argument("--episode-duration", type=float, default=60.0)
    parser.add_argument("--max-rounds", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    if not args.env_file:
        args.env_file = ["/data/soffy/projects/hevi/.env"]
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
