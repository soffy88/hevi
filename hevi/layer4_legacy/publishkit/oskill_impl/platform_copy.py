"""多平台发布文案（oskill 层）。

按上游 ``八平台发布文案-模板.md`` + ``platform-copy.md`` 生成：每平台一套
主推/备选标题、正文、话题、置顶评论，B站/YouTube 另加**成片实际时间戳**的
章节。规则降级时产出的是可直接发布的成套文案，不是占位串。
"""

from __future__ import annotations

import re

from hevi.layer4_legacy.publishkit.oprim_impl.contracts import (
    PLATFORMS,
    PlatformCopy,
    PlatformSpec,
    ScriptDoc,
    timecode,
)

_SENTENCE = re.compile(r"(?<=[。！？!?])")
_NOUN_HINT = re.compile(r"(复利|白板|讲解|大模型|时间|本金|收益率|注意力|配音|分镜|预训练|对齐|推理)")
_TRAIL = "。．.，,！!？?、；;：: "
_QUESTION_PREFIX = re.compile(r"^(为什么|为何|什么是|啥是|怎么|如何|谁|哪些|请问|你知道|介绍一[下个])")
_LEADIN_CLAUSE = re.compile(
    r"^(你是否|今天我们|接下来|那么|其实|我想|不知道|大家好|各位|先说|首先说|你有没有)"
)
# 上游：评论要邀请"可回答的真实经验"，所以优先用经验式问句收尾
_ASK_EXPERIENCE = re.compile(r"(你会不会|你会先|你更|你有没有|你是否|你能不能|你会怎么|你会从)")


def _strip_tail(text: str) -> str:
    """去掉句尾标点，避免拼句时出现"？。"这种双标点。"""

    return text.strip().rstrip(_TRAIL)


def topic_label(doc: ScriptDoc, limit: int = 16) -> str:
    """把主题压成一个短标签，避免标题里同一句重复两遍。

    旁白常以"你是否好奇，X 是什么？"这类铺垫开场——铺垫不是主题，要丢掉。
    """

    raw = _strip_tail(doc.topic)
    clauses = [c.strip() for c in raw.split("，") if c.strip()]
    if len(clauses) > 1 and _LEADIN_CLAUSE.match(clauses[0]):
        raw = "，".join(clauses[1:])
    raw = _QUESTION_PREFIX.sub("", raw).strip() or raw
    if len(raw) > limit:
        # 只在标点处断（在"的/是"这类词中间断会切出"AI究竟"这种残词）
        best = raw
        for sep in ("，", "、", "；", "。"):
            if sep in raw:
                side = max((part.strip() for part in raw.split(sep) if part.strip()), key=len)
                if 5 <= len(side) <= limit:
                    best = side
                break
        return _clip_title(best, limit)
    return raw


