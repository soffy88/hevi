# MOTIONDIR-R2 独立核验报告 (2026-10-15)

核验人：`/data/soffy/projects/hevi-pubfix` 合并核验员。
核验对象：worktree `/data/soffy/projects/hevi-motiondir`，分支 `feat/motion-director`。

## 核验结论：通过 (PASS)

对照 `MOTIONDIR_FIX_R2.md` 提出的 3 项阻断项（G1 导演版自检门实际状态、G2 渲染器含 mock/硬写通过、G3 拍点对齐未达成），经逐一独立复核与实测，结果如下：

### G1 修复确认
- 4 条产品线样片（explainer, character_narrative, scene3d, montage）重新渲染后，**导演版 `director_report.passed` 全部为 `true`**（拍点对齐率均 ≥ 0.70，无违规项，kids_gate 响度 -16 LUFS 及真峰值全通过）。
- **无导演层基线版 `baseline_report.passed` 全部为 `false`**（准确触发 PPT 同步、静止冻结、拍点对齐等真实自检门失败）。
- 审了 `audit/motiondir/REPORT.md` 与各 `*_comparison_report.json`，结论一致。

### G2 修复确认（无 Mock、无硬编码）
- 已彻底移除 `hevi/director_lens/render.py` 中的 `MOCK_MP4_BYTES` / `BASELINE_MP4_BYTES` 伪 MP4 分支与 `base_report["passed"] = False` 硬写逻辑。
- 视频生成必须经过真实的 Pillow 逐帧渲染与 ffmpeg (libx264) 真实编码，音频经过真实合成与确定性响度控制归一，ffmpeg 失败时抛出异常。

### G3 修复确认（拍点对齐达成）
- `autofill` 现已将运动事件吸附到帧级拍点网格（`build_grid` + `snap_all`），导演版样片拍点对齐率均达到 `≥ 0.70` 要求（实测均达 `1.00` 或 `0.71+`）。

### 测试与确定性
- `pytest tests/test_motion_director.py` 全部 19 项测试真实通过。
- 相同 seed 两次渲染 sha256 校验和完全一致。
- `ffprobe` 能读出真实的 h264 视频流与 aac 音频流。

## 签字
独立核验员：Hevi Motion Director R2 Rechecker  
状态：DONE MOTIONDIR-R2
