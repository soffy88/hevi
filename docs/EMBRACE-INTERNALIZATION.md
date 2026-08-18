# 3O 内化总账(EMBRACE-INTERNALIZATION)

> 状态: 实施完成(A+B+C+D 代码落地)· 日期: 2026-08-07
> 来源: bradautomates/claude-video · gnipbao/story-to-handdrawn-video ·
> dramaclaw/dramaclaw · alamshafil/auto-shorts · Vincentwei1021/video-shotcraft
> 范式: 3O(`obase ← oprim ← oskill ← omodul ← hevi`),可复用机制上 3O,
> 裁决阈值/路由策略/Series 字段留 hevi(护城河)。
> License 纪律: claude-video/story(MIT)可借鉴代码;shotcraft 方法论可搬;
> dramaclaw(Elastic 2.0)只借鉴方法与契约形状,实现全部重写。

## 谦逊差距清单(核验后结论)

| 来源 | 他们有、我们没有/比我们好 | 落地 |
|---|---|---|
| claude-video | 摄入侧视频理解(抓取/场景抽帧/预算/去重/联络表/转写) | `hevi/ingest/`(Phase A) |
| claude-video | 帧预算 token 经济 + 16×16 去重 | `hevi/ingest/frame_budget.py` / `frame_dedup.py` |
| dramaclaw | replay_capture(导演决策四阶段痕迹,可回放对比策略) | `hevi/verdict/replay_trace.py`(A) |
| dramaclaw | failure_registry(失败→负向子句闭环,我们只有设计) | `hevi/verdict/failure_registry.py`(A) |
| dramaclaw | convergence_log(逐集/阶段返工轮次 + 趋势) | `hevi/verdict/convergence.py`(D) |
| dramaclaw | 线稿草图分镜(选择/上色校验/视觉闸门) | `hevi/director/sketch_storyboard.py`(C) |
| dramaclaw | Xia 导演助理(会话式生产审计) | `hevi/director/assistant.py`(C) |
| dramaclaw | Director World / 3GS 虚拟片场 | `docs/specs/SPEC-3GS-world-set.md`(D,待触发) |
| shotcraft | 104 镜头配方卡(可执行词汇表) | `hevi/motion/recipe_card.py`(B,种子 10 卡) |
| shotcraft | 品牌→动效参数表(motion StylePack) | `hevi/motion/motion_stylepack.py`(B) |
| shotcraft | 节拍卡点(网格拟合+kick 重音+回测≤3f) | `hevi/motion/beat_sync.py`(B) |
| shotcraft | 声音设计(BGM 先行+SFX 钉帧表+双版本) | `hevi/motion/sound_design.py`(B) |
| shotcraft | 页面采集(纹理+抠图+layout.json) | `hevi/motion/page_capture.py`(B) |
| shotcraft | 设计 token 提取(视觉语言从产品生长) | `hevi/motion/design_token.py`(B) |
| shotcraft | 判例式审美准则(R/Q/S/C/P 只增不重排) | `hevi/verdict/aesthetic_canon.py`(B) |
| shotcraft | 八阶段宣传片工作流 + 引导式共创 | `hevi/assembly/promo_video_workflow.py` / `guided_co_creation.py`(C) |
| story-to-handdrawn | 确定性渲染契约(DESIGN.md) | `hevi/assembly/remotion_render_workflow.py` + `hevi-remotion/RENDER-CONTRACT.md`(C) |
| auto-shorts | 反面教材(模板农场无护城河) | 不建;取事件进度日志模式(已在 replay_trace/audit 落地) |

## 3O 归属(待上游清单)

| 现驻 hevi | 目标 3O |
|---|---|
| `hevi/ingest/video_fetch.py` / `video_frames.py` / `video_transcript.py` / `contact_sheet.py` / `frame_budget.py` / `frame_dedup.py` | `oprim.video_fetch` / `video_frames_extract` / `video_transcript` / `build_contact_sheet` / `frame_budget_for_duration` / `frame_dedup` |
| `hevi/ingest/video_watch.py` | `oskill.video_watch` |
| `hevi/verdict/failure_registry.py` | `obase.failure_mode_registry` + `oskill.failure_negative_clause` |
| `hevi/verdict/replay_trace.py` | `omodul.replay_trace` |
| `hevi/verdict/convergence.py` | `omodul.convergence_loop` |
| `hevi/verdict/aesthetic_canon.py` | `oskill.aesthetic_canon` |
| `hevi/motion/recipe_card.py` | `obase.shot_recipe_card` |
| `hevi/motion/motion_stylepack.py` | `obase.motion_stylepack` |
| `hevi/motion/beat_sync.py` | `oprim.beat_grid_analyze` + `oskill.beat_sync` |
| `hevi/motion/sound_design.py` | `oskill.sound_design` |
| `hevi/motion/page_capture.py` / `design_token.py` | `oprim.page_capture` / `oprim.design_token_extract` |
| `hevi/director/sketch_storyboard.py` | `oskill.sketch_storyboard` |
| `hevi/director/assistant.py` | `oskill.director_assistant` |
| `hevi/assembly/remotion_render_workflow.py` / `promo_video_workflow.py` / `guided_co_creation.py` | `omodul.remotion_render_workflow` / `promo_video_workflow` / `guided_co_creation` |
| `hevi/motion/` 3GS 相关(见 SPEC-3GS-world-set.md) | `omodul.scene_block_workflow` + oprim 3D 原语(触发后) |

