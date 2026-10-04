"""LongCat-Video integration boundary.

这个包是 **integration boundary**,不是实现。

LongCat-Video 的官方推理栈(13.6B unified T2V/I2V/VC,refinement 为其实际推理
路径的一部分)在本仓之外;HEVI **不 vendor** 该模型代码。作为外部 execution
surface 对接,HEVI 只拥有:

  - canonical contract          → hevi/generation/models.py
  - backend interface           → hevi/generation/backend.py
  - evidence / probe contract   → hevi/generation/evidence.py, longcat_probe.py
  - adapter skeleton            → hevi/generation/longcat_adapter.py

能力准入的前置条件是 Evidence Gate 全通过(见 longcat_probe.probe)。
在准入之前,adapter 不声称 T2V/I2V/VC/refinement 任何一项。
"""

from __future__ import annotations

PROVIDER_NAME = "longcat-video"
UPSTREAM_REPO = "https://github.com/meituan-longcat/LongCat-Video"
ADMISSION_STATE = "NOT_EVALUABLE"

__all__ = ["ADMISSION_STATE", "PROVIDER_NAME", "UPSTREAM_REPO"]
