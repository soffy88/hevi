# Hevi 目录结构重构建议（只读咨询稿，未动手）

> 状态：**咨询稿**。只给出建议与成本评估，**未修改任何代码**。
> 起因：hevi/ 顶层 68 个目录混用三种命名语义（层 / 能力 / 出品形式），
> 导致"音频、视频、装配"等能力散落多目录，读起来混乱。
> 依据：全量依赖矩阵（2026-07 实测）+ 各模块代码阅读。

---

## 0. 重构总原则

**一个目录 = 一个能力域，目录名只说一件事。** 顶层只保留三层命名空间：

```
出品形式层  —— 薄，只放"前置层"（B0 故事解析、剧集规划、专属编排胶水），
              不实现任何通用能力。通用能力一律下沉调用。
能力域层    —— 厚，一个能力一个目录：sourcing(素材) / digital_human(数字人)
              / audio / video / assembly / director / verdict / cost / assets...
基础设施层  —— 横切：db / queue / auth / credits / payment / monitoring /
              observability / core / api / mcp / production(组合根)
```

**判据（复用 SPEC-002 的收敛规则）：一个能力别的出品形式会不会也用？会 → 下沉到能力域；不会 → 留在出品形式。**

---

## 1. 十域分组总览

| # | 能力域 | 现状目录 | 建议动作 |
|---|---|---|---|
| 1 | **sourcing 素材供给** | `stock/` + `assets/` | 合并；补对位校验缺口 |
| 2 | **digital_human 数字人** | `digital_human/` + `presenters/` + `audio/avatar_service.py` + `tongjian/scene_render_avatar.py` + 死目录 `livestream/` | 收拢为一个域；删死目录 |
| 3 | **audio 音频** | `audio/` + `audio_library/` + `dub/` + `explainer/voiceover.py` + `tongjian/voiceover.py` 通用部分 + `vault/identity_pack.py` 声线档案 | 合成核心保留，资产/后处理并入 |
| 4 | **video 视频** | `video/` + `image/` + `cinematic/` + `tongjian/scene_render.py` 通用部分 + `director/tongjian_render.py` | provider 接入保留；场景/图生成收拢 |
| 5 | **assembly 装配** | `assembly/`(hevi 件) + **omodul(外部主流水线)** + `tongjian/assemble.py` + `dub/_synth.py` + `director/graph_render.py` | 唯一装配域；通鉴通用件迁入 |
| 6 | **director 导演/剧本** | `director/` + `pipeline/` + `storygraph/` + `season_planner/` | director/pipeline 保留；storygraph+season_planner 合并 |
| 7 | **verdict 裁决** | `verdict/` + `tasks/continuity_report.py` | 保留，明确归属 |
| 8 | **cost 成本/弹性** | `cost/` + `resilience/` | 保留 |
| 9 | **assets 资产** | `subjects/` `style/` `vault/` `series/` `templates/` `gallery/` | 保留（命名已清晰） |
| 10 | **基础设施** | `db/ queue/ auth/ credits/ payment/ monitoring/ observability/ core/ api/ mcp/ production/` | 保留；`api/routers/` 加能力域注释 |

---

## 2. 重点域明细

### 2.1 sourcing 素材供给（用户点名）

**现状**：`stock/` 只有 186 行 = Pexels 搜索（service）+ DB 存储（repository），
被 `pro_studio.py`（/api/pro/stock/search）和 `production/capabilities.py`
（声明为 `stock_search` 能力）消费。

**问题**：
1. 目录名 `stock` 太窄——设计文档 §3.1 把它定位为"零成本供给类型"（空镜/B-roll/转场），
   还要过 **match_score 对位校验**（检索命中 vs 旁白是否对得上，<0.3 触发换素材/回退生成），
   但代码里**没有对位校验实现**（能力缺口，不是结构问题）。
2. `assets/` 是另一条供给桥（hevi async DB → oskill sync asset_loader），
   名字也叫"资产"，与 `vault/`、`stock/` 语义撞车——`assets` 指"供给侧的参考资产"，
   `vault` 指"锁定后的成品锚点资产"，两者是供应链上下游，但名字看不出来。

**建议**：
- `stock/` + `assets/` → 合并为 **`sourcing/`**（供给域），内部 `stock.py`（检索）/ `match.py`（对位校验）/ `bridge.py`（oskill 桥）。
- 对位校验 `match_score(caption, broll)` + 按 StylePack 定制的 keyword_map 列为**能力补全项**（设计 §3.1 已定，未落地）。

### 2.2 digital_human 数字人（用户点名）

