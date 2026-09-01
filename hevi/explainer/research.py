"""Research + three-script generation for Explainer Master v8.

Providers are injected at this boundary.  The default implementation uses the
same configured HEVI LLM registry as the existing E0 storyboard generator;
there is deliberately no canned/fake research response when that provider is
missing or returns malformed JSON.
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import re
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from hevi.explainer.contracts import (
    ChapterPlan,
    ConceptExpansion,
    ExplainerCapabilityError,
    ExplainerOutline,
    ExplainerResearchRequest,
    ExplainerScriptDraft,
    ExplainerServiceResult,
    HookDraft,
    HookNarrativeFunction,
    HookNode,
    ResearchFact,
    VisualType,
)

logger = logging.getLogger(__name__)


class ResearchProvider(Protocol):
    async def research(self, topic_or_url: str) -> dict[str, Any]: ...


class ScriptGenerator(Protocol):
    async def generate(
        self, topic_or_url: str, research: dict[str, Any]
    ) -> dict[str, Any]: ...


ResearchCallable = Callable[[str], Awaitable[dict[str, Any]] | dict[str, Any]]
ScriptCallable = Callable[
    [str, dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]
]


_JSON_PROMPT = """你是 HEVI 深度解说研究与脚本编剧。对下面选题做可核验的资料提炼，
并给出“递进式 Hook 矩阵”和若干结构化脚本版本（建议 3 版，至少 1 版）。

硬性要求（违反即视为废稿）：
1. 禁止输出“推荐/不推荐”标签（recommended / not recommended 一律不要）——
   每个 Hook 没有高低之分，只有叙事位置之分。
2. 禁止生成内容重复、或仅换措辞凑数的垃圾 Hook。每个 Hook 必须来自主题知识图谱中
   不同的关键知识节点，并给出它对应的叙事功能档位：
   - opening_suspense：开场总悬念（把最反直觉的矛盾摆到最前面）
   - mid_conflict：中段转折/冲突点（让观众意识到问题的核心死结）
   - climax_breakthrough：高潮解答（给出关键方法/突破，解开死结）
   三档按时间递进，缺档可以补，但档位顺序不能乱。
3. hooks 数量不写死：按主题实际知识节点动态产出（一般 3-6 个），
   不要为了凑数硬写 5 个，也不要少于 1 个。
4. 每个 Hook 必须给出：suggested_placement_s（建议切入秒数，与脚本时间轴一致）、
   narrative_function、关联的核心概念 associated_concepts（如 ["BBGKY 方程", "拓扑树"]）。
5. 不要编造来源；无法核验的事实请降低 confidence 并明确 source 为空。
6. 每个脚本必须有可编辑的 visual scaffold cues。
7. 【深度硬核要求】这是深度硬核解说视频，脚本是拿来配音的正文，不是要点提纲：
   - 字数底线：整体总字数必须落在下方【强制字数与时长要求】按 target_duration
     动态计算的区间内；默认档(1-3 分钟)不得低于 400 字(约 1.5-2 分钟语速)，
     只写两三句话凑数的一律视为废稿。
   - 单段时长：除开场 Hook（5-10 秒）外，中间每个核心解说 cue 至少需要
     30-60 秒的文本量（约 100-200 字），严格按“引入 → 展开 → 收束”组织，
     禁止一句话带过。
   - 逻辑链：visual_type 为 browser_broll、remotion_chart、manim_scene、
     whiteboard 或 infographic 的 cue，text 必须写出完整逻辑链「引入数据 →
     分析反常点 → 解释底层原理 → 得出结论」，只给结论不给过程的视为废稿。
8. 【思考链】每个脚本在 cues 之前必须给出 reasoning_depth 字段，用一段话先说明：
   本版脚本打算如何把核心理论讲透——计划展开哪些反常点、用什么数据/图表支撑、
   从哪个底层原理切入、最后怎么收束到结论。先想清楚再写台词。
9. 【🚨素材吸收与扩写矩阵】每个脚本在 cues 之前必须先输出
   material_coverage_matrix：遍历全部素材/知识节点，每个节点一条
   ConceptExpansion（original_material_point 引用原文知识点或原句；
   deep_explanation 至少 150 字，把前因后果、历史背景、底层原理、
   技术/数学/物理图景与通俗比喻彻底讲透）。矩阵必须 100% 覆盖素材，
   漏掉任何一段即视为废稿。先扩写、后写台词。

选题或材料：{topic}

【因果锚点契约(违反即废稿)】
- 每一项生成内容必须能追溯到输入中的至少两个因果锚点(选题材料/知识点);
- 禁止引入选题中不存在的人名、地名、机构、数据、秘密或背景机制;
- 禁止使用事后信息或未来结果冒充当前事实(如未发生的突破不能写成已有结论);
- facts 必须可溯源, 无法核验的 confidence 调低、source 留空。

只返回 JSON，不要 markdown：
{{
  "research_summary": "用一段话概括调研结论",
  "facts": [{{"claim":"...","source":"...","confidence":0.0}}],
  "hooks": [{{"hook_id":"H1","title":"灾难的根源",
    "narrative_function":"opening_suspense","suggested_placement_s":0.0,
    "text":"为什么经典力学在 BBGKY 方程这里彻底失效？",
    "associated_concepts":["BBGKY 方程"]}}],
  "scripts": [{{"id":"A","title":"...","viewpoint":"...","hook":"...",
    "reasoning_depth":"先用 XX 的反常数据引出矛盾，再拆解 XX 的底层原理，最后落到 XX 结论",
    "material_coverage_matrix":[{{"original_material_point":"素材原句/知识点",
      "deep_explanation":"≥150 字深度扩写:背景、原理、比喻"}}],
    "cues":[{{"step_id":1,"visual_type":"heygen_avatar","text":"...","time_estimate_s":4.5}},
             {{"step_id":2,"visual_type":"browser_broll","target_url":"https://example.gov.cn/report","highlight_selector":".data-table","text":"...","time_estimate_s":8}},
             {{"step_id":3,"visual_type":"remotion_chart","chart_data":{{"type":"bar","labels":[],"values":[]}},"text":"...","time_estimate_s":6}}]}}]
}}"""

# 🚨 极其严格的反压缩与长文本纪律 —— 彻底替换“总结本能”的生成指令。
# 所有脚本生成 prompt(单次生成 + 分章生成)都必须携带这段纪律。
_ANTI_COMPRESSION_PROMPT = """
【🚨 极其严格的反压缩与长文本纪律】:
1. 绝对禁止总结与精简!你的任务是“展开(Expand)”和
   “解构(Deconstruct)”,而不是“总结(Summarize)”。
