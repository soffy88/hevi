# AMTPL_TASK — 单 HTML draw(t) 动效模板（CPU headless 渲染），标志 `DONE AMTPL-R1`
Worktree `/data/soffy/projects/hevi-amtpl`，分支 `feat/aimotion-templates`，基线 7087c24a。完成后写 `AMTPL_DONE.md`，最后一行 `DONE AMTPL-R1`。
(通用规则见文末，必须遵守)

## 目标
落地 AIMOTION_EVAL.md 单元 B（B1/B2/B4 优先，B3 可选一个）：新包 `hevi/motion_templates/`，每个模板 = 一个自写的单 HTML 文件，一个 canvas，一个纯函数 `draw(t)`（无 CSS 动画、无 timer、无帧间状态），参数通过 JSON spec 注入；渲染器用 Playwright headless chromium 逐帧 `draw(t)` 截图 → ffmpeg H.264 yuv420p。

## 范围
1. `hevi/motion_templates/render.py`：`render(template, spec, out_mp4, w=1080, h=1920, fps=30)`；逐帧 seek（确定性：同 spec 两次渲染帧 sha256 相同，写测试）；支持 `--aspect 9:16|16:9|1:1`；先出 contact sheet（3×3 抽帧 PNG）再全渲。CLI：`PYTHONPATH=$PWD .venv/bin/python -m hevi.motion_templates.cli --template morph_ui --spec x.json --out out/`。
2. 闭式弹簧：在模板公共 JS `hevi/motion_templates/lib/spring.js` 自写实现（欠阻尼阶跃响应 + 多目标叠加；不要依赖其它未合并分支）。
3. 模板（全部 9:16 原生排版，不是横版裁切）：
   - B1 `morph_ui`：一个形状靠 size/radius/color 连续形变串起 6–10 个状态（按钮→进度条→图表→播放器…），内容在容器形变后进、下次形变前出，形变时短模糊；状态与文字由 spec 给（中文）。
   - B2 `timeline_explainer`：线稿风时间轴/知识讲解，逐条里程碑揭示，中英双语字幕（中文不拆词、不溢出安全区）；可选读入 wav 旁白对齐时间（不调用 TTS 也必须能出片）。
   - B4 `kinetic_lyrics`：动态歌词/卡点字排，按 BPM 网格（spec.bpm）每拍一个事件，可读入音频并混进成片。
   - B3（可选一个）`layer_build`：分层揭示/建造类 B-roll。
   禁项：shockwave、粒子爆发、RGB split、镜头抖动、lens flare、霓虹辉光、网格地板、闪烁背景、bouncy easing、屏上句号；禁大面积蓝紫。
4. 每个模板给 2 个示例 spec（Hevi 题材，不照搬原作），各渲出 9:16 成片（≤15s）+ 一个 16:9 版本，放 `samples/aimotion/`（不 commit mp4，>20MB 不提交；记录路径与 sha256）。
5. 测试 `tests/motion_templates/`：spec 校验、确定性、文字安全区溢出检查（实际测量 canvas measureText）、ffprobe 尺寸/fps/时长。
6. `docs/MOTION_TEMPLATES.md`：模板参数、参考来源 case id（署名，不贴作者源码）、如何注册进 fx registry（写方案，参考 hevi-fxreg，不改那个分支）。

## 验收（写进 AMTPL_DONE.md，附真实输出）
每个样片的 ffprobe（宽高/fps/时长/编码）、sha256、contact sheet 路径；确定性测试结果；pytest 条数；lint_before/after。
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
