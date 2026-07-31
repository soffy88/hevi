# Hevi 开源技能文档

> **目标**：提供清晰的技能接口文档，便于社区贡献和使用

## 核心技能接口规范

### 通用技能接口

所有 Hevi 技能应遵循以下接口规范：

```python
class SkillName:
    async def execute(self, *, param1: type, param2: type, ...) -> Dict[str, Any]:
        """
        技能执行函数
        
        Args:
            param1: 参数说明
            param2: 参数说明
            
        Returns:
            Dictionary with standard structure:
            {
                "status": "success|failed",
                "data": {...},  # 技能特定数据
                "metadata": {...}  # 可选元数据
            }
        """
        pass
```

### 标准返回格式

```json
{
  "status": "success",
  "skill_name": "skill_identifier",
  "execution_time": 1234.56,
  "inputs": {...},
  "outputs": {...},
  "metadata": {
    "version": "1.0",
    "provider": "local",
    "quality_score": 0.85
  }
}
```

## 已开源技能列表

### 1. TTS 技能 (`tts-skill`)
- **功能**: 本地 TTS 生成
- **输入**: 文本内容，语音参考，输出路径
- **输出**: 音频文件 + 语音清单
- **质量标准**: 必须使用本地模型，拒绝云端回退

### 2. 交接稿生成 (`script-to-handover`)
- **功能**: 将原始内容转换为标准交接格式
- **输入**: 原始脚本/内容
- **输出**: 带 frontmatter 的交接稿
- **质量标准**: 必须包含生产要求字段

### 3. 生产指挥 (`production-director`)
- **功能**: 编排完整生产流程
- **输入**: 交接稿文件
- **输出**: 完整视频产品
- **质量标准**: 所有阶段必须通过质量检查

### 4. 音频字幕生成 (`caption-from-audio`)
- **功能**: 从真实音频生成精确字幕
- **输入**: 音频文件
- **输出**: 带时间戳的字幕文件
- **质量标准**: 必须来自真实 ASR，非估算

### 5. 终检 (`final-qc`)
- **功能**: 综合质量检查
- **输入**: 视频、音频、字幕文件
- **输出**: QC 报告和通过/失败状态
- **质量标准**: 不通过则阻断流程

## 贡献指南

### 添加新技能的步骤

1. 在 `hevi/skills/` 下创建新目录
2. 实现标准接口
3. 添加单元测试
4. 更新此文档
5. 提交 PR

### 代码质量要求

- 所有网络调用必须异步
- 错误处理必须明确，不可静默失败
- 日志记录必须详细
- 类型注解必须完整

## API 参考

### TTS 技能
```python
result = await tts_skill_execute(
    text="Hello world",
    voice_reference="path/to/voice.wav",  # 可选
    output_path="output.wav"
)
```

### 交接稿生成
```python  
result = await script_to_handover_skill_execute(
    input_content="Raw script content...",
    title="Video Title",
    content_type="video_script"
)
```

### 生产指挥
```python
result = await production_director_skill_execute(
    handover_file="path/to/handover.md",
    output_dir="output/"
)
```

## 许可证

MIT License - 详见 `LICENSE` 文件