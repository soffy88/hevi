# Hevi 竞品能力差距分析 (Competitive Gap)

> 状态: 2026-08-18 初版存档 | 用途: 定义 hevi 相对 6 个开源竞品的能力差距, 作为后续优化(3O 内化/新增集成)的清单依据。
> 对照仓库: MoneyPrinterTurbo / OpenMontage / Toonflow-app / agent-video-pipeline / LuxTTS / claude-video (均浅克隆于 `/tmp/repo-analysis/`)。

---

## 0. 结论先行

- **hevi 的制片厂内核(一致性/裁决/成本/调度)全面领先 6 个竞品** —— 差距不在"深", 在"广"。
- 差距本质 = **外壳能力缺失**: 免费素材路径、provider 可解释路由、Agent 记忆、参考视频分析、轻量快速通道、发布闭环、Prosody/边界 QC、可编程插件。
- 与 `HEVI-ARCHITECTURE.md` 自评一致(深度不砸广度), 但**免费素材 + 参考视频 + 发布**是三块用户直接感知的体验缺口, 应优先补。

---

## 1. 竞品能力画像

### 1.1 MoneyPrinterTurbo — 一键短视频流水线
| 能力 | 说明 |
|------|------|
| 极简路径 | 主题/关键词 → LLM 脚本 → 素材搜索(Pexels/Pixabay/Coverr + 缓存 + 尺寸/时长匹配) → 7 种 TTS → 字幕(字体/位置/颜色/描边/背景全可调) → BGM → ffmpeg 合成 |
| 4 种形态 | AI Agent / Streamlit WebUI / API / CLI; 批量生成+择优 |
| LLM 广覆盖 | 12+ 直连(OpenAI/Gemini/DeepSeek/通义/火山/Grok/MiniMax/MiMo…) + 8 网关(OneAPI/LiteLLM/Ollama/Cloudflare AI Gateway…) |
| 一键发布 | TikTok / Instagram / YouTube Shorts 自动上传 |
| 架构 | controller/service/model 分层 + 任务状态机 + 素材缓存 |

### 1.2 OpenMontage — Agent-first 制片系统 (与 hevi 最同构)
| 能力 | 说明 |
|------|------|
| Agent-first 编排 | 无代码 orchestrator, coding agent 即制片人; 13 条 YAML pipeline manifest |
| 统一流程 | research → proposal → script → scene_plan → assets → edit → compose; 每阶段 director skill + checkpoint 断点续跑 + 审批门 |
| **7 维 provider 评分** | task_fit(0.30)/output_quality(0.20)/control(0.15)/reliability(0.15)/cost_efficiency(0.10)/latency(0.05)/continuity(0.05); `ProviderScore.explain()` 可解释决策日志 |
| **delivery promise** | 8 种承诺类型 + min_motion_ratio 规则表; 静默降级(motion→still)即停机 |
| **Backlot 活态故事板** | 阶段亮灯/脚本落屏/花费上墙/场景级 contact sheet 审批门(takes+成本+质量分)/ ▶REPLAY RUN 回放 |
| 免费出片路径 | Piper TTS + Archive.org/NASA/Wikimedia **CLIP 语义检索语料库**(真实素材剪辑) + Pexels/Unsplash/Pixabay 免费 key |
| 参考视频驱动 | 粘贴 YouTube/TikTok → 转录/节奏/场景/关键帧分析 → 2-3 差异化概念 + 成本估算 + 样片 |
| 双渲染运行时 | Remotion(React) + HyperFrames(HTML/GSAP 动效、SVG 角色动画) |
| 一等研究阶段 | 15-25 次 web 搜索 + 引用; 100+ 工具(face_tracker/scene_detect/bg_remove/upscale/color_grade…) / 60+ provider / 700+ skill 文件 |

### 1.3 Toonflow-app — 短剧工厂工作台 (最贴近 hevi 短剧通道)
| 能力 | 说明 |
|------|------|
| 桌面应用 | Electron + Node + better-sqlite3 + Vercel AI SDK |
| 三层 Agent | 决策层(ScriptAgent/ProductionAgent) / 执行层 / 监督层 |
| **持久化 Agent 记忆** | 本地 ONNX 向量检索: 短记忆/长摘要/语义召回 |
| 章节事件图谱 | 自动提取原著章节事件结构化存储, 驱动改编 |
| 无限画布工作台 | 类 Figma 节点编排 |
| 可编程供应商 | 设置中心写 TypeScript 供应商逻辑即时生效, 无需改源码/重启 |
| Skill 文件化 | 核心 prompt 外化为 Markdown 在线编辑 |

