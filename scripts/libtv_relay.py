"""把 hevi 的加厚剧本(或任意故事文本)中继给 LibLib.tv agent-im 出电影级视频。

验证方向(2026-07-16):hevi 自造管线出"大头念台词/圣斗士/无走位";改为"用户侧不做创作、只做
传话"——hevi 产出加厚剧本,LibLib.tv 出片。本脚本让 soffy 用自己的 LIBTV_ACCESS_KEY 先验证
这个方向成不成,再决定深接进 produce。

用法:
  # 直接把一段故事/剧本文本作为创作指令(自动包一层"出电影级视频、忠实场景/走位/动作/对白")
  LIBTV_ACCESS_KEY=xxx uv run python scripts/libtv_relay.py --text-file 剧本.txt

  # 或直接给原始 message(不包装)
  LIBTV_ACCESS_KEY=xxx uv run python scripts/libtv_relay.py --raw "生一段三国张飞失徐州的电影短片"

  # 先让 hevi 从手稿现产加厚剧本,再中继(concept→screenplay,走 qwen_cloud)
  LIBTV_ACCESS_KEY=xxx uv run python scripts/libtv_relay.py --manuscript 手稿.txt
产物落 output/libtv_relay/。
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

_BRIEF_HEADER = (
    "请根据下面这份电影分场剧本,生成一段**电影级短视频**。硬性要求:\n"
    "1. 严格忠实剧本里的**场景、人物走位、动作、对白、语气**——不要变成一个个大头念台词。\n"
    "2. 同一角色全片形象一致(服装/长相别每个镜头都变),穿戴写实、符合历史,别夸张成游戏铠甲。\n"
    "3. 有动作演动作(骑马/跪拜/喝水/拔剑等),有走位有场面调度,镜头有景别和运镜变化。\n\n"
    "分场剧本:\n"
)


def _screenplay_to_text(screenplay) -> str:
    lines: list[str] = []
    for s in screenplay.scenes:
        lines.append(f"第{s.scene_no}场 {s.time} {s.location}")
        if s.characters_present:
            lines.append("出场:" + "、".join(s.characters_present))
        if s.narration:
            lines.append("画面:" + s.narration)
        for d in s.dialogue:
            tgt = f"(对{d.target_name})" if getattr(d, "target_name", "") else ""
            lines.append(f"{d.character_name}{tgt}:{d.text}")
        lines.append("")
    return "\n".join(lines)


async def _build_message(args: argparse.Namespace) -> str:
    if args.raw:
        return args.raw
    if args.text_file:
        return _BRIEF_HEADER + Path(args.text_file).read_text(encoding="utf-8")
    # --manuscript:现产加厚剧本
    from hevi.director.concept import generate_concept_draft
    from hevi.director.screenplay import generate_screenplay_draft

    material = Path(args.manuscript).read_text(encoding="utf-8")
    concept = await generate_concept_draft(material_text=material, intent_hint="")
    screenplay = await generate_screenplay_draft(concept=concept, material_text=material)
    print(f"[产出加厚剧本] {len(screenplay.scenes)} 场")
    return _BRIEF_HEADER + _screenplay_to_text(screenplay)


async def main(args: argparse.Namespace) -> None:
    from hevi.video.libtv_service import LibtvError, generate_via_libtv

    message = await _build_message(args)
    print("=" * 72)
    print("发给 LibLib.tv agent-im 的创作指令(前 600 字):")
    print(message[:600])
    print("=" * 72)
    if args.dry_run:
        print("(dry-run:未真调 libtv。去掉 --dry-run 且设好 LIBTV_ACCESS_KEY 真出片。)")
        return
    try:
        res = await generate_via_libtv(
            message, Path("output/libtv_relay"), timeout_s=args.timeout, poll_interval_s=args.poll
        )
    except LibtvError as e:
        print(f"✗ libtv 出片失败: {e}")
        return
    print("✅ 出片完成")
    print("  项目画布:", res["project_url"])
    print("  视频:", res["video"])
    print("  全部产物:", res["files"])


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="中继剧本给 LibLib.tv 出电影级视频")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--text-file", help="剧本/故事文本文件(自动包电影级出片要求)")
    g.add_argument("--raw", help="原始创作指令(不包装)")
    g.add_argument("--manuscript", help="手稿文件:先 hevi 现产加厚剧本再中继")
    p.add_argument("--dry-run", action="store_true", help="只打印指令,不真调 libtv")
    p.add_argument("--timeout", type=float, default=1800.0, help="轮询出片超时秒(默认 1800)")
    p.add_argument("--poll", type=float, default=15.0, help="轮询间隔秒(默认 15)")
    asyncio.run(main(p.parse_args()))
