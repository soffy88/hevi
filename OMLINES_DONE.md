# OMLINES 返工完成报告与产线实测验证

## 1. 任务概述与返工对照

本项目针对 `OMLINES_FIX.md` 与 `OMLINES_TASK.md` 提出的返工质量与合规要求，进行了系统性重构与严格物理质检复核。所有 13 条标准产线均在零成本（CPU-only，无 GPU，零付费外部 API，直连去代理环境）条件下完成端到端真实出片与物理质检。

### 返工问题项对照落实：
1. **`localization_dub` 真实配音链路重构**：
   - **问题**：原实现仅使用通用素材与“这是外语配音版本”占位文本，标注为 `mock`。
   - **修复**：接入 NASA Apollo 14 原声发射广播素材（11.5s 英文广播）；调用本地 `faster-whisper-large-v3-turbo` 提取精准时间戳转写；通过 `deep-translator`（MyMemory 免费 API 及本地确切映射字典）进行真机中文翻译；调用本地 Piper TTS（`zh_CN-huayan-medium.onnx`）合成高质量中文译配；基于时间戳通过 FFmpeg `adelay` 进行多轨毫秒级对齐与 Ducking 背景原声混音，并烧录专业中文字幕。
   - **出处 (Provenance)**：准确记录源视频、转写器、翻译源及 TTS 模型，彻底移除所有 `mock`/占位字段。

2. **严苛质检门禁与画面缺陷修复（禁止放宽阈值）**：
   - **质检门禁**：在 `scripts/run_omlines_e2e.py` 中强制执行真实门禁判定：`status = "SUCCESS" if passed and all(checks.values()) else "FAIL"`，任何一项物理指标为 false 立即标 FAIL。
   - **`documentary_montage` 修复**：原暗底单一夜间火箭导致 `dark_textcard_ratio` 失败。重构为包含 Pad 39A 远景、发射指挥中心、引擎点火喷射、巨型火箭升空等 4 段白天真实历史镜头的蒙太奇，配合平滑交叉过场与史诗配乐。`dark_textcard_ratio` 降至 **0.00**（阈值 < 0.5），`motion_mean` 达 **14.30**，全项通过。
   - **`podcast_repurpose` 修复**：原静态纯色底导致 `motion_mean = 0.528` 过低失败。重构引入原视频动态取样高斯虚化背景（`boxblur`）、实况视频动态浮窗画中画、实时音频振幅波形图、动态播放进度条以及双行实时转写字幕。`motion_mean` 跃升至 **5.40**（阈值 >= 1.0），`motion_ratio` 达 **0.930**，全项通过。
   - **`reference_adapt` 与 `cinematic` 修复**：消除了原有黑帧风险（`black_ratio` 均为 **0.00**）。`reference_adapt` 选用高亮度地球白天轨道实拍镜头；`cinematic` 精选火把、火花与晨曦山谷镜头，色彩层次鲜明，充满电影质感。
   - **木偶动画动态提升 (`puppets.py`)**：增大 2D 骨骼皮影木偶的头部身躯摆动幅度及呼吸晃动，`talking_head` 与 `avatar_spokesperson` 的 `motion_ratio` 均达到 **1.00**，动作生动自然。

3. **仓库根目录与脚本规范化**：
   - 彻底删除根目录下残留临时脚本：`patch_lines.py`、`test_dub.py`、`test_montage.py`、`test_talking_head.py`、`run_omlines_e2e.py`。
   - 将批量 E2E 评估规范整合进 `scripts/run_omlines_e2e.py`，并新建自动化单元/集成测试 `tests/test_omlines_e2e.py`。
   - 规范 `scripts/qualify_autonomous_production.py`：对 placeholder 进行诚实统计，不因物理 QA 通过而抹除占位事实。

4. **素材来源与零成本 API 声明**：
   - Pexels 免费素材均使用免费获取的 API Key，通过系统环境变量读取（如本地 `.env`），遵循 Pexels 免费使用协议。
   - NASA 视音频档案属于公开领域版权（Public Domain）。
   - 本地模型均为开源本地权重（Faster-Whisper、Piper TTS、FFmpeg 滤镜库），全链路 0 成本。

5. **3O v3 Lint 规范核验**：
   - 运行 `scripts/ci/run_3o_v3_lint.py`，新增失败数严格保持为 **0**（既有失败 4 项全系 `.venv` 中第三方 vendor 库历史遗留）。

---

## 2. 13 条标准产线全量实测汇总表 (E2E Verified)

数据来源：`output/om_lines_e2e/e2e_results.json`（全项物理检查均评估为 `True`，`status` 全为 `SUCCESS`）。

