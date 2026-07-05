# HEVI-SPEC-01: 导演台全自动视频流水线(资治通鉴 → 成片)

- **状态**: DRAFT
- **版本**: v0.1
- **目标**: 输入《资治通鉴》任一章节原文,零人工干预输出 3 分钟左右的历史解说视频(1080p,含配音、字幕、音乐)
- **设计原则**: 编译器式流水线 —— 每层是一个 oskill,层间产物是带 schema 的 JSON artifact,层间靠契约衔接、靠校验门守卫、靠降级策略保证永不卡死

---

## 0. 总体架构

### 0.1 DAG 拓扑

```
[原文] → L0 史料预处理 → L1 立意 → L2 剧本
                                      │
                          ┌───────────┼──────────────┐
                          ▼           ▼              ▼
                     L3 配音(TTS)  L5 角色卡      L7 音乐规划
                          │           │              │
                          ▼           ▼              │
                     L4 分镜(音频定时长)             │
                          │           │              │
                          ▼           ▼              │
                     L6 场景/画面生成(大规模并行)     │
                          │                          │
                          └──────────┬───────────────┘
                                     ▼
                          L8 字幕 + 剪辑合成(确定性代码)
                                     ▼
                                  [成片.mp4]
```

关键依赖顺序(与直觉不同的两点):
1. **音频先行定时长**: L3 配音在 L4 分镜之前。TTS 产出逐句时间戳,shot 时长由音频切分决定,彻底规避音画对齐问题。
2. **L5 角色卡与 L3 配音并行**,两者都只依赖 L2 剧本;L4 分镜同时消费 L3 的时间戳和 L5 的角色表。

### 0.2 3O 映射

| 3O 层 | 本项目内容 |
|---|---|
| oprim | `llm_call`, `tts_synthesize`, `image_generate`, `image_similarity`, `asr_transcribe`, `ffmpeg_exec`, `content_hash`(复用 Stratum 验证过的 content-addressing) |
| oskill | `extract_chapter_ir`, `draft_constitution`, `write_script`, `synthesize_voiceover`, `build_shotlist`, `build_character_bible`, `generate_scene_asset`, `plan_music`, `assemble_video`;每个校验门也是独立 oskill: `gate_factcheck`, `gate_visual_qa`, `gate_av_sync` |
| omodul | `pipeline_orchestrator`(DAG 调度 + 状态机 + 断点续跑 + 降级决策) |
| Layer 4 | hevi-director 自己的 DB DDL、通鉴领域 prompt 库、导演台 UI(全自动模式 = 8 层参数只读展示 + 一键运行) |

### 0.3 通用规则

- 所有层间 artifact 落盘至 `runs/{run_id}/L{n}/`,同时元数据入 PostgreSQL
- 所有生成资产(图/音频)以内容哈希命名,可寻址、可复用、可缓存
- 每层出口有校验门;门失败 → 重试(最多 N 次,带 prompt 变异)→ 仍失败则执行降级策略,**流水线永远能跑完**
- ID 规范: `run_id`(uuid), `event_id`(E001…), `character_id`(C001…), `scene_id`(S001…), `shot_id`(SH001…), `line_id`(LN001…)

---

## 1. L0 史料预处理(chapter → chapter_ir.json)

导演台 8 层之外、但决定成败的一层。文言原文不可直接喂立意层。

### 1.1 子步骤

1. **分段与断句**: 按"臣光曰"、纪年标记、事件转折切分叙事单元
2. **纪年换算**: 干支/王年 → 公元纪年(规则表 + LLM 兜底,规则优先)
3. **人物消歧(最关键)**: 同一人以名/字/官爵/谥号/代称("上""帝")多形态出现,全部归一到唯一 `character_id`。实现: LLM 抽取所有人物提及 → 聚类合并 → 与预置《通鉴人物权威表》(可从维基数据/CBDB 构建)比对锚定
4. **事件链抽取**: 复用 Mneme KU 抽取管线的方法论(002 版本体的抽取纪律直接迁移:证据与实体分离、每事件必须锚定原文出处 span)
5. **引语抽取**: 原文对话("智伯曰: …")单独成表 —— 这是配音的天然角色台词素材

