# GATE④ · s1 曲沃代翼 成片段 · 送审(不发布)

## ★ 签字工件（閘④）

| 签字项 | 值 |
|---|---|
| **判定人** | **Wiki**（顾问 Claude 全权授权代拟,Wiki 裁准） |
| **日期** | **2026-07-24** |
| **闸** | 閘④ 成段评审 |
| **裁决** | ✅ **准入** |
| **裁决原文** | 「**讲得清楚明白,准入**」 |
| **钉稿件 sha256（mp4）** | `3bb3d74d8a7155c61a8037eca4f45c5978d7f6082df00eca650eb4cbba95827d` |
| **成片段** | `output/s1_quwo_daiyi/DELIVER/s1_quwo_daiyi_segment.mp4`(129.4s) |
| **打磨清单** | 转 backlog `DEBT-REGISTER.md#S1-POLISH-1`,needed-by=G2,不单集修 |

---

| 项 | 值 |
|---|---|
| 闸 | **閘④ 成段评审 · ✅ 准入**（Wiki 裁准,2026-07-24,裁决原文「讲得清楚明白,准入」）——成片段达 G0-D 杆,S13竹简/S12双半幅/地图纸雕观感通过。已知可打磨项转 backlog S1-POLISH-1(needed-by=G2,非阻断)。 · 执行 CC-A |
| 集 | s1 曲沃代翼(N0 9/9 净稿 → N1 节拍切分 → N9 段装配) |
| 成片段 | `output/s1_quwo_daiyi/assemble/s1_quwo_daiyi_segment.mp4`(**129.4s**, 4.19MB, sha256 `3bb3d74d8a7155c6…`) |
| EDL | `output/s1_quwo_daiyi/assemble/edl.json`(10 拍) |
| 装配断言 | `assertions.json` **8/8 全过** |
| 后端 | 全 deterministic_layers + 程序化纸偶 + S13竹简 + S12双半幅——**零 provider** |
| 成本 | **¥0**(全确定性/免费后端;地图镜成本≈0 红线满足) |

## 相对 G1a 最大新增(单独质量证据)

### ① S13 引文呈现首次实装(旗舰) · 帧样张 `_frames/b4_S13竹简.png`
onscreen 引文『三年春，曲沃武公伐翼，次于陘庭，韓萬御戎，梁弘為右，逐翼侯于汾隰，驂絓而止。夜獲之，及欒共叔。』(左传:0217)走**竹简纸雕**（右起竖排、竹黄、编绳、撕边、简牍 stagger 落定 ease_out_back），**引文本体上屏、不占 VO 时长**；同拍字幕带白话转述『公元前709年春，曲沃武公出兵攻打晋都翼城…』口播驱动时轴。**N0-D-010 引文呈现分离画面落地**：画面存真(逐字文言)、口播通俗(白话)，逐字取 quote.text(H2 已保真)。

### ② 两 cf 角标 S12 双半幅实装——清 G1a"数据有、画面无"欠账 · `_frames/b2/b7_S12双半幅.png`
G1a 时期 cf 只有 `make_collation_note` 平角标(GATE-G1b"S12 冲突投影 0 条")。s1 两 cf 均实装**双半幅对折立起成双屏**(中缝对折、两半各呈一源、题头「史载互异·维度」)：
- b2 `cf:egou-di-vs-zi`（继位者弟/子）：《左传》翼人立其弟鄂侯 ‖ 一说 立孝侯之子郄为君
- b7 `cf:cebming-fanwei`（册命范围）：《史记》尽併晋地而有之 ‖ 《左传》王命曲沃伯以一军为晋侯

**两说并陈不择一**，S12 picture-side 首次落地。

### ③ MapState 晋国内部地理(Q5 全环)——翼/曲沃/汾隰/陘庭/随 · `_frames/b0/b6`
`s1_mapstates.py` 临汾盆地焦点投影(lon 109–114.5/lat 33–37.5)：翼(赭红`yi`,大宗)/曲沃(青灰蓝`quwo`,小宗) 两 ForcePolygon(注册表新增,successor_of=jin) + 汾隰/陘庭/随 CityMark + 汾水/黄河。双态 翼独立→曲沃吞并(b6 tear 撕裂/合并=曲沃代翼 climax,大宗灭)。**blocking_clashes 两态皆空(§6.2b)**，成本 ¥0。

## 逐拍 EDL(节拍切分 → 镜头)