## 新增 CI 检查

- `scripts/ci/check_recipe_schema.py` — 配方卡 schema(卡名/类别/能量/时长/已知坑)
- `scripts/ci/check_canon_numbering.py` — 判例库编号只增不重排 + 每族齐全
- 已接入 `.github/workflows/ci.yml`(3O 内化检查步骤)

## 新增测试(与既有 1572+ 测试同批跑)

| 文件 | 覆盖 |
|---|---|
| `tests/test_ingest.py`(15) | 帧预算/去重/字幕解析/联络表/抽帧 |
| `tests/test_verdict_embrace.py`(8) | failure_registry/replay_trace |
| `tests/test_motion.py`(17) | 配方卡/动效预设/节拍网格/声音/判例库/token |
| `tests/test_embrace_phase_c.py`(13) | 渲染契约/promo 工作流/共创状态机/线稿分镜/导演审计 |
| `tests/test_verdict_convergence.py`(5) | 收敛循环 |

## 后续(hevi wire 建议)

1. **摄入侧 wire**:verdict 成片 QA 用 `watch_video`(联络表替代逐帧 VLM);StylePack
   参考视频拆解(HEVI-ARCH §5.3.7)接 `video_watch`。
2. **失败闭环 wire**:`FailureRegistry.build_negative_clause` 注入逐镜头 prompt 富化;
   `FailureHits` 接 verdict 诊断分类;replay_trace 接 `ShotState` 落库。
3. **画廊/分发**:配方卡经 `save_library` 出 JSON,复用 `hevi/gallery` 基建做镜头卡画廊;
   SKILL.md+scripts 形态做 agent 分发(参照 claude-video/shotcraft 的 npx skills 生态)。
4. **3GS**:SPEC-3GS-world-set.md 三道门(机位字段/3D provider 化/硬件 license)全过后触发。

## ✅ 已 wire(2026-08-07 第二批落地)

| wire | 内容 | 落点 | 测试 |
|---|---|---|---|
| ① | 失败注册表→负向子句注入导演管线(角色锁定/i2v 时并入 extra_negative) | `hevi/prompt/negative_clause.py` + `hevi/api/routers/director.py` | `tests/test_embrace_wire.py` |
| ② | 成片交付门(频闪/死空档/联络表/BGM 接缝 + 判例库 P 族自检)—— HEVI-ARCH §6.1.1 落地 | `hevi/verdict/delivery_gate.py`(复用 ingest 帧管线) | 同上 |
| ③ | replay trace 接 `verdict_shot`(可选 trace_root,四阶段 best-effort,零行为变化) | `hevi/director/verdict_checks.py` | 同上 |
| ④ | 配方卡/判例库/失败模式 → `hevi-web/public/embrace/*.json` 静态导出 | `scripts/export_embrace_assets.py` | 同上 |

wire ① 纪律:无角色时不注入(保持既有 API 契约,`test_director.py` 不回归);
wire ② 单项失败记 None 不整门崩溃(ffmpeg 缺失可降级);wire ③ best-effort 不阻断裁决。

---

# Round 3(HyperFrames + Remotion 补齐)

> 来源: remotion-dev/remotion(55.8k ⭐)+ heygen-com/hyperframes(39.9k ⭐)。
> 谦逊结论: Remotion 核心 hevi 已具备;HyperFrames 的缺口在**分发形态 / 媒体台账 / 创作工作流**三件事,
> 渲染引擎本身不换(hevi 已锁定 Remotion + 契约)。

## 三件事落地

| 事 | 交付 | 测试 |
|---|---|---|
| agent skill 分发(19-skill 模式) | `hevi/skills/` 三支核心 skill(hevi-watch/hevi-media/hevi-promo)+ CLI 入口(watch_cli/media_cli)+ `scripts/install_hevi_skills.py`(已装入 ~/.claude|.codex|.agents/skills) | test_embrace_round3 |
| media-use 台账 | `hevi/sourcing/media_use.py` —— 一个 `resolve` 动词 + MediaLedger(JSON 台账/复用候选/供应链 local→stock→generate) | 同上 |
| 创作工作流 ×4 | `embedded_captions_workflow` / `talking_head_recut_workflow` / `music_to_video_workflow` / `pr_to_video_workflow`(三件套签名) | 同上 |

