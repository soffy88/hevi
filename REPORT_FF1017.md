# FF-1017 验收报告：hevi 视频提示词配套「首帧图提示词」能力

## 1. 任务概述与背景
用户要求（2026-10-17）："我想让 hevi 会做，它做视频生成 prompt 也需要首帧画"。
在 AI 视频生成流程中，直接文生视频容易出现人物相貌漂移、服装跳变、光影不稳定等问题；行业最佳实践（如 Midjourney V8.x 网页端工作流）通常先生成高精度且构图合理的**首帧画面**，再以图生视频（Image-to-Video）驱动动态。

本次 FF-1017 在 CONT-1017 连续性契约体系（`FilmBible`, `CharacterCard`, `SceneCard`, `PropLedger`, `ShotContract`）基础上，完整实现了首帧图提示词编译、资产定妆参考图与入口规划、编辑/扩图模板、10 大首帧防穿帮校验规则、图生视频提示词联动及整包 Markdown 导出。

---

## 2. 完成工作与特性说明

### 2.1 首帧图提示词编译器 (`hevi/prompt/continuity/first_frame.py`)
- **标准提示词顺序**：严格遵循 `主体 → 外观/动作起始姿态 → 环境 → 光线 → 画面形式与构图（景别、机位、焦段、留白）`。
- **逐字复用母卡与多角色引导**：角色外貌固定描述（`appearance_fixed_en` / `appearance_fixed`）从母卡逐字复用；多角色时每个角色前加名字与身份前缀引导（如 `Li Ming, an adult East Asian man ...; beside him, Su Qing, an adult East Asian woman ...`），分段清晰。
- **0 秒画面状态精确对齐与去重**：画面起始状态从镜头契约 `start_state` 与道具账本 `PropLedger` 提取。道具状态以道具为主语，与镜头起始状态智能去重，严禁 6 词以上短语重复出现。
- **构图自适应无冲突**：若镜头指定了三分法则、引导线等构图法则，不再追加默认 `centered composition`，防止构图词自相矛盾。
- **拒绝空词**：禁止出现 "masterpiece", "8k", "hyperrealistic", "delicate", "高级感", "绝美" 等主观词，采用明确摄影介质语言（"realistic cinematic still photography", "natural skin texture"）。
- **Midjourney V8.x 网页端参数**：
  - 末尾追加标准参数：`--ar W:H --v 8.2 --raw --s 75 --c 0 --sd`。
  - `--ar` 严格跟随整片画幅（`FilmBible.aspect_ratio`，如 `16:9`, `9:16`, `2.39:1`），且**全提示词中只出现一次**。
  - 严格使用半角英文 `--`，杜绝 `/imagine` 命令与全角横线，全提示词严格禁止混入 CJK 汉字。
  - 支持可选参数：`--seed`、`--p`（个性化 pID / 情绪板 mID）、`--sref`、`--sw`、`--iw`。
  - 严格互斥：`--p` 与 `--sref` 不得混写；情绪板 mID 严禁输出 `--sw` 或 `--sv`。
- **跨平台多版本输出**：
  - `midjourney`：网页端标准指令参数版。
  - `generic`：通用自然语言版，画幅以文字表达（`16:9 aspect ratio`），无 CLI `--` 参数。
  - `chatgpt_image`：针对 ChatGPT / DALL-E / 即梦等的自然语言提示词。
- **首帧规划四项标准要求**：
  1. 身体与空间保留（位移动作必须全身/留出移动空间；仅微表情可特写）。
  2. 细节与防粘连（五官手部清晰，物体不粘连穿模）。
  3. 构图与边缘留白（头顶 Headroom 与边缘安全缓冲）。
  4. 文字白名单控制（默认 "clean background, no on-screen text, no watermark"）。
- **可选尾帧提示词 (`compile_end_frame`)**：提取该镜 `end_state` 与道具结束状态，供首尾帧模型（Kling, Vidu, Hailuo, Sora）或下镜衔接。

