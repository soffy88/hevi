# COMICNARR 交付验收报告

任务名：`COMICNARR`  
工作区：`/data/soffy/projects/hevi-comicnarr`  
分支：`feat/comicnarr-3o`  
基线 Commit：`98e216af`  
完成时间：2026-10-12  

---

## 一、做了什么

根据 `COMICNARR_TASK.md` 与返工要求 `COMICNARR_FIX.md`，本项目在零成本 CPU 环境下实现了 Pixelle 思路的“漫画解说”流水线，作为 Hevi 架构下的第 12 条零成本产线（`comic_narration`）。

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
   - **主题/文本输入 → 脚本规划（`script_planner`）**：自动切分或扩写为 6–14 句解说脚本；支持本地免费通道（Omniroute `:20128`），并配有高质量确定性规则兜底。
   - **主角视觉一致性与提示词翻译（`prompt_builder`）**：提取主角外貌固定 tokens（如橘猫特征、书生汉服特征），拼接画面描述中英翻译与风格模板 tokens；具体道具/动作前置强化（diffusers 原生不解析 `(x:1.3)` 权重语法，故用前置+重复关键词），主角 token 降为次要。
   - **双候选择优出图**：每句采用固定 seed 基数生成 2 张候选，经 OpenCLIP 评分择优入选，败选图保留于 `frames/`。
   - **TTS 解说**：默认调用本地 Piper TTS（`zh_CN-huayan-medium.onnx`），按内容哈希缓存断点续跑。
   - **BGM 伴奏与侧链 Ducking**：复用 hevi 的 `write_bgm` 与 `mix`，自动压低音乐至解说下方（-22 dB ducking）。
   - **动态 Ken Burns 运镜**：每张图预先放大 1.25 倍以防糊边，推/拉/左移/右移交替运镜，25fps 输出 1080×1920 高清片段。
   - **字幕烧录**：支持常规高对比度底部字幕（ASS/SRT）及漫画对白框（bubble）样式；换行算法避头（`。，！？、；：」』`不能落在行首）。
   - **成片与实测门禁**：最终导出 MP4，实时运行 ffprobe、volumedetect、相邻帧运动差测量，生成 6 帧 contact sheet 与 sha256 签名。

4. **风格模板（共享预设）**：
   - 共享预设 `hevi/layer4_legacy/keyframe/oprim_impl/style_presets.py`（`guofeng_anime` 为默认），`comic_color`/`manga_bw`/`guofeng_anime` 三模板统一管理。
   - `comic_color`：彩色扁平美漫风，明快 BGM，底部清晰字幕。
   - `manga_bw`：黑白日漫风（真实灰度+网点后处理），温润古风 BGM，漫画对白框。
   - `guofeng_anime`：国风动漫，非写实默认。

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
- tests/test_comicnarr_pipeline.py                         # 快速单元测试用例 (12 项用例)
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

## 四、E2E 真实出片验收与实测报告（2026-10-12 重出片）

运行命令（长任务用 `nohup setsid` 独立启动并写日志，sleep 轮询直到产物生成）：
```bash
nohup setsid .venv/bin/python scripts/e2e/comicnarr_e2e.py > e2e.log 2>&1 &
```

**重要事实声明**：本次三条成片均为 `llm_channel=deterministic_rule_fallback`。本机 Omniroute 免费 LLM 通道（`http://127.0.0.1:20128`）探测不可达——`curl` 返回 HTTP 000，`probe_free_llm()` 实测 `URLError: [Errno 111] Connection refused`。因此脚本规划走高质量确定性规则兜底（预置模板），非 LLM 生成。

### 汇总实测矩阵
| 故事用例 | 风格模板 | 实测时长 | 分辨率/帧率 | 音频响度 | 镜头数 | 关键帧互斥 | QA 判定 |
|---|---|---|---|---|---|---|---|
| **Story 1: 猫咪推杯子** | `comic_color` | **66.02s** | 1080×1920 @ 25fps | **-19.0 dB** | 11 | 全部互不相同 | **PASS** |
| **Story 2: 聊斋·促织** | `manga_bw` | **60.77s** | 1080×1920 @ 25fps | **-19.9 dB** | 11 | 全部互不相同 | **PASS** |
| **Story 3: 三国·草船借箭** | `guofeng_anime` | **60.42s** | 1080×1920 @ 25fps | **-19.4 dB** | 12 | 全部互不相同 | **PASS** |

### 产物详细路径与指标

