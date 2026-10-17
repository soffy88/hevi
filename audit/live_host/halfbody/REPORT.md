# 半身像直播数字人 v1（CPU，零付费）

实测于 ubuntu26，GPU 不可用，全部 CPU。数据见 metrics.json，样片 sample.mp4（1080x1920，31.9s，两轮问答）。

- 链路：观众提问 → ollama llama3.2:3b 逐句流式 → Piper 中文 TTS → 半身底片 + Wav2Lip-GAN-96 ONNX 对口型 → ffmpeg（MP4，或改 `-f flv rtmp://…` 推流 / `-f mpegts udp://` 给 OBS）
- 底片：Pexels 免费可商用视频 8135207（待机）/ 8135208（说话带手势），同一主播同一场景，ping-pong 循环，状态切换 8 帧交叉淡化；每帧带「AI生成」角标和字幕。
- 说话帧渲染 21.2 fps（目标 25，实时系数 0.85）；待机 56.8 fps。
- 首个画面延迟（LLM 首句 + TTS + 该句渲染）：6.8 s / 2.8 s。
- 口型-音量相关 r=0.20（lag -2 帧）；嘴部为 96px 生成，放大后略糊、唇色有接缝。
- 已知问题：CPU 下略慢于实时，需分块流式渲染；3B 模型内容质量一般（会编书名）；嘴部清晰度需 GPU 版 MuseTalk/超分。
- 底片未入库（assets/halfbody，已 gitignore），来源链接在 metrics.json。