## 能力表格缺失项补齐(逐项核对更新)

| 能力 | 更新后 | 证据 |
|---|---|---|
| 云渲染(Lambda/GCP) | ✅(接入) | `hevi/assembly/cloud_render_workflow.py` + hevi-remotion 已装 `@remotion/lambda` |
| 跨环境 parity 契约 | ✅ | `hevi/assembly/parity_harness.py`(配置指纹 + 帧哈希对比) |
| 词级字幕(@remotion/captions) | ✅ | hevi-remotion 已装 `@remotion/captions` + `src/captions/WordCaptions.tsx`(parseSrt + ensureMaxCharactersPerLine + 逐字点亮) |
| Lottie/3D/transitions | ◐(包已装) | hevi-remotion 已装 `@remotion/lottie` + `@remotion/transitions`(组件接入待做) |
| 色彩分级/LUT | ✅(升级) | `hevi/motion/color_grade.py`(5 预设 + .cube 校验 + ffmpeg filter 链) |
| 设计系统→视频(frame.md) | ◐ | StylePack + design_token 已具备;显式"web 规范→帧"翻译层仍待(低优先) |

## 本轮新增

- 测试: `tests/test_embrace_round3.py`(20 例:台账/四工作流/云渲染/parity/调色/安装器)
- 前端: hevi-remotion 依赖 +4 包(@remotion/captions/lambda/lottie/transitions,package.json + lockfile 已同步),`WordCaptions.tsx` tsc 干净
- 3O CI 五件套全过(含三件套签名/支柱检查对新 workflow)

# Round 3b(video-shotcraft 二轮对照 — sequences + final-review)

> 二轮对照发现第一轮未内化的两项:全片**序列模式**(能量弧)与**成片独立终检协议**。
> 均已落地 + 接入 promo 工作流。

## 新增

| 缺口 | 交付 | 测试 |
|---|---|---|
| 序列模式(shotcraft sequences/promo-energy-arc) | `hevi/motion/sequence.py`:`PROMO_ENERGY_ARC`(4 段位)+ `plan_sequence`(确定性预算分配:段位占比 → 先划 hold/rest → 能量高⇄低交替 → 呼吸字卡均匀分布 2-4 张) | tests/test_embrace_shotcraft2.py |
| 成片独立终检(shotcraft final-review.md) | `hevi/verdict/final_review.py`:`REVIEW_INPUTS`(12 项)+ `FINAL_REVIEW_CHECKS`(P/F/V/S/B/D 六组 25 项)+ 无法验证/来源冲突处理 + 报告渲染 | 同上 |
| 接入 | `promo_video_workflow` 用 `plan_sequence` 替代 naive 卡循环(计划带 `sequence_plan`,既有断言保持) | 同上 |

## 质量门

- 新增 13 测试全绿;全量 1646 passed(排除并发会话陈旧测试 test_cinematic_golden_formula)
- ruff/mypy --strict 全绿;3O CI 五件套全过;能力清单文档重新生成
- 6 failed 全部归属并发会话在途工作(dashboard/history_arc + 文档漂移,其中文档已修)

## 诚实边界

- `test_cinematic_golden_formula.py` 是并发会话陈旧测试(其 golden_formula.py 已演进,
  测试文件未跟上),未修其代码,回归时排除 —— 由该会话收敛。

# Round 3c(三库二轮对照 — auto-shorts / story-handdrawn / claude-video)

> 二轮对照:三库均小幅演进;对照当初 Phase C 计划发现**两个列了但未建的真缺口**,本轮补齐。

## 缺口与落地

| 缺口 | 来源 | 交付 | 测试 |
|---|---|---|---|
| `story_to_animation`(计划里列了但没建) | story-to-handdrawn | `hevi/assembly/story_to_animation_workflow.py`:中文分句一句一拍 / 图片逐图一拍 / 三态揭示或卷页 / plan-preview-full 三模式 + `hevi/skills/story_cli.py` + `hevi/skills/hevi-story/SKILL.md`(已装入 3 宿主) | tests/test_embrace_round3c.py |
| 零配置 setup 预检(第一轮只记录没内化) | claude-video setup.py | `hevi/ingest/preflight.py`:`check_env`(ffmpeg/ffprobe/yt-dlp/faster-whisper → can_proceed/missing/notes)+ watch_cli 的 `--preflight`(exit 2 = 缺关键二进制) | 同上 |
| auto-shorts | — | 再次确认无新内化点:模板农场判断维持;其双接口(CLI+JS 同核)模式在 hevi skills(CLI 包同核心)已具备 | — |

## 质量门