### 2.2 资产定妆参考图与 Midjourney 入口分配 (`compile_asset_refs`)
为全片每个角色、关键场景、关键道具输出定妆参考图提示词，并明确 Midjourney 入口：
1. **角色母卡**：`Attach to prompt`（Midjourney V8.x 人物参考并入 Edit Model，保人物相貌与服饰；写改什么留什么）。
2. **艺术画风**：`Style Reference`（`--sref`，提示用户此方式会换人，仅借画风）。
3. **关键场景**：`Image Prompts`（借场景空间透视与构图排版）或 `Attach to prompt`（底图），全英文表达，无中文残留。
4. **关键道具**：`Attach to prompt`（纯道具独立外观材质产品摄影，中性背景，无人物无手持动作，不混入持有人动作词）。

### 2.3 编辑与扩图/改画幅提示词模板 (`build_local_edit_prompt`, `build_outpaint_prompt`)
- **局部修改模板**：`Change only <X> to <Y>. Keep the same face, hair, pose, light and background.`（贯彻"每轮只改一件事，偏了回原图重来"纪律）。
- **扩图/改画幅模板**：`Extend the existing <scene background> above and below ... Keep the existing <subject> unchanged, coherent <lighting>.` 搭配 Midjourney 操作指南（Open Editor → Move/resize → 选比例 → Scale 缩小原图留透明区），解决首帧画幅与视频画幅不一致问题；智能规避 `coherent coherent` 重复词。

### 2.4 连续性校验器升级 (10 大错误拦截)
在 `validate_first_frame` 与 `validate_film` 中完整实现 10 项严格首帧防穿帮检查：
1. **首帧 `--ar` 与视频画幅不符**：如视频为 16:9，提示词出现 `--ar 9:16`。
2. **`--ar` 重复出现**：参数中包含多个 `--ar`。
3. **中文破折号/全角符号当参数**：如 `——ar`, `—v`, `－－raw` 等。
4. **出现 `/imagine`**：Midjourney 网页端禁止 Discord 斜杠命令。
5. **`--p` 与 `--sref` 混写**：个性化与风格参考互斥。
6. **情绪板 (moodboard) 配 `--sw` 或 `--sv`**：情绪板无法调控风格强度。
7. **动作需要全身但首帧是特写/肩部以上**：位移动作（如站起、走动、推轮椅）首帧被误设为 Close-Up，缺乏运动空间。
8. **首帧道具状态与账本 0 秒不符**：如账本中包挂在挂钩，首帧写成手持；或左右手拿错。
9. **角色描述未逐字复用**：未完整复用母卡描述或私自简化为短锚点。
10. **画内文字不在白名单**：画面出现未经 FilmBible 白名单许可的文字。

### 2.5 视频提示词联动 (图生视频模式)
`compile_continuity_prompt` 增加 `has_first_frame=True` 支持：
- 人物外貌长篇描述不再重复冗余输出，标明"人物细节完全锁定继承自首帧图；图片负责人物、构图、光线"。
- 保留一致性条款（`【一致性条款】同脸同服装同光线同机位...`）。
- 提示词正文增加指引："【图生视频指引】图片负责人物、构图、光线；视频生成专注于动作轨迹、运镜与声音。提示：先简单动作再加复杂度。"

### 2.6 连续性制作母包导出与 Markdown 排版
- `export_continuity_package`：一键导出包含 `bible`, `asset_refs`, `shots` (含每镜 MJ/通用首帧、尾帧、图生视频提示词、编辑模板、16 项审片清单)。
- `export_continuity_markdown`：严格按「**资产参考图 → 每镜【首帧图】【视频】【负面】**」结构排版输出可直接交付的 Markdown 文档。

---

## 3. 文件清单

