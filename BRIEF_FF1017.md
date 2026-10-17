# BRIEF FF-1017：hevi 视频提示词配套「首帧图提示词」能力

## 目标
用户要求（2026-10-17）："我想让 hevi 会做，它做视频生成 prompt 也需要首帧画"。
hevi 现在出图生视频提示词时，必须同时为每个镜头产出可直接粘贴的**首帧图提示词**（默认 Midjourney V8.x 网页端写法，另出通用自然语言版给 ChatGPT 生图/即梦等），以及按需的**编辑/扩图提示词**，并能校验首帧是否适合拿去做视频。参考资料：本目录 `research_mj_firstframe.md`（用户分享的 Midjourney 教程整理），务必通读。

## 先读
- hevi/prompt/continuity/（schemas.py FilmBible/CharacterCard/SceneCard/PropLedger/ShotContract，compiler.py，validator.py，vocab.py，checklist.py）——本分支基于 feat/continuity-1017，首帧能力要建在这套结构上，复用角色卡/场景卡/道具账本，不另起一套。
- examples/continuity_wedding_demo.py、REPORT_CONT1017.md。
- hevi/prompt/h3_compiler.py（了解现有首帧/末帧字段，若有则对接）。

## 要做
1. `hevi/prompt/continuity/first_frame.py`（或同目录合理命名）：
   - `compile_first_frame(shot, bible, platform="midjourney"|"generic"|"chatgpt_image")`：
     - 英文提示词，顺序：主体 → 外观/动作起始姿态 → 环境 → 光线 → 画面形式与构图（景别、机位、焦段、留白）。角色外貌/服装、场景描述从卡片**逐字复用**；画面状态 = 该镜 0 秒状态（站位、朝向、道具在谁手里哪只手，取自道具账本/上镜交接）。
     - 不用"高级感、绝美"等空词；写写实摄影/插画等明确形式。
     - midjourney：末尾参数 `--ar W:H --v 8.2 --raw --s 75 --c 0`，加 `--sd`（先找方向）；`--ar` 必须等于视频画幅（从 bible/平台取，如 9:16、16:9），**只出现一次**；用英文 `--`，不写 `/imagine`；可选 `--seed`、`--p <id>`、`--sref <code> --sw N`、`--iw N`（只在 bible 提供时输出；--p 与 --sref 不混写；情绪板 mID 时不得出 --sw/--sv）。
     - generic/chatgpt_image：同样内容的自然语言，不带 `--` 参数，画幅写成文字。
   - 首帧规划规则（写进输出的「首帧要求」并被校验）：动作需要的身体部位与活动空间必须在画内（起身/走动→至少全身或中景留出移动方向空间；只微笑/眨眼→肩部以上可）；脸、手清楚，物体不粘连；头顶/边缘留白；画内文字仅限白名单，默认 "no text"。
   - 可选末帧提示词（该镜结束状态），用于下一镜首帧或首尾帧模型。
2. 资产参考图：`compile_asset_refs(bible)` 为每个角色/关键场景/关键道具出一条定妆参考图提示词（中性背景、全身+半身、正面），说明后续镜头首帧把定妆图放 Midjourney **Attach to prompt**（V8.X 人物/物体参考，保人物）；只借画风才用 **Style Reference**（会换人）；借构图用 **Image Prompts**。输出里写清每张参考图放哪个入口。
3. 编辑/扩图提示词模板：
   - 局部修改：`Change only <X> to <Y>. Keep the same face, hair, pose, light and background.`（每轮只改一件事）
   - 扩图/改画幅：`Extend the existing <scene background> above/below/left/right ... Keep the existing <subject> unchanged, coherent <lighting>.` 并附操作提示（Open Editor → Move/resize → 选比例 → Scale 缩小原图留透明区）。用于首帧画幅与视频不一致时。
4. 校验器（并入 validator 或 first_frame 内）新增错误：首帧 --ar 与视频画幅不符；--ar 重复；中文破折号/全角横线当参数；出现 /imagine；--p 与 --sref 混写、情绪板配 --sw；动作需要全身但首帧是特写/肩部以上；首帧道具状态与道具账本 0 秒状态不符；角色描述未逐字复用；含未白名单文字。
5. 视频提示词联动：图生视频版提示词在有首帧时只写动作/运镜/声音（"图片负责人物、构图、光线"），不重复长篇外貌，但保留一致性条款；提示"先简单动作再加复杂度"。
6. 导出：continuity 导出包里每镜增加 `first_frame`（midjourney + generic）、可选 `end_frame`、`asset_refs`、编辑模板；markdown 导出按「资产参考图 → 每镜【首帧图】【视频】【负面】」排列。
7. demo：扩展 examples/continuity_wedding_demo.py（或新建 examples/first_frame_wedding_demo.py），婚宴故事输出资产参考图 + 每镜首帧（MJ 与通用两版）+ 一个扩图示例，并演示校验器抓到：画幅不符、推轮椅镜头首帧只到肩部、包在首帧不在账本位置。