**现状**：能力真实存在但碎成 5+ 处：

| 位置 | 内容 | 归属 |
|---|---|---|
| `digital_human/duix_service.py` (95 行) | Duix 直播边界（健康检查/推流），**唯一实现** | 保留为核心 |
| `presenters/models.py` | 出镜形象配置模型（subject_id + voice_profile + performance/motion/lipsync），被 tongjian/shortdrama/director 消费 | **数字人的"配置面"** |
| `audio/avatar_service.py` | 音频数字人（oprim.avatar_generate，肖像图+音频→口型视频） | 数字人的"合成面" |
| `tongjian/scene_render_avatar.py` (1173 行) | 云数字人渲染路径（通鉴 L6，motion_mode=cloud_avatar） | 数字人的"渲染面"，**大头** |
| `explainer/` | 头像解说通道（数字人最薄的消费形态） | 出品形式，保留 |
| `production/` v2 `digital_presenter` 配方 + preflight/preview/approve 端点 | 数字人的"能力声明面" | 保留，指向核心 |
| `pro_studio.py` livestream 端点 | 直播入口 | 保留，指向核心 |
| `livestream/`（只剩 __pycache__，源码已删） | **死目录** | **删除** |

**建议**：
- 数字人统一为 **`digital_human/` 域**，四层结构：`presenters/`（配置模型，从 presenters 迁入）→ `duix.py`（直播）→ `avatar.py`（合成，从 audio 迁入）→ `render/`（渲染路径，从通鉴 scene_render_avatar 抽通用件迁入）。
- 通鉴的 `scene_render_avatar.py` 1173 行里，**通用渲染件**（口型对齐、肖像→视频）上收，**通鉴专属件**（水墨/卡通风格文案、旁白描述式）留在通鉴——这步风险高，见 §4。
- **立即做**：删除 `livestream/` 死目录（先 grep 确认无引用）。

### 2.3 audio 音频

**现状**：合成核心 `audio/`（vibevoice 子进程隔离 + edge_tts/cosyvoice/qwen_tts/voicebox + avatar_service + bgm_library），
但"音频"被切成 7 份。

**建议**：
- `audio/` 保留 = **合成核心**（TTS 引擎 + 子进程隔离 + 情绪注入）。
- `audio_library/`（资产表 + 服务）→ 并入 `audio/` 为 `library.py`（资产是音频域的附属）。
- `dub/`（ASR→翻译→TTS→装配重烧）→ 并入 `audio/` 为 `dub.py`（音频后处理）。
- `tongjian/voiceover.py` 的**通用部分**（逐句情绪 → rate/pitch）→ 上收 `audio/`；通鉴专属的旁白风格保留。
- `vault/identity_pack.py` 的声线档案（voice）→ 属音频资产，文档标注即可，不必物理迁移（vault 是存储层，音频资产存在那里合理）。

### 2.4 video 视频

**现状**：`video/`（2539 行）provider 接入最干净（一个 provider 一个文件），
但视频生成同时存在于 `image/`（关键帧/图生）、`cinematic/`（场景闭环）、
`tongjian/scene_render*.py`、`director/tongjian_render.py`。

**建议**：
- `video/` 保留 = 云端 provider 接入 + 能力矩阵（capability_guard）。
- `image/` 是**图像生成**（qwen_image/fal/sdxl_local/json2video 场景专用），与视频并列的独立能力域，**保留**，但 json2video 明确标注"场景背景专用，禁人物"（已有红线）。
- `cinematic/`（scene_adapt/shot_planning/video_gen/platform_binding，M3 场景闭环）→ 与 `video/` 重叠度高，**评估合并**（video_gen 并入 video/，scene_adapt 并入导演层或场景资产）。
- 通鉴 `scene_render.py` 的通用画面生成件与 director/tongjian_render.py 同理，通用件上收、专属件保留。

### 2.5 assembly 装配/编译（用户点名的"编译"）

**现状**：`assembly/`（1067 行）是 hevi 侧装配件：assembler/beat_align/subtitle_align/subtitle_burner/
transition/cover_extractor/exporter/postprocess_service/aspect_ratio。
**但主装配流水线在外部 omodul 库**（`omodul.longvideo_produce`），hevi 的 assembly 只在
管线末端调用。通鉴还有一套自建 `tongjian/assemble.py`（727 行，L8）。

**建议**：
- `assembly/` 就是唯一装配域，**保留**，但文件头加注释明确边界："主流水线在 omodul，
  hevi 侧只做 hevi 专属件（字幕烧录样式/调色归一/转场卡点/多轨对齐范式）。"
