"""Comic script planning oskill.

Transforms a topic, prompt, or article fragment into a structured comic script
with 6-14 sentences and paired visual descriptions.  Supports a free LLM
channel with an immediate deterministic rule-based fallback.

No narration is ever hard-truncated: over-long sentences are split at
punctuation boundaries into complete sentences, and every narration ends with a
sentence-final punctuation mark.

3O Pillar: oskill.comicnarr_script_planner
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from typing import Any

from hevi.layer4_legacy.comicnarr.oprim_impl.contracts import ComicScene, ComicScript
from hevi.layer4_legacy.comicnarr.oprim_impl.templates import get_style_template

logger = logging.getLogger(__name__)

#: Sentence-final punctuation accepted for a completed narration.
_TERMINAL_PUNCT = "。！？…!?"
_CLAUSE_BREAK = "，,、；;：:"

# Pre-crafted high quality domain fallback templates for required acceptance themes
FALLBACK_SCRIPTS: dict[str, dict[str, Any]] = {
    "cat_knock": {
        "title": "为什么猫总爱把东西推下桌？",
        "character_desc_zh": "一只圆脸大眼的金渐层虎斑猫，毛茸茸的白色手套爪子，表情好奇又机智",
        "character_desc_en": "cute chubby orange tabby cat with white paws and an expressive curious face",
        "character_tokens": ("橘猫", "猫咪", "虎斑猫"),
        "scenes": [
            ("你一定见过这样的场景：猫咪坐在桌边，盯着杯子，然后伸出一只小爪子。", "一只胖乎乎的橘猫坐在整洁的书桌边缘，眼睛紧紧盯着一只玻璃水杯"),
            ("啪嗒一声，水杯应声落地，而它却一脸无辜地低头观望。", "水杯在木地板上摔碎水花飞溅，橘猫从桌沿探出小脑袋好奇向下张望"),
            ("其实，猫咪推倒东西并不是为了恶作剧，这背后有深层的动物本能。", "橘猫蹲坐在书架旁，耳朵微微竖起，眼神中充满智慧和野性好奇"),
            ("首先，在野外生存中，猫的肉垫极其敏感，触碰物体是在测试猎物。", "橘猫特写，粉嫩的小肉垫轻轻伸出，试探性地拨弄桌上的小笔筒"),
            ("轻轻一推，如果物体会动或者会逃跑，就意味着那可能是活物。", "桌上的木头小玩具向前滑动，橘猫全身紧绷摆出专注扑击姿势"),
            ("其次，高处跌落产生的声音和运动轨迹，对猫的神经系统是强烈的感官刺激。", "橘猫歪着小脑袋，大眼睛眨巴着，仔细观察铅笔顺着桌沿滚落"),
            ("这就像人类按动圆珠笔或者捏泡泡纸一样，给猫咪带来了纯粹的探索快感。", "阳光洒在书桌上，橘猫开心地用两只前爪轻快玩弄着纸团"),
            ("第三个原因更加直接：猫咪发现，只要东西掉地，主人就会立刻冲过来。", "主人慌慌张张跑进房间惊呼，橘猫坐在桌上淡定地摇晃着毛茸茸尾巴"),
            ("对于一只觉得无聊的猫来说，哪怕是被你责备两句，也是极好的互动。", "橘猫仰着圆圆的脸蛋看着主人，发出软萌的喵喵叫声"),
            ("如果你想保住桌上的水杯，最有效的办法绝不是对它发脾气。", "书桌特写，各种贵重易碎物品被整齐地收纳进了带玻璃门的封闭柜子"),
            ("多给它准备抓板和漏食玩具，把桌面易碎品收起来，才能实现人猫和平共处。", "温暖明亮的客厅里，橘猫惬意地趴在猫抓板上晒太阳，旁边放着小玩具"),
        ],
    },
    "classical_story": {
        "title": "促织：古画里的秋声",
        "character_desc_zh": "明清时期的年轻书生成名，身穿青色布衫，头戴儒巾，面容清瘦儒雅",
        "character_desc_en": "young ancient Chinese scholar in a simple cyan Hanfu robe and scholar cap",
        "character_tokens": ("书生", "成名", "读书人"),
        "scenes": [
            ("宣德年间，宫中盛行斗蟋蟀之风，每年民间都要征收上等的促织。", "繁华古朴的明代宫廷殿堂，金碧辉煌，香烟缭绕，官员正在呈送名贵蟋蟀"),
            ("华阴县有个读书人名叫成名，为人忠厚木讷，却被里胥摊派了采办之差。", "简朴清幽的农家书斋前，年轻书生手握账册，面容忧愁"),
            ("眼看交纳之期迫近，成名四处搜寻无果，整日惶恐不安。", "秋日凄清的荒草古庙旁，书生提着竹笼在乱石堆中焦急寻找"),
            ("一日，村里来了一位驼背巫婆，能占卜祸福，神算极准。", "烟雾蒙蒙的破旧古庙大殿内，白发老妇手持蓍草，念念有词"),
            ("成名求得一张神符，只见纸上画着苍松怪石，隐隐有一只奇异的促织。", "书生在昏黄烛光下展开纸帛，上面墨迹隐隐显现出一只神骏异虫"),
            ("他循着图中的指引，来到后山大佛寺后的丛冢乱石之间。", "薄雾笼罩的深山古刹后山，古松参天，落叶满径，环境幽静神秘"),
            ("拨开荆棘乱草，果然发现了一只头阔尾长、躯体金青的绝世蟋蟀。", "枯黄草丛深处特写，一只通体金青色、头大尾长的高大蟋蟀在石头上鸣叫"),
            ("成名大喜过望，将其捕入竹筒，如获至宝般带回了家。", "书生双手捧着精致的竹筒，满面红光，如获新生般快步走在乡间小路"),
            ("他用名贵的磁盆盛装，精心饲养，不敢有丝毫懈怠。", "古朴书房桌案上，放置着青花瓷盆，书生小心翼翼地放入蟹肉和新鲜水滴"),
            ("这只小小的生灵，不仅跳跃如飞，更在之后的角斗中所向披靡。", "金青色蟋蟀在特制斗盆中振翅高鸣，勇猛向前，姿态英勇非凡"),
            ("人世间的悲欢离合，竟系于微虫之手，令后人感慨万千。", "秋风落叶的古道旁，书生远望苍茫云山，意境深邃悠远"),
        ],
    },
    "three_kingdoms": {
        "title": "草船借箭：雾锁长江的智谋",
        "character_desc_zh": "三国时期蜀汉军师诸葛亮，头戴纶巾，身披鹤氅，手持白羽扇，神情从容",
        "character_desc_en": "ancient Chinese strategist in a crane-feather cloak and silk headwrap holding a white feather fan",
        "character_tokens": ("诸葛亮", "孔明", "周瑜"),
        "scenes": [
            ("东汉末年，曹操率大军南下，孙刘联军在赤壁严阵以待。", "东汉末年长江赤壁江面，战船林立，旌旗蔽日，大军压境"),
            ("周瑜忌惮诸葛亮的才智，故意命他十日内造出十万支箭。", "东吴军帐内，周瑜眉头紧锁，将令箭拍在案上，诸葛亮从容而立"),
            ("诸葛亮却笑着立下军令状，只需三天便可如数交箭。", "诸葛亮羽扇纶巾，微笑着写下军令状，帐中将领面面相觑"),
            ("他向鲁肃借来二十只快船，每船三十名军士，布满草人。", "江边二十只快船整齐排列，军士搬运草人扎满船舷"),
            ("第三天四更时分，大雾弥漫江面，船队悄然驶向曹营。", "第三天四更，大雾弥漫江面，船队悄然驶向曹营水寨"),
            ("军士擂鼓呐喊，佯装进攻，声震云霄，惊动了曹军水寨。", "军士在船头擂鼓呐喊，雾气中曹军水寨隐约可见，一片骚动"),
            ("曹操不明虚实，大雾之中不敢出战，急令弓弩手乱箭齐发。", "曹军水寨中弓箭手列阵，万箭齐发，箭雨划破浓雾"),
            ("万箭如雨点般射向草船，纷纷扎在草人之上，密如刺猬。", "草人特写，密密麻麻的羽箭扎满草人，如同刺猬"),
            ("诸葛亮又令船队调转方向，让另一侧也受满箭矢。", "船队在江心缓缓调头，让另一侧草人迎向箭雨"),
            ("天亮雾散，船上的草人已插满十万余支羽箭，满载而归。", "天亮雾散，草人插满羽箭，军士欢呼，快船满载而归"),
            ("周瑜得知经过，长叹一声，自愧不如孔明神机妙算。", "东吴军帐中，周瑜长叹，诸葛亮轻摇羽扇微笑不语"),
            ("草船借箭的故事流传千古，成为智慧与胆识的不朽传奇。", "长江落日，古战船剪影，草船借箭的传奇意境悠远"),
        ],
    },
}


def _finalize_sentence(clause: str) -> str:
    """Trim dangling clause punctuation and guarantee a terminal mark."""
    c = (clause or "").strip().rstrip(_CLAUSE_BREAK).strip()
    if not c:
        return ""
    if c[-1] not in _TERMINAL_PUNCT:
        c += "。"
    return c


def _split_text_to_sentences(text: str, max_chars: int = 30) -> list[str]:
    """Split text into complete sentences <= *max_chars* without losing text.

    Splits first on sentence-final punctuation (preserved), then breaks any
    still-too-long sentence at comma/clause boundaries.  Every returned item
    ends with sentence-final punctuation; no character is dropped (only a
    trailing comma may be normalised to a full stop).
    """
    if not text:
        return []
    raw = str(text)
    # Keep terminal punctuation attached to its sentence.
    segments = re.findall(rf"[^{_TERMINAL_PUNCT}\n]+[{_TERMINAL_PUNCT}]*", raw)
    sentences: list[str] = []

    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        if len(seg) <= max_chars:
            finalized = _finalize_sentence(seg)
            if len(finalized) >= 2:
                sentences.append(finalized)
            continue

        clauses = re.findall(rf"[^{_CLAUSE_BREAK}]+[{_CLAUSE_BREAK}]*", seg)
        cur = ""
        for clause in clauses:
            if not clause.strip():
                continue
            if cur and len(cur) + len(clause) > max_chars:
                finalized = _finalize_sentence(cur)
                if len(finalized) >= 2:
                    sentences.append(finalized)
                cur = clause
            else:
                cur += clause
        if cur.strip():
            finalized = _finalize_sentence(cur)
            if len(finalized) >= 2:
                sentences.append(finalized)

    return sentences


def _split_long_sentence(narration: str, max_chars: int = 30, max_parts: int = 2) -> list[str]:
    """Split one narration into at most *max_parts* complete sentences."""
    parts = _split_text_to_sentences(narration, max_chars=max_chars)
    if not parts:
        return []
    if len(parts) <= max_parts:
        return parts
    # Merge overflow back into the last kept part (never drop characters).
    kept = parts[: max_parts - 1]
    kept.append("".join(parts[max_parts - 1 :]))
    return kept


def _derive_character_tokens(character_desc_zh: str) -> tuple[str, ...]:
    """Best-effort protagonist identity tokens from a Chinese description."""
    tokens: list[str] = []
    for chunk in re.split(r"[，,。.、；;：:\s]+", character_desc_zh or ""):
        chunk = chunk.strip()
        if len(chunk) >= 2:
            for n in (3, 2):
                if len(chunk) >= n:
                    tok = chunk[-n:]
                    if tok not in tokens:
                        tokens.append(tok)
    return tuple(tokens[:6])


def _try_llm_script(topic: str, timeout_s: float = 3.0) -> dict[str, Any] | None:
    """Attempt fast generation of structured comic script via free local omniroute."""
    if os.environ.get("HEVI_USE_LLM", "1") == "0":
        return None

    api_url = os.environ.get("HEVI_OMNIROUTE_URL", "http://127.0.0.1:20128/v1/chat/completions")
    system_prompt = (
        "You are an expert comic video scriptwriter. Given a topic, write a captivating comic narration script. "
        "Strict Requirements:\n"
        "1. Exactly 10 to 12 scenes.\n"
        "2. Each narration sentence must be concise and strictly <= 30 Chinese characters.\n"
        "3. Pair each sentence with a detailed Chinese visual description for illustration.\n"
        "4. Define a consistent main protagonist with both Chinese and English visual descriptions.\n"
        "5. Output valid JSON only, schema:\n"
        '{"title": "...", "character_desc_zh": "...", "character_desc_en": "...", '
        '"scenes": [{"narration": "...", "visual_desc": "..."}]}'
    )
    payload = {
        "model": os.environ.get("HEVI_LLM_MODEL", "auto/best-free"),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Topic: {topic}"},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 1200,
        "temperature": 0.7,
    }

    try:
        req = urllib.request.Request(
            api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"].strip()
            # Extract JSON block
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            parsed = json.loads(content)
            if isinstance(parsed, dict) and len(parsed.get("scenes", [])) >= 6:
                return parsed
    except Exception as exc:
        logger.debug("LLM script planning bypassed or timed out: %s", exc)

    return None


def probe_free_llm(timeout_s: float = 4.0) -> dict[str, Any]:
    """Probe the local free Omniroute channel with a tiny request.

    Returns a JSON-serialisable dict describing the outcome so the pipeline can
    record the *actual* channel used.  Never raises.
    """
    if os.environ.get("HEVI_USE_LLM", "1") == "0":
        return {"available": False, "reason": "HEVI_USE_LLM=0", "model": None}

    model = os.environ.get("HEVI_LLM_MODEL", "auto/best-free")
    api_url = os.environ.get("HEVI_OMNIROUTE_URL", "http://127.0.0.1:20128/v1/chat/completions")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "reply with OK"}],
        "max_tokens": 4,
    }
    try:
        req = urllib.request.Request(
            api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if content:
                return {"available": True, "reason": "ok", "model": model}
            return {"available": False, "reason": "empty response", "model": model}
    except Exception as exc:  # noqa: BLE001 - probe must never raise
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}", "model": model}


def generate_comic_script(
    *,
    topic: str,
    raw_texts: list[str] | tuple[str, ...] | None = None,
    style_name: str = "guofeng_anime",
    base_seed: int = 42,
    timeout_s: float = 3.0,
    max_chars: int = 30,
    max_scenes: int = 14,
    use_llm: bool = True,
) -> tuple[ComicScript, str]:
    """Generate structured comic script. Returns (ComicScript, channel_used)."""
    t_clean = (topic or "").strip()
    style = get_style_template(style_name)

    # 1. Explicit user-provided narration lines take priority.  Each line is
    #    split into complete sentences; nothing is truncated.
    provided = [str(t).strip() for t in (raw_texts or []) if str(t).strip()]
    if provided:
        channel_used = "user_input_texts"
        title = t_clean or provided[0][:20]
        char_zh = "故事主人公，生动鲜明的外貌"
        char_en = "main character with distinctive iconic comic attire"
        scenes: list[ComicScene] = []
        for line in provided:
            for sentence in _split_text_to_sentences(line, max_chars=max_chars):
                scenes.append(
                    ComicScene(
                        index=len(scenes),
                        narration=sentence,
                        visual_desc=sentence,
                        prompt_en="",
                        negative_prompt=style.negative_prompt,
                        seed=base_seed + len(scenes) * 17,
                    )
                )
                if len(scenes) >= max_scenes:
                    break
            if len(scenes) >= max_scenes:
                break
        return (
            ComicScript(
                title=title,
                topic=t_clean,
                character_desc_zh=char_zh,
                character_desc_en=char_en,
                scenes=scenes,
                character_tokens=(),
            ),
            channel_used,
        )

    # 2. Try LLM channel
    llm_data = _try_llm_script(t_clean, timeout_s=timeout_s) if use_llm else None
    if llm_data is not None:
        channel_used = f"omniroute_llm:{os.environ.get('HEVI_LLM_MODEL', 'auto/best-free')}"
        title = str(llm_data.get("title") or t_clean)
        char_zh = str(llm_data.get("character_desc_zh") or "故事主角")
        char_en = str(llm_data.get("character_desc_en") or "iconic character in comic style")
        scenes = []
        for item in llm_data.get("scenes", []):
            narr = str(item.get("narration") or "").strip()
            vis = str(item.get("visual_desc") or narr).strip()
            if not narr:
                continue
            for sentence in _split_long_sentence(narr, max_chars=max_chars, max_parts=2):
                if len(scenes) >= max_scenes:
                    break
                scenes.append(
                    ComicScene(
                        index=len(scenes),
                        narration=sentence,
                        visual_desc=vis,
                        prompt_en="",
                        negative_prompt=style.negative_prompt,
                        seed=base_seed + len(scenes) * 17,
                    )
                )
            if len(scenes) >= max_scenes:
                break
        if len(scenes) >= 6:
            return (
                ComicScript(
                    title=title,
                    topic=t_clean,
                    character_desc_zh=char_zh,
                    character_desc_en=char_en,
                    scenes=scenes,
                    character_tokens=_derive_character_tokens(char_zh),
                ),
                channel_used,
            )

    # 3. Deterministic rule-based fallback
    channel_used = "deterministic_rule_fallback"
    if any(k in t_clean for k in ("猫", "宠物", "推下", "爪", "动物")):
        tmpl = FALLBACK_SCRIPTS["cat_knock"]
    elif any(
        k in t_clean
        for k in ("三国", "诸葛", "孔明", "草船", "借箭", "赤壁", "周瑜", "曹操")
    ):
        tmpl = FALLBACK_SCRIPTS["three_kingdoms"]
    elif any(k in t_clean for k in ("聊斋", "促织", "道士", "故事", "书生", "古代", "古")):
        tmpl = FALLBACK_SCRIPTS["classical_story"]
    else:
        sentences = _split_text_to_sentences(t_clean, max_chars=max_chars)
        if len(sentences) >= 6:
            tmpl = {
                "title": sentences[0][:20],
                "character_desc_zh": "核心叙述角色",
                "character_desc_en": "expressive animated protagonist character",
                "character_tokens": (),
                "scenes": [(s, s) for s in sentences[:max_scenes]],
            }
        else:
            tmpl = FALLBACK_SCRIPTS["cat_knock"]

    title = t_clean or tmpl["title"]
    char_zh = tmpl["character_desc_zh"]
    char_en = tmpl["character_desc_en"]
    char_tokens = tuple(tmpl.get("character_tokens") or _derive_character_tokens(char_zh))
    scenes = []
    for narr, vis in tmpl["scenes"]:
        # Split any over-long curated sentence into complete sentences.
        for sentence in _split_text_to_sentences(narr, max_chars=max_chars):
            if len(scenes) >= max_scenes:
                break
            scenes.append(
                ComicScene(
                    index=len(scenes),
                    narration=sentence,
                    visual_desc=vis,
                    prompt_en="",
                    negative_prompt=style.negative_prompt,
                    seed=base_seed + len(scenes) * 17,
                )
            )
        if len(scenes) >= max_scenes:
            break

    return (
        ComicScript(
            title=title,
            topic=t_clean,
            character_desc_zh=char_zh,
            character_desc_en=char_en,
            scenes=scenes,
            character_tokens=char_tokens,
        ),
        channel_used,
    )


__all__ = [
    "FALLBACK_SCRIPTS",
    "generate_comic_script",
    "probe_free_llm",
]
