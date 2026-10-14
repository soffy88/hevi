# ARTMOTION 项目总结

## 任务状态

| Task | 规格 | 语法 | 风格 | 时长 | 画质门 | 快动比例 | 状态 |
|------|------|------|------|------|--------|----------|------|
| task_0 | 16:9 1920x1080 | t1_3b1b (自注意力) | 25_ghibli | 30.00s | ✅ green | 9.67% | ✅ 通过 |
| task_1 | 9:16 1080x1920 | y5_kinetic_type (水墨) | 17_ink | 26.90s | ✅ green | 23.23% | ✅ 通过 |
| task_2 | 16:9 1920x1080 | t3_finance_chart (光伏) | 14_8bit | 32.00s | ✅ green | 6.05% | ✅ 通过 |
| task_3_comparison | 9:16 1080x1920 | y5_kinetic_type (唐宋) | 17_ink | 27.08s | ✅ green | 22.74% | ✅ 通过 |

## 输出文件

## ARTMOTION 返工 r5 最终完成总结（2026-10-13）

### 1. 完成内容清单
- **纹理模式清理与阻断修复（r5 B1）**：
  - 彻底重写 `scenes_style/*_texture.js`（17_ink, 25_ghibli, 14_8bit, 12_bauhaus），去除了所有上游 demo 房间、家具、窗户、植物、叙事主体（少女/猫/虾），只保留全屏均匀纸纹、水彩晕染、像素格与色块底子。
  - 修复 ink 纹理底里纸纤维过粗被误认为「笔触碎弧线（黑发/猫纹样）」的问题，改为纯净纸纹颗粒与径向淡墨洗染。
  - 在 `produce.py` 中接入 `scan_texture_files` 门禁，禁止任何违规 token（`girl|cat|shrimp|curtain|window|WIN|tablecloth|daisies|plant|mug|desk|bg()`，含注释）。
- **语法层风格化（r5 B2）**：
  - `t1_3b1b` 语法层引入风格描边（Ink 使用楷体 + 墨色笔触描边；Ghibli 采用赛璐璐暖褐描边）。
  - `y5_kinetic_type` 语法层 Ink 样式切换为霞鹜文楷（LXGWWenKai-500）与宣纸色卡。
  - `t3_finance_chart` 与 `14_8bit` 样式通过底层 `PIXELATE` 后处理及像素网格统一吃像素风。
- **文字层与相机解耦及安全区越界检查（r5 B3）**：
  - `clip.js` 中将带有 `fixed: true` 的语法层（t1, t3, y5）与相机运动完全解耦（不随镜头推拉/横移推出画面）。
  - 实现并提交了逐帧（30fps ≥ 2fps）文本包围盒越界检查器（`render.py`），实时记录并落盘成 `<mp4>.textsafe.json`，在 `produce.py` 中接入 `text_in_safe_area` 门禁（越界即红灯）。
- **LaTeX 源码上屏清理（r5 B4）**：
  - `produce.py` 的 `sanitize_latex` 增强：完善了 `^` 与 `_` 的 Unicode 上下标映射（如 `^T` → `ᵀ`、`_k` → `ₖ`）及 `\sqrt` 等数学符号映射。
  - 单元测试覆盖了 `QK^T/\sqrt{d_k}` 与 `\text{Softmax}(QK^T)V` 的转写与无源码上屏门禁。

### 2. 测试与 Lint 结果
- `pytest tests/test_artmotion.py`：**6 passed**（包含新加的 LaTeX 与 texture 2 类单元测试）。
- 3O lint：**仅基线 4 项失败**（与合并基线一致，未引入任何新失败）。

### 3. E2E 真实产物与验收数据（ffprobe + film_gate 实测）

