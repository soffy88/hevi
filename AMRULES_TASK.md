# AMRULES_TASK — 动效提示词规则 + lint（CPU-only），标志 `DONE AMRULES-R1`
Worktree `/data/soffy/projects/hevi-amrules`，分支 `feat/aimotion-rules`，基线 7087c24a。完成后写 `AMRULES_DONE.md`，最后一行 `DONE AMRULES-R1`。
(通用规则见文末，必须遵守)

## 目标
把 AIMOTION_EVAL.md §3.1/§3.3 的通用规则做成 Hevi 可复用的「提示词规则库 + 校验器」，放在新包 `hevi/motion_rules/`（不依赖未合并的 artmotion）。

## 范围
1. `hevi/motion_rules/spring.py` + `hevi/motion_rules/js/spring.js`：闭式弹簧（欠阻尼/临界阻尼阶跃响应，参数 stiffness/damping 或 omega/zeta），`value(t)` 为纯函数；多次改目标 = 每次变化一条弹簧之和（`SpringTrack([(t0,target0),(t1,target1)…])`）。Python 与 JS 两版数值一致（测试对比 200 个采样点误差 < 1e-6）。
2. `hevi/motion_rules/rules/*.yaml`（或 json）：至少 8 条规则卡，每条含 id、触发条件、反例、正确做法、来源 case id：纯 draw(t)/seek(t) 无状态、闭式弹簧、单形状连续 morph、内容进出时序（容器开始形变后进、下次形变前出）、短模糊过渡（不用黑场）、转场起点对齐 BPM 网格、首尾同帧可循环、禁项清单（shockwave rings / particle bursts / RGB split / camera shake / lens flare / neon glow / grid floor / flashing background / bouncy easing / 屏上文字句号）、真实素材非占位、先 contact sheet 后全渲。另给 `prompt_pack.py`：把规则卡渲染成可拼进 LLM 提示词的中文段落。
3. `hevi/motion_rules/lint.py`：对一个 storyboard/shot spec（JSON：shots[]，每个含 start/dur/transition/texts[{text,in,out}]/effects[]/bpm）做静态检查，红灯至少：禁项命中、转场起点不在 BPM 网格（容差参数化）、文字在容器形变前进入或形变后才离开、屏上文字带句号、单镜 > 8s；黄灯：缺 contact sheet、循环片首尾帧不同。输出结构化报告（code/level/shot/message）。
4. `hevi/motion_rules/video_checks.py`：对成片 mp4 的 ffmpeg 实测检查（真实抽帧）：闪烁检测（相邻帧亮度跳变频率）、首尾帧相似度（loop）、9:16 尺寸检查。阈值参数化。
5. 测试 `tests/motion_rules/`：每个红灯都有触发与不触发用例；video_checks 用 ffmpeg lavfi 现生成的真实小视频测（含故意闪烁片与正常片）。
6. `docs/MOTION_RULES.md`：规则说明、来源 case id 署名、如何接入 artmotion 的 storyboard_lint / omquality（写接入方案，不改那些分支）。

## 验收（写进 AMRULES_DONE.md，附真实输出）
- spring Py/JS 一致性测试输出；pytest 全绿条数；lint 对 3 个手写示例（1 合规、2 违规）的报告；video_checks 对闪烁片/正常片的结果；lint_before/after 失败数。
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