#### 1. Story 1: `output/comicnarr_e2e/story1_cat_knock/`
- **成片 MP4**：`output/comicnarr_e2e/story1_cat_knock/final.mp4` (大小: 11,587,547 字节)
  - SHA256: `76ec105aa1d12576a13014ab47a82003...`
  - 编码：H.264 / AAC 立体声 44100Hz
  - 实测时长：66.02 秒（严格在 45–75 秒要求内）
- **Contact Sheet**：`output/comicnarr_e2e/story1_cat_knock/contact_sheet.jpg`
- **关键帧**：`output/comicnarr_e2e/story1_cat_knock/frames/`（含胜选关键帧与落选候选帧，sha256 互不相同）
- **字幕文件**：`output/comicnarr_e2e/story1_cat_knock/subtitles.srt`、`subtitles.ass`
- **脚本数据**：`output/comicnarr_e2e/story1_cat_knock/script.json`
- **实测 QA**：`output/comicnarr_e2e/story1_cat_knock/qa.json`（mean_volume: -19.0 dB，within-shot motion: 39.25，OCR 相似度 1.0/1.0）
- **性能记录**：`output/comicnarr_e2e/story1_cat_knock/record.json`（生成总耗时: 254.7s）

#### 2. Story 2: `output/comicnarr_e2e/story2_cuozhi_manga/`
- **成片 MP4**：`output/comicnarr_e2e/story2_cuozhi_manga/final.mp4` (大小: 16,011,879 字节)
  - SHA256: `89488cc1558d233a6331e40d0d4afe53...`
  - 编码：H.264 / AAC 立体声 44100Hz
  - 实测时长：60.77 秒（严格在 45–75 秒要求内）
- **Contact Sheet**：`output/comicnarr_e2e/story2_cuozhi_manga/contact_sheet.jpg`
- **关键帧**：`output/comicnarr_e2e/story2_cuozhi_manga/frames/`（黑白漫画胜选与落选图，sha256 互不相同）
- **字幕文件**：`output/comicnarr_e2e/story2_cuozhi_manga/subtitles.srt`、`subtitles.ass`
- **脚本数据**：`output/comicnarr_e2e/story2_cuozhi_manga/script.json`
- **实测 QA**：`output/comicnarr_e2e/story2_cuozhi_manga/qa.json`（mean_volume: -19.9 dB，within-shot motion: 62.1，OCR 相似度 0.9804/0.9982）
- **性能记录**：`output/comicnarr_e2e/story2_cuozhi_manga/record.json`（生成总耗时: 380.94s）

#### 3. Story 3: `output/comicnarr_e2e/story3_sanguo_guofeng/`
- **成片 MP4**：`output/comicnarr_e2e/story3_sanguo_guofeng/final.mp4` (大小: 9,726,308 字节)
  - SHA256: `6aa1dcb1bfcf25100b871758781627f7...`
  - 编码：H.264 / AAC 立体声 44100Hz
  - 实测时长：60.42 秒（严格在 45–75 秒要求内）
- **Contact Sheet**：`output/comicnarr_e2e/story3_sanguo_guofeng/contact_sheet.jpg`
- **关键帧**：`output/comicnarr_e2e/story3_sanguo_guofeng/frames/`（国风动漫胜选与落选图，sha256 互不相同）
- **字幕文件**：`output/comicnarr_e2e/story3_sanguo_guofeng/subtitles.srt`、`subtitles.ass`
- **脚本数据**：`output/comicnarr_e2e/story3_sanguo_guofeng/script.json`
- **实测 QA**：`output/comicnarr_e2e/story3_sanguo_guofeng/qa.json`（mean_volume: -19.4 dB，within-shot motion: 23.94，OCR 相似度 0.9565/0.9943）
- **性能记录**：`output/comicnarr_e2e/story3_sanguo_guofeng/record.json`（生成总耗时: 266.86s）

### 文本完整性验证（实测）
- SRT 拼接（去掉换行）== 规则兜底脚本全文：Story1/2/3 均逐字匹配。
- 成片/SRT 中不存在原文没有的「。」（逗号处不硬拆、不补句号）。
- ASS 换行无行首孤立标点（避头标点 `。，！？、；：」』` 不会落在行首）。
- 三条成片均为 `deterministic_rule_fallback` 通道（Omniroute 不可达）。

---

## 五、Lint 与单元测试前后对比

