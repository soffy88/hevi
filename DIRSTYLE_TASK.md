# DIRSTYLE_TASK — Hevi「导演风格库」（六维参数 → 提示词编译 → CPU 调色/运动步骤）

分支 feat/director-styles（worktree /data/soffy/projects/hevi-dirstyle，基于 origin/closure/3o-v3-architecture-creative-baseline @ac09c747）。
**只在本 worktree 工作**，不碰主 checkout /data/soffy/projects/hevi，不合并、不 push（push 由主审独立核验后执行）。
.venv：`ln -s /data/soffy/projects/hevi/.venv .venv`（其它 worktree 同样做法；不要往里 pip 装大包）。

## 背景（核心理念）
一篇文章把 10 位导演的视觉系统拆成六维参数：**焦段/画幅、构图、光线、色彩、运动、节奏**。
提示词公式：`[导演六维参数] + [具体场景/动作] + [镜头运动] + [负面提示词]`。
核心原则：**禁止写「很电影感/cinematic/epic/masterpiece」这类虚词**，全部翻译成镜头、光线、色彩、运动的具体决策。导演名字只做内部 id，**不写进模型提示词**（参考 Mikefluff 的做法）。

### 10 位导演（文章原始参数，必须完整收录）
1. **王家卫 wong_kar_wai**：18mm 超广角贴身手持，2.35:1，前景遮挡（门框/雨伞/玻璃/烟雾），青绿阴影+洋红高光，慢门抽帧拖影，粗颗粒胶片，暗部不死黑，暧昧疏离。签名：抽帧拖影 + 青绿暖黄双色调 + 框架偷窥感，三者缺一不可。
2. **张艺谋 zhang_yimou**：中焦到大全景，严格中轴对称、人物居中，背景阵列重复（人海/方阵/灯笼墙），单一主色爆满（正红/明黄/青蓝），缓慢推进、仪式化横移。
3. **侯孝贤 hou_hsiao_hsien**：50–85mm 固定机位，远景/中远景，人物进出画、大片空景，自然窗光，低饱和褪色绿灰，几乎不动，留白。
4. **姜文 jiang_wen**：25–35mm 广角略畸变快速推拉，倾斜构图、突然大特写，硬光强投影，高反差黑白或浓烈暖金，手持甩镜跳切，节奏极快。
5. **杜琪峰 johnnie_to**：中远景冷蓝夜色，舞台式几何站位，顶光侧光、暗部大、路灯唯一暖源，长时间静止后极快爆发。
6. **贾樟柯 jia_zhangke**：手持 DV 粗粝纪实，构图随意偶切半头，荧光灯尘土散射，低饱和灰绿黄脏旧，随机跟随后突然停住。
7. **诺兰 nolan**：IMAX 大画幅，广角全景与超大特写硬切，水平稳定、高信息密度，自然/实用光低对比，冷灰钢蓝去饱和，机械精准推进。
8. **韦斯·安德森 wes_anderson**：中焦正对，绝对左右对称、人物居中，柔和均匀光，粉红/芥末黄/薄荷绿/天蓝，机械横移 + 90 度转场 + 俯拍平铺。
9. **昆汀 tarantino**：超低机位仰拍广角，对话长焦压缩，极端视角（车内/后备箱/地板向上），硬光 70 年代胶片，暖黄正红高饱和，突然推镜 + 快摇。
10. **大卫·芬奇 fincher**：中焦，毫米级精确运镜，几何监控视角，低照度单光源、暗部大，青绿阴影 + 微暖肤色去饱和，缓慢机械运镜、几乎无手持。

### 参考仓库（已放到 third_party/dirstyle_refs/，均 MIT；暂时非商用，但必须保留署名）
| 目录 | 上游 | commit | 用法 |
|---|---|---|---|
| mikefluff_skills/style-library-video/ | github.com/Mikefluff/skills | 24bbcc2 | **12 种导演风格**（chazelle/lynch/edgar-wright/fincher/inarritu/nolan/refn/soderbergh/tarkovsky/villeneuve/wes-anderson/wong-kar-wai），每种有 lens/lighting/palette/motion/editing rhythm/shot anchor/action vocabulary/best for/avoid for。**与 10 位重叠的 4 位（王家卫/诺兰/韦斯/芬奇）合并补充字段；其余 8 位作为新增风格吸收**（共 ≥18 种）。|
| nolanx/ | github.com/nolanx-ai/nolanx.ai | 595d863 | 方法论 skill（director-visual-language、cinema-studio-lens-look、shot-size-and-angle-language、storyboard-shot-design、lighting-continuity-design、sd2-pe、short-drama-hook-engineering）：吸收**镜头尺寸/角度/运镜词表**和"抽象词→具体决策"规则，用于编译器的运镜库和虚词黑名单。|
| awesome_seedance/ | github.com/ZeroLu/awesome-seedance | ea0d373 | Seedance 2.0 实战提示词（含王家卫雨夜电话亭、Villeneuve、竖屏霸总短剧、短剧雨夜）：参考**时间码分段写法**和竖屏短剧写法；可作为编译器输出样例/测试对照。|
| ai_shortfilm_prompts/ | github.com/jnMetaCode/ai-shortfilm-prompts | 5e7c374 | **只吸收 MIT [A] 部分**（templates/、methodology、cheatsheet）：21+ 套类型模板（micro-drama、found-footage-horror、fashion-film、food-asmr、cyberpunk-city、genre-camera-sop、camera-move-library、atmosphere-prefabs…）→ 作为"题材模板（genre）"层，与导演风格正交组合。**不得复制 prompts/ 下 Mx-Shell [B] All-Rights-Reserved 内容**（本次已未拷贝）。|