2. 零遗漏原则:用户提供的素材极其硬核,你必须将其拆解为多个 Concept,
   并在 `material_coverage_matrix` 中做到 100% 覆盖,
   绝不允许漏掉任何一段素材!
3. 自主挖掘与补充:如果素材中的某一段是一句硬核结论,你必须利用你的
   知识储备,挖出它的“前因后果、历史背景、技术实现细节或
   数学/物理图景”,并用生动的比喻讲透。
4. 降维打击与升维思考:对于硬核概念,按照“抛出问题 -> 讲解底层机制 ->
   使用通俗可视化比喻 -> 给出结论”的 4 步逻辑来写台词。
5. 脚本字数:有了上述的深度扩写,你的 `cues` 旁白总字数必须自然达到
   所选时长的要求(例如 10 分钟至少 2500 字)。
   每一个 cue 的旁白都要极其丰满!
"""

# 正常语速下约 250 字/分钟 —— 精准目标时长反推总字数底线与视觉 Cue 数量。
_WORDS_PER_MINUTE = 250

# 超长视频分章阈值:目标时长上界超过 6 分钟(需求字数 > 1500 字)时,单次 JSON
# 产出全部台词会导致 Attention 衰减与 JSON 损坏,必须切换为分章迭代生成。
_CHUNKED_MAX_MINUTES = 6.0


def _should_chunk(target_duration: str) -> bool:
    """是否启用分章生成:目标时长上界超过 6 分钟(≈ >1500 字)即分章。"""
    _min, max_minutes = _duration_bounds(target_duration)
    return max_minutes > _CHUNKED_MAX_MINUTES


def _duration_bounds(target_duration: str) -> tuple[float, float]:
    """解析 target_duration('1-3' 或 '8')为 (低分钟数, 高分钟数)。"""
    value = target_duration.strip()
    if "-" in value:
        parts = value.split("-")
        return float(parts[0]), float(parts[1])
    minutes = float(value)
    return minutes, minutes


def _duration_constraints(target_duration: str) -> str:
    """按目标时长动态计算严格的总字数底线与视觉 Cue 数量要求。

    字数 = 分钟数 × 250 字/分钟;视觉 Cue 至少每半分钟 1 个(约 2 个/分钟)。
    挂在完整 Prompt 末尾,对 LLM 而言是追加在基础契约之后的权威约束。
    """
    min_minutes, max_minutes = _duration_bounds(target_duration)
    min_words = int(min_minutes * _WORDS_PER_MINUTE)
    max_words = int(max_minutes * _WORDS_PER_MINUTE)
    min_cues = int(min_minutes * 2)
    body = f"""