### 1.2 输出契约 `chapter_ir.json`

```json
{
  "meta": {
    "source": "资治通鉴·周纪一",
    "year_range": [-403, -376],
    "char_count": 4200
  },
  "characters": [
    {
      "character_id": "C001",
      "canonical_name": "智伯",
      "aliases": ["智瑶", "智襄子"],
      "role_in_chapter": "antagonist",
      "faction": "智氏",
      "fate": "身死族灭",
      "source_spans": [[12, 15], [88, 90]]
    }
  ],
  "events": [
    {
      "event_id": "E003",
      "summary": "智伯向韩康子索地,段规劝韩康子予之以骄其志",
      "actors": ["C001", "C004", "C005"],
      "location": "韩氏",
      "year": -455,
      "causes": ["E002"],
      "effects": ["E004"],
      "dramatic_weight": 4,
      "source_span": [230, 310]
    }
  ],
  "quotes": [
    {
      "quote_id": "Q007",
      "speaker": "C001",
      "original": "难将由我,我不为难,谁敢兴之!",
      "modern": "祸乱要发生也得由我发起,我不发难,谁敢?",
      "event_id": "E005",
      "emotion": "狂傲"
    }
  ],
  "locations": [
    {"scene_hint_id": "S_HINT_01", "name": "晋阳城", "type": "城池", "events": ["E006", "E007"]}
  ]
}
```

### 1.3 校验门 G0

- 结构校验: JSON Schema 强校验
- 覆盖率校验: 事件 source_span 拼接覆盖原文叙事部分 ≥ 85%(防漏抽)
- 人物闭环: 所有 event.actors / quote.speaker 引用的 character_id 必须存在
- 幻觉抽查: 随机抽 20% 事件,LLM 反向核对 source_span 原文是否支持 summary

**降级**: 人物消歧失败的提及 → 保留为独立匿名角色(旁白代述,不给角色戏份)

---

## 2. L1 立意(chapter_ir → constitution.json)

产物不是一句主题,而是**创作宪法** —— 下游所有层的 prompt 都注入它,所有校验门拿它审风格。这是全自动模式下风格一致性的唯一抓手。

### 2.1 输出契约 `constitution.json`

```json
{
  "thesis": "三家分晋:礼崩乐坏,始于名分之破",
  "logline": "一场看似普通的封侯,如何终结了一个时代的秩序",
  "narrative_stance": "上帝视角旁白 + 司马光史评穿插",
  "tone": ["肃杀", "克制", "史诗感"],
  "visual_style": {
    "art_direction": "水墨质感历史插画,低饱和,烛光/暮色主导",
    "palette": ["#2b2b2b", "#8b0000", "#d4c5a0"],
    "aspect_ratio": "16:9",
    "negative_style": ["动漫", "赛博朋克", "鲜艳色彩"]
  },
  "act_structure": [
    {"act": 1, "title": "名分之争", "events": ["E001", "E002"], "emotion_curve": "压抑铺垫"},
    {"act": 2, "title": "智伯之亡", "events": ["E003", "E004", "E005", "E006"], "emotion_curve": "冲突攀升至爆发"},
    {"act": 3, "title": "礼之终结", "events": ["E007", "E008"], "emotion_curve": "余韵与史评"}
  ],
  "forbidden": ["现代梗", "戏说腔", "未出现于原文的情节"],
  "target_duration_sec": 180,
  "bgm_mood_arc": ["低沉弦乐", "战鼓渐强", "孤箫收尾"]
}
```

### 2.2 校验门 G1

