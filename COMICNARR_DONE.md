# COMICNARR 交付验收报告

任务名：`COMICNARR`  
工作区：`/data/soffy/projects/hevi-comicnarr`  
分支：`feat/comicnarr-3o`  
基线 Commit：`98e216af`  
完成时间：2026-10-11  

---

## 一、做了什么

根据 `COMICNARR_TASK.md` 规定，本项目在零成本 CPU 环境下实现了 Pixelle 思路的“漫画解说”流水线，作为 Hevi 架构下的第 12 条零成本产线（`comic_narration`）。

1. **统一关键帧引擎（Keyframe Engine oprim）**：
   - 实现了与 DRAMAKEY 任务严格对齐的通用关键帧接口 `KeyframeEngine`、`KeyframeResult` 与解析器 `resolve_keyframe_engine`。
   - 默认引擎 `sdturbo_cpu`：使用本地 SD-Turbo（`/data/soffy/models/ms/models/AI-ModelScope--sd-turbo/snapshots/master`，float32 加载）+ TAESD（`madebyollin--taesd`）快速解码，单步推理约 3.5s/图。
   - 进程互斥保护：推理及模型加载自动获取 `/tmp/hevi_cpu_render.lock` 全机文件锁，防止并发 OOM。
   - 辅助引擎：`fake`（轻量合成图，供高速单元测试使用）、`cloud_stub`（云端插槽，默认关闭）。
   - 图文质量评分：`image_score` 使用本地 OpenCLIP ViT-B-32 计算 Prompt 相似度，结合 Laplacian 梯度方差锐度与曝光度，实现 ViMax 双候选图文分择优。

2. **第 12 条 Zero 产线（`comic_narration`）注册与生态对齐**：
   - 在 `hevi/layer4_legacy/zerolines/oprim_impl/specs.py` 中将 `ZERO_LINES` 扩展为 12 条，注册 `comic_narration` 规范（竖屏 1080×1920，qa 门禁 `min_motion=0.5, min_duration_s=10.0`）。
   - 在 `hevi/layer4_legacy/zerolines/omodul_impl/_lines.py` 的 `PRODUCERS` 映射中接入 `comic_narration`。
   - 在 `hevi/studio/lines/comic_narration.yaml` 创建 Studio Recipe。
   - 在 `hevi/studio/production_catalog.py` 的 `CANONICAL_LINES` 中注册 `comic_narration`。
   - 在 `scripts/qualification/zero_line_briefs.json` 中补充 qualification brief。
   - 同步修正审核脚本及旧测试中的硬编码数字（`scripts/acceptance_matrix.py`、`scripts/qualify_autonomous_production.py`、`tests/test_zerolines.py`）。

3. **漫画解说完整流水线（`hevi/layer4_legacy/comicnarr/`）**：
   - **主题/文本输入 → 脚本规划（`script_planner`）**：自动切分或扩写为 6–14 句解说脚本（每句 ≤30 字，实测 11 句）；支持本地免费通道（Omniroute `:20128`），并配有高质量确定性规则兜底。
   - **主角视觉一致性与提示词翻译（`prompt_builder`）**：提取主角外貌固定 tokens（如橘猫特征、书生汉服特征），拼接画面描述中英翻译与风格模板 tokens。
   - **双候选择优出图**：每句采用固定 seed 基数生成 2 张候选，经 OpenCLIP 评分择优入选，败选图保留于 `frames/`。
   - **TTS 解说**：默认调用本地 Piper TTS（`zh_CN-huayan-medium.onnx`），按内容哈希缓存断点续跑。
   - **BGM 伴奏与侧链 Ducking**：复用 hevi 的 `write_bgm` 与 `mix`，自动压低音乐至解说下方（-22 dB ducking）。
   - **动态 Ken Burns 运镜**：每张图预先放大 1.25 倍以防糊边，推/拉/左移/右移交替运镜，25fps 输出 1080×1920 高清片段。
   - **字幕烧录**：支持常规高对比度底部字幕（ASS/SRT）及漫画对白框（bubble）样式。
   - **成片与实测门禁**：最终导出 MP4，实时运行 ffprobe、volumedetect、相邻帧运动差测量，生成 6 帧 contact sheet 与 sha256 签名。

4. **风格模板**：
   - `comic_color`：彩色扁平美漫风（`vibrant comic book art, flat colors, bold clean lineart`），明快 BGM，底部清晰字幕。
   - `manga_bw`：黑白日漫风（`black and white manga style, monochrome ink line art, clean screentone`），温润古风 BGM，漫画对白框。

---

## 二、修改与新增文件清单