### 1. 3O v3 Lint 对比
运行 `.venv/bin/python scripts/ci/run_3o_v3_lint.py`：
- **开工基线**：4 项 failure（全部源自软链主环境 `.venv/lib/python3.14/site-packages` 遗留 debt，本地 0 failure）。
- **完工现状**：4 项 failure（完全一致，本地代码 0 违规，未引入任何新失败）。
  ```text
  [FAIL] check_no_sibling_call.py    (site-packages baseline)
  [FAIL] check_omodul_signature.py   (site-packages baseline)
  [FAIL] check_enabled_pillars.py    (site-packages baseline)
  [PASS] check_flat_namespace.py
  [PASS] check_no_project_prefix.py
  [FAIL] check_oprim_keyword_only.py (site-packages baseline)
  [PASS] check_obase_no_reverse_dep.py
  [PASS] check_oservi_injection.py
  [PASS] check_async_contract.py
  ```
- 实测：`grep -E "hevi/"` 在 4 个失败检查的输出中命中数为 0，即全部失败均来自 `.venv/lib/python3.14/site-packages` 遗留 debt，本地 `hevi/` 代码 0 违规。

### 2. Pytest 单元测试
运行 `.venv/bin/pytest tests/test_zerolines.py tests/test_comicnarr_pipeline.py`：
```text
======================== 31 passed in 43.59s ========================
- tests/test_comicnarr_pipeline.py: 12 passed (100%)
- tests/test_zerolines.py: 19 passed (100%)
```

---

## 六、返工核对（COMICNARR_FIX.md 逐条）

1. **story1 结尾两句整句丢失** — 已修：`_split_text_to_sentences` 按句号切分（不再在逗号处硬拆），`_pack_scenes_under_limit` 在超过 `max_scenes` 时合并镜头而非丢句。实测 Story1 SRT 11 句全文（含结尾两句）在成片中逐字存在。
2. **逗号处硬拆再补「。」造成半句** — 已修：拆句函数不在逗号处切开，`_finalize_sentence` 已删除；输出 narration 中不存在原文没有的「。」。单测覆盖 texts 模式与规则兜底模式。
3. **换行孤立标点** — 已修：`wrap_subtitle_text` 避头算法（`。，！？、；：」』`不能落在行首，至少带前一个字一起换行）。单测覆盖。
4. **story1 画面与句子不符** — 已修：`prompt_builder` 把道具/动作前置并重复强化（diffusers 原生不解析 `(x:1.3)` 权重语法），中景/全景构图词（medium shot, full body, on desk）避免一律特写猫脸；主角 token 降为次要。重出 Story1 后逐镜头 CLIP 评分 0.932–1.000。
5. **COMICNARR_DONE.md 未更新/不实** — 已修：本报告如实写明 `llm_channel=deterministic_rule_fallback`（Omniroute :20128 探测不可达，curl 返回 000）、共享预设路径、每条成片时长/镜头数/sha256、已知局限。

---

## 七、Clean-room 声明

本模块遵循 Clean-room 原则纯手工自研编写：
1. **参考项目**：六个外部参考项目（火宝 huobao-drama、Toonflow、Pixelle-Video、Jellyfish、waoowaoo、ViMax）均未复制任何源代码或 workflow JSON，未 clone 其仓库。
2. **纯自主实现**：脚本拆句分词、Ken Burns 缩放滤镜数学计算、ASS 漫画框样式、OpenCLIP 双候选评分比选、BGM 侧链压低混音等代码均为团队原创开发。
3. **模型许可**：SD-Turbo 遵循 Stability AI Community 许可；Piper TTS 遵循 MIT 许可；TAESD 遵循 MIT 许可。

---

## 八、依赖说明与已知问题

- **新增依赖**：0 项（完全基于主环境已安装的 PyTorch、Diffusers、OpenCV、OpenCLIP、NumPy、FFmpeg，无任何新装包）。
- **已知说明**：
  - SD-Turbo 在 CPU float32 下单张 512px 图约耗时 3.5s，峰值内存占用稳定在 ~7.5 GB，多进程并发需继续依赖 `/tmp/hevi_cpu_render.lock` 全局文件锁保护。
  - 由于 OpenCLIP 文本输入长度限制为 77 tokens，超长提示词会被 tokenizer 自动截断末尾修饰词，此截断不影响图文核心语义对齐与画面质量。
  - 本机 Omniroute 免费 LLM 通道（:20128）当前不可达（curl 000 / Connection refused），故 E2E 三条成片均走确定性规则兜底通道；待通道恢复后可自动切换 LLM 生成。
