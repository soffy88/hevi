# ARTMOTION 项目总结

## 任务状态

| Task | 规格 | 语法 | 风格 | 时长 | 画质门 | 近黑帧 | 快动比例 | 状态 |
|------|------|------|------|------|--------|--------|----------|------|
| task_0 | 16:9 1920x1080 | t1_3b1b (自注意力) | 25_ghibli | 30.00s | ✅ green | 0 | 11.33% | ✅ 通过 |
| task_1 | 9:16 1080x1920 | y5_kinetic_type (水墨) | 17_ink | 26.90s | ✅ green | 0 | 7.76% | ✅ 通过 |
| task_2 | 16:9 1920x1080 | t3_finance_chart (光伏) | 14_8bit | 32.00s | ✅ green | 0 | 13.32% | ✅ 通过 |
| task_3_comparison | 9:16 1080x1920 | y5_kinetic_type (唐宋) | 17_ink | 27.08s | ✅ green | 0 | 7.47% | ✅ 通过 |
| task_4_portrait_ghibli | 9:16 1080x1920 | t1_3b1b (注意力样片) | 25_ghibli | 9.17s | ✅ green | 0 | 10.09% | ✅ 通过 |

## ARTMOTION 返工 r6 最终完成总结（2026-10-14）

### 1. 阻断问题修复清单
- **竖屏 ink 纹理黑底根因彻底修复与近黑帧门禁（r6 B1）**：
  - **根因修复**：`lib/paint.js` 的 `P.texture` 和 `P.grain` 支持显式传宽高（默认舞台尺寸）。`17_ink_texture.js`、`25_ghibli_texture.js`、`14_8bit_texture.js`、`12_bauhaus_texture.js` 内部一律按显式尺寸（1920×1080 或舞台画幅）建图，不再依赖舞台尺寸；`ground()` 在 boot 时调用 `P.assertOpaque(g.canvas)` 断言全透明像素为 0（若有透明像素立即抛错拒绝启动）；`clip.js` 在 `renderFrame` 最底层先铺一层不透明纸色兜底。
  - **无缝平铺与快动保活**：`paint.js` 实现 `P.tileMirror` 边缘镜像平铺，接缝处像素连续；`17_ink` 采用高频细纸纹与细密墨点，并加入按时间缓变洇开的「活墨晕」，使快动门禁稳定保持绿灯（`fast_ratio` 7.47%–7.76%）；消除了横竖硬边与漏底。
  - **新增近黑帧门禁（near_black_frames）**：在 `film_gate.py` 实现 `near_black` 检测（2fps 采样，统计单帧 luma<40 像素 >20% 的暗帧数；中位亮度 >110 的浅色风格中出现暗帧即亮红灯），并作为 `FACT_GATES` 接入 `produce.py`。
  - **全画幅竖屏验证**：Task 1、Task 3 与 Task 4 的 2fps 逐帧检测实测近黑帧均为 0（luma<40 且 >20% 的帧数 = 0；luma<60 且 >25% 的帧数 = 0）；针对 `12_bauhaus` 与 `14_8bit` 各跑 9:16 竖屏样片实测，暗帧同样为 0，确认无黑块/硬竖边问题。
- **8bit 图表文字 8× 像素化与可读性重构（r6 B2）**：
  - **分层缓冲与文字量化倍率 ≤2**：`clip.js` 中重构了 8bit 渲染流程。底纹保留 1/8 缓冲（`P.lowres`）量化，产生经典 8-bit 色场；语法层（柱/线/字）单独走 1/2 缓冲（`P.lowres2`），文字与数据像素化倍率 ≤2，避免被 1/8 降采样破坏。
  - **引入像素字体 Fusion Pixel Font**：引入开源 SIL OFL 1.1 像素字体 `FusionPixel12-400`（含完整 CJK 与数字字形），登记至 `third_party/fusion-pixel-font` 及 `docs/third_party/provenance-ledger.yaml`；在 `t3_finance_chart.js` 中为 8bit 风格配置该字体。
  - **本地 OCR 验证**：编写并提交本地 CPU-only OCR 检查脚本 `scripts/artmotion_ocr_check.py`（基于 RapidOCR / ONNXRuntime，绝不调用云端 API）。实测 Task 2 柱图数值标签：`253`, `306`, `392`, `609`, `887` **5/5 全部 100% 准确识别通过**。

