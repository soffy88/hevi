# ANATOMY_FIX_R2 — R1 核验失败，R2 修复单（完成标志：ANATOMY_DONE.md 最后一行 `DONE ANATOMY-R2`）

R1 独立核验（Hark，`audit/anatomy/verify_r1/REPORT.md`）结论：画面不是可辨认的等距机械图（是溢出的平面色块）、零件不动、几何审计（audit.mjs/lines.mjs）从未被调用、干净环境渲染失败、报告缺项。判定 FAIL。

## 已达成，不要回退
- `anatomy_explainer` 已注册（aspects 16:9/9:16），参数校验（非法对象、时长 <2 或 >15）抛错。
- 输出 1920×1080 / 1080×1920、30fps、时长正确；`kids_gate_workflow` 已接入且失败即 raise。
- `third_party/anatomy` vendor（含 LICENSE、NOTICE）在。

## 阻断项（必须全部修）

### P1（核心）画面必须是可辨认的等距机械插画，主体在画内
- 现状：`audit/anatomy/samples/windmill_16_9/frames/0000.png`、`soap_pump_9_16/frames/0060.png` 是占满屏幕的纯色圆/矩形，看不出风车/泵/齿轮结构。
- 量化：非背景像素占比 windmill_16_9=0.227、soap_pump_9_16=**0.953**（主体严重溢出 `viewBox`）。
- 复现抽帧：
  ```
  cd /data/soffy/projects/hevi-anatomy
  /data/soffy/projects/hevi/.venv/bin/python - <<'EOF'
  from PIL import Image
  Image.open("audit/anatomy/samples/windmill_16_9/frames/0000.png").save("/tmp/wm0.png")
  Image.open("audit/anatomy/samples/soap_pump_9_16/frames/0060.png").save("/tmp/sp60.png")
  EOF
  ```
- 要求：`hevi/capabilities/anatomy_explainer/figures.mjs` 修正投影缩放——`fitProjection` 的包围盒必须真实包住所有实体几何（当前 `[[-100,-100,0],[100,100,100]]` 明显小于 `cylinder(0,0,25,15,80,…)`/`slabOf(…,120,8,…)` 的世界尺寸），使整机居中且四周留边（pad ≥ 80px），不得溢出。用 `iso-kit.mjs` 的投影结果自查每个实体的屏幕包围盒都在 `[pad, width-pad]×[pad, height-pad]` 内。
- 必须新增测试（基于真实像素，不能只看几何）：渲染后取非背景像素包围盒，断言其四边都在画面内且留边 ≥40px；断言非背景占比在 0.05–0.6 之间（排除「几乎全屏色块」）。

### P2 零件必须真的动，且风车 4 片叶片不能重叠
- `figures.mjs` 风车叶片 `for (let i=0;i<4;i++)` 循环体没用到 `i`，四片画在同一位置。改为每片绕轴旋转 90°×i 排布。
- 现状帧差：windmill_16_9 第 0→60 帧（t=0→2.0s）仅 0.6% 像素变化；soap_pump 仅 0.09%。按压/转动几乎不可见。
- 要求：每个对象的运动零件在 4s 内产生可测位移；`__heviSeek(t)` 必须真正改变零件 transform。
- 必须新增测试：对每个对象取 t=0 与 t=2.0 两帧，断言运动区域（包围盒内）像素变化占比 ≥2%，且运动零件的屏幕质心位移 ≥10px。

### P3 每条片必须自动跑 anatomy 几何审计（audit.mjs + lines.mjs），失败即拒绝出片
- 现状：`grep -rn "audit.mjs\|lines.mjs" hevi/ tests/ scripts/` 无调用；renderer 流程只有 build→render→ffmpeg→kids_gate。
- 要求：在 `renderer.py` 渲帧后、编码前（或编码后出片前）调用 `third_party/anatomy/kit/audit.mjs`（不穿模、每个端点有支撑、遮挡顺序）与 `third_party/anatomy/scripts/lines.mjs`（悬空线）；任一失败 `raise` 拒绝出片（不是只记日志）。审计结果写入 `out_dir/anatomy_audit.json`。
- 必须新增测试：`test_audit_failure_rejects_render`——人为让一个零件穿模（注入坏几何/坏 HTML），断言 `render()` 抛错且不产出可用的 mp4。

### P4 干净环境必须能渲染（测试真跑通）
- 现状：`.tmp` 不存在时 `test_anatomy_render_and_assertions` FAILED（`mkdtemp '<worktree>/.tmp/iso-render-XXXXXX'` ENOENT）。render_frames.mjs 依赖 `.tmp` 存在。
- 要求：renderer 里对临时目录 `mkdir(parents=True, exist_ok=True)`（或改用 `tempfile`/`os.tmpdir()` 的绝对路径），使 `git clean -xdf` 后的干净 worktree 直接 `pytest` 全绿。
- 复现：`cd <clean worktree>; JWT_SECRET=test-only TMPDIR=$PWD/.tmp PYTHONPATH=$PWD pytest tests/test_anatomy_explainer.py -q` 必须全绿（不预先 mkdir）。

### P5 报告补全（ANATOMY_TASK 目标 7）
- `audit/anatomy/REPORT.md` 必须写：实测时长、渲染耗时、**内存峰值**（渲染进程 RSS 峰值）、完整 sha256（非截断）、**anatomy 几何审计结果**（audit.mjs/lines.mjs 输出）、kids_gate 结果。

## 自测（DONE 前必须全过，写进 DONE 真实输出）
```
cd /data/soffy/projects/hevi-anatomy
export JWT_SECRET=test-only TMPDIR=$PWD/.tmp PYTHONPATH=$PWD PATH=$HOME/.local/bin:$PATH
rm -rf .tmp   # 干净环境
/data/soffy/projects/hevi/.venv/bin/python -m pytest tests/test_anatomy_explainer.py -q   # 全过
```
- 4 对象 × 2 画幅全部重渲样片（主体在画内、零件在动、审计通过），ffprobe 时长/分辨率、sha 一致、kids_gate 结果、审计结果写入 REPORT.md。
- 3O lint 失败数 ≤ 基线 4。

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；所有 python 设 PYTHONPATH=/data/soffy/projects/hevi-anatomy；不 push；不调付费 API；渲染一次只跑一个进程；不要把 lint 日志提交进仓库。完成后在 ANATOMY_DONE.md 最后一行写 `DONE ANATOMY-R2`。