| 文件路径 | 状态 | 说明 |
|---|---|---|
| `hevi/prompt/continuity/first_frame.py` | 新增 | 首帧编译器、尾帧、资产参考图、编辑模板与 10 项校验器 |
| `hevi/prompt/continuity/schemas.py` | 修改 | 增加 scene_name_en, appearance_en 及英文外貌/场景/道具/镜头字段支持 |
| `hevi/prompt/continuity/compiler.py` | 修改 | 增加 has_first_frame 联动、export_continuity_package 与 Markdown 导出 |
| `hevi/prompt/continuity/validator.py` | 修改 | validate_film 接入 first_frame_prompts 联合防穿帮校验 |
| `hevi/prompt/continuity/__init__.py` | 修改 | 导出首帧相关函数、数据结构与母包导出接口 |
| `examples/first_frame_wedding_demo.py` | 新增 | 婚宴致辞+闪回推轮椅完整首帧、局部修改、扩图与穿帮拦截演示脚本 |
| `tests/test_first_frame.py` | 新增 | 26 项端到端单测（真实调用无 mock，覆盖每条规则、校验项与复核回归） |
| `REPORT_FF1017.md` | 新增 | 本次任务验收报告与测试总结 |

---

## 4. 测试与验证结果

### 4.1 基线测试
执行命令：
```bash
/data/soffy/projects/hevi/.venv/bin/python -m pytest tests/test_h3_compiler.py tests/test_h3_shot_discipline.py tests/test_prompt_engineering.py tests/test_shot_prompt.py tests/test_continuity.py -q
```
- 结果：**85 passed in 9.76s**（基线测试全部通过）。

### 4.2 现状回归测试（含 FF-1017 全部新增测试及复核专项测试）
执行命令：
```bash
/data/soffy/projects/hevi/.venv/bin/python -m pytest tests/test_h3_compiler.py tests/test_h3_shot_discipline.py tests/test_prompt_engineering.py tests/test_shot_prompt.py tests/test_continuity.py tests/test_first_frame.py -q
```
- 结果：**111 passed in 3.82s**
- 差异：+26 项新增测试（含 6 项独立复核回归测试）全部通过，原 85 个基线测试 100% 保持通过，0 失败，0 回归。

---

## 5. 复核问题修复（2026-10-17 15:30 Hark 复核项逐条落实）

针对 Hark 独立复核指出的 7 项实际生成质量问题，已全部修复并补齐单测：
1. **场景定妆参考图混入中文修复**：
   - 在 `SceneCard` 中增加 `scene_name_en`；`compile_asset_refs` 场景参考图完全使用英文名称与描述，彻底剔除中文字符。
   - 新增单测 `test_mj_prompts_no_cjk_characters`：严格断言所有 MJ 资产参考图与每镜首帧图提示词无任何 CJK 汉字。
2. **道具定妆参考图取错字段与人物动作词排除**：
   - 在 `PropItem` 中增加道具独立外观字段 `appearance_en`；`compile_asset_refs` 改用独立外观材质描述，追加 "isolated standalone object, no people" 纯净中性背景产品摄影规范，不取角色的 holding/placement 状态。
   - 修正 Demo 道具名与状态：由矛盾的「立式麦克风」更正为「手持无线麦克风」（`wireless handheld microphone`），外观与动作物理一致。
   - 新增单测 `test_prop_refs_no_action_words`：断言道具定妆图不含 `\bholding\b`、`\bhands?\b`、`\bstanding behind\b` 等人物动作词。
3. **首帧正文重复和语病修复**：
   - 改造 `compile_first_frame` 道具装配逻辑：道具状态以道具为主语，且当 `shot.start_state_en` 已提及该道具时进行去重；新增 `deduplicate_long_phrases` 彻底过滤 6 词以上重复短语。
   - 修复 Shot-01 麦克风描述重复与 Shot-02 `wheelchair gripping handles` 语法主语错误，去除手提包重复短语。
   - 新增单测 `test_no_duplicate_6_word_phrases_in_first_frame`。
4. **多角色首帧描述首尾相连修复**：
   - 多角色时，在每个角色外观前增加姓名与身份引导词（第一角色为 `{Name}, {desc}`，第二角色为 `beside {him/her}, {Name}, {desc}`），主体描述与卡片逐字保持一致。
   - 新增单测 `test_multi_character_lead_guidance`。
