# OMRENDER 任务完成报告

## 做了什么
1. **HyperFrames 样式渲染器接入**:
   - 在 `hevi/providers/hyperframes/provider.py` 中新加了 `hyperframes_styled` 视频提供者。
   - 实现了一个可以接受 `script_lines` 参数并生成对应 `script.md` 供 Lanshu Explainer 消费的渲染管线。
   - 接入了 Lanshu Explainer `story.py`, `sync.sh` 和 `render.sh` 工具，允许按各种风格（例如 `v6-cinematic`, `v8-chalkboard`）渲染。
2. **本地配音和时间戳提取（替代 MiniMax）**:
   - 在 `story.py` 移除了对 MiniMax 的依赖。
   - 采用本地 `piper`（音色 `zh_CN-huayan-medium.onnx`）生成音频。
   - 使用本地 `faster-whisper-large-v3-turbo` 提取词级时间戳，并适配为原引擎要求的数据格式供渲染。
3. **断网资源缓存**:
   - 使用 `sed` 批量替换了各个风格下的 HTML `https://cdn.jsdelivr.net`。
   - 全部指向本地 `hevi/providers/hyperframes/lanshu_assets/node_modules/`，避免渲染器在无网或受限网络下超时。
   - 生成脚本内置了调用 `fonts.py` 下载离线字体。
4. **SVG 骨骼动画**:
   - 创建了 `_render_character_animation_line`，在 `hevi/studio/fulfill.py` 中替代了原来的占位符。
   - 拷贝了 CMU 的 Mocap 数据集并在 `NOTICE` 添加了开源许可来源。
   - 基于 `ink-puppet.js` 构建了纯前端的渲染页面，并直接使用 `hyperframes` CLI 输出动画成品 `character_animation.mp4`。
5. **Blender 工作流 (部分成功/已知卡点)**:
   - 调整了 `hevi/creative/layer4/blender_workflow.py` 的可执行路径，修正了对 `CYCLES` 和 CPU 渲染的语法。
   - 尝试通过 Aliyun Mirror 下载 Linux Portable Blender 到 `/home/soffy/opt/blender`。
   - **卡点**：国内镜像下载百兆大文件过慢（几十KB/s），由于禁止走代理和禁止造假，已启动后台下载但在合理时间内未完成，因此该步骤在 E2E 脚本中目前会抛出 Binary not found。未造假产物。

## 文件清单
- `scripts/om_render_e2e.py` (E2E 测试脚本)
- `hevi/providers/hyperframes/provider.py` (新增 styled 提供者和 font 离线预取)
- `third_party/lanshu_explainer/tools/story.py` (接入 Piper 和 Faster-Whisper)
- `hevi/studio/fulfill.py` (实现 `_render_character_animation_line`)
- `hevi/creative/layer4/blender_workflow.py` (修补了路径和渲染配置)
- `hevi/studio/runtime.py` (接入了 `hyperframes_styled`)
- `NOTICE` (补充了 CMU 数据库引用协议)
- `assets/mocap-clips/` (CMU 动作数据)

## 如何调用
运行 `PYTHONPATH=. .venv/bin/python scripts/om_render_e2e.py` 即可完成全流程的 E2E 验证，输出见 `output/om_render_e2e/`。

## E2E 产物路径
- Hyperframes (v6/v8/v4/v9 风格) mp4 及 jpg: `output/om_render_e2e/hf_*.mp4` (已生成)
- SVG 角色动画 mp4 及 jpg: `output/om_render_e2e/character_animation.mp4` (已生成)
- Blender 渲染产物 mp4 及 jpg: 卡在依赖下载未生成（详情见上方卡点说明）。

## Lint 对比
通过了本地代码检查。
