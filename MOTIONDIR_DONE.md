# MOTIONDIR-R2：Hevi 动效导演层（Motion Director R2 返工与独立核验完成报告）

## 一、 R2 返工完成的工作
1. **拍点对齐吸附修复 (`hevi/director_lens/brief.py`)**:
   - `autofill` 现已将模板重动作事件确定性吸附至帧级拍点网格（`build_grid` + `snap_all`），确保导演版拍点对齐率满足 `≥ 0.70` 要求（实测均达标）。
2. **移除 Mock 与硬编码逻辑 (`hevi/director_lens/render.py`)**:
   - 彻底移除了原 R1 中的 `MOCK_MP4_BYTES` / `BASELINE_MP4_BYTES` 伪 MP4 兜底，改为真实的 Pillow 逐帧渲染与 ffmpeg (libx264) 真实编码（失败抛异常）。
   - 移除了原 R1 中的 `base_report["passed"] = False` 硬写，基线版的 FAIL 现由真实 `director_check_workflow` 对基线 brief 判定得出（自然触发 PPT 同步与静止冻结失败）。
3. **真实音轨合成与响度归一**:
   - 实现了本地 BGM 合成与仓内 SFX 资产混音，并通过 ffmpeg 双向闭环量测归一，严格达标幼儿响度门规范（-16 ±1 LUFS，真峰值 ≤ -1.5 dBTP）。
4. **独立核验与审计报告**:
   - 4 条产品线样片（explainer, character_narrative, scene3d, montage）全数完成真机重渲，产物、JSON 对比报告与审片面板 HTML 已沉淀至 `audit/motiondir/`。
   - 编写了独立核验报告 `audit/motiondir/verify_r1/REPORT.md`。

## 二、 测试命令与结果
- 运行测试命令：
  `JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=. /data/soffy/projects/hevi/.venv/bin/python -m pytest tests/test_kids_gate.py tests/test_director_contract.py tests/test_motion_director.py -v`
- 测试结果：30 个测试全部通过 (PASS)，包含：
  - 各线路导演版 `passed=True`、基线版 `passed=False`。
  - 真 MP4 与 AAC 音轨流验证（非 mock）。
  - 同 seed 两次渲染 sha256 校验和一致。
  - 拍点对齐率 ≥ 0.70。

## 三、 样片路径与审计产物
- 沉淀至 `audit/motiondir/`：
  - `explainer-bounce-6aa27fe8/`
  - `character_narrative-share-532e8de9/`
  - `scene3d-water-570c24a5/`
  - `montage-seed-f6696cf0/`
- 独立核验报告：`audit/motiondir/verify_r1/REPORT.md`

DONE MOTIONDIR-R2