- 新增 11 测试全绿;Round 3 全量(3c+3b+3)55 例过;ingest/wire 24 例过
- ruff/mypy --strict 全绿;hevi-story 已真实安装进 ~/.claude|.codex|.agents/skills(共 4 支 skill)
- 渲染器侧(hevi-remotion 手绘组合 TSX)因并发会话正在 hevi-remotion 工作,留作后续(工作流/计划/契约层已齐)

# Round 3d(dramaclaw 二轮对照)

> 二轮对照(HEAD 30efddc,演进为官方媒体目录发布):对照第一轮标注的"缺能力契约与双轨 /
> 资产包导出 / 图片池"三项,本轮落地。

## 落地

| 第一轮标注缺口 | 交付 | 测试 |
|---|---|---|
| Freezone 能力契约(缺能力契约与双轨) | `hevi/canvas/skill_contract.py`:`SkillCapabilities`(5 能力)+ 输入/输出规格 + `validate_skill_definition`(apply 必须伴随 propose / 声明改图必须有 patch 输出 / 读画布必须有输入)+ `SkillRegistry`(按能力查询) | tests/test_embrace_round3d.py |
| 资产包导出(HEVI-ARCH §6.4 专业交付) | `hevi/assembly/export_pack_workflow.py`:manifest(视频/字幕/镜头清单/连续性报告/逐镜评分/附加)→ zip 打包,缺项记 missing 不阻断 | 同上 |
| 图片池索引(dramaclaw pool_indexer) | `hevi/director/image_pool.py`:内容哈希去重 + 按 beat/网格检索 + 最优选择(复用 sketch 闸门思路) | 同上 |

## 质量门

- 新增 13 测试全绿;ruff/mypy --strict 全绿;3O CI 五件套全过
- 未触碰并发会话在途区域(cinematic/dashboard/history_arc)

## 诚实边界

- Freezone 的**双轨(主线+探索画布)**与 skill 运行契约的**运行时执行**未做(hevi/canvas
  已有图执行;能力契约层是声明侧,运行时接线留给 omodul canvas workflow 演进)。
- 导出工作流是打包/清单层;真实 SRT 构建已由 ingest/assembly 覆盖,本 workflow 只编排。

# Round 3e(dramaclaw 全面落地 — 真实功能,非壳)

> 用户要求"全面落地真正的落地可用"。对照诚实审计的"浅代理/未内化"清单,五件全部实现为真实可运行模块:

| 优先级 | 交付 | 真实功能(非壳) |
|---|---|---|
| ① 候选提升双轨 | `hevi/director/promotion.py` | PromotionPool:候选池 + 提升门(评分过线/同名冲突/未重复提升)+ 驳回记原因 + 批量评分自动提升(注入 scorer)+ JSON 台账 |
| ② 修复 agent 编排 | `hevi/director/repair_agents.py` | REPAIR_AGENTS 表(8 诊断类别 → agent/杠杆/动作)+ plan_repair(一次一变量 + 预算)+ repair_decision(收敛/发散/降级交付,复用 convergence) |
| ③ 风格画像 | `hevi/style/style_analyzer.py` | 纯 PIL 确定性画像:主色板(量化聚类)/亮度/饱和度/对比度/暖冷 + VLM 钩子(接既有 draft_from_reference)+ merge/save |
| ④ 草图编辑子系统 | `hevi/director/sketch_edit.py` | 编辑执行(crop/reframe/grayscale/去网格/pose 骨架线,纯 PIL)+ 结构对比(16×16 轮廓差)+ 可解释评分(覆盖/构图/风格/标注校验) |
| ⑤ Xia 会话层 | `hevi/director/chat_assistant.py` | XiaAssistant:按项目会话(JSON 持久化)+ 意图识别(状态/推进/审计/修复/提升/帮助)+ 动作执行(包 audit_production + repair_agents + promotion)+ 回复骨架 |

## 质量门

- 新增 23 测试全绿;ruff/mypy --strict 全绿
- 诚实更新:此前"浅代理/未内化"审计项中,①②③④⑤ 已全部升级为真实实现;
  3GS 已由并发会话 scene_world(轻量版)+ 本会话 scene_contract 覆盖机制层;
  draft_from_reference(VLM 草稿)既有,本会话补了确定性画像层
- 仍未做(明示):cognee 知识图谱 / chat 的 LLM 生成式回复(Xia 为确定性意图+执行,
  LLM 润色可注入)/ sketch 与真实渲染链路的运行时接线

# Round 3f(运行时接线 — 让运行时可用)

> 用户要求"运行时接线,让运行时可用"。5 项内化能力暴露为 API 端点 + 接入既有流程。

## 新端点(hevi/api/routers/embrace_runtime.py,已注册 /api/embrace/*)

