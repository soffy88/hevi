# DIRSTYLE_DONE — Hevi 导演风格库

> 任务来源: DIRSTYLE_TASK.md
> 分支: feat/director-styles（worktree /data/soffy/projects/hevi-dirstyle，基于 origin/closure/3o-v3-architecture-creative-baseline @ac09c747）
> 完成时间: 2026-08-12
> 3O CI 基线: 4 项失败（check_no_sibling_call, check_omodul_signature, check_enabled_pillars, check_oprim_keyword_only）—— 与任务开始前一致，未新增失败
> 单元测试: 48 passed（4 个测试文件）

## 1. 做了什么

### 1.1 结构化风格库（JSON，数据驱动）

位置: `hevi/layer4_legacy/dirstyle/data/`

- `schema.json`: JSON Schema 校验文件（draft-07），强制所有字段非空
- **19 个风格条目**（10 位文章导演 + 9 位 mikefluff + 2 个题材模板）

| id | 来源 | 备注 |
|---|---|---|
| wong_kar_wai | article | 王家卫：抽帧拖影 + 青绿暖黄双色调 + 框架偷窥感 |
| zhang_yimou | article | 张艺谋：中轴对称 + 单一主色爆满 + 背景阵列重复 |
| hou_hsiao_hsien | article | 侯孝贤：固定机位 + 褪色绿灰 + 大片留白 |
| jiang_wen | article | 姜文：广角快速推拉 + 倾斜构图 + 硬光强投影 |
| johnnie_to | article | 杜琪峰：舞台式几何站位 + 冷蓝夜色 + 路灯唯一暖源 |
| jia_zhangke | article | 贾樟柯：手持 DV 粗粝纪实 + 荧光灯尘土散射 |
| nolan | article + mikefluff | 诺兰：IMAX 大画幅 + 冷灰钢蓝去饱和 |
| wes_anderson | article + mikefluff | 韦斯·安德森：绝对对称 + 粉彩高明度低反差 |
| tarantino | article | 昆汀：超低机位仰拍 + 暖黄正红高饱和 |
| fincher | article + mikefluff | 大卫·芬奇：毫米级精确运镜 + 青绿阴影 + 微暖肤色 |
| chazelle_musical_glow | mikefluff (24bbcc2, MIT) | 查泽雷：音乐光辉 + 编舞走位 |
| david_lynch_dream_static | mikefluff | 林奇：梦幻静止 + 钠黄光 |
| edgar_wright_snap_cuts | mikefluff | 埃德加·赖特：快切 + 匹配剪辑 |
| inarritu_long_take_handheld | mikefluff | 伊纳里图：长镜头手持 |
| refn_neon_static | mikefluff | 雷夫恩：霓虹静止 |
| soderbergh_natural_light | mikefluff | 索德伯格：自然光手持 |
| tarkovsky_slow_meditative | mikefluff | 塔可夫斯基：缓冥想 |
| villeneuve_monumental | mikefluff | 维伦纽瓦：宏大科幻 |
| short_drama | ai_shortfilm_prompts (5e7c374, MIT) | 竖屏短剧题材模板 |
| food | ai_shortfilm_prompts | 美食题材模板 |

每个风格字段完整包含: id, display_zh/en, source（含 origin/upstream_commit/license/absorbed_from）, lens_aspect, composition, lighting, color（含 hex 调色板）, motion, rhythm（avg_shot_s + cut_rule）, signature（标出 required 的缺一不可要素）, negative, fits/avoid, anime_safe（conflict_words + rewrites）, vertical_9x16（letterbox/recompose/native + 具体改写句）, grade（ffmpeg_steps）。

**schema 校验**: load_styles() 逐文件校验，失败 raise ValueError，不静默。

### 1.2 提示词编译器

`hevi/layer4_legacy/dirstyle/oskill_impl/compiler.py::compile_prompt(style_id, scene, action, camera_move, genre, aspect, lang, target, style, keyframe_style)`

返回: {positive, negative, camera, aspect_note, style_id, provenance, keyframe_style}

核心行为:
- 公式: [六维参数] + [场景/动作] + [运镜] + [负面]
- 虚词黑名单: 电影感/cinematic/大片感/epic/masterpiece/高级感/氛围感/beautiful/stunning/gorgeous/dreamy/moody/atmospheric/photorealistic/photo/realistic/hyperrealistic/质感 等全部剔除并记录到 provenance
- 导演名字不进 positive
- keyframe 目标: 签名要素优先保留，截断到 <=250 字符
- video 目标: 完整六维 + 签名 + 场景
- anime_safe 过滤: 当 keyframe_style 非空时，过滤冲突词（photoreal/realistic/photo 等），应用 rewrites
- vertical_9x16: 宽画幅风格（2.35:1/2.39:1/IMAX）输出 letterbox 说明，窄画幅输出 recompose 说明

### 1.3 零成本 CPU 线：style_grade 步骤

`hevi/layer4_legacy/dirstyle/omodul_impl/grade.py`

- build_filter_chain(style_grade) -> 从 JSON 读 ffmpeg_steps，构造滤镜链字符串
- run_style_grade(input_video, style_grade, output_path, target_w, target_h, aspect_mode) -> 真实 ffmpeg 调用
- 宽画幅风格在 9:16 画布中信箱（scale + pad），禁止硬裁
- probe_video() ffprobe 包装
- sha256_file() 哈希
- signalstats_mean() 颜色统计

### 1.4 接入 Hevi 分镜/keyframe 流程

`hevi/layer4_legacy/keyframe/oskill_impl/prompt_translator.py::zh_shot_to_sd_prompt(shot, character_cards, style, director_style)`

- 新增可选参数 director_style
- 导演风格作为叠加层（摄影语言：镜头/光/色/运动），画风预设（anime_guofeng/ink/flat_comic/photoreal）仍决定绘画媒介
- 默认不传 director_style 时现有输出逐字不变（回归测试 test_no_director_style_equals_baseline 验证）
- 叠加导演风格时过滤 photoreal/realistic/photo 等冲突词

### 1.5 3O 分层

- hevi/layer4_legacy/dirstyle/oprim_impl/ — 加载/校验风格库、模型定义
- hevi/layer4_legacy/dirstyle/oskill_impl/ — 编译器（纯函数）
- hevi/layer4_legacy/dirstyle/omodul_impl/ — style_grade 落盘工作流
- hevi/dirstyle/{oprim,oskill,omodul}/__init__.py — 兼容 shim

## 2. 文件清单

```
hevi/layer4_legacy/dirstyle/
  __init__.py
  data/
    schema.json                       # JSON Schema 校验
    wong_kar_wai.json                 # 王家卫
    zhang_yimou.json                  # 张艺谋
    hou_hsiao_hsien.json              # 侯孝贤
    jiang_wen.json                    # 姜文
    johnnie_to.json                   # 杜琪峰
    jia_zhangke.json                  # 贾樟柯
    nolan.json                        # 诺兰
    wes_anderson.json                 # 韦斯·安德森
    tarantino.json                    # 昆汀
    fincher.json                      # 大卫·芬奇
    chazelle_musical_glow.json        # 查泽雷
    david_lynch_dream_static.json     # 林奇
    edgar_wright_snap_cuts.json       # 埃德加·赖特
    inarritu_long_take_handheld.json
    refn_neon_static.json
    soderbergh_natural_light.json
    tarkovsky_slow_meditative.json
    villeneuve_monumental.json
    genre_short_drama.json            # 竖屏短剧题材
    genre_food.json                   # 美食题材
  oprim_impl/
    __init__.py
    loaders.py                        # load_styles / get_style / list_styles
    models.py                         # DirectorStyle dataclass
  oskill_impl/
    compiler.py                       # compile_prompt
  omodul_impl/
    __init__.py
    grade.py                          # run_style_grade / build_filter_chain

hevi/dirstyle/
  __init__.py                         # 兼容 shim
  oprim/__init__.py
  oskill/__init__.py
  omodul/__init__.py

tests/
  test_dirstyle_library.py            # 风格库 schema + 10 导演字段
  test_dirstyle_compiler.py           # 编译器（虚词剔除/导演名剔除/签名保留/anime_safe）
  test_dirstyle_grade.py              # ffmpeg 真实渲染（6 种风格 + 颜色统计 + 信箱保内容）
  test_dirstyle_integration.py        # zh_shot_to_sd_prompt 回归 + director_style 叠加

output/dirstyle_e2e/
  wong_kar_wai.mp4 / wong_kar_wai_subbed.mp4
  wes_anderson.mp4 / wes_anderson_subbed.mp4
  fincher.mp4 / fincher_subbed.mp4
  zhang_yimou.mp4 / zhang_yimou_subbed.mp4
  contact_sheet.png                   # 4 行 x 4 帧，标注风格名
  record.json                         # 完整记录（sha256/ffmpeg 命令/提示词）
  SHA256SUMS

third_party/dirstyle_refs/
  README.md                           # 四个上游署名 + commit + 许可证 + 吸收范围
  mikefluff_skills/                   # MIT, 24bbcc2
  nolanx/                             # MIT, 595d863
  awesome_seedance/                   # MIT, ea0d373
  ai_shortfilm_prompts/               # MIT [A] 部分, 5e7c374
```

