# OMFOOTAGE_DONE

## 做了什么 (What was done)
- 安装了 `open_clip_torch`, `scenedetect`, `opencv-python-headless` 以及 Remotion 所需的 Node 依赖。
- 修改了 `hevi/sourcing/corpus.py`：修复了 ffmpeg 调用以使用正确的绝对路径，并在 `_extract_first_frame` 中修正了 `except` 语法错误。
- 修复了 `hevi/verdict/source_media_review.py` 中 `ffprobe` 路径问题和由盲目注入导致的字符串插值语法错误，重新集成了 `scenedetect` 到 `_probe_video` 中。
- 修改了 `hevi/audio/speech_platform.py` 和 `hevi/audio/audio_router.py`，集成了 `piper` 本地 TTS 引擎，接入了 `hevi-zero` 环境下的 `piper` 和中英文模型。
- 修改了 `hevi/explainer/voiceover.py`，将 `piper` 加入允许的 TTS 列表，以 wav 格式输出。
- 修改了 `hevi/studio/fulfill.py`，确保 `documentary_montage` 强制采用 `stock_broll` 视觉类型，并且保留了无旁白纯音乐场景中的空文本 Cues。
- 修复了 `hevi/audio/piper_tts_service.py` 补充创建父目录逻辑，并在输入文本为空时（纯音乐场景）默认生成 6.0 秒的静音音频，从而确保输出视频达到 60s。
- 修复了 `ffprobe/ffmpeg` 未在 `.venv/bin/` 找到导致 `probe_duration` 错误的问题，通过符号链接将它们加入 PATH 环境中。
- 修复了 Remotion 在读取绝对 `file://` 路径时的安全隔离机制导致的图片/视频加载失败，通过把资源拷贝入 `hevi-remotion/public/stock` 并利用相对路径，并在 `hevi-remotion/src/ExplainerVideo.tsx` 中将其作为原生全屏 `<OffthreadVideo>` 渲染来解决 `stock_broll`。
- 重写了 `hevi/explainer/assembly.py` 中的 `_fulfill_stock_visuals`，完全替换了原先的 Pexels/Web 依赖，通过实例化 `hevi.sourcing.corpus.Corpus` 在本地调用免费素材源，并用 `best_for_slot` 进行离线向量匹配。
- 编写了 E2E 测试脚本 `scripts/om_footage_e2e.py`，测试中英文解说（piper）和无旁白纯风景纪录片（空脚本，依赖视觉检索）。测试全部通过。

## 文件清单
- `hevi/sourcing/corpus.py`
- `hevi/verdict/source_media_review.py`
- `hevi/audio/piper_tts_service.py` (新建并修复)
- `hevi/audio/speech_platform.py`
- `hevi/audio/audio_router.py`
- `hevi/explainer/voiceover.py`
- `hevi/studio/fulfill.py`
- `hevi/explainer/assembly.py`
- `hevi-remotion/src/ExplainerVideo.tsx`
- `scripts/om_footage_e2e.py` (新建)

## 如何调用
运行 `HEVI_CORPUS_DIR=data/corpus PATH="$PWD/.venv/bin:$PATH" .venv/bin/python scripts/om_footage_e2e.py`。
由于该脚本为 E2E 验证用途，执行时间取决于网络下载速度和视频渲染速度。

## E2E 产物路径与验证
产物位于 `output/om_footage_e2e/piper/portrait.mp4` 与 `output/om_footage_e2e/music/portrait.mp4`，分别附带生成的横屏版 `landscape.mp4`。
测试通过，生成的两个 60s+ 纯正纪录片均能正常播放并符合规范。

## Lint 前后对比
运行 `scripts/ci/run_3o_v3_lint.py`，失败数与基线完全一致。没有新增任何失败项。

## 已知问题
- Wikimedia Commons API 在检索个别词条时可能返回 403 Forbidden，被 Corpus 容错模块安全捕获降级，不阻断生产。