- 通鉴 `assemble.py` 的**通用件**（atrim+concat 裁剪、select+setpts、字幕 remap_time、
  batch_normalize、BGM 节拍卡点）→ 上收 `assembly/`，通鉴只留排版/风格专属逻辑。
- `dub/_synth.py`（重烧）→ 复用 assembly，删除重复。

### 2.6 director / 出品形式

**现状**：`director/`（SPEC-003 五级链）+ `pipeline/`（编排枢纽，依赖 12 域，健康）+ 
`storygraph/` + `season_planner/`（短剧前置，两个目录实为一体）+ 
出品形式 `tongjian/` `explainer/`。

**建议**：
- `pipeline/` 保留，它是唯一编排枢纽，**不是乱，是汇聚**——加文件头注释说明即可。
- `storygraph/` + `season_planner/` → **合并为 `shortdrama/`**（出品形式目录，含前置层）。
- `director/` 保留；`director_pipeline` 只是它的 API 面。
- `tongjian/` `explainer/` 瘦身（通用件下沉后只留前置与编排）。

---

## 3. 行动清单（按成本排序）

### 🟢 低风险（不动逻辑，纯清理，可立即做）
| # | 动作 | 成本 |
|---|---|---|
| A1 | 删除 `hevi/livestream/` 死目录（确认无 import 后） | 5 分钟 |
| A2 | 写 `docs/ARCHITECTURE-MAP.md`：目录→能力域映射表 + 上面这份分组 | 30 分钟 |
| A3 | `api/routers/` 每个文件头加一行所属能力域注释 | 20 分钟 |
| A4 | `assembly/`、`pipeline/` 文件头加边界注释（外部库/汇聚点） | 20 分钟 |

### 🟡 中风险（移动 + 改 import，跑全量测试可兜底）
| # | 动作 | 涉及 |
|---|---|---|
| B1 | `stock/` + `assets/` → `sourcing/` | ~6 文件，import 改 4 处 |
| B2 | `audio_library/` → `audio/library.py` | ~5 文件 + 1 条 migration 不动（表名保留） |
| B3 | `dub/` → `audio/dub.py` | ~4 文件 |
| B4 | `storygraph/` + `season_planner/` → `shortdrama/` | ~10 文件，import 改 15+ 处 |
| B5 | `presenters/` 迁移到 `digital_human/presenters.py`（或文档声明归属） | ~4 文件 |

### 🔴 高风险（动大文件，回归风险高，建议缓做或只做文档声明）
| # | 动作 | 风险 |
|---|---|---|
| C1 | 拆分 `tongjian/scene_render_avatar.py`（1173 行）通用件上收 | 通鉴 L6 真实跑通件，拆错即回归 |
| C2 | 拆分 `tongjian/assemble.py`（727 行）通用件上收 | 同上 |
| C3 | 拆分 `tongjian/voiceover.py` 通用部分 | 同上 |
| C4 | 顶层目录改名（`video`/`audio` 等） | 几十处 import + 测试 + 部署 |
| C5 | 补 `stock` 对位校验 match_score | 不是重构是能力补全，需设计 keyword_map 数据 |

---

## 4. 性价比排序（建议执行顺序）

1. **A1 + A2（立即）**：删死目录 + 落盘能力映射文档——5 分钟消除 80% 的"不知道去哪找"。
2. **B1（本周）**：sourcing 合并，素材域成型。
3. **B4（本周）**：短剧前置合并，出品形式边界清晰。
4. **B2/B3/B5（次周）**：音频收拢 + 数字人配置面归位。
5. **C 系列（缓）**：通鉴大文件拆分是"锦上添花"，收益是结构整洁，风险是打坏已验证链路——
   **在下一个通鉴真实需求进来时顺手做**，不专门立项。
6. **C5 对位校验**：跟随下一个用到 stock 的出品形式（如短剧 B-roll）一起做。

---

## 5. 结论

**重构的真正收益不是目录变少，而是"能力 → 位置"的映射恢复直觉：**
- 素材去哪找 → `sourcing/`
- 数字人改哪 → `digital_human/`（配置/直播/合成/渲染四层）
- 加个 TTS 引擎 → `audio/`
- 加个云端 provider → `video/`
- 改装配逻辑 → `assembly/`（hevi 件）+ omodul（主流水线，边界写清）
- 看出品形式怎么串 → `pipeline/` 唯一枢纽 + 各出品形式前置目录

**低风险清理（A 系列）今天就能做，中风险合并（B 系列）一周内可完成，
高风险拆分（C 系列）留到自然触发的下一次需求。**