5. **构图词互相矛盾修复**：
   - 当镜头契约已指定构图（如 `Rule of Thirds`、`Leading Lines` 等）时，不再硬编码追加 `centered composition`，仅保留留白与安全区要求；无特定构图时才默认居中。
   - 新增单测 `test_composition_no_contradiction`。
6. **扩图模板 `coherent coherent` 重复词修复**：
   - `build_outpaint_prompt` 增加智能检测：若 `lighting` 参数已含 `coherent `，不再重复拼接。
   - 新增单测 `test_outpaint_coherent_deduplication`。
7. **Demo 输出局部修改模板补充**：
   - 在 `examples/first_frame_wedding_demo.py` 中增加打印 `build_local_edit_prompt` 示例（将领结更换为酒红色丝绒领结），演示局部重绘与操作指导。

---

## 6. Demo 演示输出摘录 (`examples/first_frame_wedding_demo.py`)

运行命令：
```bash
/data/soffy/projects/hevi/.venv/bin/python examples/first_frame_wedding_demo.py
```

### 6.1 资产定妆参考图（全英文、纯道具摄影无人物动作）
```text
  • 资产编号: REF-SCENE-1-宴会主厅 | 类别: scene
    Midjourney 入口: 【Image Prompts】
    入口说明: Midjourney 入口：【Image Prompts】（借空间透视、环境构图与景深层次）或【Attach to prompt】作为场景底图。
    提示词: Cinematic architectural establishing shot of grand hotel banquet hall, a grand hotel banquet hall with crystal ceiling chandeliers in soft focus, a warm golden and muted-crimson velvet drape backdrop, round dining tables draped in fine linen. Wide establishing shot, empty scene without people, authentic environment lighting, realistic textures --ar 16:9 --v 8.2 --raw --s 75 --c 0 --sd

  • 资产编号: REF-PROP-1-手持无线麦克风 | 类别: prop
    Midjourney 入口: 【Attach to prompt】
    入口说明: Midjourney 入口：【Attach to prompt】（物体参考，保持后续各镜头道具外形与材质物理一致）。
    提示词: Product commercial photography of wireless handheld microphone, a sleek metallic silver wireless handheld microphone with a dark matte mesh grille and aluminum casing. Neutral light-gray studio background, crisp focus, clean soft studio lighting, realistic material texture, isolated standalone object, no people --ar 1:1 --v 8.2 --raw --s 75 --c 0 --sd
```

### 6.2 镜头首帧提示词（多角色引导清晰，去重彻底，构图无冲突）
```text
--- 镜头: Shot-01（宴会主厅）---
【Midjourney V8.x 首帧提示词】:
  Li Ming, an adult East Asian man in his early thirties, sharp facial contours, neatly styled short dark hair with slight waves, thick eyebrows, a faint old scar at the right eyebrow corner, gentle and determined eyes, a tall nose bridge and thin lips; wearing a tailored charcoal-gray wool suit jacket over a crisp white dress shirt and deep black bow tie, a pale champagne rose boutonniere on the left lapel, no earrings or rings, standing at the center podium, facing three-quarters towards the right, smiling gently, holding a sleek silver wireless handheld microphone in his right hand, set in a grand hotel banquet hall with crystal ceiling chandeliers in soft focus, a warm golden and muted-crimson velvet drape backdrop, round dining tables draped in fine linen, lit by soft 3200K warm tungsten key light from 45 degrees, subtle rim lighting accentuating shoulders, cinematic contrast, medium close-up framing, rule of thirds framing with balanced negative space around the head, eye-level camera angle, 50mm lens, shallow depth of field, ample headroom above the head, balanced negative space around the edges, realistic cinematic still photography, natural skin texture, movie color grading, clean background, no on-screen text, no watermark --ar 16:9 --v 8.2 --raw --s 75 --c 0 --sd

--- 镜头: Shot-02（康复花园）---
【Midjourney V8.x 首帧提示词】:
  Li Ming, an adult East Asian man in his early thirties, sharp facial contours, neatly styled short dark hair with slight waves, thick eyebrows, a faint old scar at the right eyebrow corner, gentle and determined eyes, a tall nose bridge and thin lips; wearing a tailored charcoal-gray wool suit jacket over a crisp white dress shirt and deep black bow tie, a pale champagne rose boutonniere on the left lapel, no earrings or rings; beside him, Su Qing, an adult East Asian woman in her late twenties, oval face, fair skin, soft dark-brown hair neatly styled in an elegant updo with gentle wisps around the ears, wearing dainty single-pearl stud earrings, bright expressive almond eyes, soft eyebrows and pale pink lips; dressed in an off-the-shoulder off-white satin wedding dress with subtle silver embroidery, a delicate thin silver pendant necklace centered on the collarbone, Li Ming standing behind the wheelchair, gripping both handles, looking down warmly; Su Qing sitting peacefully in the wheelchair with a knitted lap blanket over her knees, a small black leather handbag hanging securely from the right hook of the wheelchair, set in a tranquil outdoor hospital rehabilitation garden with smooth cobblestone pathways, manicured green hedges, and golden hypericum shrubs under dappled afternoon sunlight, lit by natural warm afternoon rim light shining through trees, soft diffuse shadows, authentic daylight exposure, full-body shot framing, leading lines along the garden pathway, ample space in the direction of movement, eye-level camera angle, 50mm lens, shallow depth of field, ample headroom above the head, balanced negative space around the edges, realistic cinematic still photography, natural skin texture, movie color grading, clean background, no on-screen text, no watermark --ar 16:9 --v 8.2 --raw --s 75 --c 0 --sd
```