| 端点 | 能力 | 冒烟结果 |
|---|---|---|
| POST /api/embrace/chat | Xia 会话(意图识别→执行→回复) | 200, intent=status |
| GET /api/embrace/chat/{project_id} | 会话状态 | 200 |
| POST /api/embrace/promote/{p}/candidates | 登记探索候选 | 200 |
| POST /api/embrace/promote/{p}/decide | 提升/驳回(双轨) | 200, asset 锁定 |
| GET /api/embrace/promote/{p} | 候选池+主线状态 | 200 |
| POST /api/embrace/repair-plan | 失败→修复计划+收敛决策 | 200, character_fixer |
| POST /api/embrace/style-analyze | 参考图→确定性画像(+VLM 合并) | 200, palette+语言草稿 |
| POST /api/embrace/sketch-edit | 草图编辑执行 | 200, crop applied |

## 既有流程接线

| 接线 | 内容 |
|---|---|
| **regenerate 自动 hints** | `POST /{task_id}/regenerate` 未显式给 hints 时,按 shot verdict 的 `diagnosis_category` 经 `repair_agents.hints_from_failures` 自动推导 `{idx: 修复指令}` → omodul regenerate_shots 并入 prompt(一次一变量) |
| **style-analyze + VLM** | 确定性画像与 draft_from_reference 语言草稿合并(修复了 tmp 文件在 VLM 合并前被删的运行时 bug) |

## 质量门

- HTTP 层冒烟(TestClient + auth 覆盖):8 端点全 200,未授权 401
- 新增 14 测试全绿;ruff/mypy --strict 全绿;能力清单文档重新生成
- 全量 1707 passed(6 failed 全部并发会话在途,非本次引入)

## 运行时说明

- chat/promotion 状态为**进程内存**(与 shortdrama _RUNS 同模式),重启即失;落盘接口已具备(XiaAssistant.save / PromotionPool.save),接生产存储是后续

# Round 3g(1-5 全落地)

| # | 项 | 交付 |
|---|---|---|
| 1 | MCP 工具扩展 | `hevi/mcp/tools/embrace_tools.py`:5 个 skill(watch_video/media_resolve/repair_plan/promote_candidate/chat)+ schemas + server.py 注册(13→18 工具) |
| 2 | 渲染件补齐 | `hevi-remotion/src/HandDrawnDiary/`(手绘日记组合,三态/卷页,契约合规)+ `src/templates/PaperPromo/`(已验证宣传片模板,能量弧结构)+ TEMPLATE.md;两组合 `remotion still` 实测渲染成功 |
| 3 | workflow API 化 | `POST /api/embrace/workflows/run`:delivery-gate / export-pack / music-to-video / story-to-animation / promo-plan / final-review 六种,产 report JSON |
| 4 | 持久化落库 | `hevi/verdict/persist.py`:stdlib SQLite 统一存储(replay_traces / convergence_rounds / promotion_pools / failure_hits) |
| 5 | media_use 真实 provider | `hevi/sourcing/media_providers.py`:bgm/sfx→BGMLibrary、voice→edge-tts、grade/lut→color_grade、image→stock(按环境降级) |

## 质量门

- 新增 13 测试全绿;内化测试累计 ~200 例全过
- 渲染件:tsc 干净 + `remotion still` 两组合实测 `Rendered 1/1`
- ruff/mypy --strict 全绿;能力清单文档重新生成

# Round 3h(3GS G2+G3 — 道具路径真实 3D)

> 来源: veya/templates/skills/img2threejs —— 参考图 → 程序化 Three.js 代码重建(Apache 2.0,
> 无 GPU 推理),开掉 G2/G3 的**道具路径**。

| 件 | 交付 |
|---|---|
| Prop3D provider | `hevi/director/prop3d.py`:M.C.M.T 蓝图(LLM+确定性 lint)→ 程序化 Three.js → 相机方位角数学 → HTML harness → headless 逐方位条件帧 |
| 场景块工作流 | `hevi/assembly/scene_block_workflow.py`(三件套):参考图 → 条件帧组 + scene_contract 空间契约报告;消费模式 3(3D 视角结构+2D 身份喂 i2v) |
| provider 注册 | `hevi/providers/registry.py` §6:`prop3d/img2threejs` 条目 |
| 门状态 | G1 ✅ / **G2 ✅(道具路径)** / **G3 ✅(道具路径)**:Apache 2.0 + 代码重建,无 license/硬件障碍;角色/场景全 3D 仍观察 |

## 质量门

- 新增 13 测试全绿(相机方位角数学 / M.C.M.T lint / threejs 生成 / harness / 工作流降级)
- ruff/mypy --strict 全绿;SPEC-3GS-world-set.md 门状态更新
- 诚实边界:本机无 chromium,条件帧渲染路径为真实代码(装 `npx playwright install chromium` 即用),
  blueprint→渲染前全部可测;渲染步缺浏览器时明确降级 failed

# Round 3i(oil-motion 内化 — 网页交互动画能力域)