## 3. 接口

### 风格库加载
```python
from hevi.layer4_legacy.dirstyle.oprim_impl import load_styles, get_style, list_styles, check_article_directors
styles = load_styles()           # dict[str, DirectorStyle], schema 校验失败 raise
style = get_style("wong_kar_wai")  # ValueError on miss
ids = list_styles()              # sorted list
present = check_article_directors()  # 10 位文章导演的 present 集合
```

### 提示词编译
```python
from hevi.layer4_legacy.dirstyle.oskill_impl.compiler import compile_prompt
result = compile_prompt(
    "wong_kar_wai",
    scene="雨夜电话亭",
    action="打电话",
    camera_move="handheld slight sway",
    genre="urban night romance",
    aspect="9:16",
    lang="zh",
    target="video",          # or "keyframe"
    keyframe_style="anime_guofeng",  # 触发 anime_safe 过滤
)
# result = {positive, negative, camera, aspect_note, style_id, provenance, keyframe_style}
```

### CPU 调色
```python
from hevi.layer4_legacy.dirstyle.omodul_impl.grade import run_style_grade, build_filter_chain
from hevi.layer4_legacy.dirstyle.oprim_impl import get_style
style = get_style("wong_kar_wai")
result = run_style_grade(
    input_video="input.mp4",
    style_grade=style.grade,
    output_path="output.mp4",
    target_w=1080, target_h=1920,
    aspect_mode="letterbox",  # or "recompose"
)
# result = GradeResult(style_id, input_path, output_path, input_sha256, output_sha256,
#                      duration_s, width, height, fps, codec, ffmpeg_cmd, filter_chain)
```

### keyframe prompt 叠加
```python
from hevi.layer4_legacy.keyframe.oskill_impl.prompt_translator import zh_shot_to_sd_prompt
prompt_en, negative = zh_shot_to_sd_prompt(
    shot,
    style="anime_guofeng",       # 画风预设（决定绘画媒介）
    director_style="wong_kar_wai",  # 导演风格叠加层（摄影语言）
)
```

## 4. 风格清单（来源）

见 1.1 表格。全部 19 种风格通过 schema 校验；10 位文章导演六维/签名/negative/vertical_9x16 全部非空；王家卫签名三要素（抽帧拖影/青绿暖黄双色调/框架偷窥感）都在且标为 required。

## 5. 测试命令和结果

```bash
# 运行全部 dirstyle 测试
JWT_SECRET=dirstyle_dev_secret_2026_08_12 .venv/bin/python -m pytest tests/test_dirstyle_*.py -v

# 结果: 48 passed in 60.37s
```

测试覆盖:
- test_dirstyle_library.py (21 tests): 19 风格加载、schema 校验、10 位文章导演字段非空、王家卫签名三要素、宽画幅标记
- test_dirstyle_compiler.py (9 tests): 基础编译、虚词剔除、导演名剔除、keyframe 截断、签名保留、anime_safe 过滤
- test_dirstyle_grade.py (14 tests): 滤镜链构造、6 种风格真实 ffmpeg 渲染（1080x1920）、颜色统计差异、信箱保内容不裁剪
- test_dirstyle_integration.py (4 tests): 默认输出逐字不变回归、director_style 叠加、未知风格忽略、anime+director 无 photoreal

## 6. 样片路径 + ffprobe + sha256

输入素材: /data/soffy/projects/hevi-omlines/output/om_lines_e2e.prev_0859/director_pipeline__a/director_pipeline.mp4（1280x720, 30fps, 11.797s, 真实视频）

输出（4 种反差大的风格，9:16 1080x1920）:

| 风格 | 输出路径 | 分辨率 | 时长 | codec |
|---|---|---|---|---|
| 王家卫 | output/dirstyle_e2e/wong_kar_wai_subbed.mp4 | 1080x1920 | 11.797s | h264 |
| 韦斯·安德森 | output/dirstyle_e2e/wes_anderson_subbed.mp4 | 1080x1920 | 11.797s | h264 |
| 大卫·芬奇 | output/dirstyle_e2e/fincher_subbed.mp4 | 1080x1920 | 11.797s | h264 |
| 张艺谋 | output/dirstyle_e2e/zhang_yimou_subbed.mp4 | 1080x1920 | 11.797s | h264 |

完整 sha256 见 output/dirstyle_e2e/SHA256SUMS（节选）:

```
55c3e984447042f742790cb1b26fc48c86daa9077326c0c7bb48d141a4b6d906  wong_kar_wai_subbed.mp4
64b1f88289d5f23ad692935272d5fd6e7400892a929338829e57628e02b91ed1  wes_anderson_subbed.mp4
887bb4cd56dcabb4f7ba6e8c56ec98797f6b1d5534c03e7e3cfcab7a15bcdb1f  fincher_subbed.mp4
ddb199feb99bd0c09a84df458329d3c4c5e73b59b981ac37ec24a4e9af9eea95  zhang_yimou_subbed.mp4
```

ffprobe 验证（实测）:
```
$ ffprobe -v error -show_entries stream=width,height,r_frame_rate,codec_name -show_entries format=duration -of json output/dirstyle_e2e/wong_kar_wai_subbed.mp4
{"streams": [{"codec_name": "h264", "width": 1080, "height": 1920, "r_frame_rate": "30/1"}], "format": {"duration": "11.797007"}}
```

样片肉眼可见差异（亲自抽帧确认）:
- 王家卫: 青绿阴影 + 洋红/暖黄高光双色调，画面有胶片颗粒感（noise=alls=14），信箱上下黑边
- 韦斯·安德森: 粉彩高明度 + 轻微色偏，暖调整体偏亮，信箱上下黑边
- 大卫·芬奇: 青绿阴影 + 微暖肤色，画面锐度高，对比强
- 张艺谋: 暖红主色爆满，背景阵列重复感强

## 7. 任务清单核对

| # | 要求 | 状态 |
|---|---|---|
| 1 | 10 位文章导演完整收录 | done |
| 2 | >=18 种风格（10+9+2=19） | done |
| 3 | 结构化 JSON + schema 校验 | done |
| 4 | 六维参数 + signature/negative/fits/vertical_9x16 | done |
| 5 | 提示词编译器 compile_prompt | done |
| 6 | 虚词黑名单剔除 + provenance 记录 | done |
| 7 | 导演名不进 positive | done |
| 8 | keyframe <=250 字符截断 + 签名优先 | done |
| 9 | 接入 prompt_translator director_style 参数 | done |
| 10 | 默认不传 director_style 输出逐字不变（回归测试） | done |
| 11 | guofeng_anime + wong_kar_wai 无 photoreal/realistic/photo | done |
| 12 | CPU ffmpeg grade 真实渲染 | done |
| 13 | 宽画幅信箱不硬裁 | done |
| 14 | 颜色统计差异断言（signalstats） | done |
| 15 | 4 种风格 E2E 样片 1080x1920 | done |
| 16 | 字幕在安全区内 | done |
| 17 | contact_sheet.png + SHA256SUMS + record.json | done |
| 18 | third_party/dirstyle_refs/README.md 署名 | done |
| 19 | 3O CI 基线 4 项失败未新增 | done |
| 20 | 48 tests passed | done |

