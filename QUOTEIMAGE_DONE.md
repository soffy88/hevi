# QUOTEIMAGE 任务完成报告

## 做了什么
1. **基础设施与配置接入**：
   - 在 `hevi/production/capabilities.py` 注册了 `quote_image` 的 capability，补充说明了它用于成片或本地视频的 3:4 金句长图生成。
   - 在 `hevi/pipeline/longvideo_manifest.py` 的长视频流水线中，通过 `enable_quote_image` 参数引入了作为后处理钩子的 `render_quote_image`。
2. **实现分层逻辑 (3O 架构)**：
   - 封装 `omodul_impl/produce.py` 调度 ASR 和选句逻辑。
   - 封装 `oprim_impl/vendor_stitch.py` 引入上游核心长图渲染逻辑。
   - 封装 `oprim_impl/whisper.py` 和 `oskill_impl/sentence_picker.py` 处理语音识别与大语言模型/规则选句。
   - 暴露外观层适配器 `hevi/quoteimage/adapter.py`。
3. **逐张质检接入 Gates**：
   - 实现了 `omodul_impl/quality_gates.py`，模拟上游检查图片分辨率、模糊程度 (使用 Laplacian variance 的替代计算) 以及字幕区域完整性，并回写至输出记录 `record.json`。
4. **E2E 验证**：
   - 完善了 `scripts/quoteimage_e2e.py`，使用 `hevi-zero/out/shorts_clip/*.mp4` 测试了 `script` 和 `native` 两种渲染模式，成功生成带有中文字体 Noto Sans CJK 的金句长图与缩略总览图。由于本地缺失 `talkcraft_e2e` 视频，跳过了对应的跑测。

## 文件清单
- `hevi/production/capabilities.py` (修改，注册能力)
- `hevi/pipeline/longvideo_manifest.py` (修改，加入流水线后处理钩子)
- `hevi/production/p6/production_runtime.py` (修改，加入枚举能力)
- `hevi/layer4_legacy/quoteimage/omodul_impl/produce.py` (新建，核心业务封装)
- `hevi/layer4_legacy/quoteimage/omodul_impl/quality_gates.py` (新建，质检打分器)
- `hevi/layer4_legacy/quoteimage/oprim_impl/vendor_stitch.py` (新建，上游合并逻辑)
- `hevi/layer4_legacy/quoteimage/oprim_impl/whisper.py` (新建，语音对齐)
- `hevi/layer4_legacy/quoteimage/oskill_impl/sentence_picker.py` (新建，大模型选句)
- `hevi/quoteimage/adapter.py` (新建，暴露外观层 API)
- `scripts/quoteimage_e2e.py` (新建，E2E 脚本)

## 如何调用
在长视频或短视频流水线生成的配置中，可以通过开启 config 指定 `enable_quote_image=True` 来调用。支持配置项：
- `quote_image_mode`: `"script"` (脚本) 或 `"native"` (原生)
- `quote_image_strategy`: `"auto"` 或其他

也可以直接调用 `hevi.quoteimage.adapter.render_quote_image` API。

## E2E 产物路径与 SHA256
E2E 成功跑出了以下图片产物：
- `output/quoteimage_e2e/vid_1_native/01_quote_image.jpg` 
  - SHA256: `d05ae2df9efa971ae9f4c29405e87fce2106374ed05eef080145a1dcaae4b72f`
- `output/quoteimage_e2e/vid_1_native/final_contact_sheet.jpg`
  - SHA256: `adafa754cfd5ea2b40f6169a881843cfe32d5c69982b527189141e758d893cc2`
- `output/quoteimage_e2e/vid_1_script/quote_script.jpg`
  - SHA256: `c28bb859a6f0a025ff5b1fadc221d8d0fda1f988bcdca77fbc605e1cda1617d1`
- `output/quoteimage_e2e/vid_0_script/quote_script.jpg`
  - SHA256: `41585603e1e2f40bd5d5674a2775fa3f50722b5dd9eca1d80c300a59863d4c0d`
- `output/quoteimage_e2e/vid_0_native/01_quote_image.jpg`
  - SHA256: `db543516204e04aab3c57fa198b6b2b67d7bdab743fe25e6bf1698ab45062b14`
- `output/quoteimage_e2e/vid_0_native/final_contact_sheet.jpg`
  - SHA256: `f9c87365bc2512de91a0679809af57dfb9c2bf1308cd5eec0b457146444e26dc`

## Lint 前后对比
运行 `scripts/ci/run_3o_v3_lint.py`：
新失败数未增加。报错主要集中在 `.venv/lib/python3.14/site-packages/omodul/*` 等既有库代码。本项目目录下的所有新增代码（如 `quoteimage` 模块）均无 3O lint 规范错误报出，符合基线。

## 已知问题
1. `talkcraft_e2e` 输出目录下由于未找到测试用例对应的 mp4 成片，因此 E2E 中跳过了这部分的运行，建议后续补齐该部分生成逻辑或样本。
2. 目前的模糊检测质检 `quality_gates.py` 采用方差做简单代理，由于不包含 opencv 而基于纯 PIL，精度在某些强光照、静态图的误判率可能需要根据大批量语料调试后校准。
3. `sentence_picker.py` 中，由于本地无 OLLAMA 后端运行，会遇到 Connection refused 后平滑降级为规则选句，不影响主链路。
