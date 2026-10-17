# XFADEPACK_FIX — R5 返工（独立核验 2026-10-14 13:0x CST，HEAD 7719c7cb 不通过：实现已达标，但连续性测试仍是空测）

前几轮（R2–R4）的要求见 git 历史中的本文件（`git show 4768deea:XFADEPACK_FIX.md`），全部仍然有效。本轮只剩 1 项。

## 本轮核验结论（主会话自己用 ffmpeg 算的，不是引用 DONE）
素材 testsrc2(A)→smptehdbars(B)，各 2s、offset=1、d=1，ffv1 无损中间件，ffmpeg `psnr` 滤镜逐帧相邻比较。
- **实现 ✅**：6 个 custom 的「转场最后一帧 → B 下一帧」PSNR：
  - 30fps（帧 59→60）：whip 37.31 / flash 52.34 / ink 60.78 / burn 62.93 / zoom_punch 99（末帧已=B）/ glitch 99（末帧已=B）
  - 25fps（帧 49→50）：whip 39.07 / flash 49.16 / ink 42.34 / burn 54.49 / zoom_punch 99 / glitch 99
  - 全部 ≥28 dB，且末步 ≥ 倒数第二步（whip 25fps 倒数第二步 27.70→末步 39.07，n44..49 依次 15.5/16.4/18.1/20.5/27.7/39.1，是缓停不是急停）。
  - 0/25/50/75/100% 帧亲眼看：首帧=A、尾帧=B、无伪彩/乱码，6 个形态各异（flash 中点全白）。
- 64 个转场（58 builtin + 6 custom）全部 rc=0、90 帧；builtin 抽 14 个 0–100% 帧正常。
- pytest 6 文件 300 passed；3O lint 仍为基线 4 项。

## 唯一必修问题

### I1（致命）`test_custom_transition_two_end_continuity_psnr` 仍然是空测
`_F3_FPS=30`、`_F3_OFF=1.0` ⇒ 转场帧是 30..59，**帧 60 起已经是纯 B**。现在的代码：
- `i_end = _f3_idx(1.0)` = 60（纯 B），`i_post` = 61（纯 B）→ `psnr_end` 比的是两个纯 B 帧（≈99 dB），`assert psnr_end >= 28` 恒真。
- `i_penult = 59`，`psnr_penult = PSNR(59, 60)` 这才是真正的「转场末帧 → B 下一帧」，但它只出现在 `diff = psnr_end - psnr_penult >= -3` 里；因为 psnr_end≈99，这条也恒真。
- **变异验证**：把 `hevi/assembly/xfade_transitions.py` 换回 R3 版（57ddcb46，线性 whip、旧 glitch）放到 /tmp 副本跑本测试 → **6 passed**；而该旧版实测末帧→B 只有 whip 15.92 dB、glitch 15.56 dB。即测试完全拦不住 R4 要修的回归。

### 修法（只改测试，实现不用动）
```python
i_pre    = _f3_idx(0.0) - 1   # 29: A 末帧（转场前）
i_start  = _f3_idx(0.0)       # 30: 转场首帧 P=1
i_last   = _f3_idx(1.0) - 1   # 59: 转场最后一帧（P≈1/30）
i_next   = _f3_idx(1.0)       # 60: B 的下一帧（纯 B）
i_prev   = i_last - 1         # 58
psnr_end  = _psnr(of[i_last], of[i_next])   # 末步
psnr_pen  = _psnr(of[i_prev], of[i_last])   # 倒数第二步
assert psnr_end >= 28.0
assert psnr_end >= psnr_pen - 3.0
assert _psnr(of[i_start], of[i_pre]) >= 18.0
```
- 另加一个**断言自证**：`assert _psnr(of[i_next], of[i_next+1]) > 60`（证明 i_next 确实已是纯 B，防止下标再错位）。
- 再加一个**防空测的反例测试**：把 R3 的线性 whip 表达式（`if(lt(X\,W-(1-P)*W)...`，可在测试里内联构造或用 `_WHIP_BLUR` 拼）渲一次，断言它的 `psnr_end < 28`，证明此测试能抓住该回归（不 mock，真实 ffmpeg）。
- 测试仍用 libx264 渲的话注意 B 段是静态 smptehdbars，i_next/i_next+1 应很高；如编码噪声影响判断，可像核验一样用 `-c:v ffv1` 或 rawvideo 输出。

## 其余要求
- DONE 里的数值表请用修正后测试打印出的真实数（30fps 帧 58→59、59→60），删掉「n49→50 33.84/74.66」这类与当前测试配置（30fps）不对应的数字，并写明 fps/分辨率/编码器。
- 跑 `JWT_SECRET=test-only .venv/bin/python -m pytest tests/test_xfade_pack.py tests/test_assembler.py tests/test_assembly.py tests/test_beat_align.py tests/test_video_assemble_workflow.py tests/test_tongjian_assemble.py -q` 全绿；`scripts/ci/run_3o_v3_lint.py` 失败仍 ≤ 基线 4 项。
- 遵守 XFADEPACK_TASK.md：只改本 worktree，不碰主 checkout，不 push 不合并，不删数据，CPU-only，不调付费 API，禁止 mock。
- 完成后更新 XFADEPACK_DONE.md，末行写 `DONE XFADEPACK-R5`，git commit（只 add 自己的文件）。

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；所有 python 设 PYTHONPATH=/data/soffy/projects/hevi-xfadepack；不 push；不调付费 API；不要把 lint 日志提交进仓库。完成后在 XFADEPACK_DONE.md 最后一行写 DONE XFADEPACK-R5。