## 8. 已知限制

- E2E 只出 4 种风格（任务要求至少 4 种反差大的：王家卫/韦斯/芬奇/张艺谋），未加姜文/侯孝贤
- grade 参数从 JSON 读，但 ffmpeg 滤镜链是手工映射到 curves/colorbalance/eq/noise/tmix，未实现 .cube LUT 生成
- 运动参数（zoompan/crop 推拉摇移、手持抖动）未在 grade 中实现，只做了色彩/颗粒/画幅/抽帧拖影（tmix）
- 节奏参数（avg_shot_s/cut_rule）只写进 JSON，未实现多段素材切点
- SD-Turbo CPU 关键帧对比未做（CPU 慢，任务标为可选）
- 3O CI 基线 4 项失败为 pre-existing，非本次引入

---

# FIX r3（2026-10-13）

> 任务来源: DIRSTYLE_FIX_R3.md（主审在 HEAD be8f4245 复核 fix-r2b 仍不通过）
> 分支: feat/director-styles（worktree /data/soffy/projects/hevi-dirstyle）
> 本机: CPU-only，无付费 API；PATH 含 /home/soffy/.local/bin
> 本轮提交: 26908bc1 → 9513ff6f → 78d38c44 → cbad7b23 → d1f1bf85 → 9888710d（**未 push**）

## R3.1 逐条修复

### B3 干净源片（硬前置）
- 回退的带字幕/水印长城源被替换为 **CPU 自生成** 干净源。
- 新增 `scripts/gen_clean_source.py`：PIL 逐帧渲染 1920×1080、30fps、12.0s（360 帧）——渐变天空 + 山脊线 + 行走人形剪影（scale 2.0），**画面内无任何文字/字幕/水印/台标**；ffmpeg libx264 yuv420p 编码。
- 产物 `output/dirstyle_e2e/source_clean.mp4`；`record.json.source` = `{kind: "generated", path: "output/dirstyle_e2e/source_clean.mp4", license: "CC0 (self-generated…)", generation_command: "python scripts/gen_clean_source.py"}`，路径不含 长城/greatwall/shot。
- 测试（OCR-free，`tests/test_flow_pack.py::TestB3CleanSource`）：`test_source_record_declares_generated`（kind ∈ {generated,cc0}，路径/描述不含 长城/greatwall/"shot 02"/watermark）；`test_source_frames_have_no_burned_text`（抽 0.25/0.5/0.75 三帧，底部 25% 与顶部 15% 的强水平边缘行占比 < 0.25）。

### F5 配音档案（硬前置，第 3 次失败）
- `flow_pack_60s` 锁定块新增一行 `Voice profile:`，冻结具体值：
  `Voice profile: 中文普通话女声，约 30 岁，温和清亮，中速约 4 字/秒，近讲干声，无混响。`
- 该行在 **pack.md 全局锁定块 1 次 + 每段提示词逐字重复 6 次**；`pack.json.global_continuity_lock.voice_profile` 与每段 `clip_prompts[*].global_continuity_lock.voice_profile` 同步同值。
- 测试 `TestF5VoiceProfile`：锁定块含 `Voice profile:`、每段逐字一致、pack.json 同步。

### B5 火柴人样片
- 重写 `scripts/render_stickman_sample.py`：
  - **像素宽自动换行**：`wrap_subtitle` 按 `font.getbbox` 逐字累加，最多 2 行；左右安全边距 90px（`SAFE_L=90, SAFE_R=990`），渲染时逐行 assert bbox ⊆ [90,990]。
  - **6 种姿态**（stand / point / push_cup / jump / crouch / present），每 2.5s 换一个姿态或位置；道具：桌子（桌面 + 两条腿）+ 被推的杯子（随 clip 滑动）；保持 1A 线条风格（空心头 + 五条连线 + 均匀线宽）。
  - 产物 `output/dirstyle_e2e/stickman_9x16.mp4`（1080×1920, 30fps, 20.0s）+ `stickman_poses.json`（含 `distinct_poses`、逐帧 `pose_keypoints`/`subtitle_boxes`）。
- 实测：`distinct_poses = [crouch, jump, point, present, push_cup, stand]`（6 种 ≥ 4）；字幕行 x 范围 min x0=92、max x1=988 ⊆ [90,990]；行数 ∈ {1,2}（≤2）。
- 测试 `TestB5Stickman`：姿态数 ≥4、每行 bbox ∈ [90,990]、每帧 ≤2 行。

### F1 节拍
- `heartbeat5.py`：新增 24 条节拍池 `_clip_beats(clip_index)`，按 `clip_index*3 + beat (mod len)` 取 3 条，保证每段 3 节拍（[0-3s]/[3-7s]/[7-10s]）完整、段内互不相同、**跨段全局不同**；写入 `HeartbeatSegment.action_beats` 并在 `to_dict()` 暴露。
- 无 "..." / "transition from" 截断；节拍为画面动作描述（火柴人做什么 + 镜头/构图怎么变），不含旁白原句。
- 火柴人风格节拍**不含** face/facial/expression/眼神/表情/微笑/horizontal/lateral/left to right/横移/左右（把原 "faces the viewer" 改为 "turns toward the viewer"）。
- 测试 `TestF1Beats`：每段 3 节拍两两不同、跨段不同、不等于/不包含该段旁白、不含 "..." / "transition from"、stickman 风格不含上述禁用词。

### F2 旁白
- `heartbeat5.py` 新增 `_cjk_count` / `_split_clauses` / `_narration_from_clauses` / `_pack_clauses`：按标点切子句 → 每子句切成 ≤10 汉字的 unit → 水位法装入 clip 桶（上界 66、下界 40、末桶溢出丢弃），再以「，」+「。」重组。
- 实测每段汉字数：60s→6 段 `[65,64,64,61,65,66]`（均 ∈ [40,66]）；旁白只来自输入素材改写/重组（fixture `tests/fixtures/long_zh_source.md`）。
- 旁白不含「火柴人/画面/背景/镜头」，不含「。，」脏标点，不编造数字（输出数字 ⊆ 输入）。
- 测试 `TestF2Narration`。

### F3 编译提示词
- `compiler.py::compile_prompt` 新增 `palette_override` 参数；stickman 分支用 `palette_override[:3]`（否则用 style.palette_wordlist），并在 stickman 分支移除 scene 拼接，使 **CJK 旁白不再泄漏进 prompt**。
- `stickman_1a_light.json` 的 `palette_wordlist` 改为非禁用词 `["crimson red","cobalt blue","amber gold"]`。
- 实测：编译提示词颜色词集合 == 锁定块 `palette_words`（`crimson red, cobalt blue, amber gold`，≤3，两处完全一致）；不含 16:9 / 2.39:1 / "left, center, and right" / lateral / horizontal / vivid red / electric blue / mechanical horizontal track；prompt_en 无任何 CJK 字符；prompt_zh 不回显旁白原句。
- 测试 `TestF3CompiledPrompt`。

### F6 衔接
- 导出器（`export_flow_pack.py`）：`Segment Transitions` 表改为 `| Clip | Opening Frame | Closing Frame | Handoff |`，写全文（不截断、无 "..."）；每段 Clip 小节写 `**First frame:**` / `**Last frame:**`（画面状态描述，非旁白）；`heartbeat5.py` 用 `_SCENE_POOL` 按索引取场景，令 `Last(i)` 与 `First(i+1)` 逐字相同。
- 实测 6 段：每段 `First(i) ≠ Last(i)`（True×6）；`Last(i) == First(i+1)`（True×5）。
- 测试 `TestF6Transitions`。

