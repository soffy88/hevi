# AMFX_TASK — morph/材质转场 + 运动模糊/多画幅渲染工程（CPU），标志 `DONE AMFX-R1`
Worktree `/data/soffy/projects/hevi-amfx`，分支 `feat/aimotion-fx`，基线 7087c24a。完成后写 `AMFX_DONE.md`，最后一行 `DONE AMFX-R1`。
(通用规则见文末，必须遵守)

## 目标
落地 AIMOTION_EVAL.md 单元 C：新包 `hevi/motion_fx/`。

## 范围
1. 转场（≥3 个，自写实现）：`line_to_structure`（线条描绘→结构体形变接下一镜）、`water_ripple`（水面涟漪/折射位移过渡，WebGL1/WebGL2 或 numpy 实现均可，必须 CPU headless 可渲）、`glass_refract`（透明/折射材质扫过）。接口：`apply_transition(clip_a, clip_b, kind, dur, params, out)`，输入两个真实 mp4，输出 H.264 yuv420p；可选 `start` 对齐 BPM 网格（`snap_to_grid(t, bpm, division)`，写测试）。
2. 运动模糊 subframe 渲染：给 headless 逐帧渲染器（自写最小版：HTML `draw(t)` + Playwright）加 `subframes=N`（默认 4–6，按 1/(fps·N) 偏移采样后平均），或对已有高帧率片用 ffmpeg `tmix`；输出 60fps 或 30fps 参数化。对比测试：同一快速运动场景 N=1 与 N=6 的帧间差异/边缘模糊度实测数值。
3. 9:16 自动裁摆：`reframe(in_16x9, out, aspect="9:16")`：主体检测（CPU：OpenCV 显著性/运动能量/人脸，任选，不调付费 API）→ 裁切窗口平滑跟踪，主体占比 ≥50%，无上下空带；对竖屏素材直接通过。同一 `draw(t)` 场景也支持一次并行出 9:16/16:9/1:1。
4. 样片：用 ffmpeg lavfi/自绘生成的真实素材 + 仓库内已有视频素材，各转场出一支 9:16 样片（≤8s）；reframe 对 2 支 16:9 素材出竖屏版。放 `samples/aimotion_fx/`（不 commit mp4，记录路径 + sha256）。
5. 测试 `tests/motion_fx/`：每个转场输出时长 = a+b−dur（±1 帧）、尺寸/编码正确、转场中段帧与两端帧都不同（真实抽帧比较）；reframe 裁窗不出界、主体占比；snap_to_grid。
6. `docs/MOTION_FX.md`：参数、参考来源 case id（署名，不贴源码）、如何并入 hevi-xfadepack 的转场注册（写方案，不改那个分支）。

## 验收（写进 AMFX_DONE.md，附真实输出）
每支样片 ffprobe + sha256 + 转场中段抽帧路径；subframe 对比数值；reframe 主体占比实测；pytest 条数；lint_before/after。
## 通用规则（必须遵守）
- 你在独立 worktree（当前目录）里工作，基线 `7087c24a`（feat/omrender-3o）。**只改本 worktree**。绝对不要碰主 checkout `/data/soffy/projects/hevi`（只允许经 `.venv` 软链只读使用其 Python 环境），也不要改任何其它 hevi-* worktree（只读参考）。
- **不删除 worktree 以外的任何文件；永远不要清理磁盘**（不删缓存、node_modules、docker 镜像、日志等）。开工及每次长渲染前 `df -h /data`，可用 < 5G 时写 `DISK_FULL_NOTE.md`、commit、停止。
- 所有 python 命令都设 `PYTHONPATH=$PWD`（即本 worktree 绝对路径）。pytest：`PYTHONPATH=$PWD JWT_SECRET=test-secret-local .venv/bin/python -m pytest <你的测试> -q`。PATH 含 /home/soffy/.local/bin（ffmpeg/ffprobe）与 /home/soffy/.nvm/versions/node/v26.4.0/bin。Playwright 浏览器在 /home/soffy/.cache/ms-playwright（headless chromium，CPU 渲染）。
- CPU-only（GPU 已坏，WebGPU 不要用）；不调用任何付费 API；不重建容器；不 push、不合并到其它分支。
- **版权边界**：awesome-ai-motion（`/data/soffy/refs/awesome-ai-motion`，只读）里作者作品的源码、画面不随其 MIT 许可。**不要把任何作者作品的源码复制/vendor 进本仓库**，只吸收技法与提示词规则，用自己的实现从零写；在 docs 里按 case id 注明参考来源（署名，不贴源码）。
- 开工先跑 `PYTHONPATH=$PWD .venv/bin/python scripts/ci/run_3o_v3_lint.py > lint_before.txt 2>&1` 记基线，结束跑 `lint_after.txt`，失败数不得多于基线。
- 优先新增文件；不改 `hevi/video/quality_profile.py`、`hevi/studio/*`、`hevi/api/*`、`hevi/production/capabilities.py` 等现有核心文件。
- 每完成一步 `git add <只加自己的文件> && git commit -m "<branch>: step N ..."`（不要 `git add -A`；不提交 >20MB 文件、软链、日志、中间帧）。hook 报错时用 `git -c core.hooksPath=/dev/null commit ...`。
- 长任务（渲染、E2E）用 `nohup setsid <cmd> > <log> 2>&1 &` 启动并 sleep 轮询到产物生成。
- 禁止 mock/占位/写死产物；DONE 文件里的数据必须来自真实 ffprobe/抽帧/测试输出，不得自称"独立验证通过"。
- 参考资料：`/data/soffy/projects/hevi-aimotion-eval/AIMOTION_EVAL.md`（调研结论，必读）、`/data/soffy/refs/awesome-ai-motion/prompts/*.txt` 与 `data/cases.json`（只读）。只读参考 Hevi 已有实现：`/data/soffy/projects/hevi-artmotion`（artmotion 规则/引擎，未合并，不要 import）、`/data/soffy/projects/hevi-fxreg`（fx registry）、`/data/soffy/projects/hevi-xfadepack`（转场包）、`/data/soffy/projects/hevi-omquality`。
- 不要询问，直接执行到底。
