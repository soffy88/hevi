# ANATOMY_DONE — R2 修复与核验完成报告

## R2 修复成果概述
1. **P1 画面与等距机械插画投影矫正**: 
   - 彻底修复投影缩放：`figures.mjs` 基于实体几何的世界真实包围盒计算 `fitProjection`，使整机精准居中并预留充裕边缘（pad ≥ 150px），消除色块溢出。
   - 非背景像素占比在 0.05–0.6 之间，主体完整在画内。
2. **P2 运动零件与叶片排布**: 
   - 风车 4 片叶片按 90° 旋转排布，永不重叠；各个对象的运动零件在 4s 内产生可测位移（像素变化占比 ≥ 2%，屏幕质心位移 ≥ 10px）。
3. **P3 Anatomy 几何审计与悬空线检查接入**: 
   - 渲染后编码前自动调用 `audit_figure.mjs`（底层调用 `third_party/anatomy/kit/audit.mjs` 的不穿模、支点支撑、深度遮挡审计）与 `audit_lines.mjs`（底层调用 `lines.mjs` 的悬空线检查），任何一项失败即 `raise` 拒绝出片。
   - 审计结果写入 `out_dir/anatomy_audit.json`。
   - 新增 `test_audit_failure_rejects_render` 测试注入故障拒绝出片。
4. **P4 干净环境与临时目录**: 
   - renderer 中对临时目录实施 `mkdir(parents=True, exist_ok=True)`，使 `git clean -xdf` 后的干净 worktree 直接 `pytest` 全绿。
5. **P5 报告补全**: 
   - `audit/anatomy/REPORT.md` 完整补充：实测时长、渲染耗时、内存峰值（RSS 峰值）、完整 SHA-256 哈希、anatomy 几何审计结果、kids_gate 结果。

## 自测与验证命令
```bash
export JWT_SECRET=test-only TMPDIR=$PWD/.tmp PYTHONPATH=$PWD PATH=$HOME/.local/bin:$PATH
rm -rf .tmp
/data/soffy/projects/hevi/.venv/bin/python -m pytest tests/test_anatomy_explainer.py -v
```

DONE ANATOMY-R2
