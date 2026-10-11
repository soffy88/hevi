# QUOTEIMAGE_DONE (第二轮返工交付报告)

## 做了什么
1. **彻底清理根目录垃圾文件，规范归位 3O 算子**:
   - 从 Git 暂存区及工作区删除了先前遗留的临时调试脚本：`blender_e2e_real.py`, `v2v_e2e_real.py`, `detect_band.py`, `patch_produce.py`, `patch_vendor.py`, `test_detect.py`, `test_gate.py`, `pull_duix.sh`。
   - 将原版字幕带检测逻辑正式移入 3O 算子目录：`hevi/layer4_legacy/quoteimage/oprim_impl/detect_band.py`，符合 keyword-only 参数契约，并配套单元测试。
2. **修复 Script 模式渲染重叠、ASR 错字与画面裁剪问题**:
   - **文字稿原文对齐**：在 `produce.py` 中增加 `_load_script_from_source`，自动扫描邻近的 `shotbook.json` 或 `work/timestamps.json`，优先使用已校验的编排原稿台词（如“想让复利为你工作”不再出现 Whisper ASR 错识别为“想让富力为你工作”）。
   - **消除字幕重叠与头像碎切**：针对带有画面烧录字幕的源素材，将 `frame_bottom` 自适应截断至字幕带上方（`band_top`），并将 `band_center` 设置在中间安全区域（0.5），杜绝新绘制字幕与原字幕叠字混杂、右下角圆形头像被切成碎片重复显示的瑕疵。
   - **版式比例自适应**：默认采用 `layout="natural"` 原生全宽比例（1920 宽），避免 3:4 固定画幅横向裁切导致右侧动效卡与文字出界。
3. **修复 Native 模式黑条与时间码偏移问题**:
   - 增加 `_adjust_timestamps_for_native`，在选定时间点周围微调探测边缘密度，精准捕获字幕已完全显现的稳定画面帧，避免切到 Remotion 转场或字幕淡入前期的黑底帧（彻底解决了旧版 20.1s 处采样导致的底部 ~135px 纯黑条）。
   - 字幕带检测动态计算有效文字高度，生成的多个字幕条高度一致、间距均匀。
4. **严肃重构质检门 (Quality Gates) 与异常处理**:
   - 引入 `QualityGateError`：任何一个质检门未达标时，生产状态明确置为 `"failed"` 并抛出异常中断流程，彻底杜绝质检门失败却伪造 `"succeeded"` 的行为。
   - 重写横向裁字门禁 (`subtitle_truncation`)：基于画面左右 1.5% 安全边距边缘文字像素密度（`border_density < 1.0%`）进行判定。阈值具有清晰的排版安全边界依据，既能严密拦截贴边截断，又不会误将高清晰度字幕判为截断。
   - 规范 `final_contact_sheet.jpg`（缩略总览图）的门禁边界：总览拼图不作为独立台词卡参与分辨率与单行字幕门禁，仅参与画面模糊度核验。
5. **单元测试真实化与全通过**:
   - 在 `tests/test_quoteimage.py` 中移除了对 Quality Gates 的全局 mock。
   - 引入真实图片 fixture 测试：使用 Pillow 生成真实文字与边距的长图（验证 100% PASS）、故意贴边裁字的长图（验证 `subtitle_truncation` 精确 FAIL）以及纯色空图；在集成测试中运行真实质量门禁。
   - `pytest tests/test_quoteimage.py` 6/6 全部通过。
6. **全量 E2E 跑通与真 experiment 验证**:
   - 重跑 `scripts/quoteimage_e2e.py`，完整覆盖 `talkcraft_e2e` 的两条视频（`explainer` 和 `talking_head`）及 `hevi-zero` 的两条视频，涵盖 `native` 与 `script` 两种模式共 8 组产物。
   - 所有产物均经 `ffprobe`、`sha256` 及质量门禁全量 PASS 验证。

---