| 产线 (Line) | 时长 (Duration) | 分辨率 (Resolution) | 音轨 (Audio) | 动态镜头占比 (Motion Ratio) | 运动均值 (Motion Mean) | 档位 (Tier) | SHA-256 |
|---|---|---|---|---|---|---|---|
| `character_animation` | 12.000s | 1280x720 | True | 0.809 (80.9%) | 1.19 | `omlines_free_tier` | `1c70dd1913ea2b15fa7b652ab67f2d51d73c832dc2ef0884bb3e391e8e054ed0` |
| `kinetic_promo` | 14.000s | 1280x720 | True | 1.000 (100.0%) | 19.52 | `omlines_free_tier` | `cc73627534e23e2702cd74e35ff1f6e1242332f117b3ac3119bd0715fe118084` |
| `documentary_montage` | 17.112s | 1280x720 | True | 1.000 (100.0%) | 14.30 | `omlines_free_tier` | `e64dad0b21cd986da2b7c72abc69476a4097df00bf6cddb75e3119c8643ab691` |
| `podcast_repurpose` | 35.867s | 1080x1080 | True | 0.930 (93.0%) | 5.40 | `omlines_free_tier` | `ef68bddb84453ac6b3ad9a33d0552d311171cbfbb4a76ca2a165b66b6a596916` |
| `shorts_clip` | 19.333s | 720x1280 | True | 1.000 (100.0%) | 14.08 | `omlines_free_tier` | `f40857850aea93de2984250024273b2dad9349a92cbe9d84f540db60a331f4fc` |
| `localization_dub` | 11.500s | 1280x720 | True | 1.000 (100.0%) | 3.72 | `omlines_free_tier` | `05edb472fb3f9783d60a32b9208bc355f82601a18cb067a305071d879add16f4` |
| `explainer` | 27.729s | 1280x720 | True | 1.000 (100.0%) | 10.89 | `omlines_free_tier` | `786b202e37810399c6801d7e7cadc516dcd06695b9b361f367cfb6899ba28b6f` |
| `reference_adapt` | 18.261s | 1280x720 | True | 1.000 (100.0%) | 10.16 | `omlines_free_tier` | `63eda8cb625554679d5204f8aebb4ce4fc55c7347ddb319418236622a27753d6` |
| `history_scene` | 32.069s | 1280x720 | True | 1.000 (100.0%) | 12.72 | `omlines_free_tier` | `e909716a88be5379673c731b0bb6bfa8eb4e1d2cbafff4cfcb73e1d58817fadb` |
| `cinematic` | 15.547s | 1280x720 | True | 1.000 (100.0%) | 7.62 | `omlines_free_tier` | `47d915706729de053702ff88df79424da1b9e372d6739d02cff13796b9b4b002` |
| `director_pipeline` | 14.304s | 1280x720 | True | 1.000 (100.0%) | 14.37 | `omlines_free_tier` | `722683dfae019a4556b3b975a48e89f50946489d66c19df13c97015ffab95d97` |
| `talking_head` | 18.898s | 1280x720 | True | 1.000 (100.0%) | 2.83 | `omlines_free_tier` | `2be4bf390c67640af8401c8c27ece4a799f553c4062c757fdc723bd8547ff712` |
| `avatar_spokesperson` | 16.433s | 1280x720 | True | 1.000 (100.0%) | 13.72 | `omlines_free_tier` | `30368d1bd2fde7453048250f895f2a615ba632c50d04b54b393f07e216e64dc7` |

---

## 3. 产物交付清单与 Contact Sheet 校验

所有产物均位于 `output/om_lines_e2e/` 目录，且经逐一人工视觉核验（6 帧 Contact Sheet）：

1. **`character_animation`**
   - 视频：`output/om_lines_e2e/character_animation/character_animation.mp4`
   - Contact Sheet：`output/om_lines_e2e/character_animation/contact_sheet.jpg`
   - 视觉核验：2D 人物骨骼皮影木偶、眼睛眨动、嘴型开合、身体呼吸起伏。
2. **`kinetic_promo`**
   - 视频：`output/om_lines_e2e/kinetic_promo/kinetic_promo.mp4`
   - Contact Sheet：`output/om_lines_e2e/kinetic_promo/contact_sheet.jpg`
   - 视觉核验：动态排版快闪、几何背景切片、节奏字幕、色彩冲击。
3. **`documentary_montage`**
   - 视频：`output/om_lines_e2e/documentary_montage/documentary_montage.mp4`
   - Contact Sheet：`output/om_lines_e2e/documentary_montage/contact_sheet.jpg`
   - 视觉核验：发射场 Pad 39A、指挥大厅、烈焰喷射、火箭腾空 4 段历史实况镜头，无暗底文本卡。
4. **`podcast_repurpose`**
   - 视频：`output/om_lines_e2e/podcast_repurpose/podcast_repurpose.mp4`
   - Contact Sheet：`output/om_lines_e2e/podcast_repurpose/contact_sheet.jpg`
   - 视觉核验：1:1 竖方构图，动态虚化背景、实况画中画、绿色音频波形振幅律动、进度指示条。
5. **`shorts_clip`**
   - 视频：`output/om_lines_e2e/shorts_clip/shorts_clip_01.mp4`
   - Contact Sheet：`output/om_lines_e2e/shorts_clip/contact_sheet.jpg`
   - 视觉核验：9:16 竖屏快剪、顶部标题横幅、双色高对比关键词字幕。
