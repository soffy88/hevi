# Hevi 抄作业手册：2天跑通短视频生产

> **目标**：新人可在2天内搭建并运行完整的短视频生产流程
> **对标**：rnskill + 双轨 TTS 标杆

## 第1天：环境搭建与配置（4-6小时）

### 上午：基础环境（2小时）
1. **克隆项目**
   ```bash
   git clone <repo-url>
   cd hevi
   ```

2. **安装依赖**
   ```bash
   pip install -r requirements.txt
   # 或使用 poetry
   poetry install
   ```

3. **配置本地 TTS 模型**
   - 下载 IndexTTS2 模型到 `vendor/indextts2/`
   - 配置 `configs/tts_routing.json`：
     ```json
     {
       "production_provider": "local-indextts2",
       "allowed_providers": ["local-indextts2"],
       "fallback_enabled": false,
       "validation_enabled": true
     }
     ```

### 下午：生产硬门配置（2-4小时）
1. **验证 TTS 隔离**
   ```bash
   python -m hevi.scripts.validate_tts_provider
   ```

2. **设置声线参考文件**
   - 准备 `.wav` 格式的声线参考文件
   - 计算 SHA-256 并填入配置：
     ```bash
     shasum -a 256 your_voice_sample.wav
     ```

3. **测试单个 Skill**
   ```bash
   # 测试 TTS Skill
   python -c "from hevi.skills.tts_skill import tts_skill_execute; import asyncio; asyncio.run(tts_skill_execute(text='Hello World', output_path='test.wav'))"
   ```

## 第2天：完整流程验证（4-6小时）

### 上午：端到端测试（2-3小时）
1. **运行示例**
   ```bash
   cd hevi/examples/end-to-end-demo
   python run_example.py
   ```

2. **验证硬门功能**
   - 确认没有云端 TTS 被使用
   - 验证字幕来自真实音频 ASR
   - 检查 QC 门是否正常工作

### 下午：定制化调整（2-3小时）
1. **准备自己的脚本**
   - 使用标准 handover 格式
   - 包含必要的 frontmatter

2. **测试自定义内容**
   ```bash
   # 使用你的脚本文件
   python run_example.py --script your_script.md
   ```

## 常见问题排查

### Q: TTS 验证失败
A: 检查 `configs/tts_routing.json` 是否设置了正确的本地 provider

### Q: 字幕生成失败
A: 确认 `hevi.analysis.transcribe` 模块正常工作

### Q: 渲染阶段卡住
A: 检查 GPU 资源和相关模型是否正确安装

## 预期产出物清单

每次完整运行应产生：
- ✅ `audio_output.wav` - 音频文件
- ✅ `audio_output.json` - 语音清单  
- ✅ `subtitles.srt` - 字幕文件
- ✅ `rendered_video.mp4` - 成品视频
- ✅ `rendered_video.qc.json` - QC 报告

## 质量标准确认

- [ ] 无静默 fallback（失败时直接报错）
- [ ] 所有关键步骤都有硬门检查
- [ ] 云端 TTS 在生产中被完全隔离
- [ ] 字幕来自真实音频而非估算
- [ ] 成片通过 QC 检查

## 进阶配置选项

### 声线定制
```json
{
  "voice_reference_path": "path/to/your/voice_sample.wav",
  "voice_reference_sha256": "your_calculated_hash_here"
}
```

### 生产参数调优
- `performance_track_tier`: 控制表演细节级别
- `auto_rework_max_rounds`: 自动返工轮数
- `shot_retry_max`: 单镜头重试上限

---

**完成标志**：能够使用自己的脚本输入，生成完整的、通过 QC 的短视频输出。