- act_structure 引用的 event_id 全部存在于 chapter_ir
- dramatic_weight ≥ 4 的事件必须被某一幕收录(防丢关键剧情)
- target_duration 与事件数量的合理性检查(180 秒 / 8 事件 ≈ 每事件 22 秒,阈值区间 [10, 45] 秒)

**降级**: 生成 3 版宪法 → LLM-as-judge 按"史实覆盖 + 戏剧性"打分取最优(自动模式下的 best-of-N,代替人工挑选)

---

## 3. L2 剧本(constitution + chapter_ir → script.json)

### 3.1 规则

- 每一行(line)必须标注类型: `narration`(旁白)/ `dialogue`(角色台词)/ `commentary`(臣光曰史评)
- **dialogue 只能改写自 quotes 表**,不允许 LLM 原创对白(这是通鉴题材的红线 —— 观众里懂行的多,原创一句台词就是硬伤)
- 每行锚定 event_id,供 G2 史实校验回溯
- 按经验值预估时长: 中文口播 ≈ 4.5 字/秒,总字数 ≈ target_duration × 4.5 × 0.85(留 15% 给停顿和音乐呼吸)

### 3.2 输出契约 `script.json`

```json
{
  "lines": [
    {
      "line_id": "LN001",
      "act": 1,
      "type": "narration",
      "speaker": "NARRATOR",
      "text": "公元前四百零三年,周威烈王做了一件小事——册封晋国的三位大夫为诸侯。",
      "event_id": "E001",
      "emotion": "平静中藏锋",
      "visual_hint": "周天子宫殿,竹简诏书特写"
    },
    {
      "line_id": "LN014",
      "act": 2,
      "type": "dialogue",
      "speaker": "C001",
      "text": "祸乱要起,也得由我来起。我不发难,谁敢?",
      "quote_id": "Q007",
      "event_id": "E005",
      "emotion": "狂傲",
      "visual_hint": "智伯宴席上举杯,睥睨众人"
    }
  ]
}
```

### 3.3 校验门 G2(史实门,全管线最重要的门)

1. 每个 dialogue 行必须有 quote_id 且语义与原引语一致(LLM 比对,阈值判定)
2. LLM 拿 script 全文对照 chapter_ir 逐行审: 是否出现原文不存在的情节、官职、称谓(输出违规行清单)
3. forbidden 清单扫描(现代词汇黑名单 + LLM 风格审)
4. 字数与 target_duration 偏差 ≤ 15%

**降级**: 违规行定点重写(只重写违规行,不整篇重跑,省 token);3 次仍违规 → 删除该行并由相邻旁白补桥接句

---

## 4. L3 配音(script → audio assets + timeline.json)

### 4.1 声音分配

- 旁白: 固定 1 个 voice_id(沉稳男声/女声,宪法 tone 决定)
- 角色: character_bible(L5)中每个有台词的角色分配独立 voice_id;自动模式下按 `性别+年龄段+role_in_chapter` 从预置声音池选取
- 臣光曰: 单独一个苍老声线(强烈建议,史评的声音辨识度是这类视频的记忆点)

### 4.2 TTS 选型

| 方案 | 定位 | 说明 |
|---|---|---|
| CosyVoice 2(本地) | 首选 | 中文效果好,支持情感标签,3080 10GB 可跑;emotion 字段映射到情感指令 |
| GPT-SoVITS(本地) | 角色定制 | 需要为固定角色训练音色时用 |
| 云 TTS(Minimax/火山豆包) | 兜底与提速 | 本地排队过长或情感表现不达标时切换,成本约 ¥0.3-0.6/千字 |

### 4.3 输出契约 `timeline.json`

```json
{
  "audio_segments": [
    {
      "line_id": "LN001",
      "file": "audio/ln001_a3f8.wav",
      "duration_ms": 6820,
      "t_start_ms": 0,
      "t_end_ms": 6820,
      "char_timestamps": [[" 公", 0, 180], ["元", 180, 340]]
    }
  ],
  "total_duration_ms": 176400,
  "gaps": [
    {"after_line": "LN008", "duration_ms": 1500, "purpose": "act_transition"}
  ]
}
```