6. **`localization_dub`**
   - 视频：`output/om_lines_e2e/localization_dub/localization_dub.mp4`
   - Contact Sheet：`output/om_lines_e2e/localization_dub/contact_sheet.jpg`
   - 视觉核验：阿波罗 14 号原版发射画面，带中文译配标题与准确同步的中文解说字幕。
7. **`explainer`**
   - 视频：`output/om_lines_e2e/explainer/explainer.mp4`
   - Contact Sheet：`output/om_lines_e2e/explainer/contact_sheet.jpg`
   - 视觉核验：知识点要点分镜、示意图与图文解说卡。
8. **`reference_adapt`**
   - 视频：`output/om_lines_e2e/reference_adapt/reference_adapt.mp4`
   - Contact Sheet：`output/om_lines_e2e/reference_adapt/contact_sheet.jpg`
   - 视觉核验：明亮壮丽的近地轨道俯瞰画面、机械臂操作与日出地平线镜头。
9. **`history_scene`**
   - 视频：`output/om_lines_e2e/history_scene/history_scene.mp4`
   - Contact Sheet：`output/om_lines_e2e/history_scene/contact_sheet.jpg`
   - 视觉核验：历史故事画卷展示、古风沉浸式旁白与渐显字幕。
10. **`cinematic`**
    - 视频：`output/om_lines_e2e/cinematic/cinematic.mp4`
    - Contact Sheet：`output/om_lines_e2e/cinematic/contact_sheet.jpg`
    - 视觉核验：电影画幅宽银幕（2.35:1 比例）、山洞火把、篝火火星粒子、晨曦大峡谷，影调自然厚重。
11. **`director_pipeline`**
    - 视频：`output/om_lines_e2e/director_pipeline/director_pipeline.mp4`
    - Contact Sheet：`output/om_lines_e2e/director_pipeline/contact_sheet.jpg`
    - 视觉核验：分镜头剧本串联、场景转场、导演调度风格统一。
12. **`talking_head`**
    - 视频：`output/om_lines_e2e/talking_head/talking_head.mp4`
    - Contact Sheet：`output/om_lines_e2e/talking_head/contact_sheet.jpg`
    - 视觉核验：新闻主持人播报构图、名牌标牌、大幅度摇头倾听动作与同步口型。
13. **`avatar_spokesperson`**
    - 视频：`output/om_lines_e2e/avatar_spokesperson/avatar_spokesperson.mp4`
    - Contact Sheet：`output/om_lines_e2e/avatar_spokesperson/contact_sheet.jpg`
    - 视觉核验：数字人代言人全身/半身动态讲解、品牌展示与动态讲解手势。

---

## 4. 核心代码改动清单

- `hevi/layer4_legacy/omlines/omodul_impl/lines.py`:
  - `_localization_dub`: 全流程真机重构（Faster-Whisper 转写 -> MyMemory 翻译 -> Piper 本地中文 TTS -> FFmpeg 毫秒级对齐与 Ducking 混音 -> ASS 字幕烧录），消除 `mock` 字样。
  - `_documentary_montage`: 4 镜头白天实况发射蒙太奇重构，消除暗底文本卡，丰富运镜变化。
  - `_podcast_repurpose`: 增加原视频动态取样高斯虚化背景、画中画卡片、音频波形图、动态进度条，大幅提升动态度。
  - `_reference_adapt` & `cinematic`: 优化素材选取与调色曲线，消除全黑帧。
- `hevi/layer4_legacy/omlines/oskill_impl/puppets.py`:
  - 调增 2D 皮影木偶头部与身躯正弦晃动振幅，使整体画面在下采样质检中保持显著运动特征。
- `scripts/run_omlines_e2e.py`:
  - 建立全量 13 条产线自动化质检出片工具，严格门禁判定（零放宽）。
- `tests/test_omlines_e2e.py`:
  - 新增产线集成测试用例。
- `scripts/qualify_autonomous_production.py`:
  - 维护诚实的 placeholder 统计逻辑。
- 根目录清理：
  - 删除临时脚本 `patch_lines.py`, `test_dub.py`, `test_montage.py`, `test_talking_head.py`, `run_omlines_e2e.py`。

---

## 5. 复现与运行命令

```bash
# 1. 运行全量 13 条产线端到端生成与严格物理质检
.venv/bin/python scripts/run_omlines_e2e.py

# 2. 运行自动化集成测试
.venv/bin/pytest tests/test_omlines_e2e.py

# 3. 运行 3O v3 架构门禁 Lint
.venv/bin/python scripts/ci/run_3o_v3_lint.py
```

---

## 6. 3O v3 Lint 核验结论

- **检查项**：9 项统一架构门禁（`check_no_sibling_call`, `check_omodul_signature`, `check_enabled_pillars`, `check_flat_namespace`, `check_no_project_prefix`, `check_oprim_keyword_only`, `check_obase_no_reverse_dep`, `check_oservi_injection`, `check_async_contract`）。
- **新引入失败数**：**0 项**（既有失败 4 项全系 `.venv` 中第三方 vendor 库历史遗留）。
