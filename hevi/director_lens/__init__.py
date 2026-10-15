"""Hevi 动效导演层 (Motion Director) —— 线路无关的制作链层。

一个 ``DirectorBrief`` 描述整条制作链的决策:参考 → 分镜 → 主次/景深 → 节拍 →
物理/运动 → 光 → 声 → 自检。它不是动画专用:讲解、角色叙事、3D、实拍混剪等任何
产品线都通过一个薄适配器把同一份 brief 翻译成该线已有的输入。

模块划分:

  - ``brief``      DirectorBrief 数据模型 + 规则/模板自动补全 (纯 CPU, 确定性)
  - ``beat``       BPM×fps → 帧级拍点网格 + 重动作吸附 (允许微偏移)
  - ``motion``     纯函数运动语言 (预备→拉伸→冲击→压扁→过冲→回稳→次级) + 物理
  - ``stagger``    错相编排器 (主体先动, 次层延迟; 同一时刻只有一个主事件)
  - ``audio``      从运动长出 SFX + BGM ducking + 混音到幼儿响度
  - ``gate``       director_check 全线通用出片前闸门
  - ``adapters``   各产品线薄适配器 (DirectorBrief → 该线已有输入)
  - ``render``     CPU 确定性渲染 (导演版 + 无导演层基线对照版)
  - ``review``     逐帧审片单文件 HTML
  - ``capabilities`` 三个能力注册 (director_brief / director_check / motion_director)

设计原则(来源: awesome-ai-motion 作者观点 / 用户 2026-10-15):高级感来自删自由度、
加约束,而不是加特效。所有运动是时间的纯函数,由速度/冲量推导,不是随机 easing;
上一段末速度接续下一段初速度。
"""

from __future__ import annotations

__all__ = [
    "brief",
    "beat",
    "motion",
    "stagger",
    "audio",
    "gate",
    "adapters",
    "render",
    "review",
]
