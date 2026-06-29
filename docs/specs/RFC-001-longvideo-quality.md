# RFC-001 — 长视频生成质量架构改造

状态: Draft · 作者: 2026-06-29 全面审计 · 范围: L1 编排 / L2 视频内核 / L3 音频数字人 / L4 合成

## 升级后状态 (2026-06-29, obase v0.16.0 / oprim v3.10.33 / oskill v4.3.0)

上游 E1-E6 已交付并被 hevi 采用。**但 omodul 仍为 v1.28.0(未升级)**,它是编排
管线本体,因此受其约束的项无法仅靠本次升级闭合:

- ✅ **P0-2 拼接顺序/去重 已修**: `longvideo_orchestrator._order_and_dedup_shots`
  在 `bridged_assembler_fn` 里按镜头序号排序 + 每序号保留最大(选中)变体,
  消除 omodul `glob("*.mp4")` 的乱序与重复变体。(单测覆盖,无需 GPU)
- ✅ **P0-1 参考帧条件化 已闭合** (2026-06-29, omodul v1.33.1): 直接在主库修复并
  发布 —— omodul `_select_ref_image`(角色优先,环境兜底)把 ref_set 作为
  `reference_image` 透传给 video_fn(commit c948cd0,已推 origin + tag,15 测试过)。
  hevi 升 omodul v1.33.1 + `injected_video_fn` 收 reference_image → 非空设 mode=i2v
  转发,空则走 t2v。成片实际连续性待 GPU E2E 终验。
- ⏸️ **E2 video_cost_proposal / E5 render_shot / code-render**: 是并行成本系统/
  新特性(代码渲染镜头需 Playwright+chromium),非 RFC 既有缺陷的修复;swap 现有
  estimator 风险高,留作单独特性接线。
- 🔒 **仍需保留的 workaround(经核实上游 bug 未修)**: `patched_storyboard_fn`
  (oskill storyboard_planner 对 Chapter.scenes=list[dict] 调 .model_dump());
  `bridged_assembler_fn`(video_assembler 仍是 avatar_videos/bgm_path 签名);
  registry `_patched_wan_invoke`(新 oprim 默认转 wan2.6/generation 端点,hevi
  仍需 wan2.1/video-synthesis + 参数过滤)。

**结论: 要完成 P0-1 及其余深层项,下一步是升级/改 omodul 让其把 ref_set 透传给
video_fn(或在 hevi 覆盖该内部函数)。本次已闭合 P0-2。**


## 背景

hevi 的成片质量核心逻辑在 vendored 依赖 `omodul.agentic_longvideo_pipeline` +
`oskill` 里，hevi 通过 `hevi/pipeline/longvideo_orchestrator.py` 注入
`video_fn / audio_fn / storyboard_fn / assembler_fn` 来对接。**几乎所有质量缺陷
都出现在这个注入边界上** —— omodul 计算了大量一致性/参考信息，但 hevi 注入的
函数没有把它们用上。对标 Runway Gen-3 / Kling / Sora / HeyGen，当前长视频本质上
是"一堆相互独立的 t2v 片段 + 可能重复的废片 + 硬切拼接 + 整轨音频贴 -shortest"。

修复分两类：**(I) 可在 hevi 注入边界解决**（首选，无需改 vendored 库）；
**(II) 需向 omodul/oskill 提 RFC 或改 vendored 行为**。

> ⚠️ 验证：所有改动都需要 GPU + 真 provider 跑 E2E 才能确认成片质量，本机
> 无 GPU，因此本 RFC 只给设计与改法，不含已验证实现。

---

## P0 — 摧毁核心卖点（镜头连续性 / 成片可用性）

### P0-1 参考帧被算出却从未喂给视频生成 → 连续性完全失效
- 现状: `longvideo_orchestrator.py` 的 `injected_video_fn(*, prompt, output_path, **kw)`
  只透传 prompt/output_path；omodul `select_reference` 算出的角色/环境参考集
  (`ref_set`) 仅在事后 `consistency_fn` 打分时用，生成阶段每个镜头都是独立 t2v，
  无任何角色/场景 conditioning。
- 影响: 角色/场景跨镜头不一致 —— 这正是 Kling/Runway/Sora 的核心能力。
- 改法 (类 I): 让 `injected_video_fn` 接收 `ref_set`/上一镜头末帧，作为
  `reference_image` 走 i2v 调用 provider；或重写 shot 循环把上一镜头末帧作为下一
  镜头首帧。需确认 omodul 是否把 ref 透传进 `current_fn`（当前只传 prompt/output_path
  → 可能需配合 P0-from-omodul）。

### P0-2 拼接 glob 整个 shots 目录 → 成片含废片 + 重复 + 乱序
- 现状: omodul `assembler_fn(shot_videos=list(shots_dir.glob("*.mp4")))` 把目录里
  所有 mp4（每镜头 v0/v1 两变体 + 重试残留）全传进来；hevi `bridged_assembler_fn`
  仅过滤 `size>64`，不去重不排序；`glob` 顺序不保证。