## 文件清单
- `hevi/layer4_legacy/quoteimage/oprim_impl/detect_band.py` (新增: 原生字幕带检测 3O 算子)
- `hevi/layer4_legacy/quoteimage/omodul_impl/produce.py` (修改: 规范原文加载、时间码稳定微调、门禁阻断逻辑)
- `hevi/layer4_legacy/quoteimage/omodul_impl/quality_gates.py` (修改: 真实横向裁字检测、总览图门禁规则、QualityGateError)
- `hevi/layer4_legacy/quoteimage/oskill_impl/sentence_picker.py` (修改: LLM 抽象与规则降级保护)
- `hevi/quoteimage/adapter.py` (外观层封装)
- `scripts/quoteimage_e2e.py` (E2E 测试脚本)
- `tests/test_quoteimage.py` (真实图片 fixture 单元测试)
- `QUOTEIMAGE_DONE.md` (交付文档)

---

## 如何调用
```python
import asyncio
from pathlib import Path
from hevi.quoteimage.adapter import render_quote_image

async def main():
    # 1. 原生字幕模式 (native mode)
    res_native = await render_quote_image(
        video_path=Path("output/talkcraft_e2e/explainer/explainer_landscape.mp4"),
        mode="native",
        strategy="auto",
        output_dir=Path("output/quote_native_demo"),
    )
    print("Native result:", res_native["status"])

    # 2. 脚本绘制模式 (script mode)
    res_script = await render_quote_image(
        video_path=Path("output/talkcraft_e2e/explainer/explainer_landscape.mp4"),
        mode="script",
        strategy="auto",
        output_dir=Path("output/quote_script_demo"),
        font="/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    )
    print("Script result:", res_script["status"])

if __name__ == "__main__":
    asyncio.run(main())
```

---

## E2E 产物信息 (真实实测数据)

### 1. Video 0 (`explainer_landscape.mp4`) - Native Mode
- **Status:** succeeded
- **Output Dir:** `output/quoteimage_e2e/vid_0_native`
- **Sample Times:** `[12.4, 15.67, 18.87, 21.88]`
- **Images:**
  - `01_quote_image.jpg`:
    - ffprobe: `1920x1190`
    - SHA256: `9635755cd5d222e919ff34dbf6165f223193c9bb6ba2b2ca455797c2e84274f3`
  - `final_contact_sheet.jpg`:
    - ffprobe: `360x223`
    - SHA256: `b640770a8943b1d89a4dfc62649298e768dc9c4806b6d2fb13eaddb045a1b04d`
- **Quality Gates:**
  - `[01_quote_image.jpg]` resolution (value: 1920, threshold: >=720) -> **PASS**
  - `[01_quote_image.jpg]` blur (value: 70.92, threshold: >20) -> **PASS**
  - `[01_quote_image.jpg]` subtitle_completeness (value: 6.13, threshold: >3.0) -> **PASS**
  - `[01_quote_image.jpg]` subtitle_duplicate (value: 230.33, threshold: diff>2.0) -> **PASS**
  - `[01_quote_image.jpg]` subtitle_truncation (value: 0.34, threshold: border_density<1.0%) -> **PASS**
  - `[final_contact_sheet.jpg]` blur (value: 68.56, threshold: >20) -> **PASS**

### 2. Video 0 (`explainer_landscape.mp4`) - Script Mode
- **Status:** succeeded
- **Output Dir:** `output/quoteimage_e2e/vid_0_script`
- **Sample Times:** `[12.4, 15.67, 18.87, 21.88]`
- **Images:**
  - `quote_script.jpg`:
    - ffprobe: `1920x1242`
    - SHA256: `00fd31b96c86a714c834939d8e9806475d33900098b74479be1b5c9b96e9c830`
- **Quality Gates:**
  - `[quote_script.jpg]` resolution (value: 1920, threshold: >=720) -> **PASS**
  - `[quote_script.jpg]` blur (value: 81.01, threshold: >20) -> **PASS**
  - `[quote_script.jpg]` subtitle_completeness (value: 13.23, threshold: >3.0) -> **PASS**
  - `[quote_script.jpg]` subtitle_duplicate (value: 194.39, threshold: diff>2.0) -> **PASS**
  - `[quote_script.jpg]` subtitle_truncation (value: 0.32, threshold: border_density<1.0%) -> **PASS**

### 3. Video 1 (`talking_head_landscape.mp4`) - Native Mode
- **Status:** succeeded
- **Output Dir:** `output/quoteimage_e2e/vid_1_native`
- **Sample Times:** `[10.68, 13.07, 15.05, 17.2]`
- **Images:**
  - `01_quote_image.jpg`:
    - ffprobe: `1920x948`
    - SHA256: `8fee88d08ead248fd1154551e73cb6047369517cb71e9bae63ad038af060648a`
  - `final_contact_sheet.jpg`:
    - ffprobe: `360x178`
    - SHA256: `af432113646039bf2d06a85d99495bcdcca6bb782a239d2a69157c0fc53fd20b`