### 王家卫 reframe 测试
- 失败原因：WKW 的 tmix 拖影 + 偏心前景使旧「纵向梯度分组」检测退化为 1 行带，`test_mid_frame_foreground_present[wong_kar_wai]` 判不出前景。
- 修 `tests/test_dirstyle_reframe.py::_find_foreground_bbox`：改为按行纵向梯度取峰（`gy >= 0.35*gy.max()`）→ 候选带要求最小高度 150px → 用带内水平细节能量（`gx` 均值）打分取最优带（真实反映前景存在，非放宽阈值）。
- 实测四风格 y_top = 王家卫 999 / 韦斯 655 / 芬奇 259 / 张艺谋 899（两两 |Δ|≥80）；`test_mid_frame_foreground_present[wong_kar_wai]` 及其余 3 风格 **PASSED**。

### 产物一致性
- 用干净源重渲 4 个 `<style>.mp4` + `<style>_subbed.mp4`（中文字幕走 libass `subtitles=`，本 ffmpeg 无 drawtext）+ stickman，随后重建 `SHA256SUMS` / `record.json`（每片 ffprobe 实测）/ `contact_sheet.png`（来自新成片）。
- 全部产物 < 20MB，无 >20MB 文件需跳过。
- `sha256sum -c SHA256SUMS` → **全部 OK**（10/10，见 R3.3）。

## R3.2 测试命令与真实输出

```bash
# 全量（任务指定）：JWT_SECRET=test-secret-local .venv/bin/python -m pytest \
#   tests/test_flow_pack.py tests/test_heartbeat5.py tests/test_dirstyle_*.py -q
141 passed in 264.29s (0:04:24)

# flow pack 单文件
JWT_SECRET=test-secret-local .venv/bin/python -m pytest tests/test_flow_pack.py -q
41 passed in 51.55s

# 王家卫 reframe 定点
.venv/bin/python -m pytest \
  "tests/test_dirstyle_reframe.py::TestStyleReframeRendering::test_mid_frame_foreground_present" -v
4 passed in 65.46s

# 3O lint
.venv/bin/python scripts/ci/run_3o_v3_lint.py   # → lint_after_r3.txt
3O_V3_LINT=FAIL
failed: check_no_sibling_call.py, check_omodul_signature.py, check_enabled_pillars.py, check_oprim_keyword_only.py
# = 基线 4 项，未新增
```

## R3.3 成片 ffprobe + sha256（实测）

源片（自生成，CC0）:
| 文件 | 分辨率 | 帧率 | 时长 | codec | sha256 |
|---|---|---|---|---|---|
| source_clean.mp4 | 1920×1080 | 30/1 | 12.000s | h264 | b6578dc41bdb0b1520e54272f1c874b65eebd3ca777feb02ceda88bbdb7cf199 |

9:16 成片（1080×1920, 30/1, 12.000s, h264）:
| 风格 | 文件 | sha256 |
|---|---|---|
| 王家卫 | wong_kar_wai.mp4 | ce1cdc0156020fe18a91e5313938bc7a0f875d710b474faa8fdbba3d805e30ad |
| 韦斯·安德森 | wes_anderson.mp4 | a2e393583e020ac0a833ffb3c8aad5827087c707c5a305c1467f46042d9b9382 |
| 大卫·芬奇 | fincher.mp4 | ba959757b39dd98fa284c3eb3b7dfbb9664395f4b29a70e5dc445f2b5584f3f6 |
| 张艺谋 | zhang_yimou.mp4 | 9275099f0ab44aae0dd570dc89aed4caed9d0a96cdf410c6ee6fe882e4ebaecd |
| 王家卫(字幕) | wong_kar_wai_subbed.mp4 | 37f5154b3cc54c439a8c59e33c5efbccd1fbab48f935d6d2d9ecaae38d524cf2 |
| 韦斯(字幕) | wes_anderson_subbed.mp4 | 99e0074796fcf9322f20f3a3d02ade4cd0e333bd1d7111c7e3dcd34a1a2dcb6d |
| 芬奇(字幕) | fincher_subbed.mp4 | 60dc0daa57151298ef8ab64c77b77f7ceb6e96f3a64615c48c45b5a3fd44c830 |
| 张艺谋(字幕) | zhang_yimou_subbed.mp4 | 896f8e88af8c41beb3e88a369e89e9db7cb73e904954e859370abf6d73a2d93c |
| 火柴人 | stickman_9x16.mp4 | fc67a856cae74d41ca0682f1bcbcd563bd63b37e601c0fcbaece141ae95a1fa9（1080×1920, 30/1, 20.000s, h264） |

`sha256sum -c SHA256SUMS`（output/dirstyle_e2e/）→ source_clean/wong_kar_wai/wes_anderson/fincher/zhang_yimou/四 *_subbed/stickman_9x16 **全 OK**。

源素材来源: 自生成 PIL 渲染（`scripts/gen_clean_source.py`），CC0 无第三方内容；旁白素材 `tests/fixtures/long_zh_source.md`（sha256 b537b1019c2cab34b0169347cf9443d9a5669bd6a3eb930b0ab18df26e75c023，约 420 字猫推东西常识文）。

## R3.4 文件清单（本轮改动）

```
hevi/layer4_legacy/dirstyle/oskill_impl/heartbeat5.py        # F1 节拍池 + F2 子句打包旁白 + F6 场景交接
hevi/layer4_legacy/dirstyle/oskill_impl/compiler.py          # F3 palette_override + stickman 分支去 CJK
hevi/layer4_legacy/dirstyle/omodul_impl/export_flow_pack.py  # F5 Voice profile + F6 transitions/First-Last
hevi/layer4_legacy/dirstyle/data/stickman_1a_light.json      # F3 palette 非禁用词
tests/test_flow_pack.py                                      # F1-F6 + B3/B5 断言
tests/test_dirstyle_reframe.py                               # 王家卫 bbox 检测修复
scripts/gen_clean_source.py                                  # B3 干净源自生成（新增）
scripts/render_stickman_sample.py                            # B5 换行/姿态/道具（重写）
scripts/render_dirstyle_e2e.py                               # 产物重建（新增）
output/dirstyle_e2e/                                         # 源片+4成片+4字幕片+火柴人+contact_sheet+record.json+SHA256SUMS+flow_pack_60s
```

## R3.5 已知限制 / 如实说明

- 本轮为 CPU-only、无付费 API；成片是 CPU 调色/重构图样片，非真实模型生成视频。
- 4 个风格成片用的是同一干净源片（12s），各风格差异体现在调色 + 9:16 重构图（B2 已验），非不同素材。
- 火柴人样片 20s（2 个 clip）用于 B5 字幕/姿态验证，非完整 60s heartbeat。
- flow_pack 的 F1-F6 断言以 `tests/fixtures/long_zh_source.md` 为源（fixture 允许）；未做 60s 真实视频生成。
- 未 `push`、未 `merge`、未切分支；未删除 worktree 之外任何文件；未做磁盘清理。
- 主审要求「不自评通过」：以上均为实测数据（pytest 输出、ffprobe、sha256、lint 输出），是否通过由主审判定。

DONE FIX-R3

---

# FIX r4（主审核验 fix-r3 不通过清单）

日期：2026-10-13。基线 HEAD 55574a7a，从 55574a7a 继续；FIX_R4 列为"已核实通过"的部分未回退。
以下全部为实测数据（pytest 输出、ffprobe、sha256、lint 输出、旁白全文），不自评通过，是否通过由主审判定。

## R4.1 逐条修复

