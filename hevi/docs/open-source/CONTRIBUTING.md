# 贡献指南 (Contributing Guide)

感谢你有兴趣为 Hevi 项目做贡献！本文档提供了有关如何参与项目开发的详细信息。

## 行为准则

请阅读并遵守我们的 [行为准则](CODE_OF_CONDUCT.md)。

## 开发环境设置

### 1. 克隆项目

```bash
git clone https://github.com/your-org/hevi.git
cd hevi
```

### 2. 设置虚拟环境

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# 或 .venv\Scripts\activate  # Windows

pip install -r requirements.txt
pip install -r requirements-dev.txt  # 开发依赖
```

### 3. 验证环境

```bash
python -c "import hevi; print('Environment OK')"
```

## 贡献类型

### 代码贡献

1. **Bug 修复**: 修复现有问题
2. **功能开发**: 添加新功能
3. **性能优化**: 提升系统性能
4. **重构**: 改进代码结构
5. **测试**: 增加测试覆盖率

### 非代码贡献

1. **文档**: 改进文档质量
2. **翻译**: 翻译国际化内容
3. **设计**: UI/UX 改进建议
4. **测试**: 功能测试和反馈
5. **社区**: 帮助其他贡献者

## 开发流程

### 1. 分支策略

- `main`: 生产就绪代码
- `develop`: 开发中代码
- `feature/*`: 功能分支
- `hotfix/*`: 紧急修复分支
- `release/*`: 发布准备分支

### 2. 提交规范

使用约定式提交 (Conventional Commits):

```
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

**类型**:
- `feat`: 新功能
- `fix`: Bug 修复
- `docs`: 文档更新
- `style`: 代码格式调整
- `refactor`: 代码重构
- `test`: 测试相关
- `chore`: 构建过程或辅助工具变动

**示例**:
```
feat(tts-skill): 添加多语言支持

- 支持中文、英文、日语
- 添加语言检测功能
- 更新测试用例

Closes #123
```

### 3. 代码规范

#### Python 规范
- 遵循 PEP 8
- 使用类型提示
- 保持函数简短 (小于 50 行)
- 编写有意义的变量名

#### 测试要求
- 核心功能必须有单元测试
- 测试覆盖率不低于 80%
- 集成测试覆盖主要流程

#### 文档要求
- 每个公共函数必须有 docstring
- 复杂逻辑需要注释说明
- 更新相关文档

### 4. 提交流程

1. **Fork 仓库**
2. **创建功能分支**
   ```bash
   git checkout -b feature/amazing-feature
   ```
3. **编写代码**
4. **运行测试**
   ```bash
   pytest
   ```
5. **提交更改**
   ```bash
   git add .
   git commit -m "feat: add amazing feature"
   ```
6. **推送分支**
   ```bash
   git push origin feature/amazing-feature
   ```
7. **创建 PR**

## 技术栈

### 后端
- Python 3.10+
- FastAPI
- AsyncIO
- Pydantic
- SQLAlchemy

### 前端 (Web UI)
- React/Next.js
- TypeScript
- Tailwind CSS

### 架构组件
- 微服务架构
- 消息队列
- 缓存系统
- 任务调度器

## 代码结构

```
hevi/
├── skills/                 # 可执行技能模块
│   ├── tts-skill/          # TTS 技能
│   ├── script-to-handover/ # 交接稿技能
│   └── ...                # 其他技能
├── api/                    # API 接口
├── core/                   # 核心功能
├── audio/                  # 音频处理
├── video/                  # 视频处理
├── configs/               # 配置文件
├── docs/                  # 文档
├── tests/                 # 测试代码
└── scripts/               # 脚本工具
```

## 测试策略

### 单元测试
- 针对单个函数/类
- 快速执行
- 高覆盖率

### 集成测试
- 测试组件交互
- 验证端到端流程

### 性能测试
- 评估系统性能
- 识别瓶颈

## 质量标准

### 代码审查清单

- [ ] 代码功能正确
- [ ] 符合编码规范
- [ ] 有足够的测试
- [ ] 文档已更新
- [ ] 没有安全漏洞
- [ ] 性能合理

### 自动检查

- Black 代码格式化
- Flake8 代码质量
- MyPy 类型检查
- Bandit 安全扫描

## 常见问题

### 本地开发环境问题

Q: 依赖安装失败?
A: 确保使用正确的 Python 版本，尝试 `pip install --no-cache-dir`

Q: 测试失败?
A: 检查环境配置，运行 `pytest -v` 获取详细信息

### 代码贡献问题

Q: 如何开始贡献?
A: 查看 "good first issue" 标签的问题

Q: PR 被拒绝怎么办?
A: 根据反馈进行修改，询问具体原因

## 联系方式

- **问题**: GitHub Issues
- **讨论**: GitHub Discussions
- **实时**: Slack (如果有的话)

## 感谢

感谢所有为 Hevi 项目做出贡献的人！