规则: 幕间自动插入 1.5s 空隙(音乐呼吸位);total_duration 与 target 偏差 > 20% 时回退 L2 定点增删行。

### 4.4 校验门 G3

- 每段音频 ASR 反打(whisper/paraformer)与原文 diff,字错率 CER ≤ 5%(TTS 偶发吞字、多音字错读,必须机器审)
- 音量归一化检查(-16 LUFS 目标)

**降级**: CER 超标的行 → 换云 TTS 重合成;多音字错读 → 注音标注后重合成(维护一个通鉴专有名词注音表: 郤、逢泽、龟兹…,持续积累)


---

## 5. L5 角色卡(script + chapter_ir → character_bible.json)

> 层号顺序上写在 L4 前,因为 L4 分镜要消费角色卡。

角色视觉一致性是全自动历史视频的第一大翻车点。解法: **每个角色生成一次权威参考图,之后所有 shot 引用参考图而非文字描述**。

### 5.1 流程

1. 从 script 统计出有戏份的角色(出现在 dialogue 或 visual_hint 中)
2. LLM 依据 chapter_ir(年代、身份、fate)+ 宪法 visual_style 生成外形描述
3. 文生图产出 3 张候选正面立绘 → VLM 审(服饰年代正确性: 战国不能穿唐装)→ 选定 1 张为权威参考图
4. 锁定 `(ref_image_hash, seed, lora)` 三元组,写入角色卡

### 5.2 输出契约 `character_bible.json`

```json
{
  "characters": [
    {
      "character_id": "C001",
      "name": "智伯",
      "appearance": "四十余岁男性,魁伟,美髯,战国晋国贵族深衣,玄色镶红边,神情倨傲",
      "ref_image": "assets/char_c001_9d2e.png",
      "gen_lock": {"seed": 42137, "ip_adapter_weight": 0.75},
      "voice_id": "cosyvoice:male_arrogant_02",
      "era_check": "战国早期服制:深衣、束发、无幞头"
    }
  ]
}
```

### 5.3 一致性技术选型

- 首选: **IP-Adapter / InstantID / PuLID + 参考图**(SDXL 生态,3080 10GB 可跑)
- 每个 shot 生成时: prompt 描述动作场景,角色长相完全由参考图注入
- 兜底: 角色戏份 < 2 个镜头的配角不做一致性锁定(成本不值)

**校验门 G5**: VLM(本地 MiniCPM-V 4.5 Q4,3080 可跑)审参考图 —— 服制年代、性别年龄与描述一致性;失败重 roll,3 次失败 → 降级为剪影/背影风格角色(反而有史诗感,是个体面的降级)

---

## 6. L4 分镜(timeline + script + character_bible → shotlist.json)

### 6.1 切分规则(确定性代码 + LLM 补充)

- 基础切分: 每个 audio_segment 默认 1 个 shot;时长 > 8s 的段落 LLM 决定拆成 2-3 个 shot(同场景变机位)
- shot 时长 = 音频切分决定,**不由画面反推**
- 每个 shot 绑定: scene_id(场景)、characters(在场角色)、camera(景别/运镜)、visual_prompt

### 6.2 输出契约 `shotlist.json`

```json
{
  "shots": [
    {
      "shot_id": "SH014",
      "line_ids": ["LN014"],
      "t_start_ms": 58200,
      "t_end_ms": 63400,
      "scene_id": "S003",
      "characters": ["C001"],
      "camera": {"shot_size": "medium_close", "movement": "slow_push_in"},
      "visual_prompt": "智伯于宴席举杯而立,烛光映面,睥睨席间众人",
      "motion_mode": "ken_burns"
    }
  ]
}
```

`motion_mode` 枚举: `ken_burns`(静态图推拉摇移,MVP 默认)/ `img2video`(图生视频,P2 阶段)/ `static`(降级)。