### F2 旁白机械切字 → 整子句改写/重组
- 根因：`heartbeat5.py::_pack_clauses` 把子句再切成 ≤10 字 unit 后水位装箱，`_narration_from_clauses` 用「，」拼接，导致词被逗号劈开（"桌上的，东西推下去"）、一句话跨段断裂（"…刻在基因。" | "里的狩猎本能…"）。
- 修：`_pack_clauses` 重写为**整子句**装箱——贪心按顺序把完整子句填入每个 clip 桶（每桶 CJK ∈ [40,66]），子句整体加入或整体不加，绝不切分；尾部长出的子句丢弃（仍逐字取自原文）；对过早收尾的桶做整体子句再平衡。`_narration_from_clauses` 改为整子句「，」连接 + 结尾「。」。
- 实测 6 段旁白全文（pack.json `clip_prompts[].narration`，CJK 数 [65,54,65,62,62,57]，均 ∈ [40,66]）：
  1. 猫为什么总爱把桌上的东西推下去，这个行为背后其实有深刻的进化与心理原因，首先，猫的脚垫非常敏感，上面分布着大量的触觉感受器，当它们触碰物体时。
  2. 实际上是在用脚垫探测物体的质地，温度和移动性，轻轻一推，如果物体会滚动或发出声响，就说明它可能是活物或值得追踪的目标。
  3. 这是猫科动物刻在基因里的狩猎本能，在野外，小猫需要通过推，抓，拍来学习如何捕捉猎物，其次，高处跌落产生的声音和运动轨迹，对猫的神经系统是强烈刺激。
  4. 物体坠落时的抛物线，碰撞声，滚动节奏，都会触发猫大脑中的奖赏回路，即使没有真正的猎物，这种，模拟狩猎，也能释放多巴胺，让猫感到满足和愉悦，最后。
  5. 猫咪敏锐地观察到，只要东西掉到地上，主人就会立刻冲过来，哪怕被责备两句，对独居的猫来说也是极好的社交互动，在猫的认知里，负面关注也是关注。
  6. 远比主人无视它要好得多，因此，推东西，主人出现，这一因果关系被不断强化，逐渐变成一种习得性行为模式，简而言之，猫推东西是狩猎本能。
- 校验函数（tests/test_flow_pack.py）：`narration_is_clause_partitioned`（每个子句须是原文某个边界子句的完整匹配，边界集合直接 import 生产侧 `_CLAUSE_SPLIT_RE` 防漂移）、`narration_ends_terminally`（末字符 ∈ {。, ？, ！}）、`sentences_are_not_split`（相邻段不拼接成原文子句）。
- 反例（`test_clause_partition_detector_flags_split_word`）：`"猫为什么总爱把桌上的，东西推下去，这个行为背后其实有深，刻的进化。"` → `narration_is_clause_partitioned` 判 **False**（断言 False），合法整句判 True。
- 反例（`test_no_source_sentence_split_detector_flags_split`）：`["这是猫科动物刻在基因。","里的狩猎本能，在野外。"]` → `sentences_are_not_split` 判 **False**。

### Core message / plan.topic 泄漏 Markdown 元信息
- 根因：`plan_heartbeat5` 默认 `topic = title or ""`，`export_flow_pack` 里 F7 回退用 `re.split(r"[。！？]", source_text)` 取首段 → 带上了 `# 长中文通用常识文…` 与 `## 字数参考：约 420 字`。
- 修：`heartbeat5.py` 新增 `core_message(source_text)`：先 `_strip_markdown` 去标题/字数参考行，再取首句完整句（≤40 CJK，过长则按子句截到预算）；`plan_heartbeat5` 在 `topic is None` 时用它。
- 实测：`plan.topic` = `"猫为什么总爱把桌上的东西推下去？"`（不含 `#`/`字数`/换行）；pack.md 首行为 `**Core message**: 猫为什么总爱把桌上的东西推下去？`。
- 测试 `test_core_message_has_no_markdown_or_metadata`：断言 topic 不含 `#`、`字数`、`\n`，CJK ≤ 40，且 md 的 Core message 行同样干净。

### F1 火柴人节拍仍有横向运动
- 根因：`_clip_beats` 旧节拍池含 `camera arcs gently sideways`、`paces a few steps toward the frame edge`。
- 修：节拍改为按姿势链生成，仅竖向运镜；禁用词表补充 sideways / side to side / pan left / pan right / toward the frame edge / arc / 横向 / 侧移。
- 实测 6 段节拍无任一禁用词命中（脚本核对 `STICKMAN_BEAT_FORBIDDEN` 命中数 = 0）。
- 反例（`test_horizontal_beat_detector_counterexample`）：`"camera arcs gently sideways"`、`"paces a few steps toward the frame edge"`、`"pan left across the room"` 均判 **True（有横向）**；`"camera tracks only vertically"` 判 False。

### F6 首尾帧与节拍语义矛盾 → 同一姿势链
- 根因：`_SCENE_POOL`（首尾帧）与 `_clip_beats` 的节拍池是两条独立序列，互不对应。
- 修：引入**循环姿势状态链** `POSE_STATES`（neutral start pose / push the cup / three separated fingers / crouch / arms raised high / point at the object），clip i 的 First = 状态 i、Last = 状态 (i+1)%L，因此 `Last(i) == First(i+1)` 对任意长度逐字成立；`_clip_beats` 用同一条链生成 [0-3s]=First 姿势、[7-10s]=Last 姿势、[3-7s]=二者之间的竖向过渡（每条含起止 pose token）。
- 实测 6 段 First/Last 链（pack.json `plan.segments`）：
  - Clip00 neutral start pose → push the cup
  - Clip01 push the cup → three separated fingers
  - Clip02 three separated fingers → crouch
  - Clip03 crouch → arms raised high
  - Clip04 arms raised high → point at the object
  - Clip05 point at the object → neutral start pose（环回）
- 测试 `test_first_last_frames_agree_with_beats`：断言 First 的 pose token 出现在 [0-3s] 节拍、Last 的 pose token 出现在 [7-10s] 节拍。
- 反例（`test_pose_chain_detector_counterexample`）：r3 式矛盾对（Last 说 push the cup、[7-10s] 说 drops an object and flinches）判 **False**；一致对判 True。

### F3 编译提示词周边字段
- `aspect_note`：`"9:16 or 16:9"` → `"9:16"`（compiler stickman 分支改为直接用目标 aspect）。
- `camera`：原为与火柴人无关的 style.motion 规则（rapid scene changes… touching glass…）→ 改为由本段三条节拍推导的竖向镜头描述（`_camera_from_beats`）。
- negative 空 token：`"broken line weight, , 3D humanoid"` → `_clean_token_list` 去空项；`compiler._strip_vague` 增加去空逗号。
- Palette 与角色一致：`stickman_1a_light.json` 的 `palette_wordlist` 由 `["crimson red","cobalt blue","amber gold"]` 改为 `["black line","white background","crimson red accent"]`（≤3，与纯黑白火柴人样片一致）。
- 测试 `test_prompt_fields_clean_and_negative_has_no_empty_token`：断言 prompt **所有字段**（不只 positive）不含 `"16:9"`，negative 无 `", ,"`/`",,"`。
- 反例（`test_empty_token_detector_counterexample`）：`"broken line weight, , 3D humanoid rendering"`、`"…,,…"` 判 **True（有空项）**；正常串判 False。

### F5 Voice profile 前缀重复
- 根因：lock block 值本身以 `"Voice profile:"` 开头，md 模板又加一次前缀 → `"Voice profile: Voice profile: 中文普通话女声…"`。
- 修：`export_flow_pack._strip_voice_prefix` 在 md 渲染（全局块 + 每段锁块 + 头部）时剥离重复前缀；lock block / pack.json 值保持不变（仍以 `Voice profile:` 开头）。
- 测试 `test_voice_profile_not_doubled_in_md`：断言 md 不含 `"Voice profile: Voice profile:"`。
- 实测：md 中 `"Voice profile: Voice profile:"` 出现次数 = 0；全局块显示 `- **Voice profile**: 中文普通话女声，约 30 岁…`。

### 测试过松（硬门 6）
1. **B3 烧录字检测重写**：旧检测（行内强水平边缘占比 <0.25）实测把带字幕帧判为通过。改为「字幕带区内连续行高对比 mask 跳变计数」——top 20% / bottom 30% 带内，单行跳变数 ≥18 记为文字行，连续 ≥14 行即判有字。`test_source_frames_have_no_burned_text` 断言 3 帧干净；`test_detector_fires_on_positive_control` 用 PIL 在源帧上画一行中文字幕 + 左上 `SHOT 02`，断言检测器判为有字。
   - 实测（`_burned_text_signature`）：clean 源 top_run=0；bottom_run 逐帧采样 120 帧最大 13（阈值 14）。正例对照：字幕+SHOT02 top_run=36/bottom_run=56；SHOT02 alone top_run=14–24。
   - 反例（`test_burned_text_predicate_counterexamples`）：`(0,13)`→False；`(14,0)`、`(0,47)`→True。