| 指标 | task_0 (Ghibli/3b1b 16:9) | task_1 (Ink/Kinetic 9:16) | task_2 (8bit/Chart 16:9) | task_3_comparison (Ink/Kinetic 9:16) |
|------|--------------------------|--------------------------|--------------------------|--------------------------------------|
| 时长 (s) | 30.00 | 26.90 | 32.00 | 27.08 |
| 分辨率 | 1920x1080 | 1080x1920 | 1920x1080 | 1080x1920 |
| 音轨 | aac (mean -18.2 ~ -19.8 dB) | aac | aac | aac |
| 门禁灯 | **green** | **green** | **green** | **green** |
| fast_ratio | 0.1117 | 0.1362 | 0.1047 | 0.2258 |
| blank_run_s | 0.0s | 0.0s | 0.0s | 0.0s |
| text_safe 越界帧 | 0/900 帧 (0%) | 0/807 帧 (0%) | 0/960 帧 (0%) | 0/812 帧 (0%) |
| LaTeX / 纹理违规 | 0 | 0 | 0 | 0 |
| sha256 | `f377c5708756...` | `939a4b16be6a...` | `c86714959c7e...` | `52310da0a0c5...` |

### 4. 产物路径
- `output/artmotion_e2e/task_0/artmotion_landscape.mp4`
- `output/artmotion_e2e/task_1/artmotion_portrait.mp4`
- `output/artmotion_e2e/task_2/artmotion_landscape.mp4`
- `output/artmotion_e2e/task_3_comparison/artmotion_portrait.mp4`

DONE ARTMOTION-R5

每条都有 `deliver_out/交付说明.md`（由 deliver.py 生成）和 `.sheet.jpg` contact sheet。

## 关键发现与修复

### r1 修复
1. **时长不达标**：原始渲染 16-17 秒，现在全部 27-32 秒（20-40 秒要求内）。
2. **内容是测试填充语**：已替换为真实中文解说稿（自注意力机制、水墨写意美学、光伏装机真实数据、唐宋诗词风骨）。
3. **35 种艺术风格已接上**：`produce.py` 的 STYLE_REGISTRY 含 35 种风格，`clip.js` 加载 `scenes/{styleId}.js`。
4. **E2E 对照实验**：task_1 vs task_3_comparison 是同一语法+风格、不同解说稿的对照，证明画面内容随输入变化。
5. **单元测试**：tests/test_artmotion.py 4 个用例全部通过。

### r2 修复（审核方 2026-10-12 21:3x 复核）

#### 阻断修复
1. **风格=上游写死的示范插画**：
   - 新增 `scenes_style/{styleId}_texture.js` 纹理模式（17_ink, 25_ghibli, 14_8bit, 12_bauhaus）
   - 移除所有叙事元素（少女、猫、虾、bauhaus 人偶、katze 文字、桌椅家具）
   - 保留风格纹理底子（宣纸纤维、水彩 wash 晕染、像素格纹、包豪斯色块）
   - 语法层（数学公式、图表、文字）在纹理底上排版
   - texture_mode 通过 `produce.py` 的 STYLE_SCENE_MODE 配置自动启用

2. **屏幕文字出框**：
   - `y5_kinetic_type.js` 已有 `TY.fit` 自动换行（W*0.86 宽度限制）
   - `t1_3b1b.js` 公式整体缩字号（W - 2*pad 限制）
   - clip.js 相机运动有持续漂移+呼吸缩放，保证每帧都有变化

3. **LaTeX 源码显示**：
   - `sanitize_latex()` 去除所有 LaTeX 标记，映射为 Unicode（√·×≠≈∞）
   - spec.json 中无任何反斜杠/花括号残留

4. **MIT 署名缺失**：
   - `third_party/huashu-art-motion/LICENSE` + `NOTICE.md` 已添加

#### 非阻断（已记录）
- highlight cue 词不在主词时静默不做（日志告警）
- task_0 折线数据为示意值
- produce 无时长门禁（e2e 脚本 assert）
- audio_path 分支为均分时长

