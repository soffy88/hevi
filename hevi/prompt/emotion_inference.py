"""主线情绪配音(SPEC-002 B1)—— 台词文本 → 逐行情绪标注,不改 oskill 私有库 schema。

tongjian 的情绪来自剧本生成 LLM 本身(script.py 的 prompt 直接要求逐行输出
`"emotion": "情绪(如 倨傲/决绝/惊惧)"`,跟台词同一次 LLM 调用产出)。主线走的是
oskill 私有库的 `script_writer`/`storyboard_planner`,私有库没有"情绪"这个概念,
改它的 prompt 模板不在 hevi 这边可控范围内(vendored 依赖,SPEC-002 §4.2 明确要求
优先评估复用/不碰私有库数据模型)。

这里的做法:私有库产出台词文本之后,hevi 侧另起一次**批量**(全片一次 LLM 调用,
不是逐行调用)分类,补上情绪标注——不修改 oskill 的 ShotPlan/Script 对象,只在
`longvideo_orchestrator.py` 把结果包进 hevi 自己的 SimpleNamespace 包装对象里,
跟 `character_voices` 那处已有的包装同一个模式(见 injected_audio_fn)。

用于给 `hevi/audio/edge_tts_custom.py::synthesize_with_voice_control` 的逐行
`emotion` 消费点用(该函数已支持读取每行 `.emotion` 属性,2026-07-13 加的)。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_EMOTION_INFER_PROMPT = """给下面这些视频台词/旁白逐行标注情绪基调,每行一个简短
中文词或短语(如"倨傲""决绝""惊惧""悲怆""平静""喜悦""紧张"),吃不准就填"平静"。

{numbered_lines}

只输出 JSON:{{"emotions": ["第1行情绪", "第2行情绪", ...]}}——数组长度必须严格等于
台词行数,顺序一一对应,不要合并/跳过任何一行。"""


async def infer_line_emotions(lines: list[str], *, llm: Any = None) -> list[str]:
    """→ 与 lines 等长、逐行对应的情绪标签列表。

    best-effort:LLM 不可用/调用失败/输出解析失败/长度不匹配 → 整批返回空字符串
    (`emotion_to_rate_pitch("")` 退化为 "+0%"/"+0Hz",跟没有情绪配音时行为一致)——
    这一步故障绝不能阻断配音生成(同 hevi 其它 lint/审核步骤的既有惯例)。
    """
    if not lines:
        return []
    if llm is None:
        try:
            from obase.provider_registry import ProviderRegistry

            # 结构化 JSON 输出优先用 qwen_cloud(本地 ollama 对这类任务不可靠,
            # 同 e2e-local-llm-json-blocker 记录的既有教训);没注册才退回 default。
            try:
                llm = ProviderRegistry.get().llm("qwen_cloud")
            except Exception:
                llm = ProviderRegistry.get().llm("default")
        except Exception as e:
            logger.warning("emotion_inference: no LLM available, skip: %s", e)
            return [""] * len(lines)

    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(lines))
    try:
        resp = await llm(
            messages=[
                {
                    "role": "user",
                    "content": _EMOTION_INFER_PROMPT.format(numbered_lines=numbered),
                }
            ],
            max_tokens=1024,
        )
        content = resp.get("content") if hasattr(resp, "get") else str(resp)
        m = re.search(r"\{.*\}", content, re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
        emotions = [str(x) for x in (data.get("emotions") or [])]
        if len(emotions) != len(lines):
            logger.warning(
                "emotion_inference: length mismatch (%d lines, %d emotions), skip",
                len(lines),
                len(emotions),
            )
            return [""] * len(lines)
        return emotions
    except Exception as e:
        logger.warning("emotion_inference: inference failed, skip: %s", e)
        return [""] * len(lines)
