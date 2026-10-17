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