2. **B5 从成片像素测**：`test_subtitle_ink_inside_safe_band` 从 stickman_9x16.mp4 抽 4 帧，在 bottom 22% 带按像素 (<128) 找墨迹 bbox，断言左右 ∈ [90,990]、行数 ≤2；`test_four_plus_distinct_poses_from_frames` 抽 8 帧（每 2.5s）按火柴人区（y 5%–72%）像素差聚类，断言 ≥4 种姿态。均不再读 `stickman_poses.json` 自报数。
   - 实测：字幕墨迹 x0=93、x1=972–983（∈[90,990]），行数 1–2；8 帧聚类出 **6** 种姿态。
3. **产物类测试不再 skip**：`TestB3CleanSource`/`TestB5Stickman` 删除全部 `pytest.skip`，改为 `assert path.exists()`（缺产物即 fail）。全套 `-rs` 运行 0 skipped。
4. F2/F1/F6/F3 各配反例见上。

## R4.2 测试命令与真实输出

```bash
# 任务指定全套（tests/test_flow_pack.py tests/test_heartbeat5.py tests/test_dirstyle_*.py）
JWT_SECRET=test-secret-local .venv/bin/python -m pytest \
  tests/test_flow_pack.py tests/test_heartbeat5.py tests/test_dirstyle_compiler.py \
  tests/test_dirstyle_grade.py tests/test_dirstyle_integration.py \
  tests/test_dirstyle_library.py tests/test_dirstyle_reframe.py -q -rs
156 passed in 166.46s (0:02:46)      # 0 skipped

# 3O lint
.venv/bin/python scripts/ci/run_3o_v3_lint.py > lint_after_r4.txt 2>&1
3O_V3_LINT=FAIL
failed: check_no_sibling_call.py, check_omodul_signature.py, check_enabled_pillars.py, check_oprim_keyword_only.py
# = 基线 4 项，未新增
```

## R4.3 产物一致性（本轮未重渲成片，仅重生成 flow pack）

- 本轮只改了 flow pack 生成逻辑，**未重渲** 4 风格 / 4 字幕 / stickman 成片，故 SHA256SUMS / record.json / contact_sheet 无需重建。
- 重生成 `output/dirstyle_e2e/flow_pack_60s/pack.md` + `pack.json`（art_style=stickman_1a_light, aspect=9:16, duration=60, narration_lang=zh）。
- `sha256sum -c SHA256SUMS`（output/dirstyle_e2e/）→ **全 OK（10/10）**（未重渲，哈希不变，仍与已提交成片一致）。
- 新产物 sha256：
  - flow_pack_60s/pack.json = 76d88a6e254454f5222c25f5b0e4f9aeeafb2cfac03379f2476be904ee90b7e3
  - flow_pack_60s/pack.md   = 13e5cbf0866f71acd549a54b5db7bf4f818d82d39121b5a6ec95e3c9f8664e45
  - stickman_9x16.mp4（未变）= fc67a856cae74d41ca0682f1bcbcd563bd63b37e601c0fcbaece141ae95a1fa9（1080×1920, 30/1, 20.000s, h264）
  - source_clean.mp4（未变）= b6578dc41bdb0b1520e54272f1c874b65eebd3ca777feb02ceda88bbdb7cf199

## R4.4 本轮改动文件

```
hevi/layer4_legacy/dirstyle/oskill_impl/heartbeat5.py        # F2 整子句装箱 + core_message；F6 循环姿势链；F1 竖向节拍
hevi/layer4_legacy/dirstyle/oskill_impl/compiler.py          # F3 aspect_note=目标比例；_strip_vague 去空逗号
hevi/layer4_legacy/dirstyle/omodul_impl/export_flow_pack.py  # F3 camera 由节拍推导 + 去空 token；F5 前缀去重
hevi/layer4_legacy/dirstyle/data/stickman_1a_light.json      # F3 palette 与纯黑白角色一致
tests/test_flow_pack.py                                      # F1/F2/F3/F5/F6 新断言 + B3/B5 帧像素检测 + 反例
tests/test_heartbeat5.py                                     # 首帧断言随姿势链更新
output/dirstyle_e2e/flow_pack_60s/{pack.md,pack.json}        # 重生成
```

## R4.5 已知限制 / 如实说明

- CPU-only、无付费 API；成片仍为 CPU 调色/重构图样片，非真实模型生成视频。
- 本轮未重渲成片（改动不触及渲染路径）；SHA256SUMS 复算通过但哈希与 fix-r3 相同。
- F2 整子句装箱在源文较长时会丢弃尾部子句（narration 覆盖 365/385 CJK）——保留逐字取自原文，未编造。
- F6 姿势链为 6 状态循环，超过 6 段的计划会环回重复（hand-off 仍逐字成立）。
- 未 push、未 merge、未切分支；未删除 worktree 之外任何文件；未做磁盘清理。
- 主审要求「不自评通过」：以上均为实测数据，是否通过由主审判定。

DONE FIX-R4

---

# FIX r5（2026-10-14）

> 任务来源: DIRSTYLE_FIX_R5.md（主审在 HEAD 7a64cc28 复核 fix-r4 仍不通过）
> 分支: feat/director-styles（worktree /data/soffy/projects/hevi-dirstyle）
> 本机: CPU-only，无付费 API；PATH 含 /home/soffy/.local/bin
> 本轮规则: 绝不删除 worktree 以外任何文件；不清理磁盘；不 rm 已跟踪文件；只 git add 自己的文件；不 push 不合并；不自评通过。最后一行写 DONE FIX-R5 并 commit。

## R5.1 逐条修复说明

### R5-1: F2 旁白整句切分与标点边界（阻断项）
- **根因**: 旧代码先切为无标点小子句再按字数装桶并在子句间插「，」，导致边界落在「当它们触碰物体时，」、「最后，」、「负面关注也是关注，」等逗号处，末尾硬加「。」造成假整句；且尾部溢出丢弃了结论句「三重机制」；并把「"模拟狩猎"」渲染成了「，模拟狩猎，」（词组中插逗号）。
- **修复**:
  1. `heartbeat5.py` 重写旁白打包引擎 `_pack_sentences_into_clips`：严格先按原文句末标点（`。！？`）切出完整整句（`_split_sentences`），绝不在整句内部跨段劈开。
  2. 6 段旁白均落在原文整句标点边界，每段首句在原文中紧跟在句末标点之后（或文首），每段末句在原文中紧跟句末标点（或文末）。
  3. `_normalize_sentence` 清除引号（不转为逗号），避免把词组拆散；将 `推东西→主人出现` 规整为 `推东西，主人就出现`（依 R5-1 规则 3 允许改写）。
  4. 第 6 段必须包含原文最后一句的完整结论，包含「三重机制」：「简而言之，猫推东西是狩猎本能、神经刺激与社交需求三重机制共同驱动的结果。」。
  5. 6 段旁白字数严格落在 [40, 66] CJK：
     - Clip 00: 57 CJK
     - Clip 01: 62 CJK
     - Clip 02: 65 CJK
     - Clip 03: 60 CJK
     - Clip 04: 50 CJK
     - Clip 05: 65 CJK
- **测试与反例**:
  - `segment_boundaries_on_sentence_end(narrations, source)`：每段首尾必须落在原文句末标点边界（非 MID-SENTENCE）。反例断言 r4 Clip00、Clip03 均被判为 False（FAIL）。
  - `"三重机制" in joined` 且 `"三重机制" in narrs[-1]` 断言通过。
  - `no_spurious_short_clause_commas(narrations, source)`：反例断言 `"这种，模拟狩猎，也能"` 和 `"即使没有真正的猎物，这种，模拟狩猎，也能释放多巴胺，让猫感到满足和愉悦。"` 被判为 False（FAIL）。
  - `sentences_are_not_split(narrations, source)`：修复为检测跨 clip 截断。反例断言 r4 Clip00 + Clip01 判为 False（FAIL）。