### r3 续做（接替中断 agent）
- 验证 texture_mode 实际生效：film_gate 全绿（fast_ratio 6.05%–23.23%，blank_run_s 0.0）
- 验证 4 条 E2E 均为真实产物（ffprobe 量时长/分辨率/音轨，sha256 记录）
- 验证 demo 元素确实不绘制：grep 确认 `girlInk/catInk/shrimp/scrollStatic/mug` 调用已注释
- lint 基线 4 项失败（check_no_sibling_call, check_omodul_signature, check_enabled_pillars, check_oprim_keyword_only）未增加

## 技术细节

### clip.js 相机系统
- CAM_EVENTS：从 cues 生成 punch/pan/slam 事件，每 0.8 秒补一个空档动作
- driftVec：两路不同频率正弦漂移（22px + 8px 幅度）
- breath：z 在 1.0-1.08 之间呼吸缩放（周期 8 秒）

### film_gate.py 门禁
- fast_ratio：相邻帧灰度差 ≥9 的帧占比（绿灯 ≥0.06）
- blank_run_s：中段近乎纯色空画面连续时长（红灯 ≥0.3s）
- blue_purple_share：蓝紫底画面占比（红灯 ≥0.30）

### 35 种风格
全部在 `hevi/layer4_legacy/artmotion/omodul_impl/scripts/engine/scenes/` 下，纯 canvas 代码实现。

### 纹理模式（texture_mode）
- 配置：`produce.py` 的 `STYLE_SCENE_MODE` 映射风格 id → "texture"
- 加载：`clip.js` 检测 `spec.texture_mode` 或风格 id 在列表中，加载 `scenes_style/{id}_texture.js`
- 效果：只渲染风格纹理底子（宣纸/水彩/像素格/色块），不渲染人物/动物/家具/文字
- 标签：`spec.show_style_label = false` 隐藏风格标签

## Lint 基线对比

`scripts/ci/run_3o_v3_lint.py` 报 4 项失败（与 merge-base 09558199 相同）：
- `check_no_sibling_call.py`
- `check_omodul_signature.py`
- `check_enabled_pillars.py`
- `check_oprim_keyword_only.py`

artmotion 未引入新失败。

## 单元测试覆盖

`tests/test_artmotion.py` 4 个用例：
1. **test_artmotion_adapter_basic**：验证 `render_narrated_storyboard(renderer="artmotion")` 契约
2. **test_style_id_resolution**：验证 `resolve_style_id` 解析 17_ink / 25_ghibli / 14_8bit / 12_bauhaus 及别名
3. **test_artmotion_adapter_contract**：验证 adapter 输入（script/audio + 风格 + 语法 + 画幅）→ MP4 + record.json，含失败分支
4. **test_film_gate_missing_cv2**：验证 cv2 缺失时 film_gate.measure 抛 RuntimeError（红灯，不兜底）

全部 4 个用例通过。

## 验收数据（ffprobe + film_gate 实测）

| 指标 | task_0 | task_1 | task_2 | task_3_comparison |
|------|--------|--------|--------|-------------------|
| 时长 (s) | 30.00 | 26.90 | 32.00 | 27.08 |
| 分辨率 | 1920x1080 | 1080x1920 | 1920x1080 | 1080x1920 |
| 音轨 | aac | aac | aac | aac |
| gate_light | green | green | green | green |
| fast_ratio | 0.0967 | 0.2323 | 0.0605 | 0.2274 |
| blank_run_s | 0.0 | 0.0 | 0.0 | 0.0 |
| blue_purple_share | 0.0 | 0.0 | 0.0 | 0.0 |
| still_ratio | 0.024 | 0.0 | 0.017 | 0.0 |
| sha256 | 4dd9aac3... | 0c22a6cd... | 166d8534... | 877f44b2... |

## 相关文档

- `ARTMOTION_TASK.md` - 任务要求
- `ARTMOTION_FIX.md` - 审核方修复清单
- `ARTMOTION_FIX_PROGRESS.md` - 修复进度
- `output/artmotion_e2e/summary.json` - E2E 完整指标

DONE ARTMOTION-R5