## 验收
- 新增单测（真实调用、不 mock）覆盖上面每条规则与每个校验错误、三种 platform 输出差异、--ar 跟随视频画幅。
- 回归：tests/test_h3_compiler.py tests/test_h3_shot_discipline.py tests/test_prompt_engineering.py tests/test_shot_prompt.py 以及 continuity 新测试，无新增失败（先跑基线）。
- python 用 /data/soffy/projects/hevi/.venv/bin/python，在本 worktree 下运行。

## 规则
CPU-only，不调付费 API，不真的调用 Midjourney；不 push、不 merge、不部署；不删 worktree 外文件；/data 很紧（约 13G），不要生成大文件、不要装新包；每步 commit。
最后写 REPORT_FF1017.md：做了什么、文件清单、测试（基线 vs 现在）、demo 输出摘录、未完成项；最后一行 `FF1017 DONE` 或 `FF1017 BLOCKED`。

## 复核问题（2026-10-17 15:30 Hark 独立复核，未通过，请逐条修复后再写 DONE）
测试 105 passed、demo 能跑、参数格式正确，但 demo 实际输出质量不合格：
1. 场景定妆参考图提示词混入中文：`Cinematic architectural establishing shot of 宴会主厅, ...` / `of 康复花园`。Midjourney 版必须全英文：场景用英文名（schemas 已有英文字段就用，没有就只用英文场景描述）。加测试：所有 MJ 提示词（资产参考图+每镜首帧）不含 CJK 字符。
2. 道具定妆参考图提示词取错字段：`Product commercial photography of microphone, holding a silver wireless microphone in his right hand, left arm resting...`、轮椅 `standing behind the wheelchair with both hands...`。道具参考图要描述道具本身外观材质（中性背景、无人物、无手持动作），不能用角色持有状态。另外 demo 道具名「立式麦克风」与镜头里的手持无线麦矛盾，修正 demo 数据。加测试：道具参考图不含 holding/hand/standing behind 等人物动作词。
3. 首帧正文重复和语病：Shot-01 `microphone held in his right hand, holding a silver wireless microphone in his right hand`；Shot-02 `wheelchair gripping both rubber handles`（主语错成轮椅）、手提包短语出现两次、`standing behind the wheelchair` 出现两次。道具账本状态与 start_state 已表达的内容要去重，道具状态句子以道具为主语。加测试：同一镜首帧提示词里不出现重复的 6 词以上短语。
4. 多角色首帧把两人外貌描述直接首尾相连，看不出哪段属于谁。每个角色描述前加名字/身份引导（如 `Li Ming, an adult East Asian man ...; beside him, Su Qing, an adult East Asian woman ...`），角色母卡描述本体仍逐字复用。
5. 构图词互相矛盾：Shot-01 同时有 `rule of thirds framing` 和 `centered composition`；固定追加的 `centered composition` 不能和镜头自身构图冲突（镜头有构图要求时不加默认 centered）。
6. 扩图模板输出 `coherent coherent warm afternoon sunlight`（lighting 已含 coherent 时重复），修掉并加测试。
7. demo 导入了 build_local_edit_prompt 却没输出：在 demo 中打印一条局部修改模板示例（如只把领结换成酒红色）。
修完后重跑全部回归（含 test_first_frame.py）与 demo，在 REPORT_FF1017.md 新增「复核问题修复」节，贴修复后的 demo 片段，最后一行仍为 `FF1017 DONE`。

## 复核问题（2026-10-17 第2轮，同样问题复发）
1. 场景参考图提示词仍含中文场景名（"of 宴会主厅"、"of 康复花园"），MJ 提示词必须全英文。
2. 道具参考图提示词仍从持有状态生成（"holding a silver wireless microphone in his right hand"、"standing behind the wheelchair with both hands gripping"、"hanging from the hook"），道具定妆图应只描述物体本身，不含人物动作。
3. 首帧中短语重复："microphone held in his right hand, holding a silver wireless microphone in his right hand"；"handbag hanging ... , a small black leather handbag hanging ..."；"wheelchair gripping both rubber handles, standing behind the wheelchair ... gripping"。需去重。
4. 构图冲突："rule of thirds" 与 "centered composition" 同时出现；只保留一个。
5. 扩图模板仍有 "coherent coherent"。
6. demo 未展示局部修改（local edit）模板输出。
7. 双人镜头里 Li Ming 的外貌描述后直接接 an adult ... woman，缺少分隔/标签。
修完需重跑 demo 自查以上七点后再写 FF1017 DONE。
