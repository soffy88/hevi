"""制作手艺知识库加载器 —— 把 ``hevi/skills/knowledge/`` 下的中文手艺手册按阶段读出来,
喂给导演/调度的 LLM 提示词。

知识库目录是**纯数据**(只有 Markdown,没有 ``__init__.py``、没有 Python),本模块是它
唯一的读取入口。三条硬规则:

1. **未知阶段抛 ValueError,绝不静默返回空串。** 静默空串是最坏的失败模式:调用方会
   以为"已经注入手艺知识",实际 prompt 里什么都没有,现场根本看不出来。
2. **截断必须留可见标记。** ``max_chars`` 截断拼接结果时,尾部追加 ``<!-- truncated at
   N chars -->``。悄悄截断等于悄悄改写别人的指令,模型不会知道自己看到的不是全文。
3. **每次调用真读盘,不做缓存。** 知识库是人手改的,任何缓存都会让"改了文件不生效",
   而且在长跑进程里悄悄返回旧内容。

读取失败(目录缺失 / 文件读不动)同样抛 ``ValueError``,由调用方 try/except 兜住 ——
生产链**不许因为知识库缺失而断**。仓库里已经接好的三处都是这个模式:
``hevi/director/screenplay.py``、``hevi/director/shot_list.py``、
``hevi/director/storyboard.py``(各自的 ``_craft_knowledge`` 私有函数)。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 截断标记。必须以 HTML 注释形式出现:人眼可见(万一 prompt 被打印出来),
# 而渲染时被吞掉(不会把注释当字幕烧进画面)。
_TRUNCATION_TEMPLATE = "<!-- truncated at {n} chars -->"

# stage id -> 有序的 Markdown 文件名。下游阶段会把相关手艺域一并带进来:
# 分镜阶段要带镜头提示词,剪辑阶段要带字幕与音乐,合成阶段要带调色。
STAGE_FILES: dict[str, tuple[str, ...]] = {
    "research": ("01-research.md",),
    "proposal": ("02-proposal.md",),
    "screenplay": ("03-screenplay.md",),
    "storyboard": ("04-storyboard.md", "craft-shot-prompt.md"),
    "materials": ("05-materials.md",),
    "editing": ("06-editing.md", "craft-subtitle.md", "craft-music.md"),
    "composite": ("07-composite.md", "craft-grading.md"),
    "review": ("08-review.md",),
    "subtitle": ("craft-subtitle.md",),
    "grading": ("craft-grading.md",),
    "music": ("craft-music.md",),
    "voice_acting": ("craft-voice-acting.md",),
    "shot_prompt": ("craft-shot-prompt.md",),
}

#: 全部 stage id,顺序即流水线顺序(研究 → 提案 → 脚本 → 分镜 → 素材 → 剪辑 → 合成 → 审片),
#: 后面接五个手艺域。
ALL_STAGE_IDS: tuple[str, ...] = tuple(STAGE_FILES)

# 别名表:中文阶段名、常见同义词、以及 ``NN-`` 文件前缀数字。键统一小写,
# ``-``/空格归一成 ``_``(见 resolve_stage)。
_ALIASES: dict[str, str] = {
    # 导演八阶段
    "研究": "research",
    "调研": "research",
    "选题": "research",
    "research": "research",
    "01": "research",
    "提案": "proposal",
    "策划": "proposal",
    "立项": "proposal",
    "proposal": "proposal",
    "02": "proposal",
    "脚本": "screenplay",
    "剧本": "screenplay",
    "编剧": "screenplay",
    "screenplay": "screenplay",
    "script": "screenplay",
    "03": "screenplay",
    "分镜": "storyboard",
    "分镜头": "storyboard",
    "镜头表": "storyboard",
    "storyboard": "storyboard",
    "04": "storyboard",
    "素材": "materials",
    "素材准备": "materials",
    "拍摄": "materials",
    "material": "materials",
    "materials": "materials",
    "05": "materials",
    "剪辑": "editing",
    "剪片子": "editing",
    "粗剪": "editing",
    "精剪": "editing",
    "editing": "editing",
    "edit": "editing",
    "06": "editing",
    "合成": "composite",
    "后期合成": "composite",
    "特效": "composite",
    "抠像": "composite",
    "composite": "composite",
    "compositing": "composite",
    "07": "composite",
    "审片": "review",
    "审看": "review",
    "成片审查": "review",
    "质检": "review",
    "review": "review",
    "qc": "review",
    "08": "review",
    # 手艺域
    "字幕": "subtitle",
    "字幕条": "subtitle",
    "subtitle": "subtitle",
    "captions": "subtitle",
    "调色": "grading",
    "色彩分级": "grading",
    "分级": "grading",
    "一级校准": "grading",
    "grading": "grading",
    "color": "grading",
    "colour": "grading",
    "音乐": "music",
    "配乐": "music",
    "bgm": "music",
    "音效": "music",
    "music": "music",
    "配音": "voice_acting",
    "配音表演": "voice_acting",
    "旁白": "voice_acting",
    "声音表演": "voice_acting",
    "voice": "voice_acting",
    "voice_acting": "voice_acting",
    "镜头提示词": "shot_prompt",
    "镜头提示": "shot_prompt",
    "提示词": "shot_prompt",
    "shot_prompt": "shot_prompt",
    "shotprompt": "shot_prompt",
    "prompt": "shot_prompt",
}

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)


def knowledge_dir() -> Path:
    """知识库目录的绝对路径(``hevi/skills/knowledge``)。目录可能不存在 —— 调用方要能容错。"""
    return Path(__file__).resolve().parents[1] / "skills" / "knowledge"


def _read(name: str) -> str:
    """读一个知识库文件。缺失或读不动都抛 ValueError,并把可用阶段与实际路径说清楚。"""
    path = knowledge_dir() / name
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(
            f"读取制作手艺知识库失败:{path}({exc})。"
            f"可用阶段:{', '.join(ALL_STAGE_IDS)}。知识库目录必须随仓库一起分发。"
        ) from exc


def _front_matter(text: str) -> str:
    m = _FRONTMATTER_RE.match(text)
    return m.group(1) if m else ""


def _field(text: str, field: str) -> str:
    m = re.search(rf"^{field}:\s*(.+?)\s*$", _front_matter(text), re.MULTILINE)
    return m.group(1) if m else ""


def _unknown(stage: Any) -> ValueError:
    return ValueError(
        f"未知制作阶段:{stage!r}。可用阶段:{', '.join(ALL_STAGE_IDS)}"
        f"(中文别名如 '分镜'/'调色' 也认,完整别名见 hevi/production/craft_knowledge.py)。"
    )


def _truncate(text: str, max_chars: int | None) -> str:
    """按 max_chars 截断,并追加可见标记。``None`` 或 ``<=0`` 表示不限制。"""
    if max_chars is None or max_chars <= 0 or len(text) <= max_chars:
        return text
    marker = _TRUNCATION_TEMPLATE.format(n=max_chars)
    return f"{text[:max_chars]}\n{marker}"


def _normalize(name: str) -> str:
    return name.strip().lower().replace("-", "_").replace(" ", "_")


def resolve_stage(name: str) -> str | None:
    """大小写不敏感 + 别名容忍的阶段名解析:``"分镜"``/``"SUBTITLE"``/``"04"`` 都能命中。

    解析不出来返回 ``None``(而不是抛异常),让调用方决定是报错还是走默认。
    """
    raw = str(name or "").strip()
    if not raw:
        return None
    key = _normalize(raw)
    if key in STAGE_FILES:
        return key
    return _ALIASES.get(key) or _ALIASES.get(raw)


def _resolve_or_raise(name: Any) -> str:
    stage = resolve_stage(str(name))
    if stage is None:
        raise _unknown(name)
    return stage


def load_stage(stage: str, *, max_chars: int | None = None) -> str:
    """加载单个阶段的手艺知识(该阶段所有文件的拼接 Markdown)。

    Args:
        stage: stage id、中文别名或 ``NN-`` 前缀数字。
        max_chars: 截断上限,作用于**拼接结果**;截断时尾部追加可见标记。
            ``None``/``<=0`` 表示不限制。

    Raises:
        ValueError: 阶段未知,或知识库文件缺失/读不动。
    """
    key = _resolve_or_raise(stage)
    body = "\n\n".join(_read(name) for name in STAGE_FILES[key])
    return _truncate(body, max_chars)


def load_stages(stages: Iterable[str], *, max_chars: int | None = None) -> str:
    """加载多个阶段,每段加一个章节标题,用 ``---`` 分隔。阶段去重且保持传入顺序。

    Raises:
        ValueError: 任一阶段未知,或知识库文件缺失/读不动。
    """
    keys: list[str] = []
    for item in stages:
        key = _resolve_or_raise(item)
        if key not in keys:
            keys.append(key)
    if not keys:
        return ""
    blocks = []
    for key in keys:
        title = _stage_title(key)
        body = "\n\n".join(_read(name) for name in STAGE_FILES[key])
        blocks.append(f"## 制作手艺知识:{key}({title})\n\n{body}")
    return _truncate("\n\n---\n\n".join(blocks), max_chars)


def _stage_title(stage: str) -> str:
    """取阶段首份文件 front-matter 里的 title;取不到就退回文件名,不抛错。"""
    for name in STAGE_FILES[stage]:
        try:
            text = _read(name)
        except ValueError:
            continue
        title = _field(text, "title")
        if title:
            return title
    return STAGE_FILES[stage][0]


def list_stages() -> list[dict[str, Any]]:
    """列出全部阶段及其体积。``chars`` 是 load_stage 不截断时的字符数。"""
    return [
        {
            "stage": stage,
            "title": _stage_title(stage),
            "files": list(STAGE_FILES[stage]),
            "chars": sum(len(_read(name)) for name in STAGE_FILES[stage]),
        }
        for stage in ALL_STAGE_IDS
    ]
