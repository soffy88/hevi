# Provider 能力矩阵（地图/图解讲解轨）

> 依据：HEVI-EXPLAINER-PIPELINE-SPEC-001 §9。**逐模板证据授权**——i2v 类后端须有实测条目方可授权某模板类。
> 每条 = 一次真机实证的结论，非厂商宣称。状态：live · 首条 2026-07-21（G0 探针）。

---

## Wan-2.1 · `i2v_keyframe_pair`（dashscope wan i2v，keyframe_pair 模式）

| 维度 | 结论 | 证据 |
|---|---|---|
| 真插值（非硬拼尾帧）| ✓ | G0：真实末帧 vs 目标关键帧 SSIM 0.49–0.80（非 1.0）；末段相邻帧 SSIM 无向下尖峰、末对最高 |
| 尾部收敛稳定 | ✓ | G0：T-0.5s / 倒数第5 / 末帧三点 SSIM 几乎相等（尾部已 settle） |
| **near_static 大色块** | **可用** | G0 S1：统一晋红块 B1a PASS（三质心同族红、jin_center 红） |
| **细分多色 transform** | **不可用** | G0 S2/S3：中央韩赵魏三小块塌成单色红（赵蓝/魏绿丢失），min 色分离≈1；只周边大国保色 |
| 授权范围 | near_static / 单主体 / 大色块镜；**地图分治镜不授权** | 上两行 |

- **数据出处**：`output/g0_sanjia_fenjin/g0_verify_report.md`、`b1_remeasure_result.json`、`b1a_structural_result.json`。
- **规格参数**：4–8s · 16:9 · 无镜头运动 · 重跑 ≤3 · 降级显式打标禁静默。
- **G0 处置**：地图轨改 `deterministic_layers` 默认后端（§9）。

---

## `deterministic_layers`（`map_state.render_map_state_png` + 装配层动画）

| 维度 | 结论 | 证据 |
|---|---|---|
| 色保真 | ✓（by construction，色从注册表确定性绘制，零塌色）| — |
| B1a/B2 | 构建期恒绿 | `test_map_state::test_b1a_by_construction_deterministic_backend` |
| 材质档次（纸质感 vs 平面矢量）| **✓ 已验（Wiki 目检签字 2026-07-21）** | G0-D 三镜 + 并排对比条 |
| 运动/材质工艺 | 撕边(deckle+撕纸白芯) · 有机纸纤维 fbm · 2.5D 接触阴影 · 回弹落定 · 云漂 | `hevi/tongjian/map_anim.py` |

> **G0-D 通过（2026-07-21 Wiki 签字）**：`deterministic_layers` 是地图/图解轨的验证后端。材质三问闭环——
> 纸质感读作纸雕（非平矢量）、与 i2v 版并排无档次落差（S3 三色保真处更优）、Wiki 目检签字。
> 交付：`output/g0d_deterministic/`（S1 铺陈 / S2 裂线隐现 / S3 撕裂 + compare/ 两条 i2v 并排对比条）。
