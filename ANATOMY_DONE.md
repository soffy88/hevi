# ANATOMY_DONE — 「会动的小机器」幼儿科普镜头线完成报告

## 成果概述
1. **Anatomy Kit Vendoring**: 成功将 `wheresryan22/anatomy` 的几何、渲染、审计核心模块引入 `third_party/anatomy/`（保留 LICENSE，附带 NOTICE 署名）。
2. **Hevi Capability `anatomy_explainer`**: 
   - 注册在 `hevi/capabilities/registry.py` 中，支持 4 个幼儿科普机械对象：`windmill`（风车转磨盘）、`waterwheel`（快乐转水车）、`soap_pump`（按压洗手液）、`clock_gear`（滴答小闹钟）。
   - 支持 16:9 (1920x1080) 与 9:16 (1080x1920) 两种画幅输出。
3. **渲染引擎与确定性**:
   - 使用 Headless Chrome (SwiftShader) 逐帧推进时间（30fps）捕获无抖动截图，FFmpeg (v7.0.2) 渲染合成 MP4。
   - 同参数同 seed 两次渲染 sha256 结果完全一致。
4. **安全与质检闸门 (kids_gate)**:
   - 全面接入 Hevi `kids_gate` 质检：单/平均镜头时长、光敏闪烁频率、响度标准 (-16 LUFS)、语速、竖屏字幕字号（≥56px）、台词与视觉内容审查。
   - 色彩饱和度平均值 ≥ 0.35。
5. **测试覆盖**:
   - `tests/test_anatomy_explainer.py` 完整验证注册、参数校验、多对象多画幅渲染、sha256 一致性、kids_gate 检查及像素级饱和度。全量测试通过。
6. **样片与报告**:
   - 样片与关键帧 PNG 已存入 `audit/anatomy/samples/`（单文件均 ≤ 1MB）。
   - 实测实证报告已写入 `audit/anatomy/REPORT.md`。

## 复现与验证命令
```bash
PYTHONPATH=/data/soffy/projects/hevi-anatomy JWT_SECRET=test-only /data/soffy/projects/hevi/.venv/bin/pytest tests/test_anatomy_explainer.py -v
```

DONE ANATOMY-R1