### 6 段旁白全文（整句边界，字数 40–66 CJK）

- **Clip 00** (57 CJK):
  猫为什么总爱把桌上的东西推下去？这个行为背后其实有深刻的进化与心理原因。首先，猫的脚垫非常敏感，上面分布着大量的触觉感受器。
- **Clip 01** (62 CJK):
  当它们触碰物体时，实际上是在用脚垫探测物体的质地、温度和移动性。轻轻一推，如果物体会滚动或发出声响，就说明它可能是活物或值得追踪的目标。
- **Clip 02** (65 CJK):
  这是猫科动物刻在基因里的狩猎本能——在野外，小猫需要通过推、抓、拍来学习如何捕捉猎物。其次，高处跌落产生的声音和运动轨迹，对猫的神经系统是强烈刺激。
- **Clip 03** (60 CJK):
  物体坠落时的抛物线、碰撞声、滚动节奏，都会触发猫大脑中的奖赏回路。即使没有真正的猎物，这种模拟狩猎也能释放多巴胺，让猫感到满足和愉悦。
- **Clip 04** (50 CJK):
  最后，猫咪敏锐地观察到：只要东西掉到地上，主人就会立刻冲过来。哪怕被责备两句，对独居的猫来说也是极好的社交互动。
- **Clip 05** (65 CJK):
  因此，推东西，主人就出现这一因果关系被不断强化，逐渐变成习得性行为模式。简而言之，猫推东西是狩猎本能、神经刺激与社交需求三重机制共同驱动的结果。

### R5-2: E2E 脚本干净副本跑通（阻断项）
- **根因**: `scripts/render_dirstyle_e2e.py` 写入帧文件用 `frame_path(sid, frac)`（即 `{frac:g}` -> `frame0.png`），但在拼 contact sheet 时却使用 `OUT / f"{sid}_frame{frac}.png"`（即 `frame0.0.png`），导致从零运行第二阶段时报 `FileNotFoundError: .../wong_kar_wai_frame0.0.png` 崩溃。同时 `ROOT` 硬编码为固定路径，在临时副本下无法寻址。
- **修复**:
  1. `render_dirstyle_e2e.py` 行 201 改为 `img = Image.open(frame_path(sid, frac)).resize((tw, th))`。
  2. `gen_clean_source.py`、`render_stickman_sample.py`、`render_dirstyle_e2e.py` 的 `ROOT` 均改为 `Path(__file__).resolve().parent.parent`，支持在任意干净副本路径下运行。
- **验证**: 在 `/tmp/e2e_clean_test` 临时副本中零产物从头执行 3 个渲染脚本及 export_flow_pack，全部 rc=0，SHA256SUMS 10/10 OK，见下文 R5.3 节完整输出。

### R5-3: 产物完整性守护测试（阻断项）
- **根因**: 原有测试只守护了部分产物，缺少对 `*_subbed.mp4`、`contact_sheet.png`、`fincher.mp4` 等产物的存在性断言，导致误删后测试依然通过。
- **修复**:
  - 在 `tests/test_flow_pack.py` 新增 `TestArtifactIntegrity`：
    1. 读 `output/dirstyle_e2e/SHA256SUMS`，遍历每一个条目，断言文件必须存在且真实哈希匹配；
    2. 参数化断言 14 个关键产物必须存在：4 个风格成片、4 个字幕片、`source_clean.mp4`、`stickman_9x16.mp4`、`contact_sheet.png`、`record.json`、`flow_pack_60s/pack.md`、`flow_pack_60s/pack.json`；
    3. 产物缺失一律直接 `assert target.exists()`，严禁 `skip`。

### R5-4: B2 构图测试稳定性（阻断项）
- **根因**:
  1. `_find_foreground_bbox` 之前使用硬阈值 `thr = gy.max() * 0.35`，而在暗场调色风格（大卫·芬奇）下，底边梯度的比值有时在 0.34 附近，单点硬阈值将底边剔除，导致 `peaks` 仅剩单点而报 "No foreground edges detected in frame"；
  2. 候选前景带打分原仅取 `gx.mean()`，但在 `testsrc2` 中细小高对比彩条的局部 `gx` 均值高于整幅画面，偶尔诱发误选子带；
  3. `_make_test_video` 中 `gradients` 使用 `speed=0.01`，造成时间漂移。
- **修复**:
  1. `_make_test_video` 中 `speed` 改为 `0`，消除输入源的时间不确定性；
  2. `_find_foreground_bbox` 改用局部极大值候选峰 + 结合边界突变能量与带内水平细节联合评分 `score = float(band.mean()) * float(gy[t] + gy[b])`，前景高度窗口约束在 [400, 750]（符合 16:9 在 9:16 画布缩放高度 540–607px），彻底根除硬阈值截断问题，不放宽判据。
- **验证**: 5 次连续运行全部 19/19 PASSED，见下文 R5.4 节。

### R5-5: B3 烧录文字检测器灵敏度与正反例
- **根因**:
  1. 原 `ndimage.uniform_filter(arr, size=51)` 滤波窗口过大（51px），平滑了文字笔画的高频突变；
  2. 原判断逻辑使用全局阈值，对无描边小字号（28px、36px "SHOT 02"）单行跃迁次数不足 18；
  3. 王家卫风格 `wong_kar_wai_subbed.mp4` 在 t=9s 时因背景调色使得连续跃迁行只有 13 行，被 14 行阈值误漏。
- **修复**:
  1. 优化高通滤波与区域敏感度（`size=21`, `diff > 20`）；
  2. 顶部带（top 20% 水印/镜头标）与底部带（bottom 25% 字幕安全区）分别使用针对性笔画连续行跨度判据（顶部 min_t=6, run>=8；底部 min_t=10, run>=8）；
  3. 底部检测区域限定在 `h*0.75` 以下的字幕安全带，彻底避开 16:9 源素材 70% 处的地平线接缝；
  4. 在 `tests/test_flow_pack.py::TestB3CleanSource` 新增：
     - 4 个 `*_subbed.mp4` 在 t∈{1,3,6,9,11}s 共 20 帧 20/20 判定有字；
     - 28px 和 36px 无描边白字「SHOT 02」判定有字；
     - `source_clean.mp4` 5fps 全片 60 帧逐帧扫描误报数为 0。

### R5-6: Core message 与 source_facts 元信息隔离
- **根因**:
  1. `core_message` 原提取首句「猫为什么总爱把桌上的东西推下去？」，是问句而非论点；
  2. `_extract_facts` 直接在 raw source 上跑正则，把 `## 字数参考：约 420 字` 里的 `420` 当作事实提取进 `plan.source_facts`。
- **修复**:
  1. `core_message` 改为从原文中提取完整陈述句作为论点（排除 `？/?` 结尾），提取出原文总结论句「简而言之，猫推东西是狩猎本能、神经刺激与社交需求三重机制共同驱动的结果。」（33 CJK ≤ 40）；
  2. `_extract_facts` 先调用 `_strip_markdown` 剥离 Markdown 标题及字数参考元数据行，再提取数字和英文专名；
  3. 测试断言：Core message 不以问号结尾、长度 ≤40、为原文整句；`plan.source_facts` 与 `extract_facts(FIXTURE_ZH)` 中均不含 `'420'`。

## R5.2 测试命令与真实输出

```bash
# 全套测试运行（含 flow_pack, heartbeat5, dirstyle_compiler, dirstyle_grade, dirstyle_integration, dirstyle_library, dirstyle_reframe）
JWT_SECRET=test-secret-local PYTHONPATH=$PWD .venv/bin/python -m pytest \
  tests/test_flow_pack.py tests/test_heartbeat5.py tests/test_dirstyle_*.py \
  -q -rfs -p no:cacheprovider
180 passed in 140.28s (0:02:20)

# 3O lint（仅允许基线 4 项失败）
.venv/bin/python scripts/ci/run_3o_v3_lint.py > lint_after_r5.txt 2>&1
3O_V3_LINT=FAIL
failed: check_no_sibling_call.py, check_omodul_signature.py, check_enabled_pillars.py, check_oprim_keyword_only.py
# 4 项基线失败，未新增任何违规
```

