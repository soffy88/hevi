# KIDSMANIFEST_FIX — R2 修复单（来自独立核验 verify_r1，结论 FAIL）

- worktree：`/data/soffy/projects/hevi-kidsmanifest`，分支 `feat/kids-manifest`，当前 HEAD 含 R1 提交 `84d9c0d7`/`916cc940`
- 先读：`KIDSMANIFEST_TASK.md`（仍有效，硬规则全部继续适用）、`audit/kidsmanifest/verify_r1/REPORT.md`、`audit/kidsmanifest/verify_r1/probe_counterexamples.py`、`probe_results.json`、`KIDS_ANIME_DIRECTION.md`、`CAPABILITY_CONTRACT.md`、RENOISE_EVAL §3.3/§4
- 完成：更新 `KIDSMANIFEST_DONE.md`（新增「R2 修复」一节，逐项写命令+结果），最后一行 `DONE KIDSMANIFEST-R2`，commit。不 push。
- 通用复现前缀（下文记为 `$PY`）：
  `cd /data/soffy/projects/hevi-kidsmanifest && PATH=$HOME/.local/bin:$PATH JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=$PWD /data/soffy/projects/hevi/.venv/bin/python`
- 总验收：`$PY audit/kidsmanifest/verify_r1/probe_counterexamples.py .tmp/probe_r2.json` 输出中，除 M13、M15（K2 范围，可保持 OK）外**不得出现 MISS**；且 G0_*/M0_ok/M0_ok2 仍为 PASS/OK。不要修改该 probe 脚本来"让它过"；修代码。

## 故事闸门（hevi/kids/story_gate.py）

### FIX-1 硬性安全：惊吓/暴力/成人主题必须 FAIL
- 复现：probe G1（怪兽吃小孩、血、刀枪、尸体）、G2（喝酒/抽烟/恋爱）
- 期望：status FAIL，新规则如 `R8_CONTENT_SAFETY`，location 指到 `logline`/`theme`/`beats[i].text`，message 列命中词
- 实际：PASS，无任何 finding
- 实现：本地确定性规则词表，覆盖 KIDS_ANIME_DIRECTION「禁止出现」全部类别（暴力、血、武器、恐怖、惊吓、危险行为示范、嘲笑羞辱、广告/品牌）+ 成人内容（酒、烟、恋爱/亲吻、赌博等）。优先复用 `hevi/quality/kids_gate.py` 已有台词词表（若有），不要两套词表。童趣「小怪兽」（《刷刷牙小怪兽》）不得误伤 —— G0 四部必须仍 PASS。
- 必须新增测试：G1/G2 FAIL 且 rule/location 正确；《刷刷牙小怪兽》仍 PASS。

### FIX-2 告别拍互动问句 + 复述拍「一句话+一个动作」+ 尝试拍
- 复现：G3（farewell「再见啦。」）、G8（recap「然后大家去睡觉了。」）
- 期望：farewell 末句必须是问句（？/?/吗/呢 结尾）否则 FAIL；recap 必须复述 theme（与 theme 实质重合，或显式 `recap_theme`/`action` 字段）且含一个动作，否则 FAIL/WARN；attempt 的 `failed_once` 语义落实（至多失败一次）
- 实际：均 PASS
- 必须新增测试：G3 FAIL、G8 FAIL 或 WARN，location 为 `beats[5]` / `beats[4]`

### FIX-3 口语语言锁真校验
- 复现：G4（spoken_language=zh-CN，台词全英文）
- 期望：FAIL `R7_SPOKEN_LANGUAGE`，location `beats[i].text`（按字符集/CJK 比例等确定性方法判断）
- 实际：PASS（只检查非空）
- 必须新增测试：G4 FAIL；四部试点仍 PASS

### FIX-4 情绪缺失不得静默通过
- 复现：G5（所有 emotion 为空）
- 期望：至少 WARN（建议 FAIL：6 拍都须有 emotion），location `beats[i].emotion`
- 实际：PASS
- 必须新增测试

### FIX-5 固定 IP 角色/声音/配色一致 + 单主题
- 复现：G6（fixed_characters=[char_bear]，全文只有小狐狸）、G7（theme 含 5 个并列主题）
- 期望：G6 FAIL/WARN —— 固定角色须在 story 中出现（beats 中出现其 id 或 name；story 输入允许 `characters: [{id,name,voice_ref,palette}]`），并提供 story↔manifest 交叉校验函数（story 固定角色必须在 manifest.characters 存在，且 voice_ref/palette/seed 一致）；G7 FAIL/WARN —— 主题由顿号/和/与等分隔出 ≥2 个独立主题判多主题
- 实际：均 PASS（只检查非空）
- 必须新增测试：G6、G7、story↔manifest 角色不一致 FAIL

### FIX-6 logline 生成 + 公式校验；复用既有 narrative 逻辑
- TASK 目标1 要求「logline 生成/校验」并「复用 hevi/narrative/quality.py / continuity.py」。当前只有 len≥8，未复用任何既有逻辑。
- 期望：确定性 `generate_logline(story)`（角色+问题+解决+主题），公式校验（含主角、问题/目标、结果/主题），并真实调用 `NarrativeQualityGate` 或 continuity 中可复用部分（确实不可复用则在 DONE 中写明原因与函数名）
- 必须新增测试：生成确定性；缺主角/缺问题的 logline FAIL

## Manifest（hevi/kids/consistency_manifest.py）

### FIX-7 固定角色锚点必须锁定
- 复现：probe M10（characters[0].anchor_ref/seed/voice_ref 全 None）
- 期望：FAIL（如 `M6_FIXED_CHARACTER`），location `characters[0].anchor_ref` 等
- 实际：OK
- 必须新增测试

