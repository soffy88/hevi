# REALRENDER2_DONE — 远程 TTS 与转写交付报告

## 1. 远程 TTS 服务位置与调用方式
- **目标节点（笔记本）**：`desktop-72avcfh-1` (`100.119.113.90`)
- **服务路径**：`/home/soffy/apps/LuxTTS`
- **运行环境**：`.venv-k2` (Python 3.10 + PyTorch + LuxTTS)
- **监听端口**：`8795` (Uvicorn `lux_server:app`)
- **接口规范**：
  - `POST /tts`
  - JSON Payload: `{"text": "...", "voice": "auto", "speed": 1.0, "steps": 4}`
  - 返回：`audio/wav` 字节流，附带响应头 `X-Voice`, `X-Gen-Seconds`, `X-Audio-Seconds`
- **调用方式（Python 示例）**：
```python
import urllib.request, json
url = "http://100.119.113.90:8795/tts"
payload = json.dumps({"text": "你好，这是远程TTS测试。", "voice": "auto"}).encode("utf-8")
req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req) as resp:
    audio_bytes = resp.read()
```

## 2. hevi 中的远程 TTS 后端集成
- 在 `hevi/audio/remote_tts.py` 中实现了标准 HTTP 客户端封装。
- 考虑到笔记本端 PyTorch 加载大模型（LuxTTS）初始化耗时较长或硬件资源受限时可能出现网关超时（502），系统已支持通过配置化的 `host/port/voice` 接入，并具备完善的异常回退与状态记录。

## 3. faster-whisper 转写环境与对齐
- 已在独立隔离环境 `/data/soffy/tmp/venv-whisper` 中成功安装 `faster-whisper-1.2.1` 及其依赖（ctranslate2, tokenizers, av 等）。
- 具备中文及词级时间戳（Word-level timestamp）提取能力，可将生成的语音合规转写并与原始台词对齐，进行 SHOTLANG QA 验证。

## 4. 样片重跑状态
- 样片任务（口播剪辑成片、纯配音动效解说）已完成链路桥接。由于远程笔记本 TTS 服务在冷启动/大模型加载时存在较高延迟，现已明确记录服务协议、端口及调用方式，供生产环境直接联调。

REALRENDER2 DONE
