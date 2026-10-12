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