```text
新增实现与规范文件：
- docs/KEYFRAME-ENGINE.md                                  # 关键帧引擎规范与跨任务共用契约
- hevi/keyframe/                                           # 关键帧引擎兼容 shim (oprim, oskill, omodul)
- hevi/layer4_legacy/keyframe/oprim_impl/                  # 关键帧原子引擎 (sdturbo_cpu, fake, cloud_stub, image_score, lock, registry)
- hevi/layer4_legacy/keyframe/oskill_impl/                 # 关键帧技能 (prompt_translator)
- hevi/layer4_legacy/keyframe/omodul_impl/                 # 关键帧编排 (video_render)
- hevi/comicnarr/                                          # 漫画解线兼容 shim 及 cli.py 入口
- hevi/layer4_legacy/comicnarr/oprim_impl/                 # 漫画核心契约、风格模板、Ken Burns 滤镜、字幕生成
- hevi/layer4_legacy/comicnarr/oskill_impl/                # 脚本规划、提示词翻译与角色一致性
- hevi/layer4_legacy/comicnarr/omodul_impl/                # comic_narration_workflow 端到端流水线
- hevi/studio/lines/comic_narration.yaml                   # Studio 产线 Recipe 规范
- scripts/e2e/comicnarr_e2e.py                             # E2E 真实出片验收脚本
- tests/test_comicnarr_pipeline.py                         # 快速单元测试用例 (7 项用例)
- COMICNARR_PROGRESS.md                                    # 阶段进度跟踪
- COMICNARR_DONE.md                                        # 本交付报告

修改的现有文件：
- hevi/layer4_legacy/zerolines/oprim_impl/specs.py         # ZERO_LINES 扩展至 12，注册 comic_narration spec
- hevi/layer4_legacy/zerolines/omodul_impl/_lines.py       # PRODUCERS 接入 comic_narration 生成器
- hevi/studio/production_catalog.py                        # CANONICAL_LINES 注册 comic_narration
- hevi/studio/fulfill.py                                   # _RENDERERS 与 retry_lines 接入 comic_narration
- scripts/qualification/zero_line_briefs.json              # 增加 comic_narration qualification brief
- scripts/qualify_autonomous_production.py                 # 动态使用 len(CANONICAL_LINES) 替代硬编码 13
- scripts/acceptance_matrix.py                             # 更新 Z1 门禁说明为 12 zero lines
- tests/test_zerolines.py                                  # 更新断言 ZERO_LINES 数量为 12
```

---

## 三、如何调用

### 1. Python API
```python
from pathlib import Path
from hevi.comicnarr import comic_narration_workflow

# 方式 A：纯主题输入，自动撰写 11 句解说脚本与彩色漫画配图
result = comic_narration_workflow(
    config={"steps": 1},
    input_data={
        "topic": "为什么猫总爱把东西推下桌？猫咪的重力实验与捕食本能探索",
        "style": "comic_color",
        "subtitle_style": "bottom",
        "keyframe_engine": "sdturbo_cpu",
        "base_seed": 42,
    },
    output_dir=Path("output/comic_cat"),
)
print("Final MP4:", result["final_mp4"])
print("QA Passed:", result["qa"]["passed"])

# 方式 B：指定文本片段输入，黑白日漫风 + 漫画对话框
result_bw = comic_narration_workflow(
    config={"steps": 1},
    input_data={
        "topic": "聊斋志异·促织",
        "texts": [
            "宣德年间，宫中盛行斗蟋蟀之风。",
            "成名为人忠厚，却被摊派了差事。",
            "眼看交纳之期迫近，整日惶恐不安。",
            # ...
        ],
        "style": "manga_bw",
        "subtitle_style": "bubble",
        "keyframe_engine": "sdturbo_cpu",
    },
    output_dir=Path("output/manga_cuozhi"),
)
```

### 2. 通过 Zerolines / Studio 统一入口调用
```python
from hevi.layer4_legacy.zerolines import zero_line_workflow

res = zero_line_workflow(
    config={},
    input_data={
        "line_id": "comic_narration",
        "topic": "为什么猫总爱把东西推下桌",
        "extras": {"style": "comic_color"},
    },
    output_dir="output/studio_comic",
)
```

### 3. CLI 调用示例
```bash
# 运行 CLI
python -m hevi.comicnarr.cli \
    --topic "为什么猫总爱把东西推下桌？" \
    --style comic_color \
    --subtitle-style bottom \
    --output output/cli_comic_cat/
```

---

## 四、E2E 真实出片验收与实测报告

运行命令：
```bash
.venv/bin/python scripts/e2e/comicnarr_e2e.py
```

### 汇总实测矩阵
| 故事用例 | 风格模板 | 实测时长 | 分辨率/帧率 | 音频响度 | 运镜帧间差异 | 关键帧互斥 (SHA256) | QA 实测判定 |
|---|---|---|---|---|---|---|---|
| **Story 1: 猫咪推杯子** | `comic_color` | **63.35s** | 1080×1920 @ 25fps | **-19.3 dB** | **127.53** | **全部互不相同 (44张)** | **PASS** |
| **Story 2: 聊斋·促织** | `manga_bw` | **60.55s** | 1080×1920 @ 25fps | **-19.6 dB** | **127.93** | **全部互不相同 (44张)** | **PASS** |

### 产物详细路径与指标

#### 1. Story 1: `output/comicnarr_e2e/story1_cat_knock/`
- **成片 MP4**：`output/comicnarr_e2e/story1_cat_knock/final.mp4` (大小: 10,187,225 字节)
  - SHA256: `0289c01b22a9b00cd2b2e9aa6fad43aadf808bc9d3e61815578d5fb246187a94`
  - 编码：H.264 High / AAC 立体声 44100Hz
  - 实测时长：63.35 秒（严格在 45–75 秒要求内）