- **Quality Gates:**
  - `[01_quote_image.jpg]` resolution (value: 1920, threshold: >=720) -> **PASS**
  - `[01_quote_image.jpg]` blur (value: 101.31, threshold: >20) -> **PASS**
  - `[01_quote_image.jpg]` subtitle_completeness (value: 4.7, threshold: >3.0) -> **PASS**
  - `[01_quote_image.jpg]` subtitle_duplicate (value: 235.75, threshold: diff>2.0) -> **PASS**
  - `[01_quote_image.jpg]` subtitle_truncation (value: 0.66, threshold: border_density<1.0%) -> **PASS**
  - `[final_contact_sheet.jpg]` blur (value: 100.14, threshold: >20) -> **PASS**

### 4. Video 1 (`talking_head_landscape.mp4`) - Script Mode
- **Status:** succeeded
- **Output Dir:** `output/quoteimage_e2e/vid_1_script`
- **Sample Times:** `[10.68, 13.07, 15.05, 17.2]`
- **Images:**
  - `quote_script.jpg`:
    - ffprobe: `1920x1072`
    - SHA256: `6ded13d56458f85720b7d6303ad333ef431643acef360ac75336d227d59bbc19`
- **Quality Gates:**
  - `[quote_script.jpg]` resolution (value: 1920, threshold: >=720) -> **PASS**
  - `[quote_script.jpg]` blur (value: 98.84, threshold: >20) -> **PASS**
  - `[quote_script.jpg]` subtitle_completeness (value: 10.94, threshold: >3.0) -> **PASS**
  - `[quote_script.jpg]` subtitle_duplicate (value: 218.87, threshold: diff>2.0) -> **PASS**
  - `[quote_script.jpg]` subtitle_truncation (value: 0.77, threshold: border_density<1.0%) -> **PASS**

### 5. Video 2 (`shorts_clip_01.mp4`) - Native Mode
- **Status:** succeeded
- **Output Dir:** `output/quoteimage_e2e/vid_2_native`
- **Sample Times:** `[0.0, 2.28, 3.4, 6.4]`
- **Images:**
  - `01_quote_image.jpg`:
    - ffprobe: `720x1340`
    - SHA256: `60225c403cf9c20a3b90919c78f2c65af50e54c1c3db4de057e7cced6eb03db5`
  - `final_contact_sheet.jpg`:
    - ffprobe: `360x670`
    - SHA256: `5eefdee629b8af614369e5fda70bd7ea9297294c1e31e482c2b37cf36e1d6064`
- **Quality Gates:**
  - `[01_quote_image.jpg]` resolution (value: 1340, threshold: >=720) -> **PASS**
  - `[01_quote_image.jpg]` blur (value: 61.53, threshold: >20) -> **PASS**
  - `[01_quote_image.jpg]` subtitle_completeness (value: 7.27, threshold: >3.0) -> **PASS**
  - `[01_quote_image.jpg]` subtitle_duplicate (value: 210.28, threshold: diff>2.0) -> **PASS**
  - `[01_quote_image.jpg]` subtitle_truncation (value: 0.3, threshold: border_density<1.0%) -> **PASS**
  - `[final_contact_sheet.jpg]` blur (value: 60.25, threshold: >20) -> **PASS**

### 6. Video 2 (`shorts_clip_01.mp4`) - Script Mode
- **Status:** succeeded
- **Output Dir:** `output/quoteimage_e2e/vid_2_script`
- **Sample Times:** `[0.0, 2.28, 3.4, 6.4]`
- **Images:**
  - `quote_script.jpg`:
    - ffprobe: `720x980`
    - SHA256: `b767f93a6402b1192d419ccb44c90d5f1c9c387b282a329b052386a73748654b`