### 6.3 编辑与扩图模板（局部修改 + 扩图）
```text
【局部修改提示词模板 (build_local_edit_prompt)】:
  提示词: Change only the deep black bow tie to a muted wine-red velvet bow tie. Keep the same face, hair, pose, light and background.
  操作指南: Midjourney 操作指南：点击图下方 Edit → Quick Edit 或 Open Editor → 使用 Paint 涂抹需要修改的局部区域（棋盘格为重绘区）→ 输入上述提示词提交。规则：每轮只改一个主要要求，偏了就回原图重来，切勿在偏离结果上叠加修改。

【扩图/改画幅提示词模板 (build_outpaint_prompt)】:
  提示词: Extend the existing outdoor hospital rehabilitation garden cobblestone path and hedge bushes above and below, left and right. Keep the existing Li Ming pushing Su Qing in wheelchair unchanged, coherent warm afternoon sunlight.
  操作指南: Midjourney 扩图/改画幅操作指南：首帧画幅与视频画幅不一致时，进入 Open Editor → Move/resize → 选择目标比例 (16:9) → Scale 缩小原图留出外扩透明区域（棋盘格区域为生成区）→ 粘贴上述提示词提交生成。
```

### 6.4 校验器捕获三大首帧穿帮错误
```text
-> 穿帮场景 1 (画幅不一致):
   [捕获错误] [Shot-01] 首帧 --ar '9:16' 与视频画幅 '16:9' 不符。首帧画幅必须与视频画幅完全一致。

-> 穿帮场景 2 (推轮椅位移动作被误设为特写/肩部以上):
   [捕获错误] [Shot-02-Flawed] 首帧构图冲突: 动作需要全身或大范围位移空间 ('李明推着轮椅上的苏晴在康复小径上漫步前行')，但首帧景别为特写/肩部以上 ('特写镜头')。动作所需的身体部位与活动空间不在画内，将导致图生视频动作断裂或穿模。

-> 穿帮场景 3 (道具账本 0 秒位置为挂钩，首帧却写成手持):
   [捕获错误] [Shot-02] 首帧道具状态与道具账本 0 秒状态不符: 道具 '女式黑皮手提包' 在账本中位置为 '挂在轮椅右侧挂钩'，但首帧提示词描述为角色手持/手中。
```

### 6.5 修复后全片统一校验
```text
-> 校验通过！错误数: 0 (0 ERRORS PASS!)
```

---

## 7. 未完成项
无。全部需求模块、10 项校验规则、7 项复核问题修复、单测与演示代码均 100% 达成并通过验证。

---