### FIX-8 spoken_language 取值校验
- 复现：probe M11（spoken_language S3=en-US，audience.spoken_language=zh-CN）
- 期望：FAIL `M3_SPOKEN_LANGUAGE`，location `spoken_language[shot_index=3]`；spoken_language 中出现不存在的 shot_index 也 FAIL
- 实际：OK
- 必须新增测试

### FIX-9 时长绑定一致
- 复现：probe M9（shots[0].duration=4.0，shot_spec.duration=1.0）
- 期望：FAIL（如 `M5_DURATION_BINDING`）；shot_spec.duration 存在时须等于 shot.duration（容差 0.05s）；M5 的 ≥2.5/平均≥3.5 对实际渲染时长生效
- 实际：OK —— 实际渲染只有 1 秒却通过
- 另：`manifest_from_task_specs` 缺 durations 时默认 4.0 属编造值，改为取 spec.duration，缺失则报错
- 必须新增测试

### FIX-10 shot_index 唯一，切点按真实镜号
- 复现：probe M12（两个 shot_index=1）
- 期望：FAIL（如 `M7_SHOT_INDEX`）；M2 期望切点按排序后的真实 shot_index 生成，不是 `range(1,n)`
- 实际：OK
- 必须新增测试：重复镜号、跳号（1,2,4）

### FIX-11 @引用 扫描全部文本字段
- 复现：probe M7b（shots[2].camera="跟拍 @char_bear"）、M7c（theme.closing_action 含 @char_bear）
- 期望：FAIL `M4_REF_RESOLUTION`，location 精确到字段
- 实际：OK（只扫 line 与 transition_table）
- 实现：扫描 manifest 中所有字符串字段；若本 worktree 有 `hevi/huobao/refs.py` 则复用 `UnknownAssetReferenceError` 语义
- 必须新增测试

### FIX-12 M0 错误归类、errors 列表、shot_spec 未知字段
- 复现：
  `$PY -c "import json;from hevi.kids.consistency_manifest import validate_manifest;m=json.load(open('tests/fixtures/kids/manifest_fox_star.json'));del m['theme'];m['shots'][0]['shot_spec']['transition_in']='zz';print(validate_manifest(m).to_dict())"`
- 期望：缺 theme → `M_SCHEMA`（或类似），只有 loc 含 `shot_spec` 的才标 M0；errors 每条对应各自 loc
- 实际：两条都标 `M0_SHOTSPEC_DELEGATION`「ShotSpec 校验失败」，errors 两条都是 `M0:shots.0.shot_spec.transition_in`
- 另：shot_spec 未知字段（probe M14 `tempalte`）必须被拒 —— 在 manifest 层检查 shot_spec 原始 dict 的键 ⊆ `ShotSpec.model_fields`（不要改 shot_spec.py 行为；若必须改，shot_spec 全部测试须仍过）
- 必须新增测试

### FIX-13 绑定回写不得静默跳过
- 复现：probe B4（任务行 shot_index=99 不在 manifest → 静默跳过）
- 期望：`attach_to_task_shot_rows` 对两侧镜号不匹配返回/抛出明确错误（默认 strict 抛）
- 必须新增测试

### FIX-14 Style Bible 逐字前置（§3.3 规则3）
- 期望：提供 `compile_shot_prompt(manifest, shot_index)`（或接入 `hevi/prompt/h3_compiler.py` 扩展点），输出以 style_bible 四段**逐字**开头；校验函数检测 prompt 是否逐字包含四段，不含则 FAIL
- 必须新增测试：改 style_bible 任一字 → 编译结果随之改变；篡改后的 prompt 校验 FAIL

## 能力契约

### FIX-15 GET /api/capabilities 可见
- 复现：`$PY -c "from hevi.api.main import app;print(sorted(r.path for r in app.routes if 'capabilit' in r.path))"` → 无 `/api/capabilities`
- 期望：按 CAPABILITY_CONTRACT.md 新增 `GET /api/capabilities`（列出 registry 全部能力：name/kind/aspects/params_schema/description/line），返回含 `kids.story_gate`、`kids.consistency_manifest`、`qa.kids_gate`；独立 router 文件并挂到 app
- 必须新增测试：TestClient `GET /api/capabilities` 200 且含上述 3 个名字

### FIX-16 非法参数必须报错
- 复现：`get('kids.consistency_manifest').render({'wrong':1}, Path('.tmp/x'), duration=1, aspect='9:16', seed=1)` 不抛异常；`get('kids.story_gate').render({'story':'not a dict'},...)` 以 AttributeError 崩出
- 期望：两项新能力用 `params_schema` 校验参数（jsonschema 已安装则用之，否则最小手写校验），非法参数抛 `CapabilityError`（registry 无此类则在 registry.py 定义）
- 必须新增测试

## 测试质量
- 补：未知 template、未知 sfx 两条 manifest 测试（DONE R1 声称有但实际没有）
- 确定性测试改为两个独立子进程比较 SHA-256
- 每个 FIX 都要有对应测试，真实代码路径；不得 mock、不得硬编码期望输出
- 回归：`$PY -m pytest tests/test_kids_manifest.py tests/test_kids_gate.py tests/test_shot_spec_api.py tests/test_shot_spec_render.py -q` 全过（ffmpeg 在 `~/.local/bin`，PATH 必须包含）
- 3O lint 失败数仍 ≤4 且是基线 4 项
- 重新生成 `docs/kids/manifests/`、`docs/kids/gate_reports/`，DONE 中更新 SHA-256

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；所有 python 设 PYTHONPATH=/data/soffy/projects/hevi-kidsmanifest；不 push；不调付费 API；不要把 lint 日志提交进仓库。完成后在 KIDSMANIFEST_DONE.md 最后一行写 DONE KIDSMANIFEST-R2。