### 1.4 agent-video-pipeline — 严格 QC 的本地流水线 Skill
| 能力 | 说明 |
|------|------|
| 配置契约铁律 | 外部配置根 `.agent-video/`(profiles/runtime/projects/assets) + resolved profile **冻结 + SHA 校验 + 来源角色**; 配置失效即停止 |
| 不可变质量规则 | 上游缺失/未批准/QC 失败/SHA 过期 → 停下游; 音画同步强制; 数字人用同一份获批母带 |
| QC 脚本面 | 12 个 validate: prosody / voice_stability / av_alignment / scene_pacing / semantic_motion / layout_boxes / episode_independence / audio_boundaries + run_gates |
| Prosody 前置 | 先产 prosody.json(重音/停顿/语速) 再配音 |
| 其他 | 语义运动规划 / VoxCPM2 本地 TTS / 批量生产 / 断点续跑 / 增量重建 / 隐私边界(个人素材外置) |

### 1.5 LuxTTS — 轻量高质克隆 TTS (模型)
| 能力 | 说明 |
|------|------|
| 性能 | zipvoice 架构蒸馏 **4 步采样**、**48kHz**、**150x 实时**、**<1GB VRAM**、CPU 可跑、MPS |
| 克隆 | SOTA 级声音克隆(对标 10 倍大模型); 采样参数 rms/t_shift/speed/return_smooth |
| 生态 | Gradio / ComfyUI 节点 / ONNX / fal.ai 托管 |

### 1.6 claude-video (/watch) — 给 Agent「看视频」
| 能力 | 说明 |
|------|------|
| 视频理解 | yt-dlp 下载 + 字幕优先(免费) + Whisper 兜底(Groq/OpenAI) |
| 帧工程 | 场景感知抽帧 + keyframe 快速模式 + 帧去重(16×16 灰度 MAD) + 自动帧预算(时长→帧数) + 3 档 detail + --start/--end 聚焦窗口 |
| 多宿主 | Claude Code / Codex / Cursor / 50+ agents 插件 |

---

## 2. hevi 差距清单

### 🔴 A 级: 架构级差距

| # | 差距 | 竞品参照 | hevi 现状 | 处置 |
|---|------|---------|-----------|------|
| A1 | **Provider 多维可解释评分 + 决策日志** | OpenMontage 7 维加权 + explain() | 有 ProviderRegistry/成本路由, 但元数据散在 3 张 video-only dict, 选择不可解释、无审计日志 | 3O 内化: hevi/providers/scoring.py |
| A2 | **Pipeline manifest 化 + checkpoint 断点续跑** | OpenMontage YAML manifest + checkpoint; obase.Pipeline/Stage/RunState | 管线写死在代码里, 无 manifest 文件、无跨阶段 checkpoint 恢复 | 3O 内化: obase.Pipeline 骨架 + YAML loader |
| A3 | **Agent 记忆系统(跨会话)** | Toonflow ONNX 向量检索短/长记忆 | 无跨会话 Agent 记忆, 长文改编上下文靠 prompt 硬塞 | 新增: hevi/memory/ (SQLite + 语义召回) |
| A4 | **免费/开放素材语料库 + 语义检索** | OpenMontage Archive.org/NASA/Wikimedia + CLIP; MPT Pexels/Pixabay/Coverr | 只有 Pexels stock | 新增: hevi/video/material_corpus.py |
| A5 | **轻量「主题→短视频」快速通道** | MPT 极简路径 | 全是重流程(制片厂), 无「一句话出片」档 | 新增: hevi/quick/ (omodul 风格) |

### 🟠 B 级: 能力级差距

| # | 差距 | 竞品参照 | hevi 现状 | 处置 |
|---|------|---------|-----------|------|
| B1 | 视频理解/参考视频驱动创作 | claude-video /watch + OpenMontage reference_input | ✅ 已有 hevi/ingest/ + hevi-watch skill(摄入侧); 参考视频→概念链路未接 | 已覆盖摄入侧; 概念链路留 TODO |
| B2 | 跨平台一键发布 | MPT TikTok/IG/YT Shorts | 无发布闭环 | 新增: hevi/publishers/ 骨架 |
| B3 | Prosody 前置 + 音频边界稳定化 | AVP analyze_prosody + stabilize_aligned_continuous | 有 subtitle_align, 无 prosody 规划层 | 新增: hevi/audio/prosody.py |
| B4 | 质量检查面广度 | AVP 12 个 validate | verdict 强于图像身份/返工; 语速节奏/边界稳定性/集独立性缺 | 新增: hevi/verdict/production_checks.py |
| B5 | 可编程供应商插件 | Toonflow 设置中心写 TS 即时生效 | 加 provider 要改代码+重建容器 | 新增: hevi/providers/plugin_config.py (能力声明文件加载) |
| B6 | 双渲染运行时 | OpenMontage Remotion + HyperFrames | ✅ `video/hyperframes` + `kinetic_promo` + `runtime.select`(2026-08-18)。缺 CLI 逐卡回退,不拆 Remotion | 已接线 |
| B7 | 活态制片状态板 + 场景级审批门 + 回放 | OpenMontage Backlot | 有导演台 DP2, 无花费上墙/REPLAY RUN/contact sheet 审批 | 文档 TODO |
| B8 | 轻量本地克隆 TTS 档 | LuxTTS 4 步/48kHz/<1GB/CPU | 有 F5/CosyVoice/Echo(重、GPU), 缺 LuxTTS 级低资源档 | 新增: hevi/audio/lux_tts_service.py (可选集成) |
| B9 | ✅ | `hevi/video/material_corpus.py` + `GET /api/material/{source}` | 2026-08-18 |
| B10 | 实时网络研究为一等阶段 | OpenMontage research 15-25 次搜索+引用 | screenplay 无系统化事实研究/引用 | 3O 内化: oskill.web_research + hevi/research/ |
| B11 | 参考音频→克隆试听/对比 UI | MPT TTS 实时试听 | voice_studio 有, 集成深度待比 | 文档 TODO |