署名：在 third_party/dirstyle_refs/README.md 写清四个上游、commit、许可证、吸收范围；在仓库已有第三方台账（THIRD_PARTY_NOTICES.md / NOTICE，先 grep 找现有位置）登记；风格库每条吸收来的风格写 `source:` 字段。

## 必须实现

### 1. 结构化风格库（YAML 或 JSON，数据驱动）
建议 `hevi/layer4_legacy/dirstyle/data/director_styles.yaml`（+ genre_templates.yaml）。每种风格字段至少：
- `id`、`display_zh/en`、`source`（article / mikefluff / …）
- 六维：`lens_aspect`（焦段、画幅，例如 2.35:1/1.85:1/IMAX 1.43:1/16:9）、`composition`、`lighting`、`color`（含调色板 hex）、`motion`、`rhythm`（平均镜头时长、切点规则）
- `signature`（签名要素列表，标出"缺一不可"的）
- `negative`（风格专属负面，例如韦斯不要手持/不对称；王家卫不要死黑/干净数码）
- `fits` / `avoid`（适合/不适合题材）
- `vertical_9x16`：竖版改写规则 —— 宽画幅风格（2.35:1、IMAX 等）**禁止硬裁**：要么 `letterbox`（9:16 画布中嵌入宽画幅区并上下黑边，字幕放黑边区）、要么 `recompose`（把构图规则改写成竖版：对称轴改为竖中轴、前景遮挡改为上下框、空景改为上方留白等）；每种风格写明选哪种以及具体改写句。
- `grade`：给第 3 节 CPU 线用的可执行参数（见下）。
提供 schema 校验（jsonschema 或 dataclass 校验），加载失败要报错，不得静默。

### 2. 提示词编译器
`compile_prompt(style_id, scene, action, camera_move=None, genre=None, aspect="9:16", lang="zh"|"en", target="keyframe"|"video")` →
`{positive, negative, camera, aspect_note, style_id, provenance}`。
- 按公式拼：六维参数（具体） + 场景/动作 + 运镜（来自运镜库，nolanx/jnMetaCode camera-move-library 吸收） + 负面。
- **虚词黑名单**（cinematic、电影感、大片感、epic、masterpiece、高级感、氛围感、beautiful…）：出现在用户输入时要翻译/剔除并记录到 provenance；输出里一个都不能有（测试断言）。
- 导演名字不进 positive。
- keyframe 目标输出适合 SD-Turbo（短、英文 token 为主，≤77 token 截断策略要合理，签名要素优先保留）；video 目标输出适合 Seedance/Kling/Wan 一类的中英文长描述（可带时间码分段）。
- **接入 Hevi 分镜/keyframe 流程**：现有两套预设 `hevi/prompt/style_presets.py`（DEFAULT_KEYFRAME_STYLE=anime_guofeng）与 `hevi/layer4_legacy/keyframe/oprim_impl/style_presets.py`（DEFAULT_STYLE=guofeng_anime，dramakey/comicnarr 用），以及 `keyframe/oskill_impl/prompt_translator.py`。要求：
  - 导演风格是**叠加层**（摄影语言：镜头/光/色/运动），画风预设（国风动漫/ink/manga…）仍决定**绘画媒介**。默认（不传 director_style）时现有输出**逐字不变**（加回归测试，比较改动前后 prompt）。
  - 短剧/漫剧默认国风动漫：叠加导演风格时**不得引入写实/photoreal/film grain photo/真人**等与非写实默认冲突的词（风格库里给每种风格写 `anime_safe` 改写或冲突词过滤；测试：guofeng_anime + wong_kar_wai 的 positive 不含 photoreal/realistic/photo，negative 仍保留原预设的反写实负面）。
  - 在 prompt_translator / 分镜生成处加可选参数 `director_style`，打通到 keyframe prompt。
- 3O 分层：实现放 `hevi/layer4_legacy/dirstyle/{oprim_impl,oskill_impl,omodul_impl}`，`hevi/dirstyle/{oprim,oskill,omodul}/__init__.py` 是兼容 shim；oprim=加载/校验风格库、ffmpeg 滤镜构造；oskill=编译器（纯函数）；omodul=style_grade 落盘工作流。读 docs/3O-MIGRATION-REPORT.md，照 talkcraft/zerolines 的方式。

