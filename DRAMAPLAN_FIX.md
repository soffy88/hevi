# DRAMAPLAN_FIX 第四轮（审核方独立核验 @6ad40e9b，2026-10-12）— 不通过，返工

已确认通过、**不要改坏**：
- R1 审稿提示词已中立（初审/复审均允许 error|warning、0–100，无"务必报错/允许通过"）；run6 真实分布 EP1 50→55→55 拒、EP2 55→40→80 拒、EP3 70→55→85 过，复审能真拒稿，review_all_passed=false 如实。
- R2 scene_diffs 保存改前/改后 summary/narration/dialogue 全文，run6 可见真实 LLM 改写（如 EP1 场1 玉玦/母妃动机扩写）。
- R3 orchestrator 实调（每章上游 5 镜，tts="第i句，前半，后半，尾巴。"）：30/60/120s → 6/12/24 镜严格单调；60s/120s 拆分后拼接与原文逐字一致、无空 tts、子镜 image_prompt 互不相同。P1.2 单测已走真 orchestrate_longvideo。
- R4 run6 最终剧本/分镜无 C00x 说话人；规则层 char_id_as_speaker=error；分镜无重复 tts。R5 edge_sources 边级标注。
- 68 passed（chapters/review/shot_budget/rework/llm_channel/zerolines）；3O lint=基线 4 项；OpenMontage(AGPL) 长行比对 0 命中。

## F1（阻断）script_to_storyboard 丢台词、丢旁白（run6 生产产物实证）
- 对白行数 > scene.shot_count 时多余台词被直接丢弃：run6 `storyboards/ep01.json` 场2 剧本 9 句对白，分镜只有 6 镜，
  「她说……你不是在逃，是去寻找属于你的光。」「我信她的话……也信你。」「……谢谢您。我不会让她失望的。」全部丢失（恰是本场情感核心）。
- 有对白的场，narration 完全不进分镜（ep01 场2、ep02 场2 的旁白丢失）。
- 末尾 `shots[:shot_budget]` 硬截断同样可能丢镜。
- 要求：剧本每句对白与旁白必须全部进入分镜（可多句合入一镜，或在预算内增镜/重分配 shot_count，超预算时合并而不是丢弃）。
  单测：9 句对白+旁白、shot_count=6 → 所有对白文本和旁白都能在分镜 tts 中按序找到；run7 的 QA 自动断言"剧本对白/旁白覆盖率=100%"。
## F2 分镜 tts 质量
- 镜头指令被当作配音读出：tts_text 出现「动作特写：…」「环境细节：…」「人物近景：…」（ep01 SH03/SH04、ep03 SC02）。镜头描述只能进 image_prompt，tts 只放可朗读的台词/旁白；无可读内容时不要用 summary 拼凑。
- 标点被改坏：`rstrip("。，！？")+"。"` 把问句改成陈述（「完美契合？」→「完美契合。」「真的有血缘？」→「…血缘。」），省略号后追加句号（「福伯……。」）。保留原句末标点，只在无标点时补"。"。
- 镜头时长无下限：ep02 场3 两镜 0.5s/1.0s 却要读完整句台词。规则层应检查场时长/每镜时长下限（如 ≥ 按字数估算的朗读时长、且 ≥1.5s），不合格判 error 进入返修，分镜层按字数分配时长。
## F3 执行层改稿可清空场次（无守卫）
- run6 EP3 第1轮返修后场1 `dialogue=[] narration=""`（整场无任何内容），EP1 第2轮场1 对白被清空。执行层返回空场/内容大幅缩水时须拒收该改写（保留原场或重试），规则层增加"空场"error。单测覆盖。
## F4 split_single_shot_plan 字符级兜底切成单字
- 实测 `split("甲乙丙丁戊己庚辛，壬癸。", 3)` → `["甲","乙","丙丁戊己庚辛，壬癸。"]`，5/7 份同理全是单字镜。原因：回退找标点的 while 循环在区间内无标点时退到 start+1。
  要求：区间内找不到标点就按均分点切（不回退到单字），各子镜字数大致均衡（max/min ≤ 2，字数允许时）；加单测。
## F5 画面描述
- 同场分镜 image_prompt 仅出场角色+"全景/中景/特写"三档不同，主体描述（scene.summary）逐镜相同（ep01 10 镜仅 7 种）。请按该镜 tts 内容/说话人动作生成区分描述。
- image_prompt 写死「写实短剧风格」，与组内默认画风（国风动漫插画、写实真人默认关闭）冲突：画风应来自参数/配置，默认不写死写实。
## F6 说明（不阻断，但 DONE 要如实写）
- 监督层最终 score 由 `_score_from_issues`（100-20×error-5×warning）计算，LLM 返回的 score 被丢弃；DONE 不得称其为"LLM 打分"。可选：记录 llm_score 字段一并落盘。

## 完成标准
- 新 E2E run7（免费 NIM/ollama，不调付费 API），record.json 写通道与调用次数；QA 增加：对白/旁白覆盖率=100%、tts 无镜头指令前缀、问句标点保留、无空场、每镜时长≥下限。DONE 逐条写证据，不得夸大。
- 不改 site-packages、不 push/merge。提交用 `git -c user.name="hevi-dramaplan agent" -c user.email=dramaplan@hevi.local commit ...`，不要修改 .git/config。
- 长任务 `nohup setsid ... > e2e_run.log 2>&1 &` 独立启动并 `sleep 300` 循环轮询到产物完成再结束会话。
- 审核证据：/workspace/projects/eebf6af3-74b0-405d-a51b-f07939a41036/audit/dramaplan/r4_*（审核方本地）。
