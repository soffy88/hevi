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
