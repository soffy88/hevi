"""火柴人导演线 —— 中文优先的导演提案生成 + CPU 渲染。

模块划分:

* :mod:`whitelist`  —— 全部枚举项(动作/道具/隐喻/镜头/转场/SFX/BGM/风格/比例)白名单
* :mod:`schema`     —— proposal.json 的 schema 版本与校验
* :mod:`narration`  —— 文案 → 中文旁白重写 + 无编造数字/人名/引语校验
* :mod:`storyboard` —— 定时分镜表(每 10s 一段, 段内三拍, continuity 双向)
* :mod:`proposal`   —— 组装 proposal.json + proposal.md
* :mod:`render`     —— 参数化火柴人 CPU 渲染 → 真实 mp4
* :mod:`cli`        —— 命令行入口
"""

from __future__ import annotations

SCHEMA_VERSION = "stickdir/proposal/1"
