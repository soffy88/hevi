# DRAMAPLAN_FIX 第三轮（审核方独立核验 @32ac9d98，2026-10-12）— 不通过，返工

已确认通过、**不要改坏**：
- P1 真实 orchestrator 路径（审核方用 orchestrate_longvideo 实调，仅替换上游 shot generator=每章 5 镜）：30/60/120s → 6/12/24 镜，严格单调；archetype 1-5min 未设时长 → 按 180s 得 36 镜；storyboard_planner 收到 shots_per_scene_min/max。
- P2 大纲每集 12、Σ=36=total；P3 storyboards 每镜 event_id 均在图内、镜头数=Σscene.shot_count≤预算；P5 chapters 用 memory_store.by_key 检索前文摘要注入 prompt；
- 测试 206 passed（test_director_verdict 需 PATH 含 ffmpeg）；3O lint=基线 4 项；AGPL 长行比对仅样板代码。

## R1（阻断）审稿回路被提示词操纵，"返修—再审"是预设结果
- `review.py::_SUPERVISOR_PROMPT_INITIAL` 写着「**务必**将最突出的一处场次问题定为 "error"」——强制制造错误以保证出现返修轮；
  `_SUPERVISOR_PROMPT_REVISED` 的 JSON 模板只允许 `"severity": "warning"`、`"score": 80到100`，并要求「允许剧本通过审稿」——复审永远不可能拒稿。
  所以 run5 三集都是 rounds=2、必过，qa 的 review_has_revision_round / review_all_passed 无意义。
- 要求：初审/复审用同一中立标准（error|warning 均允许、score 0–100，不得暗示必须报错或必须通过）；复审仍可拒稿，达到 max_rounds 未过就如实 passed=false 并记录。
  E2E 的 review_has_revision_round 不得作为必过项；如实报告真实出现返修的集数。单测：复审 LLM 返回 error → 不通过并进入下一轮。
## R2 返修前后文本无法核对
- review_log 只存 12 位 hash（scene_diffs before/after），没有改前文本，无法证明 LLM 真改稿。要求 scene_diffs 同时保存 before/after 的 summary/narration/dialogue 全文（或 unified diff），E2E 至少一集展示真实 LLM 改写内容。
## R3 镜头拆分丢台词/造空镜（生产路径 bug）
- `shot_budget.split_single_shot_plan`：子镜只取 `clauses[j]`，当分句数 > 拆分数时其余分句**被丢弃**；分句数 < 拆分数时子镜 tts 为空。
  审核实测（orchestrator 路径，每镜 tts="第0句，前半，后半，尾巴。"）：60s 拆 2 → 只剩「第0句」「前半」，「后半，尾巴」丢失；120s 拆 3 → 「尾巴」丢失。
  另外 image_prompt 仅追加「（分镜j/n）」，子镜画面描述完全相同。
- 要求：分句按顺序**分组**分配到子镜，全部保留（拼接后与原文一致），不足时按时长分配而不是空串；子镜 image_prompt 给出区分（景别/动作递进）。单测断言 "".join(子镜 tts) 覆盖全部原文、无空 tts。
- P1.2 的单测 `test_orchestrator_counting_shot_gen_chain_with_fixed_5_shots` 是在测试里重写了一遍 _counting_shot_gen_fn，不是真调用链：改为 monkeypatch `default_longvideo_shot_generator` 与 `agentic_longvideo_pipeline`，调用真正的 `orchestrate_longvideo`（可参考审核脚本思路：fake pipeline 内调用 providers["shot_gen_fn"]）。
## R4 分镜/剧本质量问题
- 最终剧本与分镜出现角色 ID 当说话人：ep01 场2 `C003：少爷，盘缠我备好了。` / `C001：多谢福伯。`（ep2 也有 C001/C004，LLM 监督已指出却仍放行）。规则层把 char_id 当合法人名放过——改为必须映射成角色名，char_id 作说话人视为 error。
- script_to_storyboard 重复台词：ep01 SH04 与 SH01 台词完全相同。对白不足时用旁白/动作描述补，不要循环复用。
## R5 缝合标记口径
- causal_source 标在「被缝合的目标事件」节点上（CH02E001/CH03E001 = stitched），而其自身 effects 是抽取的；真正的缝合边在 CH01E002→CH02E001。改为边级标注（如 `stitched_edges: [[from,to]]` 或 causes_sources 映射），DONE 如实描述。
## 完成标准
- 新 E2E run6（免费 NIM/ollama），record.json 写通道与调用次数；DONE 逐条写证据，不得夸大。不改 site-packages、不调付费 API、不 push/merge。
- 提交作者：共享 .git/config 被写成 "OMQUALITY agent"，请用 `git -c user.name="hevi-dramaplan agent" -c user.email=dramaplan@hevi.local commit ...`，不要修改 .git/config。
- 长任务必须 `nohup setsid ... > e2e_run.log 2>&1 &` 独立启动并 `sleep 300` 循环轮询到产物完成再结束会话。
