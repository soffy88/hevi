# SHOTSPEC_DONE — W1 ShotSpec 后端(分支 feat/shot-spec)

GAP_PLAN §2 W1:为单镜引入统一规格 ShotSpec(模板/入场转场/特效/风格/音效/运镜/
字幕样式/时长),提供 API,并让 assembler 渲染时读取 spec。全部步骤已完成并提交,
验收数据来自真实 ffmpeg/ffprobe/测试输出(无 mock、无占位、无写死产物)。

## 做了什么

1. **规格模型 + 校验** `hevi/production/shot_spec.py`
   - pydantic v2 模型 `ShotSpec`,字段:`template` / `transition_in` / `effect` /
     `style` / `sfx`(list[{id, offset}])/ `camera` / `subtitle_style` / `duration`。
   - 取值全部对既有注册表/manifest 校验:template → FX 注册表(171 条)、
     transition_in → xfade 注册表(64 条,含 `cut` 硬切)、effect → 内置 5 种 +
     注册表 style 类(57 条)、sfx.id → sfx manifest(70 资产)+ 注册表 sfx 源。
     未知值 → pydantic ValidationError(FastAPI 转 422)。
   - `duration > 0`;`0 ≤ sfx.offset < duration`(给 duration 时校验,否则只校验非负)。
   - `style`:若 `hevi/layer4_legacy/dirstyle` 已合并则校验其风格 id,否则自由字符串
     (代码标注 `# TODO(dirstyle): validate once feat/director-styles merges`)。
     **未创建/改动任何 dirstyle 文件**。
   - 持久化:挂在任务现有存储 `shot_states.selection_json["shot_spec"]`(零迁移,
     与 `hevi/season_planner/preparation.py` 同构,不新建数据库)。

2. **API 路由** `hevi/api/routers/shot_spec.py`(挂到 `hevi/api/main.py`,prefix `/api`)
   - `GET   /tasks/{id}/shots/{i}/spec`  读单镜(未设置 → `spec: null`)
   - `PATCH /tasks/{id}/shots/{i}/spec`  部分更新(只覆盖显式给出的键;显式 null 清空)
   - `PUT   /tasks/{id}/shots/spec`      批量整组替换(逐条校验,任一非法整体 422;
     未列出的镜号规格清空)
   - 404:任务不存在/非本人、镜号不存在。复用 tasks 路由的 `get_repository` 依赖与鉴权。

3. **渲染** `hevi/production/shot_spec_render.py` + `hevi/assembly/assembler.py` 薄扩展
   - `effect_filter`:`warm→colortemperature=4000`、`cool→9500`、`mono→hue=s=0`、
     `vignette→vignette=PI/5`、`sharpen→unsharp`;注册表 style 类条目按 id 关键词
     尽力而为映射(blur/sketch/outline/mono/soft…),未命中即 no-op。
   - `seam_transitions`:逐镜 `transition_in`(第 1 镜忽略)→ `build_xfade_chain` 的
     逐接缝 token 列表;全等于默认时回落成 str,保持旧 filter_complex 逐字不变。
   - `shot_start_times`:各镜起点(扣 xfade 重叠,与 `build_xfade_chain` offset 公式
     **严格一致**)——sfx 定位基准。
   - `build_sfx_mixdown_filter`:各镜 sfx(起点+offset)→ adelay + amix 一段 filter,
     末级标签 `[specsfx]`,并入总混音。
   - `assemble_longvideo(shot_specs=...)` 仅经 xfade-pack 已提供接口扩展:每镜 effect
     并入归一化 `-vf`(`_normalize_shot(extra_vf=)`)、逐接缝转场走 `build_xfade_chain`
     的 list 支持、sfx 轨走 `build_audio_filter(extra_sfx_filter=)`。**不传 shot_specs
     时旧路径逐字不变**(test_xfade_pack 226 项全绿,含 golden filter_complex)。

## 文件清单(新增/修改)

新增:
- `hevi/production/shot_spec.py` — 模型 + 校验 + 持久化 helper
- `hevi/production/shot_spec_render.py` — spec → ffmpeg 片段(纯函数)
- `hevi/api/routers/shot_spec.py` — GET/PATCH/PUT
- `tests/test_shot_spec_api.py` — 19 项 API 单测(TestClient)
- `tests/test_shot_spec_render.py` — 12 项真实 ffmpeg 验收
- `scripts/shot_spec_demo.py` — E2E 样片生成
- `output/shotspec_e2e/record.json` — 样片记录(命令/filter_complex/ffprobe/sha256/spec)
- `lint_before.txt`(基线覆盖)、`lint_after.txt`

修改:
- `hevi/api/main.py` — 挂载 shot_spec router(2 行)
- `hevi/assembly/assembler.py` — `shot_specs` 可选参数 + `extra_vf`/`extra_sfx_filter`
  两处最小透传(向后兼容)

**未触碰**任何禁止改动文件(quality_profile / studio / style_presets / dirstyle /
capabilities / explainer / `hevi/fx/*` / `xfade_transitions.py`)。

## 接口

```
GET   /api/tasks/{task_id}/shots/{shot_index}/spec   → {task_id, shot_index, spec|null}
PATCH /api/tasks/{task_id}/shots/{shot_index}/spec   body=部分字段 → {.., spec}
PUT   /api/tasks/{task_id}/shots/spec                body={specs:[{shot_index,spec}]} → {count, specs}
```

ShotSpec 字段:`template, transition_in, effect, style, sfx[{id,offset}], camera,
subtitle_style, duration`(全部可选)。