### 2. 非阻断项与工程优化
- **横屏纹理平铺接缝消除**：`25_ghibli` 与 `17_ink` 全面采用 `P.tileMirror` 镜像平铺，接缝处相邻像素连续镜像对称，彻底消除了横屏下出现的横向/竖向突变接缝。
- **说明文字衬底增强**：`t1_3b1b.js` 的折线末端标签在 `OUT`（风格描边）开启时增加半透明暖纸色背景描边衬底，避免小号字压在高对比水彩色块上看不清的问题。
- **still_ratio 假门禁清理**：`produce.py` 将原写死 `passed: True` 的 `still_ratio` 移出 `gates` 质量门列表，作为只记录的 `info` 提示项输出。
- **流式 HTTP Blob 传帧优化**：`render.py` 将页面渲染传帧改为通过本地 HTTP POST 二进制流直接传给 Python 端管道写入 ffmpeg，避免 Playwright JSON-RPC 传输数千兆 Base64 字符串导致的内存泄露，彻底解决了 5GB cgroup 下的长片 OOM 崩溃问题。

### 3. 测试与 Lint 结果
- `pytest tests/test_artmotion.py`：**6 passed**（包含 LaTeX 清理、纹理违规检测及适配器契约测试）。
- 3O lint：**仅基线 4 项失败**（与分支基线完全一致，未引入任何新失败）：
  - `check_no_sibling_call.py`
  - `check_omodul_signature.py`
  - `check_enabled_pillars.py`
  - `check_oprim_keyword_only.py`

### 4. E2E 真实产物与验收数据（ffprobe + film_gate 实测）

| 指标 | task_0 (Ghibli 16:9) | task_1 (Ink 9:16) | task_2 (8bit 16:9) | task_3_comparison (Ink 9:16) | task_4_portrait_ghibli (Ghibli 9:16) |
|------|----------------------|-------------------|--------------------|------------------------------|--------------------------------------|
| 时长 (s) | 29.997 | 26.900 | 31.998 | 27.067 | 9.167 |
| 分辨率 | 1920x1080 | 1080x1920 | 1920x1080 | 1080x1920 | 1080x1920 |
| 视频编码 | h264 yuv420p | h264 yuv420p | h264 yuv420p | h264 yuv420p | h264 yuv420p |
| 音轨 | aac (-19.6 dB) | aac (-19.2 dB) | aac (-19.8 dB) | aac (-18.2 dB) | aac (-19.5 dB) |
| 画质门禁灯 | **green** | **green** | **green** | **green** | **green** |
| fast_ratio | 0.1133 | 0.0776 | 0.1332 | 0.0747 | 0.1009 |
| blank_run_s | 0.0s | 0.0s | 0.0s | 0.0s | 0.0s |
| blue_purple_share | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| **近黑帧数 (near_black)** | **0 帧** | **0 帧** | **0 帧** | **0 帧** | **0 帧** |
| **8bit OCR 命中** | -- | -- | **5/5 (253,306,392,609,887)** | -- | -- |
| **text_safe 越界帧** | **0/900 帧 (0%)** | **0/807 帧 (0%)** | **0/960 帧 (0%)** | **0/812 帧 (0%)** | **0/275 帧 (0%)** |
| LaTeX / 纹理违规 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| 文件大小 | 58,931,961 B | 120,891,307 B | 16,144,591 B | 118,409,109 B | 14,763,159 B |
| sha256 | `9d125e5c...` | `57aa26f3...` | `4e5b69a6...` | `42496701...` | `24daa95e...` |

### 5. 产物路径
- `output/artmotion_e2e/task_0/artmotion_landscape.mp4`
- `output/artmotion_e2e/task_1/artmotion_portrait.mp4`
- `output/artmotion_e2e/task_2/artmotion_landscape.mp4`
- `output/artmotion_e2e/task_3_comparison/artmotion_portrait.mp4`
- `output/artmotion_e2e/task_4_portrait_ghibli/artmotion_portrait.mp4`

每条成片均有对应的 `.sheet.jpg` 接触网格拼图与 `work/*.textsafe.json` 逐帧越界检查落盘。

DONE ARTMOTION-R6