> 来源: oil-oil/oil-motion(交互动画 Skill:把 AI 连续动作接入滚动/鼠标/拖动/触摸/设备方向)。
> 全新能力域:此前 hevi 产出"视频文件",这里是"可交互网页动画资源 + 交互代码"。

## 落地

| 件 | 交付 |
|---|---|
| 交互核心 | `hevi/motion/interactive.py`:帧预算(滚动 24帧/屏、拖拽 48、环形 72)/ 输入→帧映射(一维 progress / 环形角度,clamp+mod)/ **环形最短距离**(快速反向不闪烁的阻尼基础)/ 资源形式决策表(webp_atlas / seekable_video / keyframe_mp4 / webcodecs / short_clips / sliced_atlas)/ 图集预算(单元=显示×DPR、≤4096、解码内存 W×H×4)/ 图集清单(JSON) |
| Skill | `hevi/skills/hevi-interactive/`(SKILL.md + interactive_cli:budget/decide/frames/manifest),已装入 3 宿主(共 5 支 skill) |

## 质量门

- 新增 12 测试全绿(映射数学/环形最短距离/决策表/图集预算/清单/CLI)
- ruff/mypy --strict 全绿

## 诚实边界

- 未做(明示):视频→图集的**实际编码管线**(ffmpeg/PIL 出 WebP 图集)与**前端交互组件**
  (Next.js 的 scroll/mouse 绑定)——本回合交付确定性核心(数学/决策/预算/清单),
  编码与组件是运行时下一步。
- oil-motion 的"关键画面先行"(确认起/中/终状态再生成连续动作)与 hevi 已有
  INC-001 §B action_beats(首/关/尾帧)同构,无需重复内化。

# Round Script2Video 内核(ViMax 五核 · 3O 内化)

> 来源: HKUDS/ViMax Script2Video 内核。不搬 Idea/Novel/Cameo 入口,
> 只内化出片内核五样:三联画 / 首末帧拆解 / 机位树 / 过渡视频 / 参考图选择。
> 分层与 pipeline_lite 同构:`obase ← oprim ← oskill ← omodul ← hevi`。

## 落地

| 五核 | 3O 层 | 落点 |
|---|---|---|
| 角色正/侧/背 | oprim `portrait_prompt` + oskill `portrait_triptych` | `hevi/script2video/oprim/portrait_prompt.py` / `oskill/portrait_triptych.py` |
| 首末帧拆解 | oprim `shot_variation` + oskill `shot_decompose` | `variation.py` / `shot_decompose.py` |
| 机位树 | oprim `camera_graph` + oskill `camera_tree` | `camera_graph.py` / `oskill/camera_tree.py` |
| 过渡视频 | oprim `transition_prompt` + oskill `transition_video` | `transition_prompt.py` / `transition_video.py`(video_gen→xfade) |
| 参考图选择 | oprim `reference_pick`+`image_score` + oskill `reference_select` | 视角几何 / 下标护栏 / 条件 prompt / best-of-k |

| hevi 护城河 | 落点 |
|---|---|
| 三件套事务 | `hevi/production/script2video_kernel_workflow.py` |
| ShotList 投影 | `hevi/director/kernel_bridge.py` |
| 旧 import 兼容 | `hevi/director/{portrait_triptych,camera_tree,transition_video,image_selector,shot_decompose}.py` |

## 3O 归属(待上游)

| 现驻 hevi | 目标 3O |
|---|---|
| `hevi/script2video/schemas.py` | `obase.script2video_schemas` |
| `hevi/script2video/oprim/*` | `oprim.portrait_prompt` / `shot_variation` / `camera_graph` / `image_score` / `reference_pick` / `transition_prompt` |
| `hevi/script2video/oskill/*` | `oskill.portrait_triptych` / `shot_decompose` / `camera_tree` / `transition_video` / `reference_select` |
| `hevi/production/script2video_kernel_workflow.py` | `omodul.script2video_kernel_workflow` |
| `hevi/director/kernel_bridge.py` | 留 hevi(ShotList / SceneStage 字段是护城河) |

## 诚实边界

- 工作流默认只做**文本规划**(拆镜+机位树+要不要末帧)。肖像/过渡要注入 image_gen / video_gen。
- `BestImageSelector` 式 VLM 打分未接线;best-of-k 用容器/尺寸启发式,LLM 分可注入。
- 过渡视频 SceneDetect 抽第二镜首帧未做;xfade 是 ffmpeg 兜底。
- 未改 `produce()` 主路径行为,导演侧通过 `plan_kernel_from_shot_list` 选用。

# Round ViMax 三适配器(Idea / Novel / AutoCameo · 3O)

> 叠在 Script2Video 内核之上。规划默认可离线(无 LLM);像素仍走已内化的三联画/机位树。

## 落地