- 影响: 每镜头出现多次、含被一致性否决的变体、叙事乱序。
- 改法 (类 I): hevi 自管 best_frame 列表传给 assembler，按 shot_id 排序、每个
  idx 只保留被选中的变体；不信任 glob。

### P0-3 音视频时间轴独立 → 永久不同步
- 现状: 所有台词拼成单条 `audio.wav`，视频各 shot 独立固定时长，最后用
  `-shortest` 贴整轨 → 谁短截谁，旁白与画面节奏对不上。
- 改法 (类 I/II): 音频驱动时长 —— 先 TTS 出每句时长，再据此定/裁 shot 时长；
  或逐 shot 携带其对白音频，先合成再 concat。需改注入的 audio/assembler 协作。

---

## P1 — 显著影响质量/健壮性

- **P1-1 跨编码拼接用 `-c copy` 会崩/花屏**（类 I）：回退 concat 路径强制
  `concat_filter` 重编码并统一 `scale/pad/setsar/fps`，禁止 `-c copy`
  （`longvideo_orchestrator.py:185` 附近）。
- **P1-2 无 i2v 衔接/转场**（类 I）：`AssistService.make_transition` 与 kernel 的
  i2v 模式已存在但未接入长视频；ltx2_cloud 默认 `mode="t2v"`、reference_image 恒
  None。接入末帧→首帧 i2v 链。
- **P1-3 逐镜头 prompt 绕过 prompt 工程**（类 I）：负向/风格/provider 适配只作用
  于顶层 topic，真正打到模型的 per-shot prompt 无负向无风格。在 `injected_video_fn`
  内对每个 shot prompt 再跑 `adapt_prompt_for_provider` + 风格/负向注入。
- **P1-4 负向提示词被丢弃**（类 I）：`prompt_pipeline.engineer_prompt` 只返回
  `result["prompt"]`，丢掉 negative_prompt；云 provider 实际无负向。
- **P1-5 fallback 整体重跑无镜头级 checkpoint**（类 I+II）：`run_with_fallback`
  失败后从头重跑（含 LLM 写剧本 + 全部镜头）。落盘已生成镜头并在重试时跳过；
  `ShotState` 表已存在但 `run_task` 从不写入。
- **P1-6 TTS 子进程错误被吞**（类 I，已部分缓解）：Wave D 已加超时+杀进程+末 10 行
  输出；仍可进一步把 stderr 分离。
- **P1-7 Duix 数字人未接入长视频主流程**（类 II）：`avatar_service.generate_avatar_clip`
  零调用；缺"数字人讲解 + B-roll 穿插"的镜头级编排。

## P2 — 参数/成本/打磨

- 镜头时长&分辨率全线对不上：`duration_mapper.clip_s=20` vs wan_local 写死 81f@16fps≈5s；
  quality_profile 竖屏 720×1280 vs wan_local 写死横屏 832×480。
- `capability_guard.validate_request` 是死代码（无调用方）→ 非法分辨率/时长/fps 直达。
- 无运镜控制（推/拉/摇/移、motion strength、guidance scale 未暴露）；style_presets 仅 3 个。
- 单镜头失败被 omodul `except: pass` 静默吞 → 占位帧 → 被 size 过滤丢弃 → 叙事断档无告警。
- 无响度归一(loudnorm/R128)；BGM 固定 0.3 权重无 ducking 无 fade；字幕用规划时长漂移
  （应 ASR 强制对齐）；xfade 转场是死代码，实际全硬切。
- `hevi/assembly/` 整个模块多为死代码（postprocess/transition/aspect_ratio），与真实
  成片路径脱节 → 要么接入要么明确标注废弃。

---

## 建议实施顺序

1. **先打通三条 P0**（参考帧进入生成 + assembler 只拼 best_frame + 音频驱动时长），
   它们直接决定成片是否具备基本镜头连续性与可用性。
2. 再补 P1（i2v 衔接、逐镜头 prompt+负向、镜头级 checkpoint）。
3. P2 为质量打磨。
4. `hevi/assembly/` 死代码：接入主流程或删除以免误导。

## 依赖 omodul/oskill 的项（需提上游 RFC）

- `current_fn` 仅收 prompt/output_path（P0-1 需透传 ref）。
- shots `glob` + 不删淘汰变体（P0-2 根因在 omodul）。
- 单镜头 `except: pass` 静默吞错。
- `_make_video_fn` 直接调原始 `oprim.video_generate`，绕过 hevi 在 registry 打的
  wan endpoint 补丁（fallback 会用到坏的 wan 调用）。

## 验证策略

每项改动需在 GPU 机器上跑 `scripts/integration/test_local_e2e_v3.py` 或等价 E2E，
人工核验：① 跨镜头角色/场景一致性 ② 无重复/乱序/废片 ③ 旁白与画面节奏对齐
④ 拼接无花屏 ⑤ 字幕时间码对齐。建议引入少量"成片回归"基线（关键帧哈希 + 时长断言）。
