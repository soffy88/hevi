"""冷启动编排 (oskill_cold_start_single)

职责：编排单题冷启动链路：识别 -> 元认知自评 -> 苏格拉底引导。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from oprim.ocr_paper import OCRPaperInput, ocr_paper
from oprim.speech_to_math import SpeechToMathInput, speech_to_math

from oskill.metacog_scaffold import MetacogScaffoldInput, metacog_scaffold
from oskill.socratic_guide_v2 import SocraticStateV2


@dataclass(frozen=True)
class ColdStartInput:
    student_id: str
    input_type: str  # 'image', 'voice', 'text'
    content: str  # b64, url, or raw text
    question_context: str | None = None  # 如果已知


async def cold_start_single(
    inp: ColdStartInput, *, caller: Any, model: str = "claude-sonnet-4-6"
) -> dict:
    """执行冷启动链路。"""

    # 1. 识别
    recognized_text = ""
    confidence = 1.0

    if inp.input_type == "image":
        ocr_res = await ocr_paper(OCRPaperInput(image_b64=inp.content), caller=caller)
        if not ocr_res.success:
            return {"error": ocr_res.error, "status": "failed"}
        recognized_text = ocr_res.raw_text
        # ocr_paper v3.5.0 暂无 confidence，这里模拟
        confidence = 0.9
    elif inp.input_type == "voice":
        stt_res = await speech_to_math(SpeechToMathInput(audio_b64=inp.content), caller=caller)
        if not stt_res.success:
            return {"error": stt_res.error, "status": "failed"}
        recognized_text = stt_res.latex_text
        confidence = stt_res.confidence
    else:
        recognized_text = inp.content

    # 2. 低置信度校验信号
    if confidence < 0.8:
        return {
            "status": "require_confirmation",
            "recognized_text": recognized_text,
            "message": "识别置信度较低，请确认题目是否正确。",
        }

    # 3. 元认知自评
    meta_res = await metacog_scaffold(
        MetacogScaffoldInput(
            question=recognized_text, student_id=inp.student_id, input_content=recognized_text
        ),
        caller=caller,
    )

    # 4. 初始化引导状态
    # 注意：这里仅返回初始化后的状态和第一步，实际循环由调用方（omodul）驱动
    state = SocraticStateV2(
        question=recognized_text,
        correct_answer="",  # 冷启动可能不知道正确答案，需要 LLM 自行推理或后续补充
    )

    return {
        "status": "ready_for_guidance",
        "recognized_text": recognized_text,
        "metacog": meta_res.self_eval,
        "socratic_state": state,
    }


__version__ = "0.1.0"
