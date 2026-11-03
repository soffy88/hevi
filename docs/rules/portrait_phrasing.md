# 人物提示词表述规范（指引）

写人物提示词（定妆、逐镜人物描述、PixStag 首帧/motion_prompt、
gpt_edit 人物编辑）前，先按人物词表的表述规范写：**详细到可执行，
反对空泛堆词。**

全文（12 条条文，每条配词表正例与空泛反例）在词表包内：

- `hevi/image/portrait_vocab/PHRASING.md`

速览条文：

1. 动作必带支撑点与承重关系
2. 动态必带方向、幅度与停止位置
3. 视线、脸、身体三轴分开写
4. 冲突项二选一，绝不堆叠
5. 同义形容词只留一个
6. 每组只挑一个，按需选、不全叠
7. 先人物后场景，身份先行
8. 每轮只改最差一处，其余保持
9. 手与物必写接触关系与双手分工
10. 幅度词克制量化，可选动作不默认
11. 取景与动作分开写
12. 静态写瞬间，动态写过程，不混写

取用方式：

- 查词与组装：能力 `image.portrait_vocab`（list / search /
  assemble），或 `from hevi.image.portrait_vocab import assemble,
  phrasing_rules`；组装产物 `detail_zh` 即规范风格的范例文本。
- 手写提示词时对照 PHRASING.md 的正例改写空泛句，冲突对由组装器
  的 `find_conflicts` 兜底检出。
