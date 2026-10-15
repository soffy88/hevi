# KIDSMANIFEST-R1 独立核验报告（verify_r1）

- 核验对象：worktree `ubuntu26:/data/soffy/projects/hevi-kidsmanifest`，分支 `feat/kids-manifest`，提交 `84d9c0d7` + `916cc940`（只看 `1115f853..HEAD`）
- 核验时间：2026-10-15（Asia/Shanghai）
- 依据：`KIDSMANIFEST_TASK.md`；`/data/soffy/projects/hevi-renoise/RENOISE_EVAL.md` §3.3、§4 K1；`KIDS_ANIME_DIRECTION.md`；`CAPABILITY_CONTRACT.md`
- **结论：FAIL**（不 push；已写 `KIDSMANIFEST_FIX.md`，启动 R2）

## 证据文件（本目录）
- `probe_counterexamples.py` —— 核验员自写反例脚本（真实代码路径，无 mock）
- `probe_results.json` —— 44 个用例逐条结果（expect / got / verdict / detail）
- `pytest.txt` —— soffy 默认 PATH 下跑（ffmpeg 不在 PATH → kids_gate 6 例 FileNotFoundError，属环境，非回归）
- `pytest_with_ffmpeg.txt` —— PATH 加 `~/.local/bin`：`101 passed`（kids_manifest 24 + kids_gate 6 + shot_spec_api/render 71）
- `pytest_offline_unshare.txt` —— `unshare -n` 断网跑 `tests/test_kids_manifest.py`：`24 passed`
- `lint.txt` —— 3O lint：失败 4 项 = 基线（check_no_sibling_call / check_omodul_signature / check_enabled_pillars / check_oprim_keyword_only），无新增

## 逐条结果

| # | 项 | 结果 | 说明 |
|---|---|---|---|
| A1 | 验收1：4 部试点 gate 输出 PASS/WARN/FAIL + finding（规则名+位置） | 通过 | 4 部均 PASS，7 条 finding 带 rule+location |
| A2 | 验收2：3 类坏样本 FAIL、合规 PASS | 通过（字面） | 但规则本身过浅，见 F1 |
| A3 | 验收3：未知 template/transition_in/sfx/style → M0 失败（委派 ShotSpec） | 通过 | 4 种均由 `ShotSpec` 校验器报错，确为委派 |
| A4 | 验收3：缺 Style Bible 段 / 缺切点 / 未知 @引用(line) / duration<2.5 / 平均<3.5 → FAIL；合法 → OK | 通过 | probe M5/M5b/M6/M6b/M7/M8/M8b/M0_ok |
| A5 | 验收4：确定性 | 通过 | 两个独立进程哈希一致：gate fox `c28f1df5…`、manifest fox `720b84d8…`，与 DONE 一致；docs 文件哈希也一致 |
| A6 | 验收5：零网络、无 mock | 通过 | `unshare -n` 断网 24 passed；hevi/kids 无 requests/httpx/socket/mock |
| A7 | 验收6：≥2 部全链路 + manifest JSON | 通过 | fox_star / slide；manifest→`selection_json["shot_spec"]`→回读一致；改 manifest 会改变写回值 |
| A8 | 验收7：pytest / 不回归 / lint≤4 | 通过 | 101 passed（需 ffmpeg 在 PATH）；lint=4 基线 |
| A9 | DONE 中 schema 路径/类名 | 通过 | `hevi/kids/consistency_manifest.py::KidsConsistencyManifest`、`validate_manifest`、`model_json_schema()` 真实存在 |
| A10 | 能力注册 registry get/list | 通过 | `kids.story_gate`、`kids.consistency_manifest` 可 get/list/render |
| **F1** | **目标1：故事闸门规则实质缺失** | **FAIL** | 见下方「故事闸门反例」，8 个应拦反例全部 PASS |
| **F2** | **manifest 绑定/一致性漏洞** | **FAIL** | 缺角色锚点、语言冲突、时长绑定不一致、重复 shot_index、非 line 字段 @引用 全部 OK 放行 |
| **F3** | **GET /api/capabilities 不存在** | **FAIL** | `hevi.api.main.app.routes` 中无 `/api/capabilities`（只有 /api/creative/capabilities 等无关路由），契约要求的接入点不可见 |
| F4 | M0 把非 ShotSpec 错误也标成 ShotSpec 委派失败；errors 列表重复最后一个 loc | FAIL（小） | 删 theme → `M0_SHOTSPEC_DELEGATION @theme "ShotSpec 校验失败：Field required"`；errors=["M0:shots.0…","M0:shots.0…"] |
| F5 | Style Bible 编译期「逐字前置」(§3.3 规则3, `hevi/prompt/h3_compiler.py`) | 未实现 | 只检查非空 |
| F6 | 未复用 `hevi/narrative/quality.py` / `continuity.py`；logline 无「生成」、无公式校验（仅 len≥8） | 未达成 | TASK 目标1 明确要求 |
| F7 | 测试质量 | 不足 | 未知 template/sfx 无测试（DONE 声称有）；确定性只测同进程；无安全/语言/告别问句/锚点等反例测试；registry 非法参数不抛 CapabilityError（返回 qa FAIL，`validate_params` 为 no-op） |

### 故事闸门反例（全部应拦，实际全 PASS）
| id | 构造 | 期望 | 实际 |
|---|---|---|---|
| G1 | 惊吓/暴力：怪兽吃小孩、血、刀枪、尸体 | FAIL | PASS |
| G2 | 成人：喝酒抽烟谈恋爱 | FAIL | PASS |
| G3 | 告别拍「再见啦。」无互动问句 | FAIL | PASS |
| G4 | 声明 zh-CN，台词全英文 | FAIL | PASS |
| G5 | 全部节拍 emotion 为空 | FAIL/WARN | PASS |
| G6 | fixed_characters=[char_bear]，全文只有小狐狸 | FAIL/WARN | PASS |
| G7 | 主题「分享、刷牙、勇敢、轮流和种子发芽」 | FAIL/WARN | PASS |
| G8 | 复述拍「然后大家去睡觉了。」不复述主题无动作 | FAIL/WARN | PASS |

### manifest 反例
| id | 构造 | 期望 | 实际 |
|---|---|---|---|
| M10 | 角色 anchor_ref/seed/voice_ref 全空（缺角色锚点） | FAIL | OK |
| M11 | spoken_language S3=en-US，audience=zh-CN | FAIL | OK |
| M9 | shot.duration=4.0，shot_spec.duration=1.0 | FAIL | OK |
| M12 | 两个 shot_index=1 | FAIL | OK |
| M7b/M7c | `@char_bear` 写在 shots[].camera / theme.closing_action | FAIL | OK |
| M14 | shot_spec 拼写错字段 `tempalte`（静默忽略） | FAIL | OK（ShotSpec 基座也不禁 extra，记录） |
| B4 | 任务行 shot_index=99 不在 manifest | FAIL/WARN | 静默跳过 |
| M13/M15 | 场景色板与 color_grade 冲突 / age_max=18 | 参考 | OK（色板/服装冲突属 K2/P5，仅记录） |

## 判定
验收 1–7 的「字面」检查都能过，但测试集只覆盖了作者自造的 3 个坏样本；TASK 目标 1 要求的告别互动问句、复述一句话+动作、口语语言锁、固定 IP 角色/声音/配色一致、单主题，以及 KIDS_ANIME_DIRECTION 的硬性安全（惊吓/暴力/成人），实质都没实现；manifest 对角色锚点、语言、时长绑定、重复镜号、@引用范围存在放行漏洞；契约要求的 GET /api/capabilities 不可见。判 **FAIL**。