| 拍 | intent | 镜头(后端) | start | dur | sfx |
|---|---|---|---|---|---|
| b0 | establish | 全图铺陈(翼/曲沃/周) | 0.0 | 11.7 | establish |
| b1 | character | 立牌·桓叔(程序化纸偶,曲沃色) | 11.7 | 10.1 | character |
| **b2** | dual_account | **S12 双半幅(egou)** | 21.8 | 12.7 | expand |
| b3 | route | 曲沃屡伐翼(路线) | 34.5 | 17.3 | route |
| **b4** | battle | **S13 竹简(武公伐翼引文)** | 51.9 | 18.2 | highlight |
| b5 | battle | 落点·诱杀小子侯@曲沃 | 70.1 | 7.7 | battle |
| b6 | split_merge | **撕裂/合并·曲沃吞并翼** | 77.8 | 11.9 | split_merge |
| **b7** | dual_account | **S12 双半幅(cebming)** | 89.7 | 10.9 | expand |
| b8 | hold | 题字·throughline 应验 | 100.6 | 14.6 | hold |
| b9 | hold | 题字·counterpoint 郑伯克段 | 115.2 | 14.3 | hold |

## 装配层断言 8/8 · R-hard/结构

| # | 断言 | 结果 |
|---|---|---|
| A1 | 节拍完整(EDL 10 拍=叙事拍) | ✓ |
| A2 | 色不撞 §6.2b(两态 blocking_clashes 空) | ✓ |
| A3 | 质心力色胜纸色 B1a(翼采样距注册17/曲沃6,均胜纸色) | ✓ |
| A4 | S13 引文逐字=净稿 quote(H2 保真) | ✓ |
| A5 | S12 两 cf 双半幅(egou+cebming 两说并陈) | ✓ |
| A6 | VO 驱动无漂(每拍 clip≈VO,最大漂 0.038s) | ✓ |
| A7 | 成本≈0(后端全确定性,无 provider) | ✓ |
| A8 | 时长自洽(129.5s=拍时长和) | ✓ |

## 成本分后端记(全 ¥0,地图镜≈0 红线满足)

| 后端 | 拍 | 成本 |
|---|---|---|
| deterministic_layers(地图/图解) | b0/b3/b5/b6/b8/b9 | **¥0**(纯 Pillow/ffmpeg) |
| 程序化纸偶(立牌 S7) | b1 | **¥0** |
| S13 竹简纸雕 | b4 | **¥0** |
| S12 双半幅纸雕 | b2/b7 | **¥0** |
| TTS(edge_tts 非官方免费) | 全 10 拍 | **¥0**(无付费 API) |
| BGM(预置 asset)+ SFX(lavfi 合成占位) | 全段 | **¥0** |

**合计 ¥0**。无任何按次付费后端,故无"不为零逐笔解释"之需(红线满足)。

## 人工分钟按闸口分账

**建造全自动(CC-A agent),人工=闸口评审**(非逐拍手工装配——这是 s1 相对 G1a 手工装配的关键降本):
| 闸口 | 阶段 | 人工触点 |
|---|---|---|
| 閘⓪ | N0 净稿(9/9) | soffy 已裁「过」(gate review) |
| 閘① | N2 事实选用/beat→shot 映射 | 规则自动(净稿字段驱动:onscreen→S13/cf→S12/intent→map),人工=复核 |
| 閘④ | N9 成段评审 | **本次送审**(待人评) |

MapState 坐标、S13/S12 形态、立牌配色均 agent 授权(注册表/契约约束);人工分钟 = 三闸评审时间,**非手工装配工时**。G1a 判据2a(人工分钟基线)曾 permanently FAIL、移交 G2 首集——s1 提供的基线是:**净稿(N0)机器 9/9 + 装配(N1–N9)机器全自动,人工仅闸口评审**;精确闸口评审分钟由本次人评落定。

## 帧样张(证据)
`output/s1_quwo_daiyi/assemble/_frames/` 逐拍 10 张:b4_S13竹简 / b2·b7_S12双半幅 / b6_split_merge(吞并) / b0_establish / b1_character / b3_route / b5_battle / b8·b9_hold。

## 送审请求(閘④)
- **不发布**(红线)。请顾问/Wiki 评审成片段:S13 竹简/S12 双半幅/地图纸雕观感是否达 G0-D 杆、事实与净稿一致、两说并陈是否清欠账。
- **已知可打磨**(非阻断):b4 竹简底部与字幕带略叠(可缩简牍高度让位字幕);地图河流/裂线在 _static_map 底图未显(animate 层图元,可后续补);hold 题字仅字幕带(G1a gap#6 题字层未建,沿用)。
- 准入下一步 = s2+ 推广本 N1–N9 全自动链,或 s1 定向打磨。

**工件**:成片段 + EDL + assertions.json + 10 帧样张(`output/s1_quwo_daiyi/assemble/`)。