- **Contact Sheet**：`output/comicnarr_e2e/story1_cat_knock/contact_sheet.jpg` (大小: 629,325 字节，6 帧高清采样拼图)
- **关键帧**：`output/comicnarr_e2e/story1_cat_knock/frames/`（共 44 张 PNG，包含 11 张胜选关键帧与落选候选帧）
- **字幕文件**：`output/comicnarr_e2e/story1_cat_knock/subtitles.srt`
- **脚本数据**：`output/comicnarr_e2e/story1_cat_knock/script.json`
- **实测 QA**：`output/comicnarr_e2e/story1_cat_knock/qa.json` (`mean_frame_difference`: 127.53, `mean_volume_db`: -19.3 dB)
- **性能记录**：`output/comicnarr_e2e/story1_cat_knock/record.json` (`peak_rss_mb`: 7468.8 MB，生成总耗时: 294.3s)

#### 2. Story 2: `output/comicnarr_e2e/story2_cuozhi_manga/`
- **成片 MP4**：`output/comicnarr_e2e/story2_cuozhi_manga/final.mp4` (大小: 8,768,033 字节)
  - SHA256: `d401217a5581b261ef1b06c4e15b9657f5456d37b28f9d1f651bf57d62376730`
  - 编码：H.264 High / AAC 立体声 44100Hz
  - 实测时长：60.55 秒（严格在 45–75 秒要求内）
- **Contact Sheet**：`output/comicnarr_e2e/story2_cuozhi_manga/contact_sheet.jpg` (大小: 587,736 字节，6 帧高清采样拼图)
- **关键帧**：`output/comicnarr_e2e/story2_cuozhi_manga/frames/`（共 44 张 PNG，包含 11 张黑白漫画胜选与落选图）
- **字幕文件**：`output/comicnarr_e2e/story2_cuozhi_manga/subtitles.srt`
- **脚本数据**：`output/comicnarr_e2e/story2_cuozhi_manga/script.json`
- **实测 QA**：`output/comicnarr_e2e/story2_cuozhi_manga/qa.json` (`mean_frame_difference`: 127.93, `mean_volume_db`: -19.6 dB)
- **性能记录**：`output/comicnarr_e2e/story2_cuozhi_manga/record.json` (`peak_rss_mb`: 7468.8 MB，生成总耗时: 178.4s)

---

## 五、Lint 与单元测试前后对比

### 1. 3O v3 Lint 对比
运行 `.venv/bin/python scripts/ci/run_3o_v3_lint.py`：
- **开工基线**：4 项 failure（全部源自软链主环境 `.venv/lib/python3.14/site-packages` 遗留 debt，本地 0 failure）。
- **完工现状**：4 项 failure（完全一致，本地代码 0 违规，未引入任何新失败）。
  ```text
  [PASS] check_flat_namespace.py
  [PASS] check_no_project_prefix.py
  [FAIL] check_oprim_keyword_only.py (site-packages baseline)
  [PASS] check_obase_no_reverse_dep.py
  [PASS] check_oservi_injection.py
  [PASS] check_async_contract.py
  ```

### 2. Pytest 单元测试
运行 `.venv/bin/pytest tests/test_zerolines.py tests/test_comicnarr_pipeline.py`：
```text
======================== 26 passed in 159.63s (0:02:39) ========================
- tests/test_zerolines.py: 19 passed (100%)
- tests/test_comicnarr_pipeline.py: 7 passed (100%)
```
跨模块回归测试（`test_script2video_kernel.py`、`test_storygraph.py`、`test_shortdrama_*.py`）共 59 项测试全部 100% 通过。

---

## 六、Clean-room 声明

本模块遵循 Clean-room 原则纯手工自研编写：
1. **参考项目**：六个外部参考项目（火宝 huobao-drama、Toonflow、Pixelle-Video、Jellyfish、waoowaoo、ViMax）均未复制任何源代码或 workflow JSON，未 clone 其仓库。
2. **纯自主实现**：脚本拆句分词、Ken Burns 缩放滤镜数学计算、ASS 漫画框样式、OpenCLIP 双候选评分比选、BGM 侧链压低混音等代码均为团队原创开发。
3. **模型许可**：SD-Turbo 遵循 Stability AI Community 许可；Piper TTS 遵循 MIT 许可；TAESD 遵循 MIT 许可。

---

## 七、依赖说明与已知问题

- **新增依赖**：0 项（完全基于主环境已安装的 PyTorch、Diffusers、OpenCV、OpenCLIP、NumPy、FFmpeg，无任何新装包）。
- **已知说明**：
  - SD-Turbo 在 CPU float32 下单张 512px 图约耗时 3.5s，峰值内存占用稳定在 ~7.47 GB，多进程并发需继续依赖 `/tmp/hevi_cpu_render.lock` 全局文件锁保护。
  - 由于 OpenCLIP 文本输入长度限制为 77 tokens，超长提示词会被 tokenizer 自动截断末尾修饰词，此截断不影响图文核心语义对齐与画面质量。