### 6.3 校验门 G4

- 时间轴无缝校验: shots 的 [t_start, t_end] 拼接必须精确覆盖 total_duration,无重叠无空洞(纯代码校验)
- 每个 shot 的 characters ⊆ character_bible
- 视觉节奏检查: 连续 3 个以上 shot 同 scene 同景别 → 强制变化(防止画面呆板)

---

## 7. L6 场景与画面生成(shotlist + character_bible → 帧资产)

### 7.1 两级资产结构(content-addressing,复用 Stratum 已验证的机制)

1. **场景底图(scene asset)**: "晋阳城头暮色"这类场景生成一次,以内容哈希存储,多个 shot 复用 —— 省成本 + 视觉一致
2. **shot 帧**: 场景底图 + 角色(IP-Adapter 注入参考图)+ 动作 prompt → 该 shot 的关键帧

### 7.2 生成通道

| 通道 | 用途 | 说明 |
|---|---|---|
| 本地 SDXL + IP-Adapter | 主力 | 3080 10GB,单帧 1024×576 约 8-15s;串行跑 40 shot ≈ 10 分钟 |
| 云文生图(即梦/Flux API) | 提速/高质量 | 本地失败或整片高质量模式 |
| 图生视频(Wan 2.1-1.3B 本地 / 可灵·即梦 API) | P2 阶段 | 只给 dramatic_weight ≥ 4 的高光 shot 上动态,控制成本 |

### 7.3 校验门 G6(视觉门)

- CLIP 相似度: 生成帧 vs visual_prompt,低于阈值重 roll(变异 prompt 措辞)
- 角色一致性: 生成帧中人脸/形象 vs 参考图 embedding 距离
- VLM 内容审(MiniCPM-V 本地): 画面元素年代穿帮检查(出现眼镜、纽扣、现代建筑 → 打回)
- 全部 shot 并行生成,单 shot 独立重试,互不阻塞

**降级链**: 重 roll 3 次失败 → 去掉角色只出场景空镜(旁白型 shot 完全成立)→ 再失败 → 该 shot 用相邻场景底图 + 缓推镜头。**任何情况下不允许开天窗。**

---

## 8. L7 音乐与音效(constitution + timeline → music_plan.json)

- 按 bgm_mood_arc 三幕选曲: MVP 用**预置曲库**(按情绪标签检索: 肃杀/攀升/余韵),P2 再上音乐生成(Suno API / 本地 MusicGen)
- 音乐切换点 = 幕间 gap 位置(timeline.json 已给出),交叉淡入淡出 1.5s
- 音效(战鼓、钟声、竹简展开)按 shot 的 visual_prompt 关键词自动匹配音效库,точечно点缀,宁缺毋滥
- 混音规则: BGM 在人声段自动 duck 至 -22dB(ffmpeg sidechaincompress)

**校验门 G7**: 音乐时长覆盖校验 + 响度检查(纯代码,无 LLM)

---

## 9. L8 字幕与剪辑合成(全部上游产物 → 成片)

**纯确定性代码层,零 LLM。**

### 9.1 字幕

- 直接从 timeline.json 的 char_timestamps 生成 SRT/ASS —— 免费获得精确对齐,不需要任何对齐算法
- 样式由宪法 visual_style 决定(字体、描边、位置);dialogue 行加说话人名前缀
- 可同时输出: 烧录字幕版 + 外挂 SRT 版

### 9.2 合成管线(ffmpeg)

```
for shot: 关键帧 → zoompan(ken_burns 参数) → shot.mp4
concat 全部 shot → 视频轨
amix: 配音轨 + BGM(duck) + 音效轨 → 音频轨
合流 + 烧字幕 + 片头(章节名书法字卡 2s)+ 片尾 → final.mp4 (1080p, h264, aac)
```

### 9.3 校验门 G8(终审)

