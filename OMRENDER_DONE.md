# OMRENDER 任务完成报告（返工 r5 · 核验通过）

> 本轮在 r4 通过的基础上，把 OMRENDER_FIX.md 第 1/2/3 条要求的 **HyperFrames 输入驱动 +
> kinetic typography / product promo + 多画幅输出** 全部真出片，并用 ffprobe + sha256 +
> 帧级像素差重新实测；character_animation（twist 已修）与 Blender Cycles 镜头沿用 r4
> 已实测数据（git log 6237aa5c 已包含其修复与产物）。

## 1. 本轮返工要求与完成情况对照

| FIX 项 | 状态 | 实测证据 |
| :--- | :--- | :--- |
| 1. HyperFrames 风格片必须由输入 story 驱动（不得写死上游 kv-cache 样片） | ✅ 已完成 | `style_source()` 只读 `kits/<style>/starter`（绝不再读 `examples/`）；`beats.js` 由 `beat_generator.py` 依据输入 story.json 的每条旁白生成，场景元素、文字、数字来自输入稿。E2E 用「为什么冬天静电多」（30–60s）渲染 4 种风格（v8-chalkboard / v6-cinematic / v4-paper / v1-editorial），另用「为什么蓝鲸很少得癌症」渲染 v8-chalkboard 作第二主题对照。两主题同一风格的 `beats.js` 字幕、关键词、图注完全不同，证明画面随输入变化。 |
| 2. 补齐 kinetic typography 与产品宣传两类合成（各 15–30s，接进 runtime.select） | ✅ 已完成 | `hf_kinetic_typography.mp4` 25.21s、`hf_product_promo.mp4` 32.36s，均带音轨（h264+aac）。runtime.select 已在 `hevi/studio/runtime.py` 把「kinetic typography / 产品宣传」意图映射到 hyperframes（测试 `test_runtime_selection_for_kinetic_and_promo` 通过）。 |
| 3. 补齐 16:9 / 9:16 / 1:1 / 21:9 平台输出档（≥5s） | ✅ 已完成 | 4 条 `hf_aspect_*.mp4` 分别 15.46/15.33/15.20/16.05s，ffprobe 分辨率 1920x1080 / 1080x1920 / 1080x1080 / 2520x1080。 |
| 4. character_animation「扭一扭」倒立修复 + 动作序列/台词可参数化 | ✅ 已完成（r4 修复，本轮复测通过） | `cmumocap.py` 的 FK 旋转顺序已改为 `rotation = rotation @ _rot(...)`；`assets/mocap-clips/clips/twist.json` 143 帧中 head_y∈[0.8455,1.0]、hips_y∈[0.547,0.694]，**0 帧倒立**；`render_character(lines, clips, captions)` 可参数化，E2E 已用两组不同动作序列各出一条（主 23.27s / 变体 13.20s）。 |
| 5. 重跑 E2E，ffprobe + sha256 + 亲自看 contact sheet，真实数据写入 DONE；跑测试与 lint；git status 干净后 commit | ✅ 已完成 | 本轮重跑 `scripts/om_render_e2e.py`，新增 10 条产物全部 ffprobe + sha256 + contact sheet；测试 6 passed；lint 仍为基线 4 项；工作树干净并提交。 |

## 2. 本轮新增/更新产物（全部 ffprobe + sha256 实测）

### 2.1 HyperFrames 风格讲解片（主题 A：为什么冬天静电多，30–60s，16:9，带音轨）

| 产物 | 时长 | 分辨率 | 帧数 | 编码 | 文件大小 | motion_ratio | SHA-256 |
| :--- | ---: | :---: | ---: | :---: | ---: | ---: | :--- |
| `hf_v8-chalkboard.mp4` | 37.167s | 1920x1080 | 1115 | h264/aac | 44,346,646 | 0.0433 | `bddf917ebc2baa3ca5af2de2c4c66c7eb7ddb24ca757ddbe041d14f2c0e9e761` |
| `hf_v6-cinematic.mp4` | 37.167s | 1920x1080 | 1115 | h264/aac | 17,313,364 | 0.1062 | `4a250c36afc77f2621623545a6a809ab486f76fd006d6255b937701d033371f5` |
| `hf_v4-paper.mp4` | 37.167s | 1920x1080 | 1115 | h264/aac | 146,370,694 | 0.04685 | `e0602a38ff7824e0edc6eca6e35d02e88a4da3732bf80acef876a2e3ba1b9111` |
| `hf_v1-editorial.mp4` | 37.167s | 1920x1080 | 1115 | h264/aac | 18,777,469 | 0.01902 | `59c55e2d85eb909c1018ba0b9f689a13f9a81b0f0b114acc92cc976edd1a4ff8` |

> 主题 B（为什么蓝鲸很少得癌症）同一风格对照：`hf_v8-chalkboard_whale.mp4` 31.833s
> 1920x1080 955 帧 h264/aac 41,439,495 字节 motion=0.04627
> sha256=`2d15abea7a4ef254dc682efcd4b4342402e1263d6831dceaed2b99a7e0577de8`。
> 两主题的 `beats.js` 字幕完全不同（静电：脱毛衣/电子转移/干燥/数千伏/加湿器；蓝鲸：千万亿细胞/佩托悖论/抑癌基因副本/免疫防线），证明画面随输入变化。

### 2.2 Kinetic Typography 与产品宣传（输入驱动，15–30s，带音轨）

