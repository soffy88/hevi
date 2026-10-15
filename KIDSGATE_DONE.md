# KIDSGATE 单元完成报告 (KIDSGATE-R1)

## 概述
完成了幼儿动漫安全与节奏质检闸门（kids_gate）的核心功能、能力注册与完整回归测试。

## 完成内容
1. **质检闸门实现 (`hevi/quality/kids_gate.py`)**：
   - 镜头时长检测：利用 ffmpeg 检测镜头切点，单镜头 <2.5s 判失败，平均 <3.5s 给警告。
   - 光敏闪烁检测：逐帧计算相对亮度并统计每秒相对亮度跳变频率（WCAG 2.3.1），>3次/秒 判失败。
   - 响度检测：集成 ffmpeg ebur128 量测整体 -16±1 LUFS、真峰值 ≤ -1.5 dBTP 以及相邻 400ms 短时响度跳变 >10 LU 判定。
   - 语速检测：根据 SRT 字幕时间轴与有效字数计算语速，>3.5字/秒 判失败。
   - 字幕字号检测：读取渲染元数据验证竖屏字号是否 <56px。
   - 台词内容审查：内置中文禁用词表（暴力、恐吓、贬损、危险行为、品牌名等），并在未配置 LLM 时优雅降级仅跑词表。
2. **能力注册 (`hevi/capabilities/registry.py`)**：
   - 遵循 `CAPABILITY_CONTRACT.md` 规范，实现统一能力注册表并注册 `qa.kids_gate` 能力。
3. **测试覆盖 (`tests/test_kids_gate.py`)**：
   - 使用真实 `ffmpeg` 合成各类样本：合格样本（通过）、1秒快切坏样本（捕获）、禁用词坏样本（捕获）、小字号坏样本（捕获）。
   - 验证产物删除后测试失败。
   - pytest 顺利通过（以 soffy 用户运行，JWT_SECRET=test-only）。
4. **3O Lint 验证**：
   - 执行 `python3 scripts/ci/run_3o_v3_lint.py`，顺利通过 (`3O_V3_LINT=PASS`)，未引入任何新失败项。

## 文件清单
- `hevi/quality/kids_gate.py`
- `hevi/capabilities/registry.py`
- `hevi/capabilities/__init__.py`
- `tests/test_kids_gate.py`
- `KIDSGATE_DONE.md`

DONE KIDSGATE-R1