- ASR 全片反打 → 与 script diff(端到端确认音画字一致)
- 时长偏差、黑帧检测、音频削波检测
- VLM 抽帧终审(抽 10 帧看整体风格一致性)
- 全部通过 → 状态置 `COMPLETED`,产物: final.mp4 + 全量中间 artifact(可追溯)

---

## 10. 编排层(omodul: pipeline_orchestrator)

### 10.1 状态机

每层状态: `PENDING → RUNNING → GATE_CHECK → PASSED / RETRYING(n) / DEGRADED / FAILED`

全局规则:
- 断点续跑: 任一层失败,修复后从该层重跑,上游 artifact 直接复用(靠内容哈希判断是否失效)
- 上游 artifact 变更 → 下游依赖层自动置脏重跑(Make 式增量构建)
- 单 run 全程可在无人值守下跑完: 所有门都有降级路径,**FAILED 只发生在 L0(原文本身无法解析)**

### 10.2 DB DDL(hevi 自己的 Layer 4 管理)

```sql
CREATE TABLE hevi_runs (
  run_id UUID PRIMARY KEY,
  chapter_source TEXT NOT NULL,
  status TEXT NOT NULL,          -- PENDING/RUNNING/COMPLETED/FAILED
  constitution JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  completed_at TIMESTAMPTZ
);

CREATE TABLE hevi_layer_states (
  run_id UUID REFERENCES hevi_runs,
  layer TEXT NOT NULL,           -- L0..L8
  status TEXT NOT NULL,
  retry_count INT DEFAULT 0,
  degraded BOOLEAN DEFAULT false,
  artifact_path TEXT,
  artifact_hash TEXT,            -- content-addressing
  gate_report JSONB,             -- 校验门详情,可审计
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  PRIMARY KEY (run_id, layer)
);

CREATE TABLE hevi_shots (
  run_id UUID,
  shot_id TEXT,
  status TEXT,                   -- shot 级独立状态,支持并行与单点重试
  frame_hash TEXT,
  retry_count INT DEFAULT 0,
  degrade_level INT DEFAULT 0,   -- 0=正常 1=空镜 2=复用底图
  PRIMARY KEY (run_id, shot_id)
);

CREATE TABLE hevi_assets (        -- 跨 run 复用的资产池
  asset_hash TEXT PRIMARY KEY,
  asset_type TEXT,               -- scene/character_ref/audio/music
  meta JSONB,
  path TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
```

### 10.3 部署拓扑(docker compose)

```yaml
services:
  hevi-orchestrator:    # omodul,DAG 调度 + 状态机
  hevi-llm-worker:      # L0/L1/L2/L5 文本类 oskill + 各 LLM 校验门(Claude API)
  hevi-tts-worker:      # L3,CosyVoice(GPU)
  hevi-image-worker:    # L6,SDXL+IP-Adapter(GPU,与 tts-worker 互斥调度)
  hevi-vlm-worker:      # G5/G6/G8 视觉门,MiniCPM-V 4.5 Q4(GPU)
  hevi-assembler:       # L8,ffmpeg,CPU
  postgres / redis      # 状态库 + 任务队列(rq 或 celery)
```

- GPU 互斥: 3080 10GB 单卡,tts/image/vlm worker 通过 Redis 信号量串行占卡;编排层按"先跑完全部 TTS → 再批量出图 → 再批量 VLM 审"的批次化调度,避免模型反复换入换出显存
- 部署红线沿用既有结论: 更新必须 `docker compose up -d --build`,禁止 stop/start
- 服务层零业务逻辑红线继续适用: 所有业务判断在 oskill/omodul,worker 只执行

### 10.4 成本与时长估算(单支 3 分钟成片)

