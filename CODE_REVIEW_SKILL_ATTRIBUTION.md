# code-review-skill attribution

- **来源**: https://github.com/kyy-logs/code-review-skill
- **许可证**: MIT License
- **版权**: Copyright (c) 2026 kyy-logs
- **使用方式**: 只重述其“四探针 JSON 证据契约”方法，不复制其提示词、探针 agent
  或语料。`hevi/qa/code_review_gate.py` 是 hevi 自写的确定性校验脚本：
  必需探针（behavior-review / test-coverage / repo-guard）齐全、每条 finding
  含 location/summary/evidence/severity/status、severity 只接受 high/medium/low、
  未关闭的 high 阻断。
- **CI 定位**: 可选 PR 检查（`.github/workflows/code-review-gate.yml`，
  `continue-on-error: true`），不是必需状态检查；探针 JSON 由 reviewer agent
  在独立上下文产出后传入。
- **入库日期**: 2026-11-09
