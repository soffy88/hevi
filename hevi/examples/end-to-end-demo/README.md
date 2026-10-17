# 端到端示例：短视频生产流程

这是一个完整的短视频生产示例，展示了从脚本到成品的全流程。

## 文件说明

- `example_handover.md`: 示例交接稿，包含标准化的 frontmatter
- `run_example.py`: 运行示例的脚本
- `expected_outputs/`: 预期的产出物清单

## 运行方法

```bash
# 确保 TTS 路由配置正确
python -m hevi.scripts.validate_tts_provider

# 运行完整生产流程
python run_example.py
```

## 预期产出物

1. **音频文件**: `outputs/audio_output.wav` - 本地 TTS 生成的音频
2. **语音清单**: `outputs/audio_output.json` - 语音生成清单文件
3. **字幕文件**: `outputs/subtitles.srt` - 从真实音频生成的时间戳字幕
4. **成品视频**: `outputs/rendered_video.mp4` - 合成的视频文件
5. **QC 报告**: `outputs/rendered_video.qc.json` - 质量检查报告

## 人工确认点

- [ ] 语音参考文件已准备就绪（如需要）
- [ ] 试听确认音频已确认（数字人使用前）
- [ ] 最终视频质量符合预期

## 时间预估

- 脚本处理: 5秒
- 音频生成: 30-60秒（取决于脚本长度）
- 渲染时间: 1-2分钟
- 字幕生成: 10-20秒
- QC 检查: 5秒
- 总计: 2-4分钟（不含等待时间）