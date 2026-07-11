"""IP 安全改写 pass —— 图像半边(HEVI 路线图 Phase2 #36)。

文本(topic/角色描述)那半见 hevi/prompt/ip_safety.py——那边能"改写成安全等价物";
图像做不到同样的操作(不能像文本一样重写措辞让一张已上传的照片变成"安全版本"),
这里只做**标记供人工复核**,不阻断上传、不自动删除/拒绝。

这是本来就更难的问题:没有真人名人人脸库可比对,只能靠本地 VLM 做"这张照片像不像
某个具体的、可识别的公众人物/版权角色"的粗粒度判断——checklist 式、默认通过,
命中就标记而不是直接拒绝(同 identity_pack.py 年代审核的设计惯例)。VLM 对这类
判断的准确率无法保证,这是尽力而为的第一道信号,不是可靠的人脸识别系统。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_IP_SCREENING_PROMPT = """检查这张照片:画面里是不是某个具体的、可以认出来的公众
人物/名人,或者某个具体的受版权保护的虚构角色(不是泛泛的"一个人"这类)?

只输出 JSON:{"flagged": true/false, "reason": "简短说明,不涉及就留空"}"""


async def flag_if_recognizable_person(image_path: Path | str, *, vlm: Any = None) -> list[str]:
    """→ 命中的顾虑说明列表(空列表 = 没发现问题)。

    best-effort:vlm 不可用/调用失败/解析失败 → 空列表——不能因为这一步的故障就
    阻断建角色/上传,只是"没能补上这道信号",不是"确认没问题"。
    """
    if vlm is None:
        return []
    try:
        resp = await vlm(
            messages=[{"role": "user", "content": _IP_SCREENING_PROMPT}],
            image_paths=[str(image_path)],
            max_tokens=200,
        )
        content = resp.get("content") if hasattr(resp, "get") else str(resp)
        m = re.search(r"\{.*\}", content, re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
        if data.get("flagged") and data.get("reason"):
            return [str(data["reason"])]
        return []
    except Exception as e:
        logger.warning("ip_screening: check failed for %s, skipping: %s", image_path, e)
        return []