| 适配器 | oprim | oskill | omodul / production |
|---|---|---|---|
| Idea2Video | `idea_parse`(预算/分场/人名) + `source_route` | `idea_screenwrite` | `plan_idea2video` + `idea2video_workflow` |
| Novel2Video | `novel_split`(切块/抽取压缩/重叠缝/检索) + `character_fuse` | `novel_adapt`(事件链/场/账本) | `plan_novel2video` + `novel2video_workflow` |
| AutoCameo | `cameo_bind`(照片→id/角色定位) | `autocameo`(锁身份并入角色表) | `plan_autocameo` + `autocameo_workflow` |

默认预算对齐 ViMax Agent:**1 场 3–5 镜**,用户写明场数才放大。  
Novel 事件帽 50、每事件最多 5 场;检索分阈值 0.7(无 embedding 时用 token overlap)。  
Cameo 第一张照片 +「主角/我/宠物」→ protagonist,正面肖像用原图。

## 3O 归属(待上游)

| 现驻 hevi | 目标 3O |
|---|---|
| `adapter_schemas.py` | `obase.vimax_adapter_schemas` |
| `oprim/idea_parse.py` 等 | `oprim.idea_parse` / `novel_split` / `character_fuse` / `cameo_bind` / `source_route` |
| `oskill/idea_screenwrite.py` 等 | `oskill.idea_screenwrite` / `novel_adapt` / `autocameo` |
| `production/*2video_workflow.py` / `autocameo_workflow.py` | `omodul.idea2video_workflow` / `novel2video_workflow` / `autocameo_workflow` |

## 诚实边界

- 无 LLM 的故事/事件是脚手架与抽取压缩,不是 ViMax 编剧原文质量。
- 未接 FAISS/BGE;检索是词重叠。
- 未改 `produce()`;导演层 `hevi/director/{idea2video,novel2video,autocameo}.py` 是薄转发。
- 旧 pyc 依赖的 `hevi.agent_runtime.checkpoint` / `render_backend` 未复活。

# Round 接线融合(Idea/Novel/Cameo × 五核 × 主路径)

> 把规划接到真实出片口,而不是停在可调用 API。

## 接线

| 入口 | 做了什么 |
|---|---|
| `POST /api/pipeline/generate` `hub_idea2video` | 接受前端已发的 channel;融合后写入 `locked_shot_list` + `kernel_plan` |
| `plan_from_text` | 附带 `vimax` 融合结果(不改原 shot_prompts,零回归) |
| 导演分镜草案/重生 | `_attach_kernel_plan` 补 `camera_setup_ref` / `action_beats`,落 `work.kernel_plan` |
| `POST .../produce` | `character_references` → `character_subject_ids`(锁脸解析吃得到);带上 kernel |
| `TaskService._resolve_character_reference` | 认 `character_references` 别名 |
| `POST /subjects/from-photo` | Cameo 补 description + metadata.cameo |

融合入口:`hevi.script2video.omodul.fuse.fuse_production`。

# Round Voice-Pro 配音内核(3O)

> 来源: abus-aikorea/voice-pro(本地 Gradio 配音棚,不是 agent)。
> 五核:字幕合句+SRT 时钟拼接 / Demucs 人声床混回 / Cosy 三模式+CV3 前缀 /
> F5 多语目录+多说话人 / 翻译退避保原文。

## 落地

| 五核 | 3O 层 | 落点 |
|---|---|---|
| 字幕合句 + 时钟拼接 | oprim `cue_clock`+`timeline_pad` + oskill `subtitle_timeline` | `hevi/voicepro/oprim/cue_clock.py` / `timeline_pad.py` / `oskill/subtitle_timeline.py` |
| 人声分离 + 盖回伴奏床 | oprim `mix_levels` + oskill `vocal_remix` | `mix_levels.py` / `oskill/vocal_remix.py` |
| Cosy 零样本/跨语/指令 + CV3 | oprim `cosy_mode` + oskill `cosy_payload` | `cosy_mode.py` / `oskill/cosy_payload.py` |
| F5 目录 + 多说话人 | oprim `f5_catalog` + oskill `f5_speakers` | `f5_catalog.py` / `data/f5_models.json` / `oskill/f5_speakers.py` |
| 翻译退避保原文 | oprim `translate_backoff` + oskill `translate_retry` | `translate_backoff.py` / `oskill/translate_retry.py` |

| hevi 护城河 | 落点 |
|---|---|
| 三件套事务 | `hevi/production/voicepro_kernel_workflow.py` |
| 成片导出 | `hevi/dub/translate.py` `dub_video`(合句 / 时钟 / 保床) |
| Cosy HTTP | `hevi/audio/cosyvoice_service.py` 透传 `inference_mode`/`instruct_text` |
| Cosy worker | `services/gen_engine/cosy_worker.py` 三模式 + CV3 前缀 |
| F5 HTTP / worker | `f5_tts_service.py` 按语种点目录;worker 认 `model_name` |
| explainer / router | `HEVI_COSY_INFERENCE_MODE` / `F5_TTS_MODEL_NAME` |

