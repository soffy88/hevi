# SCENE3D R1D 独立核验报告（Hark，2026-10-15 04:32–04:50 UTC）

- 对象：worktree /data/soffy/projects/hevi-scene3d，分支 feat/scene3d-line，HEAD 44460e5d（DONE SCENE3D-R1D）
- 环境：hevi 主 .venv，JWT_SECRET=test-only，TMPDIR=.tmp，PYTHONPATH=worktree，CPU SwiftShader，单进程顺序渲染
- 结论：**PASS**（C1/C2/C3 全部闭环；回归项全部通过）。已 push。

## C1 星海有真实星星（R3 阻断项）

不信自报：直接在**交付的 1080 帧**上做像素分析（`static_analysis.py`，不改反例脚本），按"亮度比局部背景高 ≥0.25"的连通亮点计数，并过滤掉大块（行星球）：

| 画幅 | 时间 | 帧 | 星状连通区域 | 最大 ΔL |
|---|---|---:|---:|---:|
| 9:16 | 1.3s | frame_00040 | 591 | 0.516 |
| 9:16 | 6.5s | frame_00196 | 348 | 0.504 |
| 9:16 | 11.7s | frame_00352 | 160 | 0.492 |
| 16:9 | 1.3s | frame_00040 | 304 | 0.481 |
| 16:9 | 6.5s | frame_00196 | 256 | 0.481 |
| 16:9 | 11.7s | frame_00352 | 216 | 0.503 |

全部 ≥40（R3 要求每帧 ≥40）。相邻时刻亮点掩码 IoU=0（星星在移动，"穿过"成立）。抽帧肉眼：紫蓝渐变上有远近层次分明的星点，行星球之外有大量小星。**R1C 的"零颗星"已修复。**

## C2 狐狸橙色、与麦田区分、天空蓝（R3 阻断项）

交付 1080 帧像素取样（`static_analysis.py`）：

| 画幅/时间 | 狐狸额头 RGB / 色相 / 饱和度 | 麦田 色相 | 天空 饱和度 / 色相 |
|---|---|---|---|
| 9:16 1.2s | (240,115,41) / 21.2° / 0.83 | 42.4° | 0.270 / 204.7° |
| 9:16 6.0s | (240,115,41) / 21.2° / 0.83 | 42.4° | 0.261 / 204.7° |
| 9:16 10.8s | (240,115,41) / 21.2° / 0.83 | 42.4° | 0.270 / 204.7° |
| 16:9 6.0s | (240,115,41) / 21.2° / 0.83 | 42.4° | 0.317 / 203.3° |

- 狐狸色相中位数 21.2°∈[18,32]，平均饱和度 0.80–0.83 ≥0.6 ✔
- 狐狸与麦田色相差 ≈21.2° ≥10° ✔（R1C 实测几乎同色 42° vs 44°，已修复）
- 顶部 15% 天空饱和度 0.257–0.317 ≥0.25，色相 203.3–204.7°∈[190,230] ✔
- 中央橙色像素数 35k–67k（稳定）

## C3 交付样片 1080 档

ffprobe（`output/scene3d_r1d/r1d_render_results.json`，我独立复算一条）：6 条成片均为 1920×1080 或 1080×1920、30/1 fps、12.0s/360 帧或 13.0s/390 帧，H.264。

## 独立确定性复算（不信自报）

`determinism.py`：用同 preset build 路径，**独立**把 star_sea_9x16 在 1080 重渲一遍（新 workdir，224.6s），MP4 SHA-256：
`0d3ee86bb4bd97c9f4f1b8eb7b9fc3c1d62ab8973f68808498e507a89ae981b9`
与交付原片**逐字节一致**。同 seed 确定性成立。

## 回归

- pytest：`tests/test_scene3d*.py` **49 passed, 1 warning, 404s**（R1C 45 项无回退 + R1D 新增 4 项视觉像素测试）。
- API（`probe_api.py`）：preview 200（video/mp4）；4:3/1:1/abc/多余字段/类型错误 → 422；未知能力 → 404；无 500。capability 层 duration=1.0/1.99 → CapabilityError ✔
- 3O lint：`failed: check_no_sibling_call, check_omodul_signature, check_enabled_pillars, check_oprim_keyword_only` = 基线 4 项，无新增。
- 抽帧拼图肉眼：狐狸正脸、橙毛、蓝天空；星海有星；无穿模。

## 证据（本目录）
- `static_analysis.py` / `static_analysis.json`：交付 1080 帧的星星与颜色像素分析
- `determinism.py` / `determinism.json`：1080 全片独立重渲 SHA 比对
- `probe_api.py` / `probe_api.json`、`pytest.log`、`lint.log`、`chain.log`

## 判定
C1（星海有星、有远近、有穿过）、C2（狐狸橙、与麦田色相差 ≥10°、天空蓝）、C3（1080 出片）均以**交付像素**实测达成；同 seed 全片 SHA 一致；pytest 49 passed；lint = 基线。**PASS，push。**
