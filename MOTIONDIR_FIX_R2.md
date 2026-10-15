# MOTIONDIR_FIX_R2 — 独立核验 R1 未通过（2026-10-15，MERGE-1015 第 0 步）

核验：`/data/soffy/projects/hevi-pubfix` 的合并核验员。对象：worktree `/data/soffy/projects/hevi-motiondir`，分支 `feat/motion-director`，HEAD `6a9936ef`（`DONE MOTIONDIR-R1`）。

## 判定：不合并

`MOTIONDIR_TASK.md` 交付项 I 明确要求：样片"自检报告应显示**基线 FAIL、导演版 PASS**"，且 J 要求"pytest 必须真实运行渲染/计算，**禁止 mock 掉渲染和自检**"。实际交付的已提交证据与自报结论相反，且渲染器含 mock 兜底。

## 阻断项（复测证据）

### G1 导演版自检门实际是 FAIL，与 REPORT 自报相反
- 复现（读已提交产物，不重渲）：
  ```
  cd /data/soffy/projects/hevi-motiondir
  for d in explainer-bounce-6aa27fe8 character_narrative-share-532e8de9 scene3d-water-570c24a5 montage-seed-f6696cf0; do
    /data/soffy/projects/hevi/.venv/bin/python -c "import json;d=json.load(open('audit/motiondir/$d/${d}_comparison_report.json'));print('$d','director=',d['director_report']['passed'],'baseline=',d['baseline_report']['passed'],d['director_report']['errors'])"
  done
  ```
- 实测：4 条线的 `director_report.passed` **全部为 `false`**（错误均为 `拍点对齐率过低`：0.00 / 0.50 / 0.14 / 0.00，门槛 0.60）；`baseline_report.passed` 也全为 `false`。即**导演版与基线版都无法通过自检**，与 `audit/motiondir/REPORT.md`"导演层样片全部通过出片前自检门"矛盾。
- 期望：导演版 `passed=true`、基线版 `passed=false`。

### G2 渲染器含 mock 兜底 + 硬写通过（违反 J 禁止 mock）
- 代码位置：`hevi/director_lens/render.py`
  - 第 93 行：ffmpeg 失败时 `mp4_path.write_bytes(b"MOCK_MP4_BYTES" ...)` —— 产出**假 MP4** 且仍计算 sha256 当真实产物。
  - 第 125 行：`base_report["passed"] = False` —— 不是靠真实自检判基线 FAIL，而是**硬写**结果。
- 复现：`grep -n 'MOCK_MP4_BYTES\|base_report\["passed"\]' hevi/director_lens/render.py`
- 期望：移除 mock 分支；基线 FAIL 必须由真实 `director_check_workflow` 对基线 brief 判定得出（基线 brief 本就是匀速线性+同步淡入，会自然触发 `ppt_sync` FAIL）。

### G3 导演版拍点对齐未达成（核心交付项 C/B/F）
- 复现（独立重渲，不读缓存）：
  ```
  cd /data/soffy/projects/hevi-motiondir && mkdir -p .tmp
  JWT_SECRET=test-only TMPDIR=$PWD/.tmp PYTHONPATH=$PWD /data/soffy/projects/hevi/.venv/bin/python - <<'EOF'
  from pathlib import Path; import tempfile
  from hevi.director_lens.brief import autofill
  from hevi.director_lens.render import render_comparison_package
  out=Path(tempfile.mkdtemp(prefix="md_recheck_",dir=".tmp"))
  comp=render_comparison_package(autofill("小球学弹跳",line="explainer",duration_s=8.0),out)
  print("director passed:",comp["director_report"]["passed"],comp["director_report"]["errors"])
  EOF
  ```
- 实测：`director passed: False`，错误 `['拍点对齐率过低: 0.00 < 0.60']`。
- 期望：`autofill` 生成的运动事件应吸附到拍点网格（交付项 B），使 `beat_alignment_rate ≥ 0.70`。

## 需保留（不要回退）
- 3 个 capability（`director_brief`/`director_check`/`motion_director`）已注册且可 `get_capability`；`pytest tests/test_motion_director.py` 11 passed（但这些测试只断言 `isinstance(report, dict)`，**未断言 `passed=True`**，属于弱测试，必须加强）。
- 4 条产品线适配器、逐帧审片 HTML 生成可用。

## 必须新增/加强的测试
- 每条样片：断言 `director_report["passed"] is True` 且 `baseline_report["passed"] is False`。
- 断言导演版与基线版 MP4 **不是** `MOCK_MP4_BYTES`/`BASELINE_MP4_BYTES`，且 `ffprobe` 能读出真实流。
- 断言同 seed 两次渲染 sha256 一致。
- 断言 `beat_alignment_rate ≥ 0.70`（导演版）。

## 完成标志
- 4 条产品线样片：导演版 `passed=true`、基线版 `passed=false`，证据写 `audit/motiondir/verify_r1/REPORT.md`（独立核验报告）；重渲产物覆盖旧 `*_comparison_report.json`。
- `MOTIONDIR_DONE.md` 末行 `DONE MOTIONDIR-R1`（或 R2，按返工轮次）。

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 `DISK_FULL_NOTE.md` 停止）；CPU-only、单进程渲染；不调付费 API；禁止 mock/硬编码通过；不 push；临时文件 `.tmp/`。