### 3. 零成本 CPU 线：可选 `style_grade` 步骤（真实 ffmpeg 处理）
把色彩/颗粒/画幅/运动/节奏映射为 ffmpeg 参数，作为可选后处理步骤（输入一段视频或一组关键帧图 → 输出风格化 9:16 片段）：
- 色彩：`curves`/`colorbalance`/`eq`/`hue`/`colorchannelmixer`，或生成 .cube LUT（`lut3d`）；分离色调（王家卫青绿阴影+洋红/暖黄高光、芬奇青绿阴影+微暖肤色去饱和、韦斯粉彩高明度低反差、张艺谋单一主色爆满、诺兰冷灰钢蓝去饱和、侯孝贤褪色绿灰…）。
- 颗粒：`noise=alls=..:allf=t` 等，粗细按风格；暗部不死黑（王家卫：抬黑位）。
- 画幅：9:16 画布内信箱黑边（2.35:1 等）或竖构图，**禁止硬裁宽画面成竖条**；字幕/文字必须在安全区内不出框。
- 运动：`zoompan`/`crop`+表达式做推拉摇移（韦斯机械横移、张艺谋缓慢推进、芬奇缓慢机械推、姜文/昆汀快推/甩镜），手持抖动近似（王家卫/贾樟柯），抽帧拖影用 `tmix`/`minterpolate`/降帧再升帧近似 step-printing。
- 节奏：剪辑节奏参数（平均镜头时长、静止后爆发等）用于多段素材的切点。
- 每种风格的 grade 参数从 YAML 读，不在代码里写死一堆 if。
- 生成的滤镜链要可打印、可复现（写进 record）。

### 4. 测试（tests/test_dirstyle_*.py，禁止 mock 渲染结果）
- 风格库：≥18 种全部通过 schema；10 位文章导演六维/签名/negative/vertical_9x16 全部非空；王家卫签名三要素都在。
- 编译器：输出无黑名单虚词、无导演名；zh/en 都能出；keyframe 长度控制；国风动漫兼容（见上）；默认不传 director_style 时与改动前逐字一致。
- style_grade：用 ffmpeg 现场生成的小测试片（testsrc2/渐变）真实跑 ≥3 种风格，断言输出 1080x1920（或你定的 9:16 尺寸）、时长、颜色统计确有差异（例如 signalstats 的 U/V 均值或饱和度差异）、信箱风格上下黑边存在且画面内容未被裁剪（宽画面完整缩放进去）。

### 5. E2E 样片（必须真出片）
- 选一段**同一素材**（仓库/机器上已有的真实视频片段或 Hevi 已生成的关键帧序列，8–15s，有人物或明显主体与运动更好；先 find /data/soffy/projects/hevi-*/output 里的现成 mp4，不要下载付费素材）。
- 至少 4 种反差大的风格：**王家卫、韦斯·安德森、芬奇、张艺谋**（可再加姜文/侯孝贤）。各出一条 9:16（1080x1920）样片到 `output/dirstyle_e2e/<style_id>.mp4`，叠一行简短中文风格名字幕（在安全区内，不出框）。
- 同时把每种风格编译出的 keyframe/video 提示词（中英）写进 record。若有余力：用已有 SD-Turbo CPU 引擎按 guofeng_anime+导演风格出 1–2 张关键帧做对比（可选，CPU 慢就跳过并如实写）。
- `output/dirstyle_e2e/record.json`：每条样片的 style_id、输入素材路径与 sha256、完整 ffmpeg 命令/滤镜链、输出路径、sha256、ffprobe（分辨率/时长/fps/codec）、编译出的提示词。
- `output/dirstyle_e2e/SHA256SUMS`、`output/dirstyle_e2e/contact_sheet.png`（每种风格一行、每行 ≥4 帧，标注风格名）。
- **亲自抽帧看**：风格之间必须肉眼可见不同；文字不出框；宽画幅风格是信箱而非硬裁。

## 通用规则
- CPU-only（RTX 3080 已坏）；不调用任何付费 API；不删任何数据；长任务（E2E 渲染）用 `nohup setsid ... > log 2>&1 &` 独立启动并 sleep 轮询直到产物生成，不得在产物完成前结束会话。
- 开工先跑 `.venv/bin/python scripts/ci/run_3o_v3_lint.py` 记基线（基线允许 4 项失败），结束再跑，新失败数不得多于基线。
- 阶段性 `git commit`（只 add 自己的文件；output/dirstyle_e2e 下样片可提交，但单文件 >20MB 不提交，在 record 里写路径）。**不要 push、不要合并**。
- 禁止 mock/占位/写死样片；DONE 里不得写未实测数据，不得自称"独立验证通过"。
- 完成后写 `DIRSTYLE_DONE.md`：做了什么、文件清单、接口、风格清单（来源）、测试命令和结果、样片路径+ffprobe+sha256、已知限制；然后 commit。不要询问，直接执行。