## 测试命令与真实结果

```
PYTHONPATH=$PWD JWT_SECRET=test-secret-local .venv/bin/python -m pytest \
  tests/test_shot_spec_api.py tests/test_shot_spec_render.py -q
→ 31 passed, 1 warning in 20.71s      (19 API + 12 render)
```

- API:`tests/test_shot_spec_api.py` — **19 passed**。覆盖 GET 默认 null / 404;
  PATCH 设置+读回、部分更新保留未给字段、显式 null 清空、未知 template/transition/
  effect/sfx → 422、offset 越界(≥duration、负值)→ 422、duration ≤0 → 422、
  404;PUT 批量整组替换、未列出镜号清空、**部分非法整体 422(合法条目也不落库)**、
  404。
- 渲染验收:`tests/test_shot_spec_render.py` — **12 passed**(真实 ffmpeg,不 mock):
  - 起点公式与 `build_xfade_chain` 逐接缝 offset 一致(含 cut 接缝);
  - 音效位置:成片音轨 onset = 镜头起点(扣重叠)+ offset,误差 ≤0.1s(3 镜 4 cue,
    期望 0.5/1.8/3.3/4.0s);无 spec → 无音轨;有 spec → 有音轨;
  - 特效:mono 镜中段帧 |U−128| < 2 且 |V−128| < 2;warm 镜 R/B 比相对基线同刻帧
    上升 >0.05;
  - 转场:dissolve/whip 接缝中点帧与全硬切基线同刻帧 SSIM < 0.98;两接缝形态不同;
    spec 指定 `cut` 的接缝以原始画面硬切进入(SSIM > 0.95);
  - 时长 = Σ时长 − Σd(±1 帧);改 spec(warm→mono)重渲成片 sha 不同。
- 回归:`tests/test_xfade_pack.py` — **226 passed**(golden filter_complex 逐字不变,
  旧路径行为未改)。

## E2E 样片 `output/shotspec_e2e/`

4 镜 × 3s,1080x1920/30fps,lavfi 彩色素材(gradients/smptehdbars/rgbtestsrc/testsrc2);
3 镜带 spec(镜4 无 spec):镜1 effect=warm + whoosh_air_up@1.0;镜2 transition_in=
dissolve + effect=mono + impact_hard@0.5,ding_bell@2.0;镜3 transition_in=whip +
effect=cool + pop_dry@1.5。转场重叠 d=0.5,理论总时长 = 4×3 − 3×0.5 = **10.5s**。

| 产物 | ffprobe duration | 视频 | sha256(前 16) |
|---|---|---|---|
| `shotspec.mp4`(带 spec) | 10.500000 | h264 1080x1920 30/1 | `5f7fcc745826edf6` |
| `baseline.mp4`(无 spec) | 10.500000 | h264 1080x1920 30/1 | `93672ac5c9a4edd5` |
| `shotspec_repatch.mp4`(PATCH 后重渲) | 10.500000 | h264 1080x1920 30/1 | `91dbd382e5f065dd` |

- 完整 sha256 见 `record.json`。三份总时长均 10.5s(= Σ − Σd,与 spec 一致)。
- **spec 改动生效证明**:先渲 `shotspec.mp4`;再经真实 API(`PUT` 写入 3 份 spec →
  `PATCH` 镜1 `effect: warm→vignette` → `GET` 读回 `effect="vignette"`)后重渲,得
  `shotspec_repatch.mp4`,与 `shotspec.mp4` **sha256 不同**(内容确实变化)。
- `record.json` 记录三次渲染的真实 ffmpeg 调用(含 xfade filter_complex:接缝1
  `transition=dissolve`、接缝2 `transition=custom:expr=…whip…`)、ffprobe、sha256、spec JSON。

复现:`PYTHONPATH=$PWD .venv/bin/python scripts/shot_spec_demo.py`

## lint 前后

- `lint_before.txt`:`3O_V3_LINT=FAIL`,failed = check_no_sibling_call,
  check_omodul_signature, check_enabled_pillars, check_oprim_keyword_only(**4 项**)。
- `lint_after.txt`:failed 集合**完全相同**(同样 4 项,基线允许 ≤4)。
- 新增文件 `ruff check` 全部 `All checks passed`。

## 已知限制

- `effect` 的注册表 style 类条目按 id 关键词**尽力而为**映射(blur/sketch/outline/
  mono/soft…),未命中的 style id 是 no-op(不影响渲染,只记录一条 info 日志);
  这不是把 talkcraft 的视觉模板完整搬进 ffmpeg,只是可做的那部分滤镜近似。
- `style` 字段在 dirstyle 未合并期间是自由字符串(不做校验),合并后需接上校验
  (代码已留 TODO 锚点)。
- `camera` / `subtitle_style` / `template` 已建模并持久化,但当前渲染路径**未消费**:
  运镜属生成期 prompt(非装配期 ffmpeg),`template` 是 FX 注册表 id、装配期无对应
  滤镜;字幕样式只在有 subtitle_path 时经既有 `get_subtitle_filter` 生效。本单元只
  保证规格可存可校可读,不改变生成期行为。
- `shot_specs` 是 `assemble_longvideo` 的**可选**新参数;既有调用方(未传)行为逐字不变,
  未把 spec 自动接进 longvideo 编排链(超出本单元边界,遵循"最小侵入")。
- 音效混音电平固定 −3 dB(仅 spec sfx 轨);若同时有旁白/BGM,由总混音 amix 叠加,
  未做逐 sfx 的电平/ducking 控制。

DONE SHOTSPEC-R1