def _clip_title(text: str, limit: int) -> str:
    """标题不承诺正文没回答的事：只裁到长度上限，裁完不出现半个词。"""

    text = text.strip().rstrip("。.，,！!？?、")
    if len(text) <= limit:
        return text
    cut = text[:limit]
    # 尽量切在标点/空格边界上，实在没有就直接截断
    for sep in ("，", "、", " ", "："):
        if sep in cut:
            idx = cut.rfind(sep)
            if idx >= max(limit // 2, 6):
                return cut[:idx]
    return cut


def _sentences(doc: ScriptDoc) -> list[str]:
    out: list[str] = []
    for line in doc.lines:
        for piece in _SENTENCE.split(line.text):
            piece = piece.strip()
            if piece:
                out.append(piece)
    return out


def _claims_minus_topic(doc: ScriptDoc, sentences: list[str], count: int) -> list[str]:
    """要点：跳过与主题重复、以及纯设问的句子——设问当标题/导语会又长又空。"""

    label = topic_label(doc)
    picked = [s for s in _core_claims(sentences, count + 3)
              if not _same_claim(s, label) and not s.endswith(("？", "?"))]
    if not picked:
        picked = [s for s in _core_claims(sentences, count + 2) if not _same_claim(s, label)]
    return picked[:count] if picked else _core_claims(sentences, count)


def _same_claim(sentence: str, label: str) -> bool:
    s = _strip_tail(sentence)
    return bool(label) and (label in s or s in label)


def _core_claims(sentences: list[str], count: int = 3) -> list[str]:
    """挑出正文要点：优先带名词提示或问句的句子。"""

    scored = []
    for i, s in enumerate(sentences):
        score = 0
        if _NOUN_HINT.search(s):
            score += 2
        if s.endswith(("？", "?")):
            score += 2
        if re.search(r"\d", s):
            score += 1
        if 12 <= len(s) <= 40:
            score += 2
        scored.append((score, -i, s))
    scored.sort(reverse=True)
    picked = [s for score, neg_i, s in scored if score >= 2][:count]
    if not picked:
        picked = sentences[:count]
    order = {s: i for i, s in enumerate(sentences)}
    return sorted(picked, key=lambda s: order[s])


def _topic_tags(doc: ScriptDoc, sentences: list[str]) -> list[str]:
    """话题：一个主题标签 + 旁白里出现的名词提示，不做正则切词（会切出残词）。"""

    tags: list[str] = []
    label = topic_label(doc)
    if label:
        tags.append(f"#{label}")
    for s in sentences:
        m = _NOUN_HINT.search(s)
        if m and f"#{m.group(0)}" not in tags:
            tags.append(f"#{m.group(0)}")
        if len(tags) >= 5:
            break
    if not tags:
        tags = ["#视频讲解", "#知识分享"]
    return tags[:5]


def _disclaimer(doc: ScriptDoc, checked_on: str) -> str:
    return (
        f"资料核对至{checked_on}。公开资料整理，未采访当事方；"
        f"本期事实边界见配套《事实与来源》。不构成消费/医疗/法律/求职建议。"
    )


def _closing_question(doc: ScriptDoc, sentences: list[str]) -> str:
    """置顶评论里的互动问题：优先用**片尾**的经验式问句，否则用经验式提问收尾。

    上游要求结尾问"你会不会"这类**可回答的真实经验**，不是"该不该买"，
    也不是把片头的设问原样搬回来当互动——所以先在最后三分之一找。
    """

    tail_lines = doc.lines[-(max(len(doc.lines) // 3, 1)):]
    for line in reversed(tail_lines):
        text = line.text.strip()
        if text.endswith(("？", "?")) and _ASK_EXPERIENCE.search(text):
            return text
    label = topic_label(doc)
    return f"关于{label}，你会先从哪一步开始？" if label else "你会先从哪一步开始？"


def _chapters(doc: ScriptDoc, limit: int = 6) -> tuple[tuple[str, float], ...]:
    """章节只用成片实际时间点；没有真实时间戳就返回空（不编时间码）。"""

    if not doc.chapters:
        return ()
    return tuple(doc.chapters[:limit])


def build_platform_copies(doc: ScriptDoc, *, checked_on: str) -> list[PlatformCopy]:
    """生成八个平台的成套文案。"""

    sentences = _sentences(doc)
    claims = _claims_minus_topic(doc, sentences, 3)
    tags = _topic_tags(doc, sentences)
    question = _closing_question(doc, sentences)
    disclaimer = _disclaimer(doc, checked_on)
    chapters = _chapters(doc)
    lead = _strip_tail(claims[0]) if claims else _strip_tail(doc.topic)
    rest = claims[1:] or claims
    tail = "。".join(_strip_tail(s) for s in rest) + "。"

    # 主标题：短主题标签 + 一句价值（不承诺正文没回答的事）
    base_title = _clip_title(topic_label(doc), 18)

    return [
        _copy_for(spec, doc=doc, base_title=base_title, lead=lead, tail=tail,
                  tags=tags, question=question, disclaimer=disclaimer, chapters=chapters)
        for spec in PLATFORMS
    ]


def _copy_for(
    spec: PlatformSpec,
    *,
    doc: ScriptDoc,
    base_title: str,
    lead: str,
    tail: str,
    tags: list[str],
    question: str,
    disclaimer: str,
    chapters: tuple[tuple[str, float], ...],
) -> PlatformCopy:
    limit = spec.title_limit
    account = doc.account or doc.brand
    summary = ""

    if spec.id == "xiaohongshu":
        # 弱化品牌名：用场景/问题作主语
        title = _clip_title(f"{base_title}，一条讲清", limit)
        alt = _clip_title(f"{_strip_brand(base_title)}是怎么讲的", limit)
        body = (
            f"我把「{base_title}」这条从头翻了一遍。\n\n"
            f"{lead}。\n{tail}\n\n"
            f"{disclaimer}"
        )
        topics = tuple(dict.fromkeys(["#" + t.lstrip("#") for t in tags[:4]]))
    elif spec.id == "bilibili":
        # 【账号名】只在输入真的给了品牌/账号时才加（上游模板要求，不编造账号名）
        titled = f"{base_title}【{account}】" if account and spec.brand_in_title else base_title
        title = _clip_title(titled, limit)
        alt = _clip_title(f"{base_title}：{lead}", limit)
        structure = "\n".join(
            f"{i + 1:02d} {name}" + (f"：{note}" if (note := _chapter_note(doc, i, name)) else "")
            for i, (name, _t) in enumerate(chapters)
        ) or "01 完整讲解：见正文"
        body = f"这期讲{base_title}。\n\n本期结构：\n{structure}\n\n{disclaimer}"
        topics = tuple(dict.fromkeys(tags + ([f"#{account}"] if account else [])))
    elif spec.id == "youtube":
        title = _clip_title(f"{base_title} | {lead}", limit)
        alt = _clip_title(base_title, limit)
        body = f"{lead}。{tail}\n\n{disclaimer}"
        topics = tuple(dict.fromkeys(tags + ([account] if account else [])))
    elif spec.id == "zhihu":
        title = _clip_title(f"{base_title}是怎么成立的？", limit)
        alt = _clip_title(f"{lead}", limit)
        body = f"按公开资料梳理：{lead}。{tail}\n\n本期不做的：不预测行情、不给投资建议。\n\n{disclaimer}"
        topics = tuple(dict.fromkeys(tags[:3]))
    elif spec.id == "wechat_mp":
        title = _clip_title(f"{base_title}", min(limit, 40))
        alt = _clip_title(f"{lead}", min(limit, 40))
        summary = _clip_title(f"{lead}。{tail}", 100)
        body = f"与视频口播稿一致：\n\n{lead}。{tail}\n\n{disclaimer}"
        topics = ()
    elif spec.id == "kuaishou":
        title = _clip_title(f"{base_title}，{len(doc.lines)}句讲完", limit)
        alt = _clip_title(base_title, limit)
        body = "\n".join(f"· {s}" for s in _core_claims(_sentences(doc), 5)) + f"\n\n{disclaimer}"
        topics = tuple(dict.fromkeys(tags[:4]))
    elif spec.id == "wechat_channels":
        title = _clip_title(base_title, limit)
        alt = _clip_title(f"{lead}", limit)
        body = f"{lead}。{tail}\n\n{disclaimer}"
        topics = tuple(dict.fromkeys(tags[:4]))
    else:  # douyin
        title = _clip_title(f"{base_title}，这条讲明白了", limit)
        alt = _clip_title(base_title, limit)
        body = (
            f"{lead}。\n{tail}\n\n"
            "不讲术语堆砌，只讲这条视频讲到的部分。\n\n"
            f"{disclaimer}"
        )
        topics = tuple(dict.fromkeys(tags[:4]))

    pinned = ""
    if spec.has_pinned_comment:
        pinned = f"{disclaimer} 另外想问你：{question}"

    return PlatformCopy(
        platform=spec.id,
        label=spec.label,
        title=title,
        alt_title=alt,
        body=body,
        topics=topics,
        pinned_comment=pinned,
        chapters=chapters if spec.has_chapters else (),
        summary=summary,
    )


def _strip_brand(text: str) -> str:
    return text


def _chapter_note(doc: ScriptDoc, index: int, chapter_title: str) -> str:
    """章节名已取首句前半个分句；这里只补剩下的部分，不重复章节名。"""

    if index >= len(doc.lines):
        return ""
    sentence = _strip_tail(doc.lines[index].text)
    if sentence.startswith(chapter_title):
        remainder = sentence[len(chapter_title):].lstrip("，,、：: ")
        # 章节名被裁断时剩下的残字（"…大奇迹" → "迹"）不算要点
        return "" if len(remainder) < 3 else _clip_title(remainder, 32)
    return "" if _same_claim(sentence, chapter_title) else _clip_title(sentence, 32)


def render_copy_md(doc: ScriptDoc, copies: list[PlatformCopy], *, checked_on: str, version: str = "v1") -> str:
    """按上游模板排版成一份 copy.md。"""

    total_s = None
    for line in doc.lines:
        if line.end_s is not None:
            total_s = max(total_s or 0.0, line.end_s)
    header = [
        f"# {doc.topic} · 八平台发布文案{version}",
        "",
        f"对应：{doc.path}（文稿 {len(doc.lines)} 句"
        + (f"，成片口播约 {timecode(total_s)}" if total_s else "")
        + "）。仅备稿，未公开发布。",
        "",
        "标题长度按各平台入口限制裁剪（小红书≤20，抖音/快手/视频号≤30，B站/YouTube/知乎≤40，公众号≤64）。",
        "",
    ]
    blocks: list[str] = []
    for copy in copies:
        lines = [f"## {copy.label}", "", f"主推标题：{copy.title}（{len(copy.title)}字）"]
        if copy.alt_title:
            lines.append(f"备选标题：{copy.alt_title}（{len(copy.alt_title)}字）")
        if copy.summary:
            lines.append(f"摘要：{copy.summary}")
        lines += ["", "正文：", "", copy.body, ""]
        if copy.chapters:
            lines.append("章节：")
            lines += [f"{timecode(t)} {name}" for name, t in copy.chapters]
            lines.append("")
        if copy.topics:
            sep = " " if copy.platform in {"douyin", "kuaishou", "bilibili", "wechat_channels", "xiaohongshu"} else \
                ("," if copy.platform == "youtube" else "、")
            lines += ["话题：" + sep.join(copy.topics), ""]
        if copy.pinned_comment:
            lines += [f"置顶评论：{copy.pinned_comment}", ""]
        blocks.append("\n".join(lines))

    footer = [
        "---",
        "",
        f"资料核对至{checked_on}。来源台账见 fact_sources.json；未补链接的条目已在 manual_todo 里列出。",
        "封面为本地帧重排版（非 AI 生成），比例与目视检查见 cover_qa.json。",
    ]
    return "\n".join(header) + "\n" + "\n".join(blocks) + "\n".join(footer) + "\n"