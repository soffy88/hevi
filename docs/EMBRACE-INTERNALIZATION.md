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
