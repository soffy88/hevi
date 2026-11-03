# portrait_vocab — 人物提示词词表

人物出图/图生视频的第三层词表（handraw 管画风、shotcraft 管镜头、
本包管人物表演）：66 条中英词条，8 组——视频微动作 6、姿态 8、
头发与头部 8、手与持物 9、动态 8、坐姿 8、站姿 9、视线 10。

每条含 `id / category / zh / en / how（怎么写得具体）/ feeling`。
数据逐字转录自 Soffy 2026-10-23 转来的人物提示词图页（归档：
`~/workspace/references/portrait-prompt-vocab/VOCAB.md`）；原稿没有
表情组（作者称自行描写），本包不编造。

## 用法

```python
from hevi.image.portrait_vocab import assemble, search

search("gaze", query="镜头")            # 找词条
assemble(                               # 组装（每类至多一个）
    {"sitting": "SI-02", "gaze": "看向镜头", "hands": "holding a cup"},
    identity="脸型五官按参考图",
    subject="成年女性穿燕麦色针织开衫",
    scene="雨后暖窗光照亮脸与手，玻璃留雨珠，室内稍暗",
    framing="拍到腰部，双手和支撑肘入画，写实皮肤，16:9",
)  # -> {"prompt_zh": ..., "prompt_en": ..., "entries": [...], ...}

assemble({"video_micro": "VM-06", "gaze": "GA-01"}, mode="motion")
# -> motion_prompt 可直接进 PixStag 镜头包
```

组装纪律进代码：同类多选拒绝；闭眼 × 看向镜头/直视镜头/侧目一瞥、
坐姿 × 站姿、坐姿 × 行走/舞动/奔跑会检出冲突（默认报错，
`on_conflict="warn"` 改为警告）。

能力入口：`image.portrait_vocab`（list / search / assemble；
返回里带 `phrasing` 规范要点）。
重建索引：`python3 build_portrait_index.py <VOCAB.md> <out.json>`。

表述规范：`PHRASING.md`（包内）——从词条归纳的 12 条写法条文
（支撑点、方向/幅度/停止位置、三轴分开、冲突二选一……），给写
人物提示词的 agent 当样例参照；`docs/rules/portrait_phrasing.md`
有指引。组装产物 `detail_zh` 即该规范风格的范例。
