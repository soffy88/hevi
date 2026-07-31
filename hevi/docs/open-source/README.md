# Hevi - 短视频自动化生产流水线

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Status](https://img.shields.io/badge/status-production--ready-brightgreen)](https://github.com/)

## 项目简介

Hevi 是一个用于短视频自动化生产的完整流水线系统，对标业界领先的 rnskill + 双轨 TTS 方案。系统设计专注于生产安全、质量保障和高效自动化。

### 核心特性

- **生产安全**：强制本地 TTS，禁止云端回退
- **质量硬门**：关键节点阻断式质量检查
- **真实音频处理**：字幕基于真实 ASR，非估算生成
- **模块化架构**：可扩展的技能系统
- **完整流水线**：从脚本到成品的一键生成

## 快速开始

### 环境要求

- Python 3.10+
- 至少 8GB RAM（推荐 16GB+）
- GPU 支持（CUDA 11.0+，用于 TTS 和渲染）

### 安装

```bash
# 克隆项目
git clone https://github.com/your-org/hevi.git
cd hevi

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# 或 .venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt

# 配置本地 TTS 模型
# 下载 IndexTTS2 模型到 vendor/indextts2/
```

### 基础配置

```bash
# 验证 TTS 配置
python -m hevi.scripts.validate_tts_provider

# 检查配置
cat hevi/configs/tts_routing.json
```

## 核心架构

### 技能系统 (Skills)

Hevi 采用模块化的技能系统，每个功能单元都是独立的技能：

```
skills/
├── tts-skill/              # 本地 TTS 生成
├── script-to-handover/     # 脚本标准化
├── production-director/    # 流水线编排
├── caption-from-audio/     # 真实音频字幕
├── final-qc/              # 终检
├── title-generator/        # 标题生成
├── hook-detector/         # 钩子检测
├── digital-twin-guard/    # 数字人保护
├── cost-tracker/          # 成本跟踪
└── qc-enhancement/        # 质量强化
```

### 生产流水线

```
脚本输入 → 标准化交接 → TTS 生成 → 视频渲染 → 字幕生成 → 质量检查 → 成品输出
    ↓           ↓           ↓           ↓           ↓           ↓
  前处理    格式统一    本地TTS    视频合成    ASR字幕    硬门检验    发布准备
```

## 使用示例

### 1. 运行完整流水线

```python
from hevi.skills.production_director import production_director_skill_execute

result = await production_director_skill_execute(
    handover_file="path/to/script.md",
    output_dir="outputs/"
)
```

### 2. 生成标题

```python
from hevi.skills.title_generator import title_generator_skill_execute

titles = await title_generator_skill_execute(
    content="关于AI未来的精彩内容...",
    num_titles=5
)
```

### 3. 质量检查

```python
from hevi.skills.qc_enhancement import qc_enhancement_skill_execute

qc_result = await qc_enhancement_skill_execute(
    file_path="output/video.mp4",
    tier="L3_advanced",
    sha_verification="expected_sha256_hash"
)
```

## 配置管理

### TTS 路由配置

`hevi/configs/tts_routing.json`:
```json
{
  "production_provider": "local-indextts2",
  "allowed_providers": ["local-indextts2"],
  "fallback_enabled": false,
  "voice_reference_sha256": "your_voice_hash_here",
  "validation_enabled": true
}
```

### 环境变量

- `HEVI_ENV`: 环境标识 (development/production)
- `GPU_ENABLED`: 是否启用 GPU 加速
- 各服务连接信息

## API 文档

详见: [技能API参考](open-source/skills-api-reference.md)

## 贡献指南

我们欢迎社区贡献！

1. Fork 项目
2. 创建功能分支
3. 添加测试用例
4. 确保测试通过
5. 提交 Pull Request

### 开发规范

- 代码必须有类型注解
- 关键功能必须有单元测试
- 错误处理必须明确
- 文档必须更新

## 许可证

MIT License - 详见 [LICENSE](../LICENSE) 文件

## 支持

- 问题反馈: [GitHub Issues](https://github.com/your-org/hevi/issues)
- 贡献指南: [CONTRIBUTING.md](CONTRIBUTING.md)
- 社区支持: [Discussions](https://github.com/your-org/hevi/discussions)

---

**注意**: 本项目处于活跃开发中，API 可能会发生变化。生产环境使用前请确认版本稳定性。