### 🟡 C 级: 形态/体验差距
- CLI 形态(MPT 四形态; hevi 缺产品化 CLI) — 部分已有 hevi/skills/*_cli.py
- 桌面端(Toonflow Electron; hevi 纯 SaaS Web) — 不做
- 多语言 UI(Toonflow 7 语言; hevi 中文为主) — 不做
- 批量生成+择优(MPT 批量多视频选最优; hevi 单任务) — 文档 TODO
- 社区生态(LuxTTS ComfyUI 节点/Gradio/ONNX; hevi 无) — 不做

---

## 3. hevi 反超的护城河(竞品没有的)

- **系列化身份一致性**: Subject 2D CLIP 锁 + Subject3D 视角帧, 跨集身份继承(竞品全是单视频)
- **五档 verdict 返工闸 + canon-copy 字节比对 + 台词 provenance 红线**(竞品只有浅审)
- **场面调度 SceneStage**: 空间图/落位/轴线/注意力/机位几何投影
- **预算熔断**: season 级 circuit_breaker + credits + payment 闭环
- **数字人口型生产级**: EchoMimicV2 已切生产默认
- **H3 w4a8 本地真机出片 + FlashVSR/RIFE 后处理**
- **中文内容原生** + 1300+ 测试的工程成熟度

---

## 4. 优化执行记录

| 差距 | 状态 | 落点 | 日期 |
|------|------|------|------|
| A1 | ✅ | `hevi/providers/scoring.py` | 2026-08-18 |
| A2 | ✅ | `hevi/pipeline/manifest.py` (obase.Pipeline + YAML loader) | 2026-08-18 |
| A3 | ✅ | `hevi/memory/` | 2026-08-18 |
| A4/B9 | ✅ | `hevi/video/material_corpus.py` | 2026-08-18 |
| A5 | ✅ | `hevi/quick/` | 2026-08-18 |
| B2 | ✅ | `hevi/publishers/`(TikTok/IG/YT 空实现 + 国内矩阵交接单 dy/ks/xhs/sph/bilibili) | 2026-08-18 |
| B3 | ✅ | `hevi/audio/prosody.py` | 2026-08-18 |
| B4 | ✅ | `hevi/verdict/production_checks.py` | 2026-08-18 |
| B5 | ✅ | `hevi/providers/plugin_config.py` + `GET /api/providers/plugins`(目录级加载/评分/注册) | 2026-08-18 |
| B8 | ✅ | `hevi/audio/lux_tts_service.py` | 2026-08-18 |
| B10 | ✅ | `hevi/research/` (oskill.web_research) | 2026-08-18 |
| B6/B7/B11 | ⏳ TODO | 见 §4.1(B7 后端事件流已落地, 前端板待排期) | — |
| 组合层 | ✅ | 100+ catalog 工具 + 13 条配方(含 kinetic_promo) + 日更/Veya + HyperFrames 第二运行时 + 画布/时间线 | 2026-08-18 |

### 4.1 后续 TODO(未实施项)
- **B7 Backlot 前端板**: 后端事件流已落地(`hevi/backlot/` + `GET/POST /api/backlot/runs/{run_id}/events` + `/status`), 前端亮灯板/花费上墙后续排期。
- **B2 真实平台上传**: 国内矩阵已写交接单(`handoff` + `HEVI_MATRIX_WEBHOOK`/`MATRIXMEDIA_BIN`);TikTok/IG/YT 仍需平台开发者账号。
- **B6 HyperFrames 集成**: HTML/GSAP 渲染运行时, 需评估与 Remotion 场景栈的并存策略(OpenMontage 在 proposal 期锁定 render_runtime)。
- **B11 TTS 试听 UI**: voice_studio 已有基础, 补对比试听。
- **B1 参考视频→差异化概念**: ✅ 已落地 —— `hevi/ingest/reference_concepts.py`(watch 结果 → 节奏分析(语速/句密度) → LLM 差异化概念 + 成本估算; 无 LLM/解析失败确定性兜底; 10 测试)。
- **CLIP 语义素材检索**: ✅ 已落地 —— `hevi/sourcing/corpus.py`(Archive.org/本地片段收录 → 首帧 CLIP 嵌入 → `rank_for_slot` 文本检索 / `find_similar_set` MMR, 中文 query 经本地 ollama 翻译兜底; 8 测试)。
- **C 级批量生成+择优**。