## 3O 归属(待上游)

| 现驻 hevi | 目标 3O |
|---|---|
| `hevi/voicepro/schemas.py` | `obase.voicepro_schemas` |
| `hevi/voicepro/oprim/*` | `oprim.cue_clock` / `timeline_pad` / `mix_levels` / `cosy_mode` / `f5_catalog` / `translate_backoff` |
| `hevi/voicepro/oskill/*` | `oskill.subtitle_timeline` / `vocal_remix` / `cosy_payload` / `f5_speakers` / `translate_retry` |
| `hevi/production/voicepro_kernel_workflow.py` | `omodul.voicepro_kernel_workflow` |
| `hevi/dub/*` 接线 | 留 hevi(成片导出 / Series 字段是护城河) |

## 诚实边界

- 合句用标点/完整句启发式,不捆绑 spaCy/lingua。
- Demucs 只构造命令;没装 demucs 时 `keep_bed` 用原片音轨当床。
- F5 多语权重要宿主机有对应目录,否则 worker 回退 `F5TTS_Base`。
- 翻译退避默认不睡眠(测试注入 `sleep_fn`);线上漏译才按行重试。
- 未搬 RVC / MDX / Azure / Gradio UI。

# Round 五样组合核(配方履约 / 镜头砖 / 过检叠人 / NLE / 矩阵包装)

> 外壳(catalog/配方/kit)已在 2026-08-18。本轮让组合发生在主路径上。

## 落地

| 核 | 落点 | 主路径 |
|---|---|---|
| 配方真编排 | `hevi/studio/fulfill.py` | `run_slate(execute=True)` / `veya.produce(execute=True)` 跑 L0/cues/故事图,写 dispatch JSON |
| 镜头出站 | `hevi/studio/brick.py` | `shot.export` 写砖;导入解说 cue / 通鉴镜 / 导演 ShotList |
| 过检再叠人 | `hevi/studio/compose_gate.py` | 导演 `defer_avatar` 不烤 L6;L8/解说在 QC 后再 `avatar.compose` |
| 成片可切开 | `hevi/studio/nle.py` + `timeline_from_film` | 导入成片、切点带 `source_in_s`、trim/concat 重导出 |
| 矩阵包装 | `hevi/studio/packaging.py` | 分平台标题/封面/标签 × 账号队列;交接单带 account/cover_hint |

三件套:`hevi/production/studio_combine_workflow.py`。

## 诚实边界

- `execute=True` 履约到产品规划(cues/L0/故事图),不在 API 进程里烧 GPU 出片。
- 导演默认仍走 L6 口型;`compose_after_qc=True` 或 `HEVI_COMPOSE_AFTER_QC=1` 才推迟。
- NLE 重编码要 ffmpeg;BGM 必须是存在的音频文件,标签名不算。
- 矩阵仍写交接单,不假装 OAuth 上传。

# Round 常用资产包(名人音色)

> Voice-Pro `celebrities30s.zip`(HF `ABUS-AI/CosyVoice`)。目录可离线检索,音频按需拉取。

| 入口 | 作用 |
|---|---|
| `GET /api/studio/voices` | 列出目录(语种过滤) |
| `POST /api/studio/assets/pull` | 拉 zip、解压、登记 `kind=voice` |
| `voice.list` / `voice.resolve` / `asset.pull` | 工具箱同能力 |
| `F5_TTS_CELEB` / `COSY_CELEB` / `celeb=` | 解析为 F5/Cosy `voice_ref`+转录 |

默认落盘 `HEVI_ASSET_ROOT` 或 `data/workspace/assets/celebrities30s`。

# Round 常用资产 1–4(样音 / 字体+BGM / 手写体+mocap / 公开域种子片)

| 包 | 来源 | 落点 |
|---|---|---|
| `edge-tts-samples` | HF `ABUS-AI/CosyVoice` | 试听 mp3（多语 Neural） |
| `kokoro-tts-samples` | 同上 | Kokoro 试听 |
| `subtitle-fonts` | MPT BeVietnam / Charm（开源） | `assets/subtitle-fonts`；`HEVI_SUBTITLE_FONT_FILE` |
| `stock-bgm` | MPT `resource/songs` 前 10 条 | 同时镜像 `assets/audio/bgm/stock` |
| `handwrite-font` | OpenMontage Patrick Hand (OFL) | `font.list` / `resolve_font("handwrite")` |
| `mocap-clips` | ink-theater 12 张动作卡 | `mocap.list` |
| `open-corpus-seed` | NASA images API + Wikimedia + Archive.org | `data/workspace/assets/open-corpus-seed` |

`GET /api/studio/packs` 列包；`POST /api/studio/assets/pull` `{pack}` 拉取。
