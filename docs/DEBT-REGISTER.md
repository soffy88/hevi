# Hevi · 债务登记册（DEBT-REGISTER）

已知债务（ID · 描述 · needed-by · 状态）。入册即显式表态，不静默背债。

---

## HARNESS-DEBT-1 · G1b 对拍多-sample 化

**入册**：2026-07-24（G1b 收口时，GATE-G1b-ep_sanjia_fenjin-20260724）。
**描述**：`tools/g1b_parity_harness.py` 现为**单-sample 对拍**——`project_event()` 只投影钉点 `sample.sanjiafenjin.json`（ev:jinyang-zhizhan 单事件）。v0.2.2 PAIRING 全覆盖后，指向非-jinyang 事件的 7 拍（B01/B02/B03/B04/B09/B10/B11）无法逐字段校验其**各自事件响应文件**（jin-gongshi-bei/zhixuanzi-liyao/zhibo-suodi/sanjiafenjin/minghou-403），只能作"跨事件比对产物"裁为可解释（GATE-G1b 裁决）。
**债**：真正逐字段闭合非-jinyang 拍，需 harness **按拍载入各自事件响应文件**（多-sample 对拍），逐拍对其指向事件投影比对。
**needed-by**：**G2 批量前**（G2 起批内自比、多集次，单-sample 口径不再够用）。
**现状口径**：单-sample 在 **G1b 语境下已完成历史使命**（首个 durable 閘① 数 + diff 全解释 + coverage 4/11→11/11 实测密度）；非阻塞 G1b 收口。
**处置**：G2 批量化设计时一并做多-sample 对拍改造；届时销此债。

---

## S1-POLISH-1 · s1 曲沃代翼成片打磨清单（閘④ 准入后）

**入册**：2026-07-24（GATE4-N0-s1-quwo-segment，soffy 准入时）。
**描述**：s1 成片段閘④ 已准入（"讲得清楚明白"），下列打磨项**非阻断**、**不单集修**，攒到 G2 批量一并做（跨集摊销）：
1. **R-soft 六条**（N0 净稿评审意见，转 N1 打磨输入）：开场钩子弱／叙事前紧后松／通俗度(甸侯/骖絓未解，宜白话或类比)／深度点题(b8 宜点"分封制自我瓦解标本")／史料机械(择处点史家笔法)／镜像对照生硬(b9"同题异构"具体化)。
2. **竹简字幕叠**：S13 竹简底部与字幕带略叠（可缩简牍高度让位字幕带）。
3. **底图河流/裂线**：`_static_map` 底图未显 rivers/fissures（animate 层图元，`render_map_state_png` 有但 `_static_map` 无）——补进确定性底图。
4. **hold 题字层**：hold 拍题字仅字幕带（沿用 G1a gap#6，无专属题字层）——建 S13-字幕卡式题字层供 thesis/counterpoint 拍。
5. **S10 时间轴拍缺席**：s1 净稿无年表回顾拍（b8/b9 是 hold 题字）；若 G2 要求年表拍种覆盖，s2+ 净稿可含 timeline 拍或 s1 补建。

**needed-by**：**G2 批量前**（批量语境下这些打磨跨集共用，单集修不摊销）。
**现状口径**：s1 閘④ 准入不受这些影响（成片"讲得清楚明白"）；均为观感/覆盖打磨非事实/机制缺陷。
**处置**：G2 首集设计时一并做（尤其 3/4 是渲染器增强，跨集复用）；届时逐项销。

### S1-POLISH-1 · 进度更新（2026-07-24，渲染器级跨集复用）
- **#2 竹简字幕叠 → ✅ 已解**：`quote_shots.render_quote_slip` 竹简 top/bot 让位底部字幕带（bot=h-200），简牍不再叠字幕；s1 已应用重渲。
- **#3 底图河流/裂线/城邑 → ✅ 已解**：`map_anim._geo_layer`（河流蓝双线+裂线+城邑点纸雕）接进 `_static_map` 与 `animate_establish`（随落定渐显）；s1/s2 establish/hold 底图现显黄河/汾水+城邑点。**渲染器级、跨集复用**（G2 批量口径已达）。
- **#1 R-soft 六条 / #4 hold 题字层 / #5 S10 时间轴拍**：仍挂 needed-by=G2（#1/#5 需净稿/集结构改，#4 需题字数据 plumbing）。
