# STICKDIR_TASK — 火柴人导演线（CPU-only），标志 `DONE STICKDIR-R1`

Worktree: `/data/soffy/projects/hevi-stickdir`，分支 `feat/stickman-director`，基于 `feat/omrender-3o` HEAD `7087c24a`（含 `hevi/studio/svg_character.py`、`hevi/studio/mocap.py`、`hevi/studio/cmumocap.py`、`assets/mocap-clips/clips/*.json`：dance_glide/dance_spin/jump/kick/march/run/shuffle/sit/twist/walk/wave）。
Step 0 已完成：`third_party/stickman-video-director/`（MIT，上游 commit `544254dd`，SKILL.md + references/*.md + LICENSE + ATTRIBUTION.md）@ `565a1f65`。

## 通用规则（必须遵守，源自 feature4/COMMON.md，按本任务调整）
- 你在独立 worktree 里工作（当前目录），基线 `7087c24a`（feat/omrender-3o）。**绝对不要碰主 checkout `/data/soffy/projects/hevi`**（只允许只读引用其 .venv，已为你建好软链）。也不要改其它 hevi-* worktree（hevi-omrender / hevi-dirstyle / hevi-talkcraft / hevi-shotspec 等只读参考）。
- CPU-only（GPU 已坏）；不调用任何付费 API（Gemini/Omni Flash/Flow 一律不用，由 Hevi CPU 渲染替代）；不重建容器；不删任何数据（worktree 外一律不删）；不 push、不合并到其它分支。
- **永远不要清理磁盘**。开工及每次长渲染前 `df -h /data`：可用 < 5G 时写 `DISK_FULL_NOTE.md`、commit、停止。
- 禁止改动：`hevi/video/quality_profile.py`、`hevi/studio/*`（现有文件全部只读；唯一例外：若线路注册必须，可**新增** `hevi/studio/lines/stickman_director.yaml`，不得改现有文件）、`hevi/prompt/style_presets.py`、`hevi/keyframe/**/style_presets.py`、`hevi/layer4_legacy/review/*`、`hevi/layer4_legacy/enhance/*`、`hevi/layer4_legacy/dirstyle/*`、`hevi/production/capabilities.py`、`hevi/api/routers/explainer.py`、`hevi/explainer/*`。优先新增文件；`svg_character.py` 只读/import 复用。
- 开工先跑 `PYTHONPATH=$PWD .venv/bin/python scripts/ci/run_3o_v3_lint.py > lint_before.txt 2>&1` 记基线（基线允许 4 项失败），结束再跑 `lint_after.txt`，失败数不得多于 4。
- 所有 python 命令都设 `PYTHONPATH=$PWD`。pytest：`PYTHONPATH=$PWD JWT_SECRET=test-secret-local .venv/bin/python -m pytest <你的测试> -q`。PATH 含 /home/soffy/.local/bin（ffmpeg/ffprobe）和 /home/soffy/.nvm/versions/node/v26.4.0/bin（hyperframes/node）。
- 每完成一步就 `git add <只加自己的文件> && git commit -m "feat/stickman-director: step N ..."`（不要 `git add -A`；不要提交 >20MB 文件、.venv/node_modules 软链、日志、渲染中间帧）。若 git LFS post-checkout/commit hook 报错，用 `git -c core.hooksPath=/dev/null commit ...`。
- 长任务（TTS 冷启动、渲染、E2E）用 `nohup setsid <cmd> > <log> 2>&1 &` 独立启动，sleep 轮询直到产物生成，不得在产物完成前结束。
- 禁止 mock/占位/写死产物；验收数据必须来自真实 ffprobe/抽帧/测试输出。DONE 里不得写未实测的数据，不得自称"独立验证通过"。
- 不要询问，直接执行到底。

## 必读参考
1. `third_party/stickman-video-director/skills/directing-stickman-videos/SKILL.md` 及 `references/storyboard-template.md`、`style-catalog.md`、`voice-continuity.md`、`prehistoric-dark-comedy.md`、`omni-flash-prompt-contract.md`。
2. 只读参考（不要复制整文件、不要改）：`/data/soffy/projects/hevi-dirstyle`（分支 feat/director-styles @7a64cc28）里已有的 `hevi/layer4_legacy/dirstyle/oskill_impl/heartbeat5.py`（五段心跳规划）、`data/stickman_1a_light.json … stickman_3_prehistoric.json`（风格 DNA/negative/grade）、`hevi/creative/director_contract.py`（本基线也有）。它们只做"提示词/flow pack"，**不出片**；本任务要真正 CPU 出片。可在本分支用独立实现复刻思路，避免 import dirstyle（未合并）。
3. `hevi/studio/svg_character.py`（HyperFrames + CMU mocap 骨骼小人）、`hevi/studio/cmumocap.py`、`hevi/audio/cosyvoice_service.py`（CosyVoice gen-engine `http://127.0.0.1:17600`，CPU，冷启动约 75s，首次调用前先 `/health` 并预热）。TTS 失败回退：`svg_character.synth_line` 用的 piper（`/data/soffy/projects/hevi-zero/.venv/bin/piper` + zh_CN-huayan-medium），须在 DONE 里写明实际用了哪个。
4. 免费 LLM：优先用 Hevi 现有 LLM 客户端/本机 ollama（`127.0.0.1:11434`，模型 `xiaoya-qwen3-4b-v2:latest`，纯 CPU）；不可用或超时则走确定性 fallback。两条路径都必须通过同一个 schema+白名单校验。

## 范围
### (a) 导演提案生成器 `hevi/layer4_legacy/stickdir/`
中文优先流水线，移植 skill 方法：
- 输入：文案 copy、aspect（`9:16`|`16:9`）、duration（30|60，按 10s 倍数）、style（`1A`|`1B`|`2A`|`2B`|`3`）。缺 aspect/style 时报错（对应 skill setup gate，不得静默默认）；duration 缺省 60。
- 文案 → 重写中文旁白：结构 钩子 → 打破预期 → 机制 → 结论 → 回调（Style 3 用 铺垫→升级→反转回调）；不得编造原文没有的数字/人名/引语（写校验函数并测试）。字数按中文约 4–5 字/秒控制，使旁白时长贴合目标时长。
- 定时分镜表：每 10s 一段，段内三拍 `[0–3s][3–7s][7–10s]`，**每 2–3s 一个动作节拍**；每拍给 动作(pose)、道具、视觉隐喻、镜头(推/拉/摇/跟/震)、转场、SFX、BGM 提示；段尾状态 = 下段开头状态（continuity 字段两边都写）；9:16 用纵深/上下堆叠调度，16:9 用左中右调度；角色/道具/声音描述符在每段逐字重复（frozen anchors）。
- 所有枚举项（动作、道具、隐喻、镜头、转场、SFX、BGM、风格、比例）来自 `stickdir/whitelist.py`（或 json）白名单；LLM 输出不在白名单内的项必须被修正或拒绝回退到确定性方案。
- 输出 `proposal.json`（含 schema 版本）+ 人读 `proposal.md`（中文）。

### (b) CPU 渲染器 → 真实 mp4
- 角色：复用 `svg_character`（HyperFrames+mocap）或新写参数化火柴人（PIL/numpy 逐帧 或 SVG→HyperFrames 或 Remotion）。参数化骨骼姿势库须覆盖白名单动作（走、跑、跳、指、举物、推门、画线、坐、挥手、思考、惊讶…），节拍间平滑插值。
- 风格（至少 1A、1B、2A 完整实现；2B、3 可简化但必须肉眼明显不同）：
  - 1A：纯白背景（逐像素 255，无纹理/渐变/阴影），黑色线条火柴人（空心圆头），≤3 种饱和强调色。
  - 1B：纯黑背景（0），白色线条火柴人，≤3 种强调色。
  - 2A：白色高光工作室 + 浅灰透视地面网格 + 青/蓝玻璃 UI 面板；火柴人戴红色毛线帽（无绒球）+ 黄 T 恤 + 黑色四肢/短裤，无细节眼睛。
  - 2B：同 2A 角色，全彩叙事环境（暖色房间/黄昏/山顶等渐变背景）。
  - 3：赭棕大地背景 + 纸张纹理 + 白色填充圆头 + 简单卡通表情 + 兽皮服装 + 小火堆点缀。
- 画幅 9:16（1080×1920）与 16:9（1920×1080），时长 30/60s；fps 30（如 CPU 太慢可 24，须写明）。
- 音频：Hevi TTS（CosyVoice 17600）合成中文旁白，全片同一音色；BGM（可程序合成的轻钢琴/pad，或仓库内已有免费素材）；SFX 优先来自 `feat/sfx-badclips` 的 `assets/audio/sfx/library/`（先 `git merge --no-commit --no-ff feat/sfx-badclips` 试合，有冲突就 `git merge --abort` 并改为只读 `git show feat/sfx-badclips:<path>` 取需要的 wav 拷入本分支自己的目录，在 DONE 里注明）。最终混音 loudnorm 到 −16 LUFS（TP ≤ −1.5）。
- 字幕：按词/标点切分（中文用 jieba 或标点+词边界，不得把一个词拆到两条或两行；英文不断词），按 TTS 实际时长对齐；字幕在安全区内，不溢出画面。字幕可烧录，同时输出 .srt。
- 画面：每 2–3s 姿势/机位/道具至少一项明显变化；人物始终完整在画内（骨骼包围盒留边距检查写进代码）。

### (c) fx registry
先 `git merge --no-commit --no-ff feat/fx-registry` 试合：无冲突则合并并把 5 个火柴人风格注册进 fx registry（按该分支的注册约定），加测试；有冲突则 `git merge --abort`，在代码里留 `# TODO(stickdir): register styles in fx registry after feat/fx-registry merges` 并写进 DONE。

### (d) 可选线路入口
提供 API 端点（新文件 `hevi/api/routers/stickdir.py`，`POST /api/stickdir/proposal`、`POST /api/stickdir/render`）或零行引擎挂钩（若 lines/registry 自动发现新 yaml/模块，则新增 `hevi/studio/lines/stickman_director.yaml`，不改现有文件）。若必须在 `hevi/api/main.py` 加 include_router，只加 1–2 行并在 DONE 注明。再给 CLI：`PYTHONPATH=$PWD .venv/bin/python -m hevi.layer4_legacy.stickdir.cli --copy-file x.txt --aspect 9:16 --duration 30 --style 1B --out out/`。

## 验收（真实测量，禁止 mock）
1. E2E 渲染两条样片（中文文案自选，200 字左右的真实观点短文）：
   - `out/stickdir_1B_9x16_30s.mp4`（style 1B，9:16，30s）
   - `out/stickdir_2A_16x9_30s.mp4`（style 2A，16:9，30s；如时间允许另出 1A/2B/3 各一条 10–30s 样片以证明风格差异）
2. ffprobe：时长 = 目标 ±0.5s，有音频流；`ffmpeg -af ebur128` 整体响度 −16±2 LUFS。
3. 每 1s 抽帧（写脚本 `scripts/stickdir_verify.py`，输出 json 报告 + contact sheet png）：
   - 每帧检测到火柴人（按风格前景色像素/连通域），且包围盒完全在画内（距边 ≥ 2%）；
   - 相邻 3s 窗口内火柴人姿势/轮廓差异超过阈值（证明每 ≤3s 有姿势变化）；
   - 字幕/文字框不越界（文字区域像素不触碰画面边缘或安全区外）；
   - 1A 背景角落/非角色区域像素 = 白（≥250），1B = 黑（≤5）——1A 至少出一条短样片（可 10s）用于此检查。
4. 字幕无断词：测试把 .srt 每条拼回与分词结果比对，不允许词被拆开。
5. pytest：proposal schema、白名单、无编造数字校验、9:16/16:9 调度差异、段尾段首 continuity、字幕切分、TTS/LLM 失败回退路径。
6. lint_after 失败数 ≤ 4（基线 4）。
7. 每步 commit。最后写 `STICKDIR_DONE.md`：做了什么、文件清单、接口（API/CLI/registry）、测试命令与真实输出、样片路径 + sha256 + ffprobe 原始输出 + LUFS、抽帧报告与 contact sheet 路径、实际使用的 TTS/LLM（CosyVoice 还是 piper、ollama 还是 fallback）、sfx/fx-registry 合并结果、lint 前后、已知限制。commit；文件最后一行写 `DONE STICKDIR-R1`。