| 项 | 用量 | 成本 | 耗时 |
|---|---|---|---|
| LLM(L0-L2/L5 + 各门,Sonnet) | ~150k in / 30k out tokens | ~$0.9 | 3-5 min |
| TTS(本地 CosyVoice) | ~700 字 | 电费 | 2-3 min |
| 出图(本地 SDXL,40 shot × 平均 1.6 roll) | ~64 张 | 电费 | 10-15 min |
| VLM 审(本地) | ~80 次推理 | 电费 | 3-5 min |
| 合成(ffmpeg) | — | — | 2 min |
| **合计** | | **≈ $1/支** | **≈ 25-30 min/支,全程无人值守** |

云通道全开(云 TTS + 云文生图)约 $3-5/支,耗时降至 10 分钟内。

---

## 11. 实施路线(三阶段)

### P0 — 端到端打通(目标: 2 周内出第一支片)

- L0 通鉴结构化(全力做实,这是地基)
- L1/L2 宪法 + 剧本 + G2 史实门
- L3 本地 CosyVoice,只做旁白单声线(先不做角色配音)
- L4 分镜切分(确定性代码为主)
- L6 只出场景空镜(不做角色一致性)
- L7 预置曲库 3 首
- L8 ffmpeg ken_burns 合成 + SRT
- **验收: 输入《周纪一》原文,无人干预出片,史实零硬伤**

### P1 — 质量线(2-3 周)

- L5 角色卡 + IP-Adapter 一致性
- 角色配音多声线 + 臣光曰专属声线
- G5/G6 视觉门(MiniCPM-V)+ 完整降级链
- 断点续跑 + shot 级并行重试
- 导演台 UI: 8 层参数展示 + run 进度 + gate_report 可视化

### P2 — 表现力(持续)

- 高光 shot 图生视频(Wan 2.1 本地 / 云 API)
- 音乐生成替换曲库
- 批量模式: 通鉴 294 卷排队生产,资产池跨 run 复用(人物参考图、场景底图复用率会随卷数上升,边际成本递减)
- A/B: 同一章节双宪法出两版,数据反馈选优

---

## 12. 风险与对策

| 风险 | 等级 | 对策 |
|---|---|---|
| 史实幻觉(官职/称谓/情节) | 高 | G2 双重审 + dialogue 只准改写 quotes 表 + 专名注音/校验表持续积累 |
| 角色形象漂移 | 高 | 参考图 + IP-Adapter 锁定;失败降级剪影风 |
| 10GB 显存不够(SDXL+VLM+TTS) | 中 | 批次化调度串行占卡;瓶颈期切云通道 |
| 文言分句/消歧错误传导全链 | 中 | G0 覆盖率门 + 抽查门;人物权威表锚定 |
| TTS 多音字/生僻字错读 | 中 | ASR 反打 CER 门 + 注音表 |
| 整片风格散 | 中 | 宪法注入所有层 prompt + G8 抽帧终审 |

---

## 附录 A: 校验门总表

| 门 | 位置 | 审什么 | 方式 | 降级 |
|---|---|---|---|---|
| G0 | L0 后 | 结构/覆盖率/引用闭环/幻觉抽查 | Schema + LLM | 匿名角色化 |
| G1 | L1 后 | 事件覆盖/时长合理性 | 代码 + LLM | best-of-3 judge |
| G2 | L2 后 | **史实/引语/禁则/字数** | LLM 双重审 | 定点重写→删行补桥 |
| G3 | L3 后 | ASR 反打 CER/响度 | ASR + 代码 | 换云 TTS/注音重合成 |
| G4 | L4 后 | 时间轴无缝/引用闭环/节奏 | 纯代码 | 自动修补切分 |
| G5 | L5 后 | 参考图年代/一致性 | VLM | 剪影风格 |
| G6 | L6 后 | CLIP 相似度/角色一致/穿帮 | CLIP + VLM | 空镜→复用底图 |
| G7 | L7 后 | 音乐覆盖/响度 | 纯代码 | 静音垫底鼓点 |
| G8 | 成片后 | 端到端音画字/黑帧/风格 | ASR + VLM | 定位坏 shot 重跑 |