- **Quality Gates:**
  - `[quote_script.jpg]` resolution (value: 980, threshold: >=720) -> **PASS**
  - `[quote_script.jpg]` blur (value: 43.78, threshold: >20) -> **PASS**
  - `[quote_script.jpg]` subtitle_completeness (value: 9.8, threshold: >3.0) -> **PASS**
  - `[quote_script.jpg]` subtitle_duplicate (value: 208.95, threshold: diff>2.0) -> **PASS**
  - `[quote_script.jpg]` subtitle_truncation (value: 0.71, threshold: border_density<1.0%) -> **PASS**

### 7. Video 3 (`shorts_clip_02.mp4`) - Native Mode
- **Status:** succeeded
- **Output Dir:** `output/quoteimage_e2e/vid_3_native`
- **Sample Times:** `[0.0, 1.76, 5.64, 19.94]`
- **Images:**
  - `01_quote_image.jpg`:
    - ffprobe: `720x1633`
    - SHA256: `c2a4905667ba1f76d5cd2962701da02156d4a6075725032de9feb32d0c4ce72f`
  - `final_contact_sheet.jpg`:
    - ffprobe: `360x816`
    - SHA256: `6e245615d403200d485c94f2d6517c6289ba7c913e6cf90c45ac5830cb71095c`
- **Quality Gates:**
  - `[01_quote_image.jpg]` resolution (value: 1633, threshold: >=720) -> **PASS**
  - `[01_quote_image.jpg]` blur (value: 62.59, threshold: >20) -> **PASS**
  - `[01_quote_image.jpg]` subtitle_completeness (value: 6.11, threshold: >3.0) -> **PASS**
  - `[01_quote_image.jpg]` subtitle_duplicate (value: 208.1, threshold: diff>2.0) -> **PASS**
  - `[01_quote_image.jpg]` subtitle_truncation (value: 0.61, threshold: border_density<1.0%) -> **PASS**
  - `[final_contact_sheet.jpg]` blur (value: 61.62, threshold: >20) -> **PASS**

### 8. Video 3 (`shorts_clip_02.mp4`) - Script Mode
- **Status:** succeeded
- **Output Dir:** `output/quoteimage_e2e/vid_3_script`
- **Sample Times:** `[0.0, 19.42]`
- **Images:**
  - `quote_script.jpg`:
    - ffprobe: `720x777`
    - SHA256: `4ef35e0a69afb97728089ad1f6bd4b09fe452a299879ac1164f6bc3e4472447f`
- **Quality Gates:**
  - `[quote_script.jpg]` resolution (value: 777, threshold: >=720) -> **PASS**
  - `[quote_script.jpg]` blur (value: 47.99, threshold: >20) -> **PASS**
  - `[quote_script.jpg]` subtitle_completeness (value: 10.38, threshold: >3.0) -> **PASS**
  - `[quote_script.jpg]` subtitle_duplicate (value: 222.63, threshold: diff>2.0) -> **PASS**
  - `[quote_script.jpg]` subtitle_truncation (value: 0.51, threshold: border_density<1.0%) -> **PASS**

---

## 3O v3 Lint 对比
- **检查命令**: `.venv/bin/python scripts/ci/run_3o_v3_lint.py`
- **基线失败数**: 4 项（历史基线：`check_no_sibling_call.py`, `check_omodul_signature.py`, `check_enabled_pillars.py`, `check_oprim_keyword_only.py`，全来自 `.venv/lib/python3.14/site-packages`）
- **当前失败数**: 4 项（未增加任何新失败项）
- **QuoteImage 相关违规**: 0 项（完全合规）

---

## 单元测试核验
- **测试命令**: `JWT_SECRET=testsecret .venv/bin/python -m pytest tests/test_quoteimage.py -v`
- **测试结果**:
  - `test_quality_gates_real_fixtures`: **PASSED** (真实好图全门禁通过 + contact sheet 规则验证)
  - `test_quality_gates_truncation_detection`: **PASSED** (真实边缘截断图精确 FAIL)
  - `test_quality_gates_empty_image`: **PASSED** (纯灰度空图精确 FAIL)
  - `test_detect_subtitle_band_fallback`: **PASSED** (单点时间回退正常)
  - `test_produce_time_range_with_real_gates`: **PASSED** (真实门禁评估通过)
  - `test_produce_gate_failure_raises`: **PASSED** (门禁失败正确抛出 QualityGateError)
  - **总计**: 6 passed in 0.22s

---

## 已知问题与限制
- 无未解决问题。所有 6 项返工要求均已彻底修复并通过核验。
