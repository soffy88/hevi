# GATE④ · s2 骊姬之乱 成片段 · 送 Wiki 看片(不发布)

| 项 | 值 |
|---|---|
| 闸 | **閘④ 成段评审** · 送 Wiki 看片 · 执行 CC-A · 2026-07-24 |
| 集 | s2 骊姬之乱（N0 9/9 净稿 → N1 节拍切分 6 拍 → N9 段装配） |
| 成片段 | `output/s2_liji/assemble/s2_liji_segment.mp4`（**69.4s**, 2.1MB, sha256 `91894c1d5ebbca7d…`） |
| EDL | `output/s2_liji/assemble/edl.json`（6 拍） |
| 装配断言 | `assertions.json` **7/7 全过** |
| 后端 | deterministic_layers（地图/题字）+ S12 双半幅纸雕——**零 provider · 成本 ¥0** |

## 逐拍 EDL

| 拍 | intent | 镜头 | start | dur |
|---|---|---|---|---|
| b0 | establish | 晋绛/三子分封地图（绛/蒲/屈） | 0.0 | 7.1 |
| **b1** | dual_account | **S12 双半幅(三子分居缘起)** | 7.1 | 11.8 |
| **b2** | dual_account | **S12 双半幅(谮词内容;史记谮词=右panel)** | 18.9 | 11.3 |
| **b3** | dual_account | **S12 双半幅(出奔缘由)** | 30.2 | 10.7 |
| b4 | hold | 题字·应验(士蒍歌 狐裘尨茸一国三公) | 40.9 | 17.0 |
| b5 | hold | 题字·counterpoint 卫宣公朝 | 57.9 | 11.4 |

## 重点：三 cf 全走 S12 双半幅（任务指名）· 帧样张 `_frames/b1/b2/b3_S12双半幅.png`
- b1 `cf:sanzi-fenju-yuanqi`（三子分居缘起）：《左传》骊姬贿二五进言 ‖ 《史记》献公边防理由径出
- b2 `cf:liji-zenci-neirong`（谮词内容）：《左传》谮辞极简『贼由大子』 ‖ 《史记》详载多层谮语（史记谮词=onscreen 引文折入右 panel）
- b3 `cf:erzi-chuben-yuanyou`（出奔缘由）：《左传》『皆知之』直接 ‖ 《史记》多一层告发环节

**两说并陈不择一**，S12 三连——延续 s1 首实装、s2 三倍呈现。

## 装配断言 7/7
A1 节拍完整(6) · A2 色不撞§6.2b(jin/qin) · A3 质心力色胜纸色 B1a(jin 采样距注册28<纸232) · A4 三 cf 全 S12 双半幅 · A5 VO 驱动无漂(0.038s) · A6 成本≈0 全确定性 · A7 时长自洽(69.4s)。

## 成本 ¥0 · 人工分钟=闸口评审
全 deterministic_layers + S12 纸雕 + edge_tts + lavfi SFX，**合计 ¥0**（地图镜≈0 红线满足）；建造全自动，人工仅闸口评审。

## MapState 建图（s2 晋献公时）
`s2_mapstates.py`：晋(jin 深红,承 s1 晋大宗) + 秦(qin context 西)；分封/出奔点走 CityMark（绛/曲沃-新城/蒲/屈/梁/翟/卫）;焦点投影 lon108.5–115.5/lat33.5–39;blocking_clashes 空(§6.2b);成本 ¥0。

## 送审请求（閘④）
不发布。请 Wiki 看片：S12 三对勘/晋绛地图/题字观感是否达 G0-D 杆、事实与净稿一致、三说并陈是否清晰。已知可打磨(转 S1-POLISH backlog 同类)：三 S12 连续可插图变化；hold 题字仅字幕带；狄/卫仅城点无势力块。