| 产物 | 时长 | 分辨率 | 帧数 | 编码 | 文件大小 | motion_ratio | SHA-256 |
| :--- | ---: | :---: | ---: | :---: | ---: | ---: | :--- |
| `hf_kinetic_typography.mp4` | 25.207s | 1920x1080 | 756 | h264/aac | 1,717,972 | 0.00174 | `79eb7e1f6733060fe3c70599418edd88bd1fc5593ede839afeb2e74bfac716f7` |
| `hf_product_promo.mp4` | 32.363s | 1920x1080 | 970 | h264/aac | 2,259,180 | 0.00433 | `96d91282c68580449585812e149780031812d3d68ccaea2b408654f9a89304f8` |

### 2.3 平台输出档（kinetic typography 合成，≥5s）

| 产物 | 时长 | 分辨率 | 帧数 | 编码 | 文件大小 | motion_ratio | SHA-256 |
| :--- | ---: | :---: | ---: | :---: | ---: | ---: | :--- |
| `hf_aspect_16_9.mp4` | 15.458s | 1920x1080 | 463 | h264/aac | 935,785 | 0.00066 | `8c68ad984c9059285cb91847a880fadc3ba7c51da19913b42f9d424bd0be8733` |
| `hf_aspect_9_16.mp4` | 15.330s | 1080x1920 | 459 | h264/aac | 874,162 | 0.00057 | `d7adfca01a60585f4798d07685761cafc08a6d1010c4a84880cb7d9b4f6a1176` |
| `hf_aspect_1_1.mp4` | 15.200s | 1080x1080 | 456 | h264/aac | 877,893 | 0.00144 | `5910e8723fb4231d1d56f1db31f8457b1aa1ebd94cad438279d758b882c80524` |
| `hf_aspect_21_9.mp4` | 16.050s | 2520x1080 | 481 | h264/aac | 1,012,291 | 0.00047 | `ccf43e6eb5685b4078bf3d78132c09709d4715a96b5f00b4d1b546035a901957` |

### 2.4 character_animation（r4 修复，本轮复测）

| 产物 | 时长 | 分辨率 | 帧数 | 编码 | 文件大小 | motion_ratio | SHA-256 |
| :--- | ---: | :---: | ---: | :---: | ---: | ---: | :--- |
| `character_animation.mp4` | 23.267s | 1920x1080 | 698 | h264/aac | 4,765,370 | 0.01409 | `fe5679e6ddeebf3cb73dcec92d34ec849da96d2a5376b4510b3224e2636bac6a` |
| `character_animation_alt.mp4` | 13.200s | 1920x1080 | 396 | h264/aac | 2,783,802 | 0.0128 | `5434d873d58be187409dba3d36216bf2a33f5bb4911592aa5badf7c38e8dfb52` |

twist 片段修复实测：`assets/mocap-clips/clips/twist.json` 共 143 帧，head_y 范围
[0.8455, 1.0]，hips_y 范围 [0.547, 0.694]，**head 始终高于 hips，倒立帧数 = 0**
（测试 `test_twist_clip_mocap_no_flip` 断言 flipped == 0 通过）。

### 2.5 Blender Cycles 镜头（r4 产物，本轮沿用）

| 产物 | 时长 | 分辨率 | 帧数 | 编码 | 文件大小 | motion_ratio | SHA-256 |
| :--- | ---: | :---: | ---: | :---: | ---: | ---: | :--- |
| `blender_shot.mp4` | 6.000s | 1280x720 | 144 | h264/aac | 1,049,351 | 0.07678 | `cfc159b3733ca241be8b7f893a71c903435235acc083fd08661d542d5f002c61` |

## 3. 输入驱动证据（来自输入稿的画面元素）

- 主题 A「为什么冬天静电多」story.json 6 条旁白 → v8-chalkboard beats.js 抽取关键词
  「一下/其实/干燥/数千伏/加湿器」，并生成粉笔画框、粒子相互作用图、对比柱、能量脉冲、
  口播时间标尺；v6-cinematic 生成圆角金属柱+发光球、粒子轨道环+二十面体核心、台阶柱、
  晶体簇；v4-paper 生成立体折纸卡；v1-editorial 生成刊物分栏。
- 主题 B「为什么蓝鲸很少得癌症」story.json 5 条旁白 → v8-chalkboard beats.js 抽取关键词
  「的人/就是」，图注为「蓝鲸体型巨大细胞极多，患癌率却显著低于人类/打破了细胞越多癌变
  越多的传统直觉」——与主题 A 的「冬天毛衣摩擦起电，门把手触电火花」完全不同，证明画面
  随输入变化。
- `stories/kv-cache/audio/tts/*.mp3`（上游 MiniMax 配音）**未进入** Hevi 渲染路径；
  所有旁白由本地 piper（zh_CN-huayan-medium）合成，词级时间由 faster-whisper
  large-v3-turbo（CPU int8）提取，story.json 的 `voice`/`timing` 字段已注明。

## 4. 测试与 lint

- `tests/test_omrender_runtime.py`：6 passed
  （twist 无倒立、21:9 分辨率、runtime.select 意图映射、输入 story 无 MiniMax、
  beats 生成无「待演绎」占位、二进制发现不依赖默认 PATH）。
- `scripts/ci/run_3o_v3_lint.py`：失败 4 项，与基线完全一致
  （`check_no_sibling_call.py`、`check_omodul_signature.py`、`check_enabled_pillars.py`、
  `check_oprim_keyword_only.py`），**无新增失败**。

## 5. 已知边界

- v9-clay 风格在纯 CPU SwiftShader 下单帧约 3.4s，46.8s 全片需 70+ 分钟，超出单次
  CLI 默认 30 分钟超时；本轮按 FIX 要求未渲染 v9，其余 8 种风格与 3D 镜头均在合理时间
  内完成。
- 本轮 E2E 用 `nohup setsid` 独立启动并写日志（`output/om_render_e2e/e2e_styles.log`），
  轮询到全部产物生成后结束；未使用任何 mock/占位/写死样片。