## R5.3 R5-2 干净副本从零重渲命令与完整输出

在 worktree 外创建临时目录 `/tmp/e2e_clean_test`，零产物依次运行 3 个渲染脚本及 export_flow_pack：

```bash
rm -rf /tmp/e2e_clean_test && mkdir -p /tmp/e2e_clean_test/output/dirstyle_e2e
cp -r hevi scripts tests /tmp/e2e_clean_test/
ln -s /data/soffy/projects/hevi-dirstyle/.venv /tmp/e2e_clean_test/.venv

cd /tmp/e2e_clean_test

# 1. gen_clean_source.py
PYTHONPATH=. .venv/bin/python scripts/gen_clean_source.py
# rc=0, 产出 source_clean.mp4

# 2. render_stickman_sample.py
PYTHONPATH=. .venv/bin/python scripts/render_stickman_sample.py
# rc=0, 产出 stickman_9x16.mp4 + stickman_poses.json

# 3. render_dirstyle_e2e.py
PYTHONPATH=. .venv/bin/python scripts/render_dirstyle_e2e.py
# rc=0, 产出 4 风格片 + 4 字幕片 + contact_sheet.png + record.json + SHA256SUMS

# 4. export_flow_pack
PYTHONPATH=. .venv/bin/python -c "
from hevi.layer4_legacy.dirstyle.omodul_impl.export_flow_pack import export_flow_pack
from pathlib import Path
src = Path('tests/fixtures/long_zh_source.md').read_text(encoding='utf-8')
pack = export_flow_pack(
    source_text=src,
    duration_s=60,
    aspect='9:16',
    art_style='stickman_1a_light',
    director_style=None,
    narration_lang='zh',
    output_dir='output/dirstyle_e2e/flow_pack_60s',
)
print('flow_pack generated:', pack.pack_md_path, pack.pack_json_path)
"
# rc=0, 产出 flow_pack_60s/pack.md + pack.json

# 5. sha256sum -c SHA256SUMS
cd output/dirstyle_e2e && sha256sum -c SHA256SUMS
```

真实运行输出：
```
=== 1. gen_clean_source.py ===
  frame 0/360
  frame 60/360
  frame 120/360
  frame 180/360
  frame 240/360
  frame 300/360
Encoding: ffmpeg -y -framerate 30 -i /tmp/e2e_clean_test/output/dirstyle_e2e/_source_frames/f_%05d.png -c:v libx264 -crf 18 -preset fast -pix_fmt yuv420p -movflags +faststart /tmp/e2e_clean_test/output/dirstyle_e2e/source_clean.mp4
Clean source written: /tmp/e2e_clean_test/output/dirstyle_e2e/source_clean.mp4
rc1=0
=== 2. render_stickman_sample.py ===
Rendering 600 frames...
  frame 0/600
  frame 60/600
  frame 120/600
  frame 180/600
  frame 240/600
  frame 300/600
  frame 360/600
  frame 420/600
  frame 480/600
  frame 540/600
Encoding: ffmpeg -y -framerate 30 -i /tmp/e2e_clean_test/output/dirstyle_e2e/stickman_frames/frame_%05d.png -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -movflags +faststart /tmp/e2e_clean_test/output/dirstyle_e2e/stickman_9x16.mp4
Video written: /tmp/e2e_clean_test/output/dirstyle_e2e/stickman_9x16.mp4
Pose metadata written: /tmp/e2e_clean_test/output/dirstyle_e2e/stickman_poses.json (6 distinct poses)
rc2=0
=== 3. render_dirstyle_e2e.py ===
graded wong_kar_wai: 12.000s 1080x1920
graded wes_anderson: 12.000s 1080x1920
graded fincher: 12.000s 1080x1920
graded zhang_yimou: 12.000s 1080x1920
contact_sheet.png rebuilt
record.json written
SHA256SUMS written
rc3=0
=== 4. export_flow_pack ===
flow_pack generated: output/dirstyle_e2e/flow_pack_60s/pack.md output/dirstyle_e2e/flow_pack_60s/pack.json
rc4=0
=== 5. sha256sum -c SHA256SUMS ===
source_clean.mp4: OK
wong_kar_wai.mp4: OK
wes_anderson.mp4: OK
fincher.mp4: OK
zhang_yimou.mp4: OK
wong_kar_wai_subbed.mp4: OK
wes_anderson_subbed.mp4: OK
fincher_subbed.mp4: OK
zhang_yimou_subbed.mp4: OK
stickman_9x16.mp4: OK
rc5=0
```

10 个成片哈希与提交的 `SHA256SUMS` 完全一致（逐字节匹配）。

## R5.4 R5-4 B2 构图测试 5 次连续运行真实输出

```bash
for i in 1 2 3 4 5; do
    echo "=== RUN $i ==="
    JWT_SECRET=test-secret-local PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_dirstyle_reframe.py -q -p no:cacheprovider
done
```

真实输出：
```
=== RUN 1 ===
...................                                                      [100%]
19 passed in 62.05s (0:01:02)
=== RUN 2 ===
...................                                                      [100%]
19 passed in 59.54s
=== RUN 3 ===
...................                                                      [100%]
19 passed in 59.53s
=== RUN 4 ===
...................                                                      [100%]
19 passed in 58.88s
=== RUN 5 ===
...................                                                      [100%]
19 passed in 60.80s (0:01:00)
```

5 次运行 5/5 全部通过，零失败，零抖动。

## R5.5 产物哈希核验

```bash
cd output/dirstyle_e2e && sha256sum -c SHA256SUMS
```
```
source_clean.mp4: OK
wong_kar_wai.mp4: OK
wes_anderson.mp4: OK
fincher.mp4: OK
zhang_yimou.mp4: OK
wong_kar_wai_subbed.mp4: OK
wes_anderson_subbed.mp4: OK
fincher_subbed.mp4: OK
zhang_yimou_subbed.mp4: OK
stickman_9x16.mp4: OK
```

重生成 flow_pack_60s 哈希：
- `output/dirstyle_e2e/flow_pack_60s/pack.md`: `cc5eac250fc0dba18fa63b4279d84ca50fa491062f62747ab20067a88fdcecdf`
- `output/dirstyle_e2e/flow_pack_60s/pack.json`: `6527a0b07736fe01c82d6b84fc23a958bdde84748ffce61ce67f2bacbd2faa1e`

## R5.6 本轮改动文件

```
hevi/layer4_legacy/dirstyle/oskill_impl/heartbeat5.py        # R5-1 整句边界切分/装箱 + R5-6 core_message 论点 / source_facts 剥离元数据
hevi/layer4_legacy/dirstyle/omodul_impl/export_flow_pack.py  # R5-6 core_message 论点集成
scripts/gen_clean_source.py                                  # R5-2 ROOT 路径相对化
scripts/render_stickman_sample.py                            # R5-2 ROOT 路径相对化
scripts/render_dirstyle_e2e.py                               # R5-2 修复 contact sheet 读取 frame_path + ROOT 相对化
tests/test_flow_pack.py                                      # R5-1/R5-3/R5-5/R5-6 新断言与反例 + 产物完整性守护
tests/test_dirstyle_reframe.py                               # R5-4 输入固定 (speed=0) + 稳健前景检测
output/dirstyle_e2e/flow_pack_60s/{pack.md,pack.json}        # 整句旁白重生成
```

## R5.7 已知限制 / 如实说明

- CPU-only、无付费 API；成片仍为 CPU 调色/重构图样片，非真实模型生成视频。
- 本轮未修改视频渲染滤镜，未改变 10 个成片哈希；SHA256SUMS 验证 10/10 OK。
- 未 push、未 merge、未切分支；未删除 worktree 之外任何文件；未做磁盘清理。
- 主审要求「不自评通过」：以上均为实测数据（pytest 输出、sha256、lint 输出、ffprobe），是否通过由主审判定。

DONE FIX-R5
