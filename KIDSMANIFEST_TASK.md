# KIDSMANIFEST_TASK — 单元 K1：幼儿故事闸门 + KidsConsistencyManifest（绑定 ShotSpec）

- worktree：`/data/soffy/projects/hevi-kidsmanifest`，分支 `feat/kids-manifest`
- 基线：`feat/kids-gate` HEAD `46d7c050`，已合并 `feat/shot-spec` `8b2588b2`（提供 `hevi/production/shot_spec.py` 校验器）→ 当前起点 `a241ada2`
- 依据：`/data/soffy/projects/hevi-renoise/RENOISE_EVAL.md` 第 3 节（尤其 3.1 试点片单、3.2 P1/P2、3.3 schema 与绑定规则）和第 4 节「单元 K1」。先完整读这两节。
- 完成文件：`KIDSMANIFEST_DONE.md`；完成标志（最后一行）：`DONE KIDSMANIFEST-R1`

## 目标
1. `kids_story_gate`（建议 `hevi/kids/story_gate.py` 或 `hevi/narrative/kids_story_gate.py`，复用 `hevi/narrative/quality.py`/`continuity.py` 的既有逻辑）：logline 生成/校验；6 节拍结构（开场问候→遇到问题→尝试（可失败一次）→解决→结尾复述主题（一句话+一个动作）→告别+互动问句）；THEREFORE/BUT 因果转场比 ≥30%；相邻节拍情绪不重复；单集单主题；固定 IP 角色/声音/配色一致；口语语言锁。
2. `KidsConsistencyManifest`（建议 `hevi/kids/consistency_manifest.py`，pydantic）：按 RENOISE_EVAL 3.3 的 schema 实现（字段：schema_version/project_id/episode/audience/theme/style_bible/characters/props/scenes/transition_table/spoken_language/shots[].shot_spec）+ 3.3 的 6 条绑定校验规则；`shots[].shot_spec` 的每个字段**委派**给 `hevi/production/shot_spec.py` 的既有校验器，不重复实现规则。与 ShotSpec 双向绑定（manifest → 任务 `shot_states.selection_json["shot_spec"]`，以及从 ShotSpec 回读）。
3. 两项能力注册进 `hevi/capabilities/registry.py`。
4. 4 部试点片单（RENOISE_EVAL 3.1：《小狐狸与星星》《轮流玩滑梯》《刷刷牙小怪兽》《种子发芽了》）写成 story 输入 fixture（自拟内容，放 `tests/fixtures/kids/`），做 dry-run（只规划/校验，不生成）。

## 可测验收标准
1. 对 4 部试点片单的 story 输入，gate 输出明确 `PASS/WARN/FAIL` + 逐条 finding（规则名 + 位置）。
2. 3 类坏样本必 FAIL：① 全 AND-THEN（因果转场 <30%）；② 相邻两拍同一情绪；③ 缺主题或缺固定角色。合规样本必 PASS。
3. manifest 校验：未知 `template/transition_in/sfx/style` → 失败（由 ShotSpec 校验器给出）；缺 Style Bible 任一段、缺任一 Transition Table 切点、未知 `@引用`、`duration<2.5`（或平均 <3.5s）→ 失败；合法 manifest → `OK`。
4. 确定性：同一输入连续两次输出的 JSON 字节一致（SHA-256 相同），在 DONE 里贴两次哈希。
5. 零网络、无 mock：断网可跑，无任何远程调用。
6. 至少 2 部片走完 `story → gate → manifest → ShotSpec dry-run` 全链路，产出可审阅 manifest JSON（提交到 `docs/kids/manifests/` 或 `tests/fixtures/kids/`）。
7. 新增单测全部真跑通过；相关既有测试（kids_gate、shot_spec）不回归；3O lint 失败数 ≤4。

## 与 K2 的接口
单元 K2（`feat/review-sheet`）并行开发并会消费本单元的 manifest schema。请在 DONE 里写清 schema 的模块路径、类名、`model_json_schema()` 导出位置，便于 K2 对接。

## 硬规则（必须遵守，违反即视为未完成）

1. **方向与契约**：开工前完整阅读本 worktree 根目录的 `KIDS_ANIME_DIRECTION.md`（Hevi 幼儿动漫方向）和 `CAPABILITY_CONTRACT.md`（能力契约）并遵守。本单元新增的每项能力都必须注册进 `hevi/capabilities/registry.py`，可被所有产线通过 registry 调用（`get/resolve`），并有测试证明可从 registry 调起。
2. **只在本 worktree 内工作**：不得修改主 checkout `/data/soffy/projects/hevi` 或任何其它 worktree；临时文件一律放本 worktree 的 `.tmp/`（并确保 `.tmp/` 不被提交）。
3. **CPU-only**：不调用任何付费 API / 远程 provider，不联网下载大模型；测试无网络出站。
4. **绝不删除 worktree 外的任何东西**；绝不"清理磁盘"，不删 node_modules、缓存、模型、其它项目文件。`df /data` 剩余 <5G 时写 `DISK_FULL_NOTE.md` 并立即停止。
5. **内存紧张**（整机 30G、多任务并行）：渲染与重测试单进程跑（pytest 不开 -n，ffmpeg 单路）；长任务用 `nohup setsid ... &` 启动并轮询到完成，产物完成前不得结束会话。
6. **禁止 mock / 占位 / 硬编码通过**：测试必须真跑真实代码路径和真实 ffmpeg/PIL 产物。pytest 以 soffy 身份运行：
   `JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=$PWD /data/soffy/projects/hevi/.venv/bin/python -m pytest <tests> -q`
7. **3O lint**：`PYTHONPATH=$PWD /data/soffy/projects/hevi/.venv/bin/python scripts/ci/run_3o_v3_lint.py`，失败数不得超过基线 4（基线 4 项：check_no_sibling_call / check_omodul_signature / check_enabled_pillars / check_oprim_keyword_only），不得新增失败项。lint 日志不要提交进仓库。
8. **许可**：Renoise 仓库无 LICENSE —— 只吸收方法论，不复制其原文或代码。BeefTV 为 MIT —— 借鉴的设计/代码须在仓库根 `NOTICE` 中署名，不得整包 vendor。
9. **git**：阶段性 commit，只 `git add` 自己创建/修改的文件（不要 `git add -A`）。不 push、不合并到其它分支、不改写历史。不要询问，直接执行到底。
10. **完成**：写 `KIDSMANIFEST_DONE.md`，如实记录每条验收标准的实测结果（命令、通过/失败数、SHA-256、产物路径），未达成的如实写明；最后一行写完成标志，然后 commit。