【强制字数与时长要求】：
1. 目标时长: {target_duration} 分钟。
2. 文本总字数: 必须严格控制在 {min_words} 到 {max_words} 字之间！绝对不能低于 {min_words} 字！
3. 知识密度与分段: 至少需要 {min_cues} 个独立的视觉 Cue (段落)。
"""
    depth_line = (
        "4. 深度约束: 不要只给结论，必须通过数据引入、反常点分析、理论拆解"
        "（甚至公式/代码）、案例论证等多个维度把问题彻底讲透。"
        "把内容掰开揉碎了写，越硬核越好！\n"
    )
    return body + depth_line


def _build_research_prompt(topic_or_url: str, target_duration: str) -> str:
    """组装完整研究 Prompt:基础 JSON 契约 + target_duration 动态字数约束 + 反压缩纪律。

    反压缩纪律必须挂在最后(位置=权威):在基础契约与动态字数约束之后追加,
    对 LLM 而言是最强收尾指令,专门压制“总结本能”。
    """
    return (
        _JSON_PROMPT.format(topic=topic_or_url)
        + _duration_constraints(target_duration)
        + _ANTI_COMPRESSION_PROMPT
    )


def _strip_markdown_fences(content: str) -> str:
    """去掉 ```json ... ``` 代码围栏(本地小模型常把 JSON 包在 markdown 里)。"""
    return re.sub(r"```(?:json)?\s*", "", content, flags=re.IGNORECASE)


def _extract_first_object(text: str) -> str | None:
    """找第一个 '{' 并用字符串感知扫描器找其配对的 '}',返回该完整对象文本。

    与旧版贪心正则 `{.*}`(从第一个 { 抓到最后一个 })不同,这里在遇到
    第一个真正闭合的 '}' 就停止,从而正确处理:
    - 前置铺垫文字(含 { 的散文)—— 从真正的对象起点开始
    - 尾随补充说明 / 多个 JSON 块 —— 只取第一个完整对象
    - 字符串值里的 { } / 转义引号 —— 扫描时忽略,不干扰括号配对
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        ch = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _sanitise_json(text: str) -> str:
    """修复 LLM 高频 JSON 错误:去掉字符串外部的注释与尾随逗号。

    单趟字符串感知扫描:字符串内部的 //(如 https://)、,}(如文案里的
    “然后,}”)原样保留,绝不误伤。修复不了的结构性错误(缺逗号等)留给
    上层重试 + 出错片段定位。
    """
    out: list[str] = []
    index, length = 0, len(text)
    in_string = False
    escaped = False
    while index < length:
        ch = text[index]
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            index += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            index += 1
            continue
        # 块注释 /* ... */(字符串外)
        if ch == "/" and index + 1 < length and text[index + 1] == "*":
            end = text.find("*/", index + 2)
            index = length if end == -1 else end + 2
            continue
        # 行注释 //(字符串外)—— URL 只在字符串值里出现,不会误伤
        if ch == "/" and index + 1 < length and text[index + 1] == "/":
            end = text.find("\n", index + 2)
            index = length if end == -1 else end + 1
            continue
        # 尾随逗号:逗号后(可带空白)紧跟 } 或 ]
        if ch == ",":
            lookahead = index + 1
            while lookahead < length and text[lookahead] in " \t\r\n":
                lookahead += 1
            if lookahead < length and text[lookahead] in "}]":
                index = lookahead
                continue
        out.append(ch)
        index += 1
    return "".join(out)


def _extract_json(content: str) -> dict[str, Any]:
    """多层防御式 JSON 提取:围栏剥离 → 平衡括号取首个完整对象 → 清洗修复 → 容错解析。

    修复顺序(每层都做字符串感知扫描,绝不误伤字符串内容):
    1. 去掉 ```json``` markdown 围栏;
    2. 取第一个真正配对的完整 JSON 对象(旧版 `{.*}` 会吞掉尾随散文里的
       '}',导致 “Expecting ',' delimiter” 这类结构性报错);
    3. 清洗字符串外的注释与尾随逗号后再试一次;
    4. 仍失败则用容错流解析器(容忍缺逗号/全角标点/内嵌引号/裸换行/True|None);
    5. 全部失败才把出错位置附近的原文片段一并报出,便于定位模型输出。
    """
    cleaned = _strip_markdown_fences(content)
    candidates: list[str] = []
    first_object = _extract_first_object(cleaned)
    if first_object is not None:
        candidates.append(first_object)
    if cleaned not in candidates:
        candidates.append(cleaned)
    last_error: Exception | None = None
    for candidate in candidates:
        for loader in (_loads_strict, _loads_sanitised, _tolerant_json_loads):
            try:
                value = loader(candidate)
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                last_error = exc
                continue
            if isinstance(value, dict):
                return value
            if isinstance(value, list) and value and isinstance(value[0], dict):
                # 模型把结果包成单元素数组时,取内层对象。
                return value[0]
            last_error = ExplainerCapabilityError(
                "MODEL_OUTPUT_INVALID", "模型研究结果不是 JSON 对象"
            )
    # 定位失败点:带出原文片段,方便排查/复现模型输出。
    position = getattr(last_error, "pos", 0) if last_error else 0
    snippet = cleaned[max(0, position - 40) : position + 40]
    raise ExplainerCapabilityError(
        "MODEL_OUTPUT_INVALID",
        f"模型研究 JSON 无法解析: {last_error}; 出错附近原文: ...{snippet!r}...",
    ) from last_error


def _loads_strict(text: str) -> Any:
    return json.loads(text)


def _loads_sanitised(text: str) -> Any:
    return json.loads(_sanitise_json(text))


def _tolerant_json_loads(text: str) -> Any:
    """容错 JSON 流解析器:直接消费字符流,容忍本地小模型的高频结构错误。"""
    return _TolerantJsonParser(text).parse()


class _JsonRepairError(ValueError):
    """容错解析失败:携带出错位置(pos),供上层把错误片段定位到真正坏点。"""

    def __init__(self, message: str, pos: int) -> None:
        super().__init__(f"{message} at char {pos}")
        self.pos = pos


class _TolerantJsonParser:
    """容错 JSON 流解析器 —— JSON 恢复的最终防线。

    容忍(全部只在字符串外生效,字符串内容原样保留):
    - 缺失逗号(换行分隔字段是本地模型的头号死因);
    - 全角标点 `，`/`：`(中文模型常把结构分隔符打成全角);
    - 未转义的内嵌 ASCII 引号(解说词里给术语加引号忘了转义);
    - 字符串内的裸换行/控制字符(模型写多行旁白不转义);
    - `True/False/None` 等 Python 字面量;未加引号的 key;
    - 输出被 max_tokens 截断:就地收束,抢救已生成的部分内容。
    """

    def __init__(self, text: str) -> None:
        self.text = text
        self.length = len(text)
        self.pos = 0

    def error(self, message: str) -> None:
        raise _JsonRepairError(message, self.pos)

    def skip_ws(self) -> None:
        text, length = self.text, self.length
        while self.pos < length:
            ch = text[self.pos]
            if ch in " \t\r\n\u3000\ufeff":
                self.pos += 1
                continue
            if ch == "/" and self.pos + 1 < length:
                nxt = text[self.pos + 1]
                if nxt == "/":
                    end = text.find("\n", self.pos + 2)
                    self.pos = length if end == -1 else end + 1
                    continue
                if nxt == "*":
                    end = text.find("*/", self.pos + 2)
                    self.pos = length if end == -1 else end + 2
                    continue
            break

    def parse(self) -> Any:
        self.skip_ws()
        # 跳过前置垃圾(含铺垫散文),直到第一个 { 或 [
        while self.pos < self.length and self.text[self.pos] not in "{[":
            self.pos += 1
        if self.pos >= self.length:
            self.error("no object start")
        return self.parse_value()

    def parse_value(self) -> Any:
        self.skip_ws()
        if self.pos >= self.length:
            self.error("unexpected end")
        ch = self.text[self.pos]
        if ch == "{":
            return self.parse_object()
        if ch == "[":
            return self.parse_array()
        if ch in "\"'":
            return self.parse_string(ch)
        if ch in "tT":
            return self.parse_literal(("true",), True)
        if ch in "fF":
            return self.parse_literal(("false",), False)
        if ch in "nN":
            # None / Null / null 都是本地模型的常见写法
            return self.parse_literal(("null", "none"), None)
        if ch in "+-0123456789.":
            return self.parse_number()
        self.error(f"unexpected char {ch!r}")
        raise AssertionError("unreachable")  # pragma: no cover

    def parse_literal(self, variants: tuple[str, ...], value: Any) -> Any:
        for variant in variants:
            head = self.text[self.pos : self.pos + len(variant)].lower()
            if head == variant:
                self.pos += len(variant)
                return value
        self.error(f"bad literal {self.text[self.pos : self.pos + 8]!r}")
        raise AssertionError("unreachable")  # pragma: no cover

    def parse_number(self) -> Any:
        text, length = self.text, self.length
        start = self.pos
        if self.pos < length and text[self.pos] in "+-":
            self.pos += 1
        while self.pos < length and text[self.pos].isdigit():
            self.pos += 1
        if self.pos < length and text[self.pos] == ".":
            self.pos += 1
            while self.pos < length and text[self.pos].isdigit():
                self.pos += 1
        if self.pos < length and text[self.pos] in "eE":
            self.pos += 1
            if self.pos < length and text[self.pos] in "+-":
                self.pos += 1
            while self.pos < length and text[self.pos].isdigit():
                self.pos += 1
        raw = text[start : self.pos]
        try:
            return float(raw) if any(c in raw for c in ".eE") else int(raw)
        except ValueError:
            digits = re.sub(r"[^0-9]", "", raw)
            if digits:
                return int(digits)
            raise ValueError(f"bad number {raw!r} at char {self.pos}") from None

    def parse_string(self, quote_char: str) -> str:
        text, length = self.text, self.length
        self.pos += 1  # 开引号
        out: list[str] = []
        escapes = {
            "n": "\n", "t": "\t", "r": "\r", "b": "\b",
            "f": "\f", "/": "/", "\\": "\\",
            '"': '"', "'": "'",
        }
        while self.pos < length:
            ch = text[self.pos]
            if ch == "\\":
                self.pos += 1
                if self.pos >= length:
                    break
                esc = text[self.pos]
                if esc == "u":
                    hex_part = text[self.pos + 1 : self.pos + 5]
                    try:
                        out.append(chr(int(hex_part, 16)))
                        self.pos += 4
                    except ValueError:
                        out.append("u")
                else:
                    out.append(escapes.get(esc, esc))
                self.pos += 1
                continue
            if ch == quote_char:
                # 收尾引号判定:下一个非空白字符是结构符(, } ] : 全角 ， ：)或
                # 另一个引号(缺逗号后紧跟下一个 key/元素)或 EOF → 收尾;
                # 否则视为正文里的内嵌引号(模型常忘了转义术语引号)。
                # ⚠️ 引号必须在收尾集合里:缺逗号的相邻字符串被吞进当前字符串,
                # 会导致整个文档被吃光直到 EOF(“unterminated string” 的头号死因)。
                nxt = self.pos + 1
                while nxt < length and text[nxt] in " \t\r\n":
                    nxt += 1
                if nxt >= length or text[nxt] in ",}]:：，\"'":
                    self.pos = nxt
                    return "".join(out)
                out.append(ch)  # 内嵌引号
                self.pos += 1
                continue
            # 其他字符(含未转义的换行/控制符)一律保留 —— 容错的关键
            out.append(ch)
            self.pos += 1
        # 输出被截断(max_tokens 耗尽等):就地收束字符串,保留已生成内容
        return "".join(out)

    def parse_key(self) -> str:
        text = self.text
        ch = text[self.pos]
        if ch in "\"'":
            return self.parse_string(ch)
        # 未加引号的 key:收集到结构分隔符为止
        start = self.pos
        while self.pos < self.length and text[self.pos] not in ":：,}][{":
            self.pos += 1
        key = text[start : self.pos].strip().strip("\"'")
        if not key:
            self.error("empty key")
        return key

    def parse_object(self) -> dict[str, Any]:
        text, length = self.text, self.length
        self.pos += 1  # {
        result: dict[str, Any] = {}
        self.skip_ws()
        if self.pos < length and text[self.pos] == "}":
            self.pos += 1
            return result
        while True:
            self.skip_ws()
            if self.pos >= length:
                return result  # 输出被截断:收尾已生成部分
            if text[self.pos] == "}":
                self.pos += 1
                return result
            key = self.parse_key()
            self.skip_ws()
            if self.pos >= length:
                return result  # 悬空 key:截断处丢弃
            if text[self.pos] in ":：":
                self.pos += 1
            self.skip_ws()
            if self.pos >= length:
                return result  # value 缺失:截断处丢弃
            value = self.parse_value()
            result[key] = value
            self.skip_ws()
            if self.pos >= length:
                return result  # 截断:收尾
            if text[self.pos] in ",，":
                self.pos += 1
                continue
            if text[self.pos] == "}":
                self.pos += 1
                return result
            # 缺逗号(换行分隔字段):下一个字符不是 } 就当新 key 开始,继续解析
            continue

    def parse_array(self) -> list[Any]:
        text, length = self.text, self.length
        self.pos += 1  # [
        result: list[Any] = []
        self.skip_ws()
        if self.pos < length and text[self.pos] == "]":
            self.pos += 1
            return result
        while True:
            self.skip_ws()
            if self.pos >= length:
                return result  # 输出被截断:收尾已生成部分
            if text[self.pos] == "]":
                self.pos += 1
                return result
            result.append(self.parse_value())
            self.skip_ws()
            if self.pos >= length:
                return result  # 截断:收尾
            if text[self.pos] in ",，":
                self.pos += 1
                continue
            if text[self.pos] == "]":
                self.pos += 1
                return result
            # 缺逗号(换行分隔元素):下一个字符不是 ] 就当新元素开始,继续解析
            continue


async def _invoke(provider: Any, *args: Any, **kwargs: Any) -> Any:
    result = provider(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


def _default_llm() -> Any:
    try:
        from obase.provider_registry import ProviderRegistry

        registry = ProviderRegistry.get()
        # v9.1: OpenCode 替换 NIM 优先; TeamoRouter grok/pi 为免费云槽;
        # 再回落 NIM(2 key 轮换) → default。
        for name in ("opencode", "grok", "pi", "teamo_free", "nim", "default"):
            try:
                return registry.llm(name)
            except Exception:
                continue
        raise ProviderRegistry.ProviderNotFoundError(  # type: ignore[attr-defined]
            "no llm provider registered"
        )
    except Exception as exc:  # pragma: no cover - depends on deployment
        raise ExplainerCapabilityError(
            "CAPABILITY_UNAVAILABLE",
            "研究模型不可用：未配置默认 LLM Provider",
            action="配置 ProviderRegistry 的 default LLM 后重试",
        ) from exc


_OUTLINE_PROMPT = """你是 HEVI 深度解说研究总编（分章大纲模式）。下面选题将产出
一个超长硬核解说视频（目标时长 {target_duration} 分钟，约 {min_words} 到 {max_words} 字）。
单次生成全部台词会导致 Attention 衰减与 JSON 损坏，所以本轮你只负责“研究 + 分章大纲
+ 素材吸收与扩写矩阵 + 版本元信息”，**绝不写任何 cues 台词**（台词在下一阶段逐章生成）。

硬性要求（违反即废稿）：
1. 【🚨素材吸收与扩写矩阵】material_coverage_matrix 必须把选题的全部硬核知识节点
   100% 拆成 ConceptExpansion：original_material_point=原文知识点或原句；
   deep_explanation=至少 150 字的深度扩写（前因后果、历史背景、底层原理、
   技术/数学/物理图景 + 通俗比喻）。漏掉任何一段素材即废稿。
2. chapters：把整支视频拆成 4-5 个章节。每章 goal 用一段话写清“本章要把什么讲透、
   从哪个反常点切入、用什么数据/图表/比喻支撑、收束到什么结论”。每章 expansions
   必须是 material_coverage_matrix 中与本章主题相关的子集（非空），逐章喂给编剧。
3. hooks：递进式 Hook 矩阵（opening_suspense → mid_conflict → climax_breakthrough），
   按知识节点动态产出 3-6 个，每个给 suggested_placement_s 与 associated_concepts。
4. versions：3 个脚本版本元信息（id/title/viewpoint/hook/reasoning_depth），视角各不相同
   （数据派/原理派/故事派等），hook 引用 Hook 的 hook_id 或文本；reasoning_depth 写清
   本版如何把核心理论讲透。
5. facts：可核验事实清单；禁止编造来源，无法核验的事实 confidence 调低、source 留空。
6. research_summary：一段话概括调研结论。
7. 禁止输出 recommended / 不推荐标签。

选题或材料：{topic}

【因果锚点契约(违反即废稿)】
- 每一项生成内容必须能追溯到输入中的至少两个因果锚点(选题材料/知识点);
- 禁止引入选题中不存在的人名、地名、机构、数据、秘密或背景机制;
- 禁止使用事后信息或未来结果冒充当前事实(如未发生的突破不能写成已有结论);
- facts 必须可溯源, 无法核验的 confidence 调低、source 留空。

只返回 JSON，不要 markdown：
{{
  "research_summary": "...",
  "facts": [{{"claim":"...","source":"...","confidence":0.0}}],
  "hooks": [{{"hook_id":"H1","title":"...",
    "narrative_function":"opening_suspense","suggested_placement_s":0.0,
    "text":"...","associated_concepts":["..."]}}],
  "material_coverage_matrix": [
    {{"original_material_point":"素材中的原句/知识点",
      "deep_explanation":"150-300 字深度扩写","source":"出处"}}
  ],
  "versions": [
    {{"id":"A","title":"版本 A","viewpoint":"...","hook":"H1",
      "reasoning_depth":"本版如何把核心理论讲透..."}}
  ],
  "chapters": [
    {{"chapter_id":"C1","title":"第 1 章标题","goal":"本章要讲透什么...",
      "expansions":[{{"original_material_point":"...","deep_explanation":"..."}}]}}
  ]
}}
"""


async def _llm_research(topic_or_url: str, target_duration: str = "1-3") -> dict[str, Any]:
    """研究入口:按目标时长路由生成策略。

    - ≤6 分钟(≤1500 字):单次生成(带素材吸收矩阵 + 反压缩纪律)。
    - >6 分钟(>1500 字):分章生成 —— Step A 大纲/矩阵 → Step B 逐章 cues →
      Step C 合并,彻底突破单次 LLM 生成的字数与深度极限。
    """
    llm = _default_llm()
    if _should_chunk(target_duration):
        return await _llm_research_chunked(llm, topic_or_url, target_duration)
    return await _llm_json(
        llm, _build_research_prompt(topic_or_url, target_duration), max_tokens=8_000
    )


async def _llm_json(
    llm: Any, prompt: str, max_tokens: int, *, retries: int = 1
) -> dict[str, Any]:
    """调用 LLM 并强解析 JSON。

    JSON 解析失败(本地小模型常见)自动重试;Provider 层错误直接包装成
    CAPABILITY_UNAVAILABLE(不重试,重试也救不回来)。分章模式下每章独立调用,
    单章 JSON 损坏只重试本章,不浪费整支视频。
    """
    last_error: str | None = None
    for attempt in range(retries + 1):
        try:
            response = await _invoke(
                llm,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                result_format="json",
            )
        except ExplainerCapabilityError:
            raise
        except Exception as exc:
            raise ExplainerCapabilityError(
                "CAPABILITY_UNAVAILABLE",
                f"研究模型调用失败: {exc}",
                action="检查 LLM Provider 健康状态",
            ) from exc
        content = response.get("content") if isinstance(response, dict) else str(response)
        if not isinstance(content, str) or not content.strip():
            raise ExplainerCapabilityError("MODEL_OUTPUT_INVALID", "研究模型返回空正文")
        try:
            return _extract_json(content)
        except ExplainerCapabilityError as exc:
            last_error = str(exc)
            logger.warning("LLM JSON 解析失败(第 %s 次尝试): %s", attempt + 1, exc)
    raise ExplainerCapabilityError(
        "MODEL_OUTPUT_INVALID", f"模型 JSON 多次解析失败: {last_error}"
    )


def _build_chapter_cues_prompt(
    topic_or_url: str,
    target_duration: str,
    version: Any,
    chapter: ChapterPlan,
    chapter_min_words: int,
    chapter_max_words: int,
    chapter_count: int,
) -> str:
    """Step B 逐章台词 prompt:只喂本章素材的深度扩写,强制写满本章字数。"""
    version_block = (
        f"版本 {version.id}({version.title})\n"
        f"视角: {version.viewpoint}\n"
        f"Hook: {version.hook}\n"
        f"思考链: {version.reasoning_depth}"
    )
    expansion_block = "\n".join(
        f"【素材点 {index}】{entry.original_material_point}\n"
        f"【深度扩写】{entry.deep_explanation}"
        for index, entry in enumerate(chapter.expansions, start=1)
    )
    min_cues = max(2, int(chapter_min_words / 150))
    return f"""你是 HEVI 深度解说编剧(分章生成模式,第 {chapter.chapter_id} 章)。
任务:只为本章节写出极其丰满的解说台词与视觉 Cue。不要写其他章节,不要重复
开场/结尾,不要全局总结——把本章素材彻底讲透。

{version_block}

本章标题:{chapter.title}
本章要讲透的目标:{chapter.goal}
本章吸收并扩写的素材(必须全部用到,不得遗漏):
{expansion_block}

{_ANTI_COMPRESSION_PROMPT}

【本章字数与 Cue 数量】全片共 {chapter_count} 章,目标总字数约
{chapter_min_words * chapter_count} 到 {chapter_max_words * chapter_count} 字;
本章需要 {chapter_min_words} 到 {chapter_max_words} 字,
至少 {min_cues} 个独立的视觉 Cue。
每个 cue 的 text 都要极其丰满(核心段落 100-200 字),严格按
“抛出问题 -> 讲解底层机制 -> 使用通俗可视化比喻 -> 给出结论”
的 4 步逻辑展开,禁止一句话带过。
visual_type 从 heygen_avatar / broll_news / browser_broll / broll_stock /
data_screenshot / remotion_chart / remotion_code / manim_scene / whiteboard /
infographic / voiceover 中选择,与解说内容匹配;公式、推导、坐标轴、逐步揭示
用 manim_scene(visual_config 可带 recipe/tex,例如 recipe=equation, tex="E=mc^2");
板书/分区手绘用 whiteboard;条目列表、步骤或因果信息图用 infographic
(入场只跟旁白短语,禁止按字数估时);
step_id 从 1 开始连续编号。

选题或材料:{topic_or_url}

只返回 JSON,不要 markdown:
{{"cues":[{{"step_id":1,"visual_type":"heygen_avatar","text":"...","time_estimate_s":6}},{{"step_id":2,"visual_type":"remotion_chart","chart_data":{{"type":"bar","labels":[],"values":[]}},"text":"...","time_estimate_s":8}}]}}
"""


def _coerce_outline(raw: dict[str, Any], topic_or_url: str) -> dict[str, Any]:
    """分章大纲容错规整:Step A 产出不规范/被截断时尽量抢救,绝不整单废掉。

    处理本地模型高频事故:
    1. hooks.narrative_function 越界(模型自造档位,如 'philosophical_lesson')
       → 按序轮换合法档位;纯文本 hook → 包装成合法节点。
    2. facts 是纯文本 → 包装成 {claim: ...}。
    3. chapters[].expansions[] 缺/过短 deep_explanation(常被 max_tokens 截断)
       → 用原文素材点补占位扩写,台词阶段围绕原文点自主扩写;整章扩写丢失
       → 用章目标合成一条占位扩写,保底台词阶段有米下锅。
    4. versions 缺失/为空(大纲 JSON 末字段,最容易被截掉) → 用 research_summary
       + 首个 hook 合成一个默认版本,保底产出一版完整脚本。
    """
    data = dict(raw)
    # ── hooks ──
    hooks: list[dict[str, Any]] = []
    for index, item in enumerate(data.get("hooks") or []):
        function = _NARRATIVE_ORDER[index % len(_NARRATIVE_ORDER)]
        if isinstance(item, str) and item.strip():
            hooks.append(
                {"hook_id": f"H{index + 1}", "text": item.strip(),
                 "narrative_function": function}
            )
            continue
        if not isinstance(item, dict):
            continue
        hook = dict(item)
        if hook.get("narrative_function") not in _NARRATIVE_ORDER:
            hook["narrative_function"] = function
        hooks.append(hook)
    data["hooks"] = hooks[:12]  # HookNode 上限 12,超出截断
    # ── facts ──
    data["facts"] = [
        item if isinstance(item, dict) else {"claim": str(item).strip()}
        for item in data.get("facts") or []
        if (isinstance(item, dict) or (isinstance(item, str) and item.strip()))
    ]
    # ── chapters + expansions ──
    chapters: list[dict[str, Any]] = []
    for index, item in enumerate(data.get("chapters") or []):
        if not isinstance(item, dict):
            continue
        chapter = dict(item)
        chapter.setdefault("chapter_id", f"C{index + 1}")
        chapter.setdefault("title", f"第{index + 1}章")
        goal = str(chapter.get("goal") or "").strip()
        if len(goal) < 20:  # ChapterPlan.goal 下限 20 字
            goal = (goal + "(本章围绕标题所述核心内容展开讲解,把相关知识点彻底讲透。)")[:2_000]
            chapter["goal"] = goal
        expansions: list[dict[str, Any]] = []
        for entry in chapter.get("expansions") or []:
            if not isinstance(entry, dict):
                continue
            expansion = dict(entry)
            point = str(expansion.get("original_material_point") or "").strip()
            deep = str(expansion.get("deep_explanation") or "").strip()
            if len(deep) < 50:  # deep_explanation 下限 50 字(缺失/被截断)
                expansion["deep_explanation"] = (
                    f"{point or '核心素材点'}:模型直出缺少扩写,台词生成时必须围绕该素材点"
                    "自主挖掘前因后果、历史背景、底层原理与通俗比喻,"
                    "按“抛出问题→机制→比喻→结论”展开讲透,不得一句话带过。"
                )
            expansions.append(expansion)
        if not expansions:
            expansions.append(
                {
                    "original_material_point": str(
                        chapter.get("title") or f"第{index + 1}章核心内容"
                    ),
                    "deep_explanation": (
                        f"{goal}:模型直出缺少扩写,台词生成时必须围绕本章目标自主挖掘"
                        "背景、底层原理与通俗比喻,按“抛出问题→机制→比喻→结论”展开讲透。"
                    ),
                }
            )
        chapter["expansions"] = expansions
        chapters.append(chapter)
    data["chapters"] = chapters
    # ── versions ──
    versions = data.get("versions")
    if not isinstance(versions, list) or not versions:
        first_hook = hooks[0] if hooks else {}
        summary = str(data.get("research_summary") or "").strip()
        data["versions"] = [
            {
                "id": "A",
                "title": summary[:40] or f"{topic_or_url[:24]}深度解析",
                "viewpoint": "深度解析",
                "hook": str(first_hook.get("hook_id") or first_hook.get("text") or ""),
                "reasoning_depth": summary or "按章节目标逐章展开,把核心理论讲透",
            }
        ]
    return data


async def _llm_research_chunked(
    llm: Any, topic_or_url: str, target_duration: str
) -> dict[str, Any]:
    """分章生成(>6 分钟/ >1500 字):Step A → Step B → Step C。

    Step A: 只让 LLM 输出研究 + 素材吸收与扩写矩阵 + 4-5 章大纲 + 版本元信息
            (不写任何台词,规避超长 JSON 的 Attention 衰减与损坏)。
    Step B: for 循环逐章把该章素材的深度扩写喂给 LLM,逐个章节生成 cues。
    Step C: Python 后端按版本合并各章 cues、重排 step_id、回填素材矩阵,
            包装成与单次生成同构的 raw dict,交给 _normalise 统一校验。
    """
    min_minutes, max_minutes = _duration_bounds(target_duration)
    min_words = int(min_minutes * _WORDS_PER_MINUTE)
    max_words = int(max_minutes * _WORDS_PER_MINUTE)

    # ── Step A: 大纲 + 素材吸收矩阵 + 版本元信息(无 cues) ──
    outline_prompt = _OUTLINE_PROMPT.format(
        topic=topic_or_url,
        target_duration=target_duration,
        min_words=min_words,
        max_words=max_words,
    )
    # Step A 的 JSON 很大(4-5 章 × 深度扩写),token 上限给足 8000,
    # 并把 chapters 放在 JSON 末尾:截断只损失可抢救的扩写,不损失 versions。
    outline_raw = await _llm_json(llm, outline_prompt, max_tokens=8_000)
    try:
        outline = ExplainerOutline.model_validate(_coerce_outline(outline_raw, topic_or_url))
    except Exception as exc:
        raise ExplainerCapabilityError(
            "MODEL_OUTPUT_INVALID", f"分章大纲校验失败: {exc}"
        ) from exc
    if not outline.material_coverage_matrix:
        # 矩阵被截断时,从章节扩写重建(章节扩写是矩阵的子集分组)。
        rebuilt = [entry for chapter in outline.chapters for entry in chapter.expansions]
        if not rebuilt:
            raise ExplainerCapabilityError(
                "MODEL_OUTPUT_INVALID", "分章大纲缺少 material_coverage_matrix(素材吸收与扩写矩阵)"
            )
        outline = outline.model_copy(update={"material_coverage_matrix": rebuilt})

    # 每章字数预算:把全片字数均摊到章节,保证最终总字数落在目标区间。
    chapter_count = len(outline.chapters)
    chapter_min = max(120, min_words // chapter_count)
    chapter_max = max(chapter_min, max_words // chapter_count)
    matrix_dumps = [entry.model_dump() for entry in outline.material_coverage_matrix]

    # ── Step B + C: 逐版本 × 逐章生成 cues,再按章节顺序合并 ──
    scripts: list[dict[str, Any]] = []
    for version in outline.versions:
        cues: list[dict[str, Any]] = []
        for chapter in outline.chapters:
            chapter_prompt = _build_chapter_cues_prompt(
                topic_or_url,
                target_duration,
                version,
                chapter,
                chapter_min,
                chapter_max,
                chapter_count,
            )
            chapter_raw = await _llm_json(llm, chapter_prompt, max_tokens=4_000)
            chapter_cues = chapter_raw.get("cues")
            if not isinstance(chapter_cues, list):
                # 空数组也重试一次:单章生成失败不应浪费整支视频。
                if not chapter_cues:
                    chapter_raw = await _llm_json(llm, chapter_prompt, max_tokens=4_000)
                    chapter_cues = chapter_raw.get("cues")
                if not isinstance(chapter_cues, list):
                    raise ExplainerCapabilityError(
                        "MODEL_OUTPUT_INVALID",
                        f"章节 {chapter.chapter_id}({version.id})的 cues 不是数组",
                    )
            cues.extend(cue for cue in chapter_cues if isinstance(cue, dict))
        if not cues:
            raise ExplainerCapabilityError(
                "MODEL_OUTPUT_INVALID", f"版本 {version.id} 逐章合并后没有台词"
            )
        for index, cue in enumerate(cues, start=1):
            cue["step_id"] = index
        scripts.append(
            {
                "id": version.id,
                "title": version.title,
                "viewpoint": version.viewpoint,
                "hook": version.hook,
                "reasoning_depth": version.reasoning_depth,
                # 每个版本回填同一份素材吸收与扩写矩阵(Step A 产物)。
                "material_coverage_matrix": [dict(entry) for entry in matrix_dumps],
                "cues": cues,
            }
        )

    return {
        "research_summary": outline.research_summary,
        "facts": [fact.model_dump() for fact in outline.facts],
        "hooks": [hook.model_dump() for hook in outline.hooks],
        "material_coverage_matrix": [dict(entry) for entry in matrix_dumps],
        "scripts": scripts,
    }


async def _mcp_research(topic_or_url: str) -> dict[str, Any] | None:
    """Use a registered GPT Researcher MCP client when deployment provides it."""
    try:
        from obase.mcp_client import McpClientRegistry

        client_name = os.environ.get("HEVI_EXPLAINER_RESEARCH_MCP", "gpt_researcher")
        client = McpClientRegistry.get(client_name)
    except (ImportError, KeyError):
        return None
    try:
        tools = await client.list_tools()
        names = {
            str(tool.get("name"))
            for tool in tools
            if isinstance(tool, dict) and tool.get("name")
        }
        tool_name = next(
            (name for name in ("research", "deep_research", "gpt_research") if name in names),
            None,
        )
        if tool_name is None:
            raise ExplainerCapabilityError(
                "CAPABILITY_UNAVAILABLE", "GPT Researcher MCP 未暴露 research 工具"
            )
        result = await client.call_tool(
            tool_name,
            {"query": topic_or_url, "topic": topic_or_url, "max_sources": 8},
        )
        if isinstance(result, dict):
            return result
        content = getattr(result, "text", None) or getattr(result, "content", None)
        if isinstance(content, str):
            return _extract_json(content)
        raise ExplainerCapabilityError("MODEL_OUTPUT_INVALID", "GPT Researcher MCP 返回格式错误")
    except ExplainerCapabilityError:
        raise
    except Exception as exc:
        raise ExplainerCapabilityError(
            "CAPABILITY_UNAVAILABLE", f"GPT Researcher MCP 调用失败: {exc}"
        ) from exc


async def _call_provider(provider: Any, topic_or_url: str) -> dict[str, Any]:
    if hasattr(provider, "research"):
        value = await _invoke(provider.research, topic_or_url)
    else:
        value = await _invoke(provider, topic_or_url)
    if not isinstance(value, dict):
        raise ExplainerCapabilityError("MODEL_OUTPUT_INVALID", "调研 Provider 返回格式错误")
    return value


_NARRATIVE_ORDER: tuple[HookNarrativeFunction, ...] = (
    "opening_suspense",
    "mid_conflict",
    "climax_breakthrough",
)
# v9: 矩阵数量按知识节点动态产出,不写死 5;仍设一个防失控上限。
_MAX_HOOKS = 12


def _to_hook_node(item: Any, index: int) -> HookNode:
    """Accept both the v9 HookNode shape and legacy HookDraft/plain-text shape.

    Legacy ``recommended`` labels are intentionally dropped — v9 prompts forbid
    them and the UI no longer renders single-choice recommendations.
    """
    if isinstance(item, dict):
        if any(key in item for key in ("hook_id", "narrative_function", "associated_concepts")):
            if item.get("narrative_function"):
                # LLM 输出枚举值不可靠(如拼错 opening_suspuspense) → 相似度归一。
                item = {
                    **item,
                    "narrative_function": _normalise_narrative_function(
                        item["narrative_function"]
                    ),
                }
            node = HookNode.model_validate(item)
            if not node.hook_id:
                node = node.model_copy(update={"hook_id": f"H{index + 1}"})
            if not node.title:
                node = node.model_copy(update={"title": node.text[:24]})
            return node
        draft = HookDraft.model_validate(item)
        return HookNode(
            hook_id=f"H{index + 1}",
            title=draft.angle or draft.text[:24],
            narrative_function=_NARRATIVE_ORDER[index % len(_NARRATIVE_ORDER)],
            suggested_placement_s=0.0,
            text=draft.text,
            associated_concepts=[],
        )
    return HookNode(
        hook_id=f"H{index + 1}", title=str(item)[:24], text=str(item)
    )


def _normalise_narrative_function(value: Any) -> HookNarrativeFunction:
    """把模型自造/拼错的叙事档位归一为合法枚举(模糊相似度, 失败兜底首个)。"""
    from difflib import get_close_matches

    if value in _NARRATIVE_ORDER:
        return value  # type: ignore[no-any-return]
    text = str(value or "").strip().lower()
    if not text:
        return _NARRATIVE_ORDER[0]
    best = get_close_matches(text, list(_NARRATIVE_ORDER), n=1, cutoff=0.5)
    if best:
        return best[0]  # type: ignore[return-value]
    # 语义关键词兜底: 开篇悬念 / 中段冲突 / 高潮突破。
    if any(k in text for k in ("suspense", "opening", "悬念", "开场")):
        return "opening_suspense"
    if any(k in text for k in ("conflict", "mid", "中段", "冲突")):
        return "mid_conflict"
    if any(k in text for k in ("climax", "breakthrough", "高潮", "突破")):
        return "climax_breakthrough"
    return _NARRATIVE_ORDER[0]


def _sanitise_raw_scripts(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """规整模型直出的 scripts:丢弃缺 text 的废 cue,空 cue 脚本整本剔除。

    一个 cue 没有 text = 没有旁白 = 对解说视频无用。与其让一个坏 cue 废掉
    整支研究,不如丢掉它,把脚本里其余有效 cue 保留下来让用户在确稿台补。
    visual_type 缺失/越界 → 补成 voiceover(最稳的兜底视觉类型)。整本脚本
    都掏空时整本剔除;全删完才在 _normalise 报“至少 1 版”。
    """
    kept_scripts: list[dict[str, Any]] = []
    for script in raw.get("scripts") or []:
        if not isinstance(script, dict):
            continue
        cues = script.get("cues")
        if not isinstance(cues, list):
            continue
        kept_cues: list[dict[str, Any]] = []
        for cue in cues:
            if not isinstance(cue, dict):
                continue
            text = cue.get("text")
            if not (isinstance(text, str) and text.strip()):
                continue  # 丢掉缺 text 的废 cue(截断/模型漏字段)
            cue = dict(cue)
            if cue.get("visual_type") not in VisualType.__args__:  # type: ignore[attr-defined]
                cue["visual_type"] = "voiceover"
            kept_cues.append(cue)
        if kept_cues:
            script = dict(script)
            script["cues"] = kept_cues
            kept_scripts.append(script)
    return kept_scripts


def _normalise(raw: dict[str, Any], topic_or_url: str, provider: str) -> ExplainerServiceResult:
    raw_scripts = _sanitise_raw_scripts(raw)
    try:
        facts = [
            ResearchFact.model_validate(item if isinstance(item, dict) else {"claim": str(item)})
            for item in raw.get("facts", [])
        ]
        scripts = [ExplainerScriptDraft.model_validate(item) for item in raw_scripts]
    except Exception as exc:
        raise ExplainerCapabilityError(
            "MODEL_OUTPUT_INVALID", f"研究脚本字段校验失败: {exc}"
        ) from exc
    # Provider output counts are inherently variable.  Keep distinct, non-empty
    # hook matrix nodes, then reuse the hooks already embedded in script drafts
    # when the provider omitted a separate matrix.  Count is not a reason to
    # discard an otherwise valid research result.
    usable_hooks: list[HookNode] = []
    seen_hook_texts: set[str] = set()
    raw_hooks = raw.get("hooks", []) or []
    for item in raw_hooks:
        if len(usable_hooks) == _MAX_HOOKS:
            break
        node = _to_hook_node(item, len(usable_hooks))
        text = node.text.strip()
        if not text or text in seen_hook_texts:
            continue
        seen_hook_texts.add(text)
        usable_hooks.append(node.model_copy(update={"text": text}))
    for script in scripts:
        if len(usable_hooks) == _MAX_HOOKS:
            break
        text = script.hook.strip()
        if not text or text in seen_hook_texts:
            continue
        # script.hook 有时引用的是 hook_id(如 "H1")而非文本,不重复入矩阵。
        if any(text == hook.hook_id for hook in usable_hooks):
            continue
        seen_hook_texts.add(text)
        usable_hooks.append(
            HookNode(
                hook_id=f"H{len(usable_hooks) + 1}",
                title=script.viewpoint or text[:24],
                narrative_function=_NARRATIVE_ORDER[
                    len(usable_hooks) % len(_NARRATIVE_ORDER)
                ],
                suggested_placement_s=0.0,
                text=text,
                associated_concepts=[],
            )
        )
    hooks = usable_hooks
    if not hooks:
        raise ExplainerCapabilityError(
            "MODEL_OUTPUT_INVALID",
            "研究结果没有可用 Hook，且脚本中也没有可提取的 Hook",
        )
    if not scripts:
        raise ExplainerCapabilityError(
            "MODEL_OUTPUT_INVALID", "研究结果至少需要包含 1 个脚本版本"
        )
    for script in scripts:
        if not script.cues:
            raise ExplainerCapabilityError(
                "MODEL_OUTPUT_INVALID", f"脚本 {script.id} 缺少视觉脚手架"
            )
    summary = str(raw.get("research_summary") or "；".join(
        fact.claim for fact in facts[:5]
    ))
    # 素材吸收与扩写矩阵:跨脚本版本并集(按 original_material_point 去重),
    # 确稿台在选定版本前即可看到全部素材点被如何深度扩写。
    coverage: list[ConceptExpansion] = []
    seen_points: set[str] = set()
    for script in scripts:
        for entry in script.material_coverage_matrix:
            point = entry.original_material_point.strip()
            if point and point not in seen_points:
                seen_points.add(point)
                coverage.append(entry)
    return ExplainerServiceResult(
        facts=facts,
        research_summary=summary,
        hooks=hooks,
        scripts=scripts,
        provider=provider,
        material_coverage_matrix=coverage,
        decision_trail=[
            {"stage": "research", "provider": provider, "outcome": "completed"},
            {
                "stage": "script_generation",
                "script_count": len(scripts),
                "outcome": "completed",
            },
        ],
    )


async def research_and_generate(
    request: ExplainerResearchRequest,
    *,
    researcher: Any = None,
    script_generator: Any = None,
) -> ExplainerServiceResult:
    """Run research and script generation with explicit provider errors."""
    if researcher is None and script_generator is None:
        mcp_result = await _mcp_research(request.topic_or_url)
        raw = mcp_result if mcp_result is not None else await _llm_research(
            request.topic_or_url, request.target_duration
        )
        provider = (
            "obase.mcp.gpt_researcher"
            if mcp_result is not None
            else "provider_registry.default"
        )
        return _normalise(raw, request.topic_or_url, provider)

    if researcher is None:
        raise ExplainerCapabilityError(
            "CAPABILITY_UNAVAILABLE",
            "调研 Provider 未注入",
            action="配置 GPT Researcher MCP Provider",
        )
    research = await _call_provider(researcher, request.topic_or_url)
    # 目标时长随 research 字典透传给注入的脚本生成器,供其构建自己的动态字数约束。
    research = {**research, "target_duration": request.target_duration}
    generated = research
    if script_generator is not None:
        if hasattr(script_generator, "generate"):
            generated = await _invoke(
                script_generator.generate, request.topic_or_url, research
            )
        else:
            generated = await _invoke(script_generator, request.topic_or_url, research)
    if not isinstance(generated, dict):
        raise ExplainerCapabilityError("MODEL_OUTPUT_INVALID", "脚本生成器返回格式错误")
    if "facts" not in generated:
        generated = {**research, **generated}
    return _normalise(generated, request.topic_or_url, "injected")


def response_payload(result: ExplainerServiceResult, topic_or_url: str) -> dict[str, Any]:
    payload = result.model_dump(mode="json")
    payload["topic_or_url"] = topic_or_url
    payload["script_versions"] = payload["scripts"]
    # v9: hooks 保留 HookNode 矩阵结构(含 narrative_function / 时间点 / 关联概念),
    # 不再拍平成纯文本列表——确稿台需要这些元数据来构建 Hook Chain。
    payload["hook_details"] = payload["hooks"]
    return payload
