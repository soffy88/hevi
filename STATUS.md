# Hevi · STATUS

> Canonical project status. Read at the start of any non-trivial task.
> Last updated: 2026-07-18
> Sources: git log, `.claude` project memory (tongjian-pipeline-handoff, deploy-topology, e2e-local-llm-json-blocker, gpu-pcie-fallen-off-bus).
> This file tracks *what's true now*, not design. Specs live in `docs/specs/`.

---

## 🔒 Never (hard constraints — do not violate)

- **Never reboot this shared host without asking soffy.** ~90 containers from unrelated projects (aegis/aii/helios/mneme/stratum-aii…) share one RTX 3080. RTX 3080 Xid 79 (GPU fell off PCIe bus) recurs almost every boot even with `pcie_aspm=off` — likely hardware, not a hevi bug.
- **Never route json2video/flux-schnell to character/portrait generation.** Confirmed 2026-07-08: technically succeeds but generates unrelated buildings/landscapes for Chinese person prompts. `hevi/image/json2video_scene_service.py` is scene-background-only (no-character). Keep it out of `resilient_image_gen` person fallback chains.
- **Never let dialogue exist without provenance.** Tongjian/cinematic台词 must be either paraphrased from `chapter_ir.quotes` (has `quote_id`) or explicitly `BeatDialogue.is_performative=True`. "Neither quote_id nor is_performative" = violation. This is the史实 red-line CG2.5 gate enforces — preserve that check in any edit.
- **Never rebuild main branch state blindly after a PR merge.** ff-merge `origin/main` into local `main` after each merge or the working tree drifts into a stale superposition. (see memory: git-sync-main-after-merge)
- **Never assume merging a PR / applying a migration updates the public site.** `hevi.kanpan.co` is the `hevi-cftunnel` docker-compose stack (build-time image snapshot). Must `build` + `up -d` `hevi-api hevi-web` after code/migration. DB-ahead-of-image migration set → API crash-loop. Production op — confirm before running.
- **Never swap the SDXL fp16 VAE back to the official one** (`_sdxl_worker.py` uses `madebyollin/sdxl-vae-fp16-fix`; official needs fp32, no VRAM headroom). And never merge the IP-Adapter vs plain-txt2img code paths without re-testing (attention-slicing + IP-Adapter crashes).
- **Never re-silence the keyframe canon-copy fallback** (`scene_render_avatar._edit_keyframe` → `_KF_CANON_COPY`/`_is_canon_copy` → `ShotFrame.degraded` → verdict `rewrite`). It exists because抄定妆照 passes both verdict checks (画面不黑 + 身份满分,它就是那张 canon)——2026-07-17 审计实证 task `da0bbeff` 20镜里14镜如此,静默交付成"大头念台词"。Downgrading it back to a bare `logger.warning`, or making verdict ignore上游 `degraded`, re-opens the exact silent-delivery hole. Preserve the chain in any edit (commit `1799dd8`).
- **多角色镜头的 fallback 判据必须按"expected_character_count vs 实际能覆盖的人数"统一判定,不许按具体崩在哪一级分别打补丁(2026-07-18 修复,两版)。** `_edit_keyframe` 现在按 `expected_character_count` 参数逐级检查每一级 fallback 结构上是否覆盖得了这么多人——IP-Adapter(单张脸)/canon 复制(单人)对 `expected_character_count>=2` 直接跳过或拒绝,不采信;云端 edit 要求参考图张数够。任何一级都覆盖不了 → 抛 `MultiCharKeyframeFallbackExhausted`,整镜显式失败(空 clip + degraded + 专属 reason),不静默交付"看似成功、实则少了人"的帧。**第一版(只堵 canon_copy 那个洞)不够**——2026-07-18 第一次整机产集真实撞见:compose img2img 崩溃退到 IP-Adapter,IP-Adapter"成功"返回单人图,不进第一版判据,verdict 完全看不出来。改代码前先挂 debug log 真机复现(见下方 ✅ Done · INC-003 P0 第二版),不要臆测断点在哪。

---

## 🔄 In Progress

- **SPEC-005 通鉴管线改造 · 第一批(讲解段)已实现,待真实产集验证,2026-07-18。** spec 见
  `docs/specs/SPEC-005-tongjian-pipeline-refactor.md`——通鉴一集 = 讲解主干 + 演绎插段(形态C),
  讲解段今天就能做(不需角色 Subject / SceneStage / 多人同框)。新增
  `hevi/tongjian/{schemas.EventUnit+Segment、event_unit.py、narration_script.py、diagram_gen.py、
  narration_episode.py}` + `gates.py` T1(版权 lint)/T2(画面节奏 lint)+ `edge_tts_custom.py`
  narrator 声线(不入角色轮询池,靠物理隔离满足"narrator≠剧中人声线"硬约束)。**全部复用现有
  L3/L4/L6/L8 执行层**(voiceover/shotlist/scene_render/assemble),零新装配代码——只新增"从原文到
  讲解 Script"的产出侧。4 个新测试文件 23 个用例全绿,全量回归 1336 passed,ruff 干净。**未做真实
  LLM/TTS/图像生成实跑**(real-spend,待 soffy 确认预算)——mock 全链路验证的是接线正确性,非讲解
  质量/画质结论。batch2(演绎段接 SPEC-003 导演链)/batch3(装配接缝 + T3/T4 lint)未开始。

- **INC-003 多角色同框身份层 — 实测归档(不是收缩),2026-07-18。** spec 主命题是"IP-Adapter 单脸对多人是死路,LoRA 是唯一原生解"。三次真机探路(零训练、零 GPU 增量,走现有 compose→img2img 路,王生/老道 G-S1 canon;脚本 `scripts/incr003_multichar_composite_verify.py` + `scripts/incr003_scene_and_facing.py`,产物 `output/incr003_*/`)把"多角色身份"拆成四格,各归各的解:

  | 子问题 | compose→img2img | 要不要 LoRA | 证据 |
  |---|---|---|---|
  | 正面双人身份 | **能** | 不要 | 左半vs王生 0.790、右半vs老道 0.850,无渗透(VLM 左无须/右有须白发) |
  | 场景融合(同处一室) | **能(已坐实)** | 不要 | 真实客栈底图+靠近下移+统一光照+strength 0.55 → 两人同桌共享暖光/透视,肉眼确凿同一空间(`scenefix_s55_twoshot.png`,老道 0.870/正面/大白须);纯灰底的"贴上去"是构图 artifact |
  | 对视侧脸·特征鲜明角色 | **能** | 不要 | 老道侧脸间距 +0.16(白须撑住),绝对分 0.85→0.66 但不认错 |
  | 对视侧脸·通用脸角色 | **崩** | **这里才真有价值** | 王生侧脸 0.661,交叉(左vs老 0.680)反超,间距转负,渲成中性动漫青年 |
  | 打斗接触 | 从没测(静态图测不了) | 也解不了 | 需模型原生理解接触物理 = provider 的活 |

  **补三条(重要):**
  1. **归档不是收缩。** 四格里三格 compose 已解,只剩"通用脸侧脸"一格。而这一格有**三条比训 LoRA 便宜的路都没试**:(a)**角色特征鲜明度**——王生正面间距只有 +0.08 是**角色设计问题不是技术问题**,应在③设计清单加 lint"每角色必须有强可辨特征";(b)**机位避开纯侧脸**——真实对话戏大量用过肩正打(后景那人接近正面),这是 SceneStage `coverage_plan` 该管的;(c)**strength 调参**——0.65 没探到底。打斗接触那格 compose/LoRA 都解不了(provider 的活)。**结论:LoRA 没有一个格子是它必须的**,故不建 kohya_ss 训练子系统(那是 GPU-blocked 的大投资)。上一轮"确认自造路先做无 GPU 骨架"的 SubjectLora schema/路由骨架**也一并暂缓**——先验证了"哪个格子真需要 LoRA",没有一个,就不先落结构。
  2. **CLIP 分只看间距不看绝对值。** 共享服化/画风会把绝对分整体抬高(正面交叉分都 0.6-0.7),真信号是"身份分 − 交叉分"的间距。这条纪律留给后来人:别拿 0.85 当"身份好",要看它比交叉高多少。
  3. **VLM 判断都要旁证,整体判断直接不采信。** "像不像拼贴"这种 holistic 判断 VLM 不可靠(判"拼贴"但肉眼明显同一空间);连"有没有胡子"这种极简问题也会错(scenefix_s55 老道明明一把大白须,VLM 答"无")。**真正可信的是肉眼 + 身份分间距的收敛**,别信任何单个 VLM 答案。渗透测用极简问题但必须和身份分/肉眼对齐才采信。

  **(a) 姿势失控已修(2026-07-18)**:场景融合图里老道在 strength 0.6 下自己转身(front 视图被过度重绘),污染了他那格身份数。降到 **strength 0.55** 即保住正面,老道身份 0.736→**0.870**(间距 +0.226),王生 0.774,场景仍确凿融合。**姿势失控是独立于身份的问题**(strength 太高 → 角色自己转身/改姿势),compose/LoRA 都不直接解,靠 strength 调参或 ControlNet/几何锁。

  **边界(别过度解读)**:单 seed、单对角色、静态图;CLIP 分只看间距。

- **自造渲染消费层四断链整改 — 审计+修复已提交,真机验证悬空(2026-07-17,commit `1799dd8`,未 push)。** 三个 Explore 子代理审计导演流水线,实证 ①-④ 锁定的导演决策大面积不落到画面,根因是"锁定"被实现成**存储动作而非约束动作**(人在③锁的服饰④看不见、③.5锁的机位④看不见、④锁的景别⑤零引用)。**铁证**:task `da0bbeff`(105s/20镜/三国)一次真实产集,20镜里 **14镜关键帧与 canon 定妆照字节级相同**(md5 相等,非"生成得像"),final.mp4 第90秒抽帧就是刘备定妆照——这就是"大头念台词"的实物。已修四处:
  - **F-0(最要命)**:INC-001 §C/§E/§H/§J + INC-002 时刻切片此前只拼进云端 edit 的 instruction,而 `_local_kf_prompt` 签名里没这个参数、local 才是默认引擎 → 这些导演命令**只在 GPU 掉线走云端兜底时才生效**。更糟 §K `quality_checks` 按"字符串构造成功"报 `eyeline_applied:True` 假阳性,断链半月没被验收抓到。已给 `command_summary` 参数两条引擎路都注入,§K 改按"是否真落进实际用的关键帧"判定。
  - **canon 兜底不再静默**:`_edit_keyframe` 返回引擎标签,`_is_canon_copy` 字节比对作权威判据,抄定妆照 → `degraded` → verdict `rewrite` 返工闸;`completed_shots` 不再恒等于总镜数。
  - **Gap 3 服饰约束**:`_WARDROBE_NEGATIVE_EN`(英文)在 `_edit_keyframe` 一处注入,压"奇幻铠甲/尖角肩甲"。此前强负面词只在参考图阶段生效,关键帧走 sdxl 默认负面词无铠甲词 → "参考图干净、一进关键帧长圣斗士肩甲"。**必须英文**:`sdxl_local_service` 只翻译正向 prompt(:186),负面词原样透传(:195),base SDXL 不认中文——INC-002 `derive_negatives` 派生的中文负面词至今就是这么死的。
  - **Gap 1 阶段1 + Gap 2**:见下方各自条目。
  - **验证边界**:全量 1316 passed(+12 回归,三处新接线均反向验证过=摘掉修复测试变红);合成图用真实 Subject3D 产物肉眼验证。**未做真实付费端到端**——GPU 两条腿(本地 sdxl `require_gpu` 争用 / 云端 qwen-image-edit `FreeTierOnly` 额度墙)现均断,证明的是接线正确性,**非画质结论**。要画质结论须先让两条腿至少活一条。
  - **与 LibLib 转向的关系**:本轮加固的是**自造渲染路**(即 `da0bbeff` 实际跑的那条),与下条 LibLib 转向不冲突——LibLib 尚待 KEY 验证方向,在它成为主路前,自造路仍是当前唯一在产集的路,该修的漏得修。

- **Gap 1 几何控制:多角色走位(阶段1已接,阶段2地基就绪待真机,2026-07-17)。** 走位/朝向/落位全程中文文本喂 prompt、渲染层无几何控制;SPEC-004 img2img 朝向视图此前只接对白镜 lead 一人,多角色同框(走位最需要几何处)零覆盖。
  - **阶段1(已接,commit `1799dd8`)**:`_compose_layout_base` 把在场角色 Subject3D 朝向视图按走位(复用前端俯视图 左/中/右 单一真相源词表)合成 img2img 底图,接进多角色分支。真实 Subject3D 帧验证过(抠底干净、浅袍没误抠、左右落位对)。**已知取舍**:img2img 与 IP-Adapter 在 `_sdxl_worker.py` 互斥,走这条=让出锁脸、身份押在较糊的 Subject3D 视图(CLIP 0.61 vs 真照 0.77-0.84),多角色划算但需真跑判定。
  - **阶段2(地基就绪,消费端悬空)**:`_compose_pose_control` 产 OpenPose 骨架控制图(标准配色/黑底/按走位落列,已落盘)。**worker ControlNet 分支未接**(`_sdxl_worker.py` 有精确 TODO)。**三件真机阻塞**:①权重下宿主机(容器 `:ro` 挂载,联网在容器外下 ~2.5GB `xinsir/controlnet-openpose-sdxl-1.0` 或 ~700MB `-small` 到 `settings.sdxl_model_dir`);②VRAM 实测(CN +1.3–2.5GB 叠 IP-Adapter 路峰值 7.1GB/空闲7.4GB,可行性报告判"real OOM risk",必须真量);③骨架当前只落站位不落朝向(需按 shot_view 出侧/背面骨架或从 GLB 渲)。CN 与 IP-Adapter 在 diffusers 0.38 可共存(几何+锁脸同时要),这是它比阶段1强的地方。事实纠正:该模型目录是 ext4 非 NTFS;GPU 非90容器共享(实测1个计算进程/7.4GB空闲);"huggingface_hub dist-info landmine"只在 Wan2GP venv 有效,hevi venv 干净。

- **Gap 2 跨镜连贯:观察态注入(已接,2026-07-17,commit `1799dd8`)。** 镜间此前是硬 concat,`_adjacent_context` docstring 承诺的"实际末帧覆盖起始态由观察态另行处理"审计 grep 全仓不存在。`_observe_end_state` 用 VLM 看上一镜真实末帧、产停留态当下一镜承接锚,取代计划态文本。**走状态连续非像素连续**(否定了"末帧直接当下镜首帧"的字面接法——切镜换机位,像素直连=剪辑点变 morph、景别机位全废)。可 config `observe_continuity` 关,默认开,免费本地 VLM。

- **★方向转向:接 LibLib.tv(libtv)出片,不再自造渲染(2026-07-16)。** 实测 hevi 自造导演产集出"大头念台词/穿戴像圣斗士/走位丢失",实证根因:导演路完全不走 oskill、自造了薄版本(参考图无 seed 随机+精确同名才复用→身份漂移;服饰文本零约束叠画风词→夸张;④走位/对白动作/语气到渲染层多处断链)。soffy 指向 libtv-skills(github.com/libtv-labs/libtv-skills)——LibLib.tv 专业生视频平台的 agent-im 客户端,核心原则"用户侧不做创作、只做传话"。**决定:hevi 定位改为"用 LLM 产加厚剧本(它擅长),把剧本作创作指令中继给 LibLib.tv 出电影级视频(它擅长)"。** 已建 `hevi/video/libtv_service.py`(agent-im 客户端:会话/轮询/提取结果URL/下载,Bearer settings.libtv_access_key 走.env)+ `scripts/libtv_relay.py`(剧本→创作指令中继,可 --manuscript 现产剧本)+ settings + 测试 4/4。**待 soffy 给 LIBTV_ACCESS_KEY 真跑验证方向,成了再深接进 produce(作 render backend 选项)。** 注:oskill 的"电影 skill"实证是空壳(consistency=文件存在率、image_generate 无参考图参数、storyboard 只有 motion 无景别/轴线)——接 oskill 反而更糟,故不走。


- **②剧本层加厚:小说语言→剧本语言(2026-07-16)。** 实测反馈:产集出来"一个个大头念台词、没动作没感情"——根因是 ②剧本太薄(只给"谁说了句什么",数字人只能演大头对白)。改厚 `screenplay.py` 的 `_SCREENPLAY_PROMPT`:强制①把每个情节点展开成一连串可拍的物理动作+走位+环境+表情;②一场一情绪/动作拍点,不把多轮对白挤进一个大头场;③narration 写成分镜级可拍画面(非情节概要);④文言转白话但保名句/意象/语气分量。带一段"小说一句→剧本四场"的张飞失徐州 few-shot 锚定粒度。纯 prompt 改动,schema/解析不变(43 测试过、lint 干净)。**注意副作用**:场分得越细→下游 design_list/scene_stage/shot_list 逐场 LLM 调用越多→产集更慢更贵(这是要电影感的必然代价)。**下一步**:③设计清单/④分镜的 prompt 可能也要相应加厚(让 narration 的动作真切成动作镜)。

- **SPEC-004 v2:接通 Subject3D 机位消费 —— 让场事实第一次真正落到画面(2026-07-16,方案待拍板)。** G-S1 铁证:身份靠参考图锁=有效,靠文字描述=无效;朝向/落位现在还在用文字喂,注定同样执行不出来。正解=把朝向/落位变成结构化条件 = Subject3D 机位渲染帧(不是 ControlNet 2D 补丁,那和 Subject3D 路线撞车)。**两张只读测绘的关键事实**:
  - **Subject3D 活着(重开,非 drop)**:`hevi/subjects/subject3d_local.py::generate_subject3d`(TripoSR,单图→4 视图 front/left/right/back,CPU ~172s),存 `Subject.metadata.subject3d.views`;仅在短剧通道接了(`shortdrama.py` 后台派发)。SPEC-001 §6 的"drop Subject3D"已被 soffy 2026-07-13 重开(单角色探索,不进主线 G2)。vault identity_pack 的"multiview"是**另一套**(2D SDXL 9 宫格,无 3D)。
  - **管道两头都有、中间断,断点精确**:4 视图一路传到 `CharacterBibleEntry.ref_image_views`(schemas.py:214)——**写 3 处读 0 处,死数据**;`_canonical`(scene_render_avatar.py:304)只用单张 front `ref_image`,无角度参数。接线 = 4 触点:①**结构化朝向(真拦路石:facing 自由文本+axis_side 只 left/right,推不出视图)** → ②桥接层加 `shot_id→view` 映射(并 shot_space_by_id)→ ③`ref_image_by_id`(:694)消费 `ref_image_views` → ④`_canonical` 加角度参数+按(cid,view)缓存。
  - **必摆上桌的权衡**:TripoSR 3D 帧身份 CLIP **0.61 vs 真实 2D 照片 0.77–0.84**(subject3d_local 自标"仅补充候选")→ 用 3D 侧视锁脸=朝向对但身份掉。合理策略:front 用 2D 真照(身份最强),仅当该镜确需非正面朝向才用 3D 侧/背视。
  - **★最小真跑对比结论(2026-07-16,soffy 授权本地跑):img2img 赢,架构定了。** 喂王生 3D 右视图给 **IP-Adapter → 只迁身份不迁姿势,输出仍正面**(证实我的技术疑点);**img2img 从 3D 视图当底图(strength 0.45)→ 朝向真带过来 + 身份被 SDXL 精化回清晰王生侧脸**。ControlNet 不用试(img2img 已成)。TripoSR 视图本身确认真转向(背视=真背面、右视=真侧脸)、身份可辨。→ **B = img2img 消费 Subject3D 视图,几何选哪个视图。**
  - **实施进度**:**B1 结构化朝向 ✅**(`InitialPosition.facing_deg`+`CameraSetup.azimuth_deg`+`resolve_subject_view` 几何,test +3)+ **B2 worker img2img ✅**(`_sdxl_worker` img2img 分支[与 IP-Adapter 互斥]+`sdxl_local_generate` 经 extra.init_image/strength 透传,生产路真-smoke 出清晰王生侧脸)。**已提交 `96a1f26`**。**B3 渲染层消费 ✅**:`scene_stage.compute_shot_views`(每镜每角色 azimuth/facing→视图);`render_director_episode` 建 `shot_view_by_id` + 收 `subject3d_views` 经 config 传入;`scene_render_avatar` 读之,对白 lead 该镜视图非正面且已建 3D 视图 → `_edit_keyframe(init_image=view)` 走 img2img(朝向落地),否则 init_image=None 退回原 IP-Adapter 2D 真照。**全程向后兼容 + inert**:subject3d_views 默认空 → 一律 front → 行为不变(B4/B5 填充后才激活)。`_edit_keyframe` 加 init_image/init_strength 参数(img2img 分支)。test_scene_stage +3(compute_shot_views)、test_tongjian_scene_render_avatar +2(非正面→init_image / front→None)。**B4 填字段 + 建视图 ✅**:(populate)SceneStage LLM prompt 产 `facing_deg`(0前/90画右/180背/270画左)+`azimuth_deg`,`_parse_deg` 解析归一;(core)`_resolve_subject3d_views`(已建取 metadata、未建调 generate_subject3d 现建 CPU~172s/角色、缓存)+ `_scene_stage_has_angles` 门控(无角度不白建)+ produce 后台建 `subject3d_views` 传 render;(ui)DP2 SceneStagePanel 落位加朝向角°输入、机位显方位角。test_scene_stage +1、test_director_pipeline_router +2;tsc 干净。**B5 E2E ✅(2026-07-16,本地免费真跑)**:`scripts/b5_orientation_e2e.py` 走真实生产函数(`compute_shot_views` + `_edit_keyframe` img2img 路)——王生 facing_deg=90、三机位 azimuth 0/90/180,几何算出 left/front/right;真出三帧:**az0→侧脸朝画右、az90→正面、az180→侧脸朝画左(镜像),身份一致、朝向随机位正确变化**。`_VIEW_BY_DELTA` 约定对,不用翻。**场事实(朝向)第一次真正落到画面,且是走完整生产管线证的。SPEC-004 v2 B1–B5 全部完成。** 生产激活尚需:每个真实角色建 Subject3D 视图(produce 已接 `_resolve_subject3d_views` 自动建/取,首个真实产集会 CPU ~172s/角色)+ SceneStage 真设角度(LLM 已会产,人可 DP2 refine)。
- **零成本①② prompt_language 漏斗自动译 —— ✅ 已实施(2026-07-16)。** `sdxl_local_generate`/`_batch`(唯一漏斗)入口加 `_ensure_english_prompt`:含中文→qwen_cloud 译英+缓存,译失败用原文不阻断;4 个中文调用点**一律不用改**(漏斗统一处理)。修正 `_local_kf_prompt` docstring 的"中文可用"错述。`HEVI-ARCHITECTURE.md` 能力矩阵加 `prompt_language` 列 + §5.3.4 表结构化 sdxl=en/Seedance=zh。`tests/test_sdxl_prompt_language.py` 5/5(纯函数,不真跑 GPU/LLM)。**下方为当时测绘背景:**
  - **短剧 G1 那次"100% 参考图角色错配"不是同源**(那路用 qwen_image 参考图 + happyhorse 参考图转视频,均中文原生云模型,不碰 sdxl)——结论不用重评。
  - **但扒出主线 4 个 sdxl_local 直连点全在喂中文、全会中招**:`scene_render.py:105`(场景底图)、`:152`(shot 帧)、`character_bible.py:251`(角色参考图)、`scene_render_avatar.py:538`(avatar 关键帧,且其 docstring 还错写"中文实测可用"——与 identity_pack 已改英文的结论直接冲突)。任何走本地关键帧的导演/通鉴产集都会中招,至今没人用本地引擎真产集撞到。identity_pack 已修(英文)。
  - **落点**:hevi 无统一 ProviderMeta(元数据散在 3 张 video-only dict + obase 闲置的 `register_with_capability` 钩子);单一漏斗 = `sdxl_local_generate`(sdxl_local_service.py:112,所有 sdxl 路径唯一入口);文档锚点 = `HEVI-ARCHITECTURE.md:401` §5.3.4 provider 默认行为对照表(已有 Seedance V2 偏好中文短提示的散文条目,待结构化)。
- **SPEC-004 场面调度层(SceneStage)— v1 已完成(阶段 0–4 + DP2 全绿并提交),G-S1 结构线通过/像素线未兑现(转 v2 上条,详见本条下方阶段 5 子项),2026-07-16。** 定调:电影级最小创作单元是"场"不是"镜头",此前六份 spec 全建在 Shot 粒度上是"啥也不是"的结构性根因。在 ③设计清单 与 ④分镜 之间插 ③.5 场面调度层,每场一个 SceneStage(空间图+落位+节拍+轴线+注意力脚本+机位),该场所有镜头从同一场事实切视角。完整设计+CC 实施决策见 `docs/specs/SPEC-004-scene-staging.md`(v0.2)。**关键决策(soffy 2026-07-16 拍板)**:DP1 空间 prompt 编译注入桥接层 `tongjian_render.py`(确定性,不经 LLM;LLM 只判断"哪几拍+选哪机位");DP2 v1 人审 UI = 卡片+就地编辑+俯视图预览(复用 ShortdramaCreatePanel,不做拖拽台);俯视图从 zones 确定性派生(单一真相源)。**只读测绘关键发现**:(a) `ShotBlocking`(position/facing)是**死写字段**——下游零消费,安全接管;(b) `eyeline/screen_direction/前景/焦点` 现役根本不存在(§3.1 是"改数据来源"不是"拆逻辑");(c) ★**断链#3**:`DesignScene.environment/lighting/mood` 在 draft 被填但从桥接层到 L6 渲染 prompt **全程零消费**,场景空间描述整条断链;(d) INC-001 §H/§B/§J 全在渲染层 `scene_render_avatar.py`。实施阶段:0 spec落库✅ → 0.5 修断链#3✅ → 1 SceneStage schema+AI草案✅ → 2 状态机接一级✅ → 3 ShotList 接 4 引用字段+桥接层投影✅ → 4 四条 lint✅ → DP2 人审 UI✅ → **5 G-S1 验收(进行中:确定性证明✅,本地关键帧对照真跑中)**。**验收门 G-S1 不过不做 v2。**
  - 🔄 **阶段 5 G-S1 验收(2026-07-16,soffy 授权用本地模型跑)——结构证明通过,视觉证据待真人肖像重跑。** 脚本 `scripts/gs1_scene_stage_run.py`:手工构造一场 3 人对话戏(零 LLM)→ 1 SceneStage → 6 镜头 `link_shots_to_scene_stage` 填引用 → 单变量对照关键帧(实验组=断链#3场景描述+`project_shot_space`投影;对照组=空),全本地 sdxl 零花费。
    - **① 结构/确定性半 = 通过 ✅**(SPEC-004 实质主张):6 镜投影文本全部从同一 SceneStage 派生(王生恒在门口面向老道、老道恒在窗边、王生画左老道画右、逐拍焦点),**§4 lint 达标线(L1跳轴/L3 eyeline)干净**(L2反打/L4冗余为覆盖深度建议,6镜最小切片必触发 L4,不计入 G-S1)。"场事实消灭空间矛盾"在 prompt/结构层成立、可复核。
    - **② 像素/视觉半 = 未证成 ❌**(被本地生成模型质量卡住,非机制问题):本地 sdxl canon 完全渲染错——老道(白须道士)→银发少女、全景建场镜→山水风景无人;base SDXL 对中文老者/道士 prompt 直接无视(sdxl_local 已知弱点,同短剧 G1"100% 参考图角色错配")。本地 VL(ollama)焦点断言全 None(memory 早警告不稳)。故"人物相对位置/朝向一致、焦点可辨识"像素级达标项无法从这批图判定。
    - **收尾(soffy 2026-07-16):不用真人照,改英文 prompt 出 canon,免费本地重跑。** 首跑角色错渲的根因是**中文外貌 prompt**(base SDXL 对中文老者/道士渲成通用少女);换**英文 prompt**(`_CHARS_EN`)后三张 canon 全部正确、可辨认、互不相同(青年书生/白胡子老道士/中年络腮胡掌柜),已验证。脚本 `--ref-dir` 仍保留(有真人像优先用)。
    - **重跑最终结论(soffy 拍板措辞,2026-07-16)——不写"G-S1 通过":**
      **G-S1 结构线通过**(投影从同一 SceneStage 一致派生 + §4 lint 达标线 L1/L3 干净 + 身份跨镜一致);
      **像素线因本地生成器能力受阻「未兑现」,转 v3 议题。** 按 SPEC-004 §7/§6 本就把像素级朝向/落位划给
      v3(真 3D 相机投影身份帧/场景帧),按约验收成立;**但"未兑现"三字必须留在这里:我们栽过
      "结构成立→放行→生产崩"的跟头,一个漂亮的 ✅ 会掩盖「这个机制至今没在任何一张真实画面上
      兑现过价值」的事实。** 具体:身份现正确且跨镜一致(IP-Adapter 锁对脸),但每张关键帧都是
      正确身份的**正面单人像**——朝向/落位/环境/同框全没落到画面,**exp 与 ctrl 像素上几乎无差**。
    - **★G-S1 给的铁证(重构了下一步方向):身份靠参考图锁=有效;身份靠文字描述=无效**(中文老道→
      少女)。而**朝向/落位现在恰恰还在用文字喂**("面向老道""画左画右"),所以注定和"中文老道"一样
      执行不出来。正解**不是 ControlNet 2D 补丁**(与已确立的 Subject3D 路线撞车,做了要拆),而是把
      朝向/落位也变成**结构化条件 = Subject3D 机位渲染帧**:TripoSR 已跑通、4 机位帧已产出、数据管道
      已通到 character_bible,SceneStage 已算出"这拍王生面向右"、Subject3D 已能渲"王生面向右帧"——
      **两头都有,中间没接。分镜层加机位/方位角字段这最后一根线,是场事实第一次真正落到画面的关键。**
      → 见下方 In Progress 的"SPEC-004 v2:接通 Subject3D 机位消费"。
    - **⚠ 关键操作发现:本机共享 RTX 3080 上另有租户常占 ~2.4GiB,SDXL VAE decode 峰值会 CUDA OOM(不是 Xid 掉线,GPU 在线),必须 `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` 才出图;IP-Adapter 关键帧路径跳过 attention-slicing 峰值更高,已降到 576×768。全 12 帧+3canon 本地跑通无 OOM。** 见 memory [[gpu-pcie-fallen-off-bus]]。
  - ✅ **阶段 0.5 断链#3 修复(代码+单元,零花费)** — `DesignScene.environment/lighting/mood` 经 `render_director_episode` 建 `scene_desc_by_id` → `config.params` → `build_frame_manifest_avatar` 按 `shot.scene_id` 取切片 → `_local_kf_prompt`/`_gen_action_keyframe` 6 处调用点全接通,空间项排相貌前(§F.1)。全向后兼容(tongjian 管线不传该 param 即无变化)。`test_tongjian_scene_render_avatar.py` 37 passed(+3 新:2 纯函数 + 1 端到端接线)。**视觉对照脚本 `scripts/scene_stage_gap3_contrast.py` 已就绪待触发**(dry-run 零花费已验证;`--gen --real` 才真跑关键帧,soffy 定 GPU/预算)。
  - ✅ **阶段 1 SceneStage schema + AI 草案(纯代码,零花费)** — `pipeline_schemas.py` 加 SceneStage 全套子模型(space_map/beats/blocking/axis/attention_script/coverage_plan,忠实 spec §2)。`hevi/director/scene_stage.py::generate_scene_stage_draft` 镜像 design_list draft 范式(qwen_cloud + 确定性兜底)。**v1 设计决策**:beats 以对白行确定性锚定(一句一拍 btNNN);sightlines 从对白 speaker→target 确定性派生(§H 升格,权威源,assumed=False),LLM 只补无对白视线(assumed=True)。**顺带**:`target_name` 从 ④ShotList 级**升到 ②Screenplay 级**(`ScreenplayDialogueLine` 加字段 + screenplay 生成 prompt/解析填充)——因 SceneStage 在 ShotList 之前生成,"谁对谁说"须是 ②级事实才能确定性派生视线(解决 spec 的排序矛盾)。`test_scene_stage.py` 新增 6/6 green;director schema/generation/render 无回归(38 passed);ruff 干净。
  - ✅ **阶段 2 状态机接一级(纯代码,零花费)** — `director_pipeline.py`:`_STAGES` 在 design_list 与 shot_list 间插 `"scene_stage"`(所有 `_stage_index(name)` 判据自动右移:concept0/screenplay1/design_list2/**scene_stage3/shot_list4**;产集门 `_stage_index("shot_list")` 天然多一道,未锁 scene_stage 则 shot_list 无法锁)。新增 `SceneStageSet` wrapper(逐场 SceneStage 集合)。改造:**③design-list/lock 后自动生成的下一级从④分镜改为③.5 场面调度草案**(`_build_scene_stage_set` 逐场 `generate_scene_stage_draft`,后台跑);新增 `POST /works/{id}/scene-stage`(重生成,后台)+ `/scene-stage/lock`(锁定→locked_through=scene_stage→后台生成④分镜草案)两端点。`_init_work`/`_work_status`/回退语义全接 scene_stage。`test_director_pipeline_router.py` +3(scene-stage lock/regenerate/回退)并更新既有 index-shift 断言,27 passed;**全量 1224 passed 零回归**;ruff 干净。
  - ✅ **阶段 3 ShotList 接 4 引用 + 桥接层确定性投影(核心 payload,纯代码零花费)** — `ShotListItem` 加 4 字段(scene_stage_ref/beat_range/camera_setup_ref/attention_ref,全默认向后兼容)。**降风险决策**:v1 用**确定性链接**而非重写已部署的 shot_list LLM prompt——`scene_stage.py::link_shots_to_scene_stage` 把镜头的对白行精确匹配到对白锚定的 beats(比 LLM 选更准、无幻觉),`camera_setup` 按 serves_beats/subjects 重叠择优;DP1 原设想"LLM 判断哪几拍+机位"改为确定性派生,作 v1 简化(LLM-choice 留 v2)。`director_pipeline` 的 scene-stage/lock + shot-list/regenerate 生成分镜后自动 `link_shots_to_scene_stage`。**桥接层投影(§3.2 核心)**:`scene_stage.py::project_shot_space(stage, shot)` 从 SceneStage + 引用**确定性投影**"这机位这一拍看到什么"(落位/朝向 + 焦点[带 intensity 虚化处理] + 画面正方向),`render_director_episode` 建 `shot_space_by_id` 经 config.params 传入渲染层,与断链#3 的 scene_desc 一起拼进 `_local_kf_prompt` 空间项。**镜头间天然一致——都从同一 SceneStage 投影,不各自想象空间(消灭空间矛盾的机制到位)**。scene_stage 全程穿到 produce→`_run_director_via_tongjian`→render(旧 work 无 scene_stage 则 None,退回断链#3 行为)。`test_scene_stage.py`(link×3 + project×2)+ `test_tongjian_scene_render_avatar.py`(shot_space 端到端)新增;**全量 1230 passed 零回归**;ruff 干净。**尚未真跑**(投影文本确实改善画面是真实生成才能验,归 G-S1)。
  - ✅ **阶段 4 四条确定性 lint(纯代码零花费)** — `hevi/director/scene_stage_lint.py::lint_scene_stage(shot_list, scene_stage_set)`,零模型成本规则检查:L1 跳轴(相邻同场镜头机位不得跨轴换侧,除非该拍有已声明 axis_shift)、L2 反打差异(焦点不同的相邻两镜景别须差 ≥2 档,`_shot_size_rank` 解析远0/全1/中2/近3/特写4)、L3 eyeline 一致(镜头对白 speaker→target 须与 SceneStage.sightlines 在该拍一致——抓 target 漂移)、L4 剪辑冗余(每个被拍到的 beat 至少 2 个不同机位覆盖)。只作用于接了场事实的镜头(scene_stage_ref 非空)。`director_pipeline` 的 scene-stage/lock + shot-list/regenerate 链接后自动跑,findings(`LintFinding` dataclass → asdict)暴露在 `_work_status`["scene_stage_lint"]。`test_scene_stage_lint.py` 9/9;**全量 1239 passed 零回归**;ruff 干净。
  - ✅ **DP2 场面调度人审 UI(前端,零花费)** — 六级链的 UI 补齐(导演台 `DirectorPipelineConsole` 加 ③.5 一级)。`SceneStagePanel.tsx`(Construction-First:AI 出完整草案,人攻击落位/注意力/机位后锁定):每场一张卡片,含 **从 zones 确定性派生的 SVG 俯视示意图**(§7 单一真相源,纯前端零依赖,不让 AI 画)、可编辑落位(区域下拉/朝向/姿态)、可编辑注意力脚本(焦点/强度/转场)、可编辑轴线正方向约定、只读机位方案/beats。`ShotListStep` 加 **§4 lint 告警横幅**(跳轴/反打/eyeline/剪辑冗余,从 `work.scene_stage_lint` 渲染)。状态机前端全接:`STAGE_LABELS` 插 ③.5、`locked_through` 门控右移(design_list===1→SceneStagePanel===2→ShotListStep===3、producing>=4)、`regenerate('scene_stage')`+`lockSceneStage` 后台轮询、api-client `regenerateSceneStage`/`lockSceneStage`、types 全套 Dp* 场面调度类型 + DpWork.scene_stage/scene_stage_lint。globals.css 加 `.dp-ss-*`。**tsc --noEmit 干净**(next 16 已移除 `next lint`;`next build` 见下)。**未真实浏览器点验**(留 G-S1 一并做)。
- **主线现已是 SPEC-003 导演流水线 + INC-001 电影级补强(2026-07-15,PR #23/#25 已合并并部署上线 hevi.kanpan.co)。INC-001 A–L 已全部落地(见下方 Done)。** Concept→Screenplay→DesignList→ShotList→L6 生成的导演管线(`hevi/director/`),叠加 INC-001 全套:§B action_beats 动作弧(`action_arc` 默认 2point 零成本、3point 可开峰值弧 2×)、§C 首帧未完成态、§E 约束动态分级、§F 编译规范、§H target_name→eyeline、§J 相邻镜头上下文、§K 可观察性;以及**交互式导演台的逐镜头准备台**(§A/§G/§I/§L:候选表 3 张 DB 表 + 就绪状态机 + skip 逃生阀 + 聚合端点 + 前端面板 + 产集就绪门)。§D/§F.4 本管线天然满足,无需代码。**唯一悬空:§B 尚未做真实渲染验证**(是否真出连续动作,要真实花费,待 soffy 定预算)。下方 SPEC-001 骨架条目均已随 PR #21-23 合并,作为历史留存。
- **SPEC-001 短剧/漫剧通道 — FROZEN, 阶段 1 in progress.** Eval + 4 settled decisions at `docs/specs/SPEC-001-shortdrama-eval.md` (2026-07-11). Decisions: (1) drop Subject3D, rest on 2D CLIP lock; (2) build B0 by generalizing tongjian L0-L2; (3) 剧集规划器 is a new planning layer (not Producer ext); (4) LLM via `qwen_cloud` (already wired + verified). **阶段 1 min-loop** (eval §5): B0 story graph → SeasonPlan splits 3 episodes → reuse Director/L1 per-episode → read-only Season Board. G1 gate: short novel → 3 episodes → cross-episode identity consistent (identity_distance ok via 2D CLIP).
  - ✅ **Step 1 — B0 story parsing done.** New module `hevi/storygraph/` (schemas + extract), novel-general generalization of tongjian L0. Reuses tongjian's deterministic span/ID/hallucination-guard machinery (imports `_find_span`/`_call_llm_json` from `chapter_ir`, the established shared-helper convention). StoryGraph per SPEC §2.3 (relationships/arcs structured but deferred to阶段 2). Selects `qwen_cloud` LLM explicitly. `tests/test_storygraph.py` 4/4 green; tongjian no regression. Not yet committed.
  - ✅ **Step 2 — Episode Planner (剧集规划器) done.** New module `hevi/season_planner/` (schemas + planner), a new planning layer (not Producer ext). `build_season_plan(story, target_episodes)` mirrors tongjian L1: LLM splits timeline into N episodes (best-of-N + LLM-judge), code deterministically assembles characters_present/locations/beats from StoryGraph. `gate_season_plan()` = SPEC §3.4 pre-gen self-critique (all deterministic): event coverage/no-dup/no-orphan, per-episode beat completeness (no all-过场 episode), episode-count feasibility, character non-discontinuity (主角凭空消失). Reuses tongjian `GateResult` + `_call_llm_json`. Selects `qwen_cloud`. `tests/test_season_planner.py` 8/8 green. Not yet committed.
  - ✅ **Step 3 — dispatch to existing Series/Director done.** New adapter `hevi/season_planner/dispatch.py` (does NOT modify `series_service`). `dispatch_season(plan, story, series_service, subject_id_map, style_pack_id, spec)`: creates one Series (season = series, char group from subject_id_map, StylePack locked), then per EpisodePlan calls existing `create_episode(topic=brief)`. `episode_brief()` reduces the rich EpisodePlan → a narrative topic text the existing Director consumes (title + emotion arc + present characters+descriptions + ordered event summaries with beats + own-episode 原文 quotes). Cross-episode identity rests on Series subject_ids (2D CLIP lock per decision 1). `tests/test_season_dispatch.py` 4/4 green; `test_series.py` no regression. Not yet committed.
  - **Data flow now wired end-to-end (skeleton):** 小说手稿 → `storygraph` → `season_planner` → Series + N episode-tasks → existing Director/L1. Real run (spend) needs: built Subjects for characters (subject_id_map) + generation infra (GPU/cloud video). Deferred per convention until soffy triggers.
  - ✅ **Step 4 — read-only Season Board frontend done** (committed `adaaa99`). `hevi-web/src/components/season/SeasonBoard.tsx` + route `/season-board` + TopNav entry (短剧) + `.hevi-sb*` styles. Read-only: 季(Series) list → 角色组/StylePack/进度 panels → 集卡片 (status badge, live SSE progress via `useSSEProgress`+`taskApi.progressUrl`, expand → cover-poster video). Pure reuse of `seriesApi`/`taskApi`.
  - ✅ **Step 4b — 幕/镜 drill-down (migration-free)**, PR #21 follow-up. 幕: dispatch stashes `EpisodePlan` into `task.config_json["episode_plan"]` via create_episode overrides (JSONB round-trip, no migration); board renders beat chips. 镜: new read-only `GET /api/tasks/{id}/shots` (owner-auth + existing `repo.get_shots`, projects shot_index/status/consistency/passed/diagnosis); board fetches on expand and renders per-shot cards. **Bug fixed in Step 4:** episodes endpoint returns raw `video_tasks` rows so task id = `ep.id` (not `ep.task_id`); board now uses `ep.task_id ?? ep.id` for video/cover/progress/shots. Backend `test_tasks.py` +2 (51 passed subset); tsc + lint clean. Committed `e5da3f4`, pushed to PR #21.
  - 🔄 **G1 acceptance — real run attempted 2026-07-11, partial evidence, not yet closed.** New one-off script `scripts/g1_shortdrama_run.py` (--dry-run/--real, mirrors `build_scene_zhibo_suodi.py`'s pattern) runs the full loop for real: 崂山道士 test manuscript (`output/shortdrama_g1/manuscript.txt`) → `storygraph.extract_story_graph` (qwen_cloud) → `season_planner.build_season_plan`/`gate_season_plan` (retries up to 5× — LLM split-quality has real variance, not a bug) → build 1 real Subject (qwen_image portrait) → `dispatch_season` → `task_service.run_task` real generation via `happyhorse_1_1_maas_lock` (阿里云百炼, the same key verified in tongjian).
    - **5 real pipeline gaps found + fixed while getting this far** (all in already-committed/adjacent core code, not spec-scoped — the shortdrama channel was the first caller to actually exercise create_episode→real-generation end-to-end):
      1. `video_tasks.topic` was `String(255)`; `episode_brief()`'s narrative brief routinely exceeds it → widened to `Text` (migration `a3c1d9e04f56`).
      2. `happyhorse_1_1_maas`/`wan_2_7_maas` were registered in `ProviderRegistry`/pricing/selector but missing from `hevi/video/provider_config.py`'s `VideoProvider` enum (config_builder rejected them) — and the main pipeline's `character_reference` convention (singular path) is incompatible with these providers' `reference_images` (list) contract. Added enum entries + a bridging adapter `happyhorse_1_1_maas_lock_generate` (`hevi/video/alibaba_maas_service.py`) registered as `"happyhorse_1_1_maas_lock"`.
      3. `longvideo_orchestrator.py`'s internal script-writer LLM was hardcoded to `ProviderRegistry.llm("default")`, which resolves to local ollama in this environment (unreliable for structured JSON, per `e2e-local-llm-json-blocker` memory) — the tongjian fix (explicit `qwen_cloud`) was never applied to this generic path. Now prefers `qwen_cloud`, falls back to `default`.
      4. `qwen_cloud`'s LLM registration was a plain `async def` — broke `oskill.shot_generator`'s sync `llm(...)` + `.get()` calling convention (only `await llm(...)` worked). Refactored `AsyncDashScopeAdapter` into a `_make_sync_llm_adapter(call_fn)` factory shared by both `"default"` and `"qwen_cloud"`; also extracted the JSON-shape coercion (`_coerce_llm_json_text`) so `qwen_cloud` gets the same numeric-ID/scenes-shape fixes `"default"` already had.
      5. The MAAS reference-to-video API needs an http(s) URL or `data:` URI for reference images, not a local filesystem path (real call failed: `Failed to download output/.../portrait_v0.png`) — `happyhorse_1_1_maas_lock_generate` now base64-encodes local paths into a data URI before calling through.
    - All 5 fixes covered by full existing test suite (994 passed) before/after each change — no regressions.
    - **Known gap, found + confirmed (not fixed):** picked `duration_archetype="short"` first to keep cost down, but that literally short-circuits scorecard/consistency scoring (`if not _is_short and character_reference:` at `longvideo_orchestrator.py:819`) — "short" is architecturally a no-reroll/no-consistency throwaway tier. Switched to `duration_archetype="1-5min"` + `LongVideoConfig.target_duration_s` override (B12, takes priority over the archetype's 180s default) to keep cost down while enabling scoring — but **`target_duration_s` does not cap shot count at all**: confirmed twice (once with a rich `episode_brief()` topic, once with `--lean` mode's deliberately one-sentence minimal topic) that the episode still converges to ~10 shots regardless. `oskill.script_writer`'s `_chapters_for_duration()` floors at 2 chapters for any `target_duration_s < 300`, and each chapter's own scene/shot count isn't governed by `target_duration_s` at all — shrinking the input topic text did not help. Real shot-count control needs a different lever (not yet found — likely inside `oskill.storyboard_planner`'s per-chapter scene count logic, not investigated).
    - **`--lean` mode added** (`scripts/g1_shortdrama_run.py --lean`): skips `season_planner`/`dispatch_season`, hand-picks N events spread across the StoryGraph, builds a one-sentence `"{name}:{event.summary}"` topic per segment, calls `create_series`+`create_episode` directly. Built to test whether smaller topic input → smaller shot count (see above: it didn't).
    - **Own-script bug found + fixed**: `_run_episodes_and_score()` was reading `s["consistency_score"]` on `shot_states` rows — that field is nested inside the `selection_json` JSONB column (`s["selection_json"]["consistency_score"]`), not a top-level column. Every prior run's G1 summary print would have silently printed "no consistency_score data" had it reached the summary section — an earlier "mean 0.669" note here was manually eyeballed from raw log lines, not the script's own output. Fixed; the script now correctly reads it.
    - **2026-07-11 final real result (`--lean --episodes 1 --real`, ~1h37m wall clock)**: one segment ("王生:王生慕道赴崂山，跪求道士收留，初遭拒绝后以死相誓终获准入观") generated 10 shots via `happyhorse_1_1_maas_lock`; the Editor's one auto-rework round (`auto_rework_max_rounds=1`) then flagged **all 10** as "参考图角色错配" and regenerated all of them — 20 real video-gen calls total for a single "small segment." Final (post-regenerate) scores: **mean identity 0.591, min 0.454, n=10, all `passed=True`** (scorecard.py `identity_floor=0.2`) → script's own G1 verdict prints "通过 ✅". Real Alibaba-side spend unknown precisely (task_service never populates `config_json.actual_usd`) — check 阿里云百炼 billing console directly; rough order of magnitude is single-digit-to-low-teens USD given 20 short clips at $0.14/s.
    - **100% of shots flagged "参考图角色错配" happened in both the full-episode run and the lean single-sentence run** — this looks like a systematic issue (likely the built Subject's single qwen_image portrait not being distinctive/matchable enough for the VLM mismatch judge), not something driven by topic content/length. Not investigated further — every real run with the current Subject will likely trigger a full regenerate round, roughly doubling real cost each time.
    - Soffy's call 2026-07-11: one real segment's worth of within-episode identity data (10 shots, mean 0.591, all passed) is enough — **decided not to run a second segment**, so there is no literal cross-episode (segment-vs-segment) comparison, only robust within-episode same-subject-across-10-shots evidence. **Soffy confirmed 2026-07-11: this within-episode evidence is accepted as satisfying G1** (same Subject holds identity across 10 distinct real shots, a valid proxy for the 2D CLIP lock the spec cares about) — **✅ G1 CLOSED, 阶段 2 unblocked.** Carry forward the two known pipeline quirks discovered above (shot-count not controllable via target_duration_s; near-certain one full regenerate round per real task, ~2x real cost) as context for any future real-spend work in this area.
  - ✅ **阶段 2 all 4 items done 2026-07-11** (1007 tests passed, tsc clean; not yet committed).
    - **B1 — storygraph relationships/evolution extraction.** `hevi/storygraph/extract.py`'s prompt now asks for a `relationships` array (from/to/relation_type/valence/evolution), parsed the same way as causes/effects (name→char_id, event_index→event_id). `arcs[]` still deliberately empty (not needed for the relationship guard). `tests/test_storygraph.py` +2 (fills relationships + drops unknown-character references).
    - **B2 — Tier0 cross-episode relationship consistency guard.** Turned out the plan's assumed hook point (`make_scorecard_consistency_fn`'s `consistency_fn`) only ever sees rendered video *frames*, never dialogue text — that hook is wrong for a text check. Real fix: `hevi/verdict/scorecard.py::check_relationship_consistency()` (deterministic — name/alias co-occurrence + a small positive/negative address-term keyword lexicon vs. the relationship's valence "as of this episode" from `evolution`) is fed dialogue text captured via a new side-channel in `longvideo_orchestrator.py`'s existing `shot_gen_fn` wrapper (`oskill.ShotPlan.tts_text`, the only place per-shot dialogue exists before rendering). Result AND-combines into the existing whole-episode `_quality["passed"]` (same coarse-proxy pattern quality_report already uses) — logged as `_quality["relationship_drifts"]`, doesn't trigger targeted shot regeneration (can't attribute a drift to one shot at this granularity). `dispatch_season` now stashes `story_relationships`/`story_characters` into each episode's `config_json` (same zero-migration JSONB pattern as `episode_plan`) since task_service has no other way to reach StoryGraph. `tests/test_shot_scorecard.py` +5, `tests/test_season_dispatch.py` +1.
    - **B3 — season-level budget circuit breaker.** `hevi/cost/circuit_breaker.py::check_series_budget()`/`get_series_spend_usd()` (same shape as the existing daily-budget pair, aggregates `video_tasks.config_json->>'actual_usd'` by `series_id` instead of by day). `Series.spec_json.budget_usd` (no migration) is checked in `series_service.create_episode()` — via `estimate_cost()` — before the task is created, so an over-budget episode never spends. `tests/test_cost.py` +4, `tests/test_series.py` +3.
    - **B4 — editable Season Board.** `SeasonBoard.tsx`'s shot cards (only when the episode is `completed`, matching the backend's 409 guard) get a checkbox each + a "↻ 重生成选中(N)" button, reusing the existing `POST /tasks/{id}/regenerate` endpoint (zero backend changes) and the same confirm→fire→poll pattern as `ScriptReviewPanel.tsx`'s "重新生成剧本" button (polls `GET /tasks/{id}/shots` until the selected shots' `retry_count` increments). Added `taskApi.regenerateShots()` to `api-client.ts`. `tsc --noEmit` clean; **live browser click-through done 2026-07-11** (soffy installed the missing Chromium system libs via `sudo npx playwright install-deps chromium` on this shared host) — real hevi-api + hevi-web dev servers, a real registered test user, one of the real completed G1-lean tasks re-owned to that user: Season Board correctly lists the season, expands to the real generated video + 10 real shot cards with scores, checkbox toggling correctly flips the regenerate button from disabled → enabled. One thing surfaced along the way, **unrelated to this diff**: hard-reloading straight to a deep link like `/season-board` can race `AuthProvider`'s token-restore effect against the page's own data-fetch effect and show a stray "请先登录" even though the user is logged in — doesn't happen via normal in-app navigation (client-side routing), not something this session touched or fixed.
  - ✅ **短剧创建入口 done 2026-07-11/12** (soffy: "立即处理，配置要顶级，功能要强大！" — Season Board had been read-only-only since Step 4, no way to actually start a new short drama from a manuscript). New router `hevi/api/routers/shortdrama.py` (prefix `/shortdrama`, registered in `main.py`), reusing the tongjian-style in-memory `_RUNS` + `BackgroundTasks` P0 pattern (no new table): `POST /runs` (manuscript → B0 extract + `build_season_plan` w/ 5x retry, → `AWAITING_CHARACTERS`), `POST /runs/{id}/replan` (discard + redo), `POST /runs/{id}/characters/{char_id}/upload` (photo → `create_subject`+`add_reference_upload`, pre-binds that character), `POST /runs/{id}/confirm` (per-character `auto`(qwen_image portrait + `create_subject`)/`existing`(reuse a subject_id) → `dispatch_season`, records `series_id`). Confirm rejects `duration_archetype="short"` (422, the known consistency-scoring-skip trap) and non-positive `series_budget_usd` (422) — `series_budget_usd` defaults to $20 and always threads into `dispatch_season`'s `spec.budget_usd`, so B3's season budget breaker is always live for anything created through this entry point. Frontend: `ShortdramaCreatePanel.tsx` (3-step wizard: manuscript+config → review characters/relationships/episodes+gate warnings+"重新规划" → per-character bind radio (auto/existing-dropdown/upload) + "⚠ 确认无误，开始真实生成($budget)" button), wired into `SeasonBoard.tsx` behind a "+ 新建短剧" toggle button that swaps out the season list; `shortdramaApi` in `api-client.ts`, lite types in `types/api.ts`. `tests/test_shortdrama_router.py` new, 10/10 green (direct-call style like `test_tasks.py`, manually drains `BackgroundTasks.tasks` to simulate the background pipeline running); full suite 1017 passed; `tsc --noEmit` clean. **Live end-to-end verified 2026-07-12**: real hevi-api(8123)+hevi-web(3123) dev servers, a fresh registered test user, real manuscript (崂山道士 vernacular retelling) submitted through the actual UI — real `qwen_cloud` extraction correctly found 3 characters + 2 relationships (师徒/夫妻) + split into 3 episodes with sensible titles/beats, gate warning correctly surfaced for a genuinely weak episode ("第1集全是铺垫/过场,无冲突或高潮"), character-binding UI rendered all 3 radio choices defaulting to auto, confirm button enabled showing the right budget ($20). **Stopped deliberately before clicking confirm** (that's real spend — dispatch → queue worker auto-generates for real) per the verification plan; dispatch/generation itself not exercised live this session. hevi-api(8123)/hevi-web(3123) dev servers left running for soffy's own continued testing.
- **HEVI-EXEC-01 M3 (场景生成闭环)** — code complete + mock full-chain verified 2026-07-09, zero real spend. New module `hevi/cinematic/` (scene_adapt/shot_planning/video_gen/platform_binding). Not yet: real `vidu_reference_to_video` call (never smoke-tested — costs money, awaits soffy `--real`), lip-sync (explicitly not implemented). Next per handoff: M4.

---

## ✅ Done

- **INC-003 P0 第二版:多角色镜头"静默退化成单人"根因定位 + 统一修复(2026-07-18)。**
  第一次整机产集(work_id=21a72719...、task_id=b3d18fff-38bb-4cdc-9923-77d7ca2f5229,真花钱约
  $25,一集2人对话戏、38镜)跑完后肉眼核验:**11 个双人镜头,`output/tasks/.../SH*_layout.png`
  一张没有**——包括真正的对白双人镜(SH002_05、SH007_06)。CLIP `character_consistency` 分数
  (mean 0.831,36/38 通过)对此**完全没有信号**(只测"画面里那个人像不像 canon",不知道该有
  第二个人),verdict/自动裁决全被这个假象骗过。
  - **排查方法(挂 debug log 本地免费复现,不臆测)**:把当时真实锁定的 concept/screenplay/
    design_list/scene_stage/shot_list 从抓拍的 JSON 快照重建,配真实 SubjectService(同一个
    dev postgres,Subject3D 视图/参考图路径都是那次真实建好的),六个会打外部付费 API 的函数
    (`qwen_image_edit`/`qwen_image_generate`/`alibaba_maas_keyframe_generate`/
    `happyhorse_animate`/`i2v_animate`/`sdxl_local_generate`)全部打桩,在 `build_frame_manifest_
    avatar → 判在场人数 → 选 compose 还是单锁 → _view_path_by_cid → 拼底图 → _edit_keyframe`
    这条链的每一步插日志,重放真实数据。**过程中真出过一次事故**:第一次挂 log 漏了
    `alibaba_maas_keyframe_generate`(kf2v 动作弧那条视频生成函数,以为只有 happyhorse/i2v 两个
    要打桩),真花了钱(约1-3刀,已停止)——教训是打桩前必须先系统 grep 一遍所有外部调用函数
    列成清单,不能凭记忆打桩,这次系统 grep 后重来零花钱复现成功。
  - **确认结果:present / `_view_path_by_cid` / 走位合成底图,全程正确**,跟真机production 里
    的实际数据一模一样,合成底图真的建出来了。**真根因在更后一步**:`_edit_keyframe` 第0级
    (img2img,吃合成底图)偶发失败(复现的正是本轮会话第一次真跑撞见过的
    "SDXL worker subprocess failed"),失败后代码退到第1级(IP-Adapter,结构上只锁 `canons[0]`
    一张脸)——**这一级"成功"了**,返回 `_KF_SDXL_IP_ADAPTER`(不是 `_KF_CANON_COPY`),完全
    绕开了此前(2026-07-18 更早)那版 P0 修复的 degraded 判据。这才是 11 个双人镜一个没同框的
    真实机制,不是路由/present 计算错了。
  - **img2img 为什么崩:倾向共享 GPU 主机瞬时资源争用,不是 compose 本身的稳定性问题。**
    用真实 `sdxl_local_generate`(非直调 worker 脚本,后者绕过了自动派生 seed 的逻辑,首次
    诊断因此误判)对同一份走位底图 + strength 0.55 连续跑 3 次,3/3 全部干净成功,没有一次
    复现崩溃。结合本机长期有据可查的"~90 个无关容器共享一块 RTX 3080"(STATUS 🔒Never 区)、
    以及本轮会话此前也在别的时间点撞见过同类瞬时崩溃——证据指向共享主机资源争用这类瞬时因素,
    不是 compose img2img 路径本身有确定性 bug。**没有做到 100% 排除**(没有在真实产集运行期间
    同步监控 GPU/主机负载),但"连续3次干净成功"至少说明这不是"只要传合成底图就必崩"级别的
    确定性问题。
  - **修复:不再按"崩在哪一级"分别打补丁,改成统一判据(见 🔒Never)。** `_edit_keyframe` 新参数
    `expected_character_count`(替换第一版的 `allow_canon_fallback: bool`)——每一级 fallback
    只有结构上真能覆盖这么多人才被采纳:IP-Adapter(单脸)对 `expected_character_count>=2`
    直接跳过、不尝试;云端 edit 要求参考图张数够;两条腿都覆盖不了 → 抛
    `MultiCharKeyframeFallbackExhausted`,整镜显式失败,不再有"某一级悄悄成功、其实少了人"
    这种情况。**顺带牵出并修了两个关联缺口**:①非对白分支的 `_view_path_by_cid` 构造此前那次
    "反转 front 判据"的 replace_all 因缩进不同没匹配到,静默漏了一处,这次一并修上;②kf2v
    峰值/尾帧(`_gen_action_keyframe`)结构上只锁 `action_ip` 一张脸,不接 compose——多角色
    动作镜头此前会让它跑、然后被新判据拦下(整镜连累失败),现在改成对多角色镜头(`len(present)
    >= 2`)干脆不尝试 kf2v 强化,退回用已经出好的(真·N 人同框)首帧 + 简单动效,不因为一个
    强化功能做不到就搭上整镜。
  - **诊断思路固化为可复用工具,没有删**:三次同类"多角色镜头静默退化成单人" bug 都是靠临时
    log 一步步跟出来的,这次固化成 `HEVI_DEBUG_MULTICHAR_CHAIN=1` 环境变量开关
    (`multichar_chain_log()`,定义在 `scene_render_avatar.py`,`director_pipeline.py`/
    `tongjian_render.py` 复用同一个),默认静音,开了就在 `build_frame_manifest_avatar` 的
    present/view_path_by_cid/kf_source 判定点 + `_run_director_via_tongjian`/
    `render_director_episode` 的 subject3d_views/scene_bg_paths/shot_view_by_id 解析点全部打印。
    下次同类问题不用重新现挂现删。
  - 回归测试 +3(img2img 崩溃退化不许被采纳为单人成功、多角色动作镜跳过 kf2v、非对白分支
    front 判据回归覆盖),全量 1344 passed,ruff 干净。**未做**:带着这次的修复重新真跑一次
    整机产集验证(这次排查全程零花钱,只在本地免费复现层面验证过修复生效;要不要再花一次
    happyhorse 钱做端到端确认,留给 soffy 决定)。scene_id 长句/短名不匹配那个(空景板传不进去)
    仍未修——soffy 明确定性"背景问题不是能力问题",记录不动。

- **INC-003 生产化收线,2026-07-18:导演流水线现在能出多人片** —— compose 底图(走位+空景板)+
  strength 0.55 + happyhorse 认说话人只动 TA 的脸,已在生产入口(`build_frame_manifest_avatar`,
  不是探路脚本)真机验证(2 次真实 happyhorse + 1 次免费本地复测,`scripts/inc003_prod_accept_e2e.py`)。
  四件生产化(工作区未提交):①`_compose_layout_base` 加 `background` 画布参数;②`init_strength`
  定档 0.55;③锁场景资产改用无人空景板口径(`_SCENE_PLATE_DIRECTION`,原口径带人,当底图会
  变三人);④对白分支补 compose 路由(此前只接了非对白分支,同框对白镜仍锁单 lead)+
  `_view_path_by_cid` 排除 front 视图的判据反转(探路证明正面才是验证过的安全档,原判据方向
  反了)。回归测试 +2,全量 1339 passed。验收:④口型落对说话人脸/⑤旁人不动嘴——买断,与 style
  无关不需重验;②落位——过;①③换回历史正剧 style(`render_director_episode` 真实装配点
  `DEFAULT_SHORTDRAMA_STYLE`,首轮测试脚本裸调用漏传落到了通鉴讲解专用的卡通兜底)后方向确认
  改善,strength 不再调。归档三条不在这条线修:①王生 CLIP 间距薄(+0.048)→③设计清单角色特征
  鲜明度 lint;③抠图白边→StylePack `img2img_strength` 字段(架构问题,§5.3 三张表待实现的槽位,
  不同 style 需要不同 strength,现在硬调会破坏已验证的 0.55);**P0 fallback 撒谎**→见
  🔒Never——两条 fallback 耗尽后静默降级成单人 canon_copy 冒充多人合成图交付,产物性质是
  "假",不是"差"。
- **INC-001 A–L 补齐(§E/§J 完整 + 逐镜头准备台 A/G/I/L + §K)— merged (PR #25) + deployed 2026-07-15,迁移已建表.** (a) §E `_director_command_summary`(约束按帧风险动态分必须/优先级)+ §J `_adjacent_context`(相邻镜收束/触发拍注入承接过渡)。(b) 交互式导演台加**逐镜头准备台**:迁移 `c7d8e9f0a1b2` 建 3 表(`shot_readiness`/`shot_extracted_candidates`/`shot_extracted_dialogue_candidates`,按 work_id+shot_id 定位),服务层 `hevi/director/shot_preparation.py`(§A.1 就绪五规则重算[纯函数]、§G 从已锁 ShotListItem 确定性物化候选[不调 LLM]、§I skip_extraction、§L 聚合;PgPool 裸 SQL 同 `_persist_verdicts`),router 5 端点(extract/confirm/preparation-state/readiness/overview,mutation 返 {action,state})+ §L.2 产集就绪门(只拦"提取后仍待确认"的镜,向后兼容旧"锁分镜直接产集"),前端 `ShotPreparationPanel.tsx` + 产集按钮 blockers 门禁。§K:ShotFrame 加 debug_context(动作弧三阶段 + 各帧消费哪阶段 + 视线/轴线)+ quality_checks;§K.1 shot_list 输出混"图1/图2/参考图"→ 修正重试一次。全量 1209 passed,tsc 干净,CI web(next build)过。**部署时序**:先合并→重建镜像,由容器启动 `alembic upgrade head` 建表(`alembic current`=c7d8e9f0a1b2 已验证),未手动碰库。
- **SPEC-003 导演流水线 + INC-001 电影级补强 — merged (PR #23) + deployed 2026-07-15.** 全自动导演管线(`hevi/director/`:concept/screenplay/design_list/shot_list/tongjian_render)+ 五档逐镜 verdict/返工 + ⑤生成接通鉴对白+口型(治音画不同步/看不到说话人)。INC-001:§B action_beats(`_infer_action_phases`,L6 首/关/尾帧分抓 trigger/peak/aftermath;`action_arc` 默认 2point)、§C 首帧未完成态、§F 编译规范、§H eyeline、§J 连续性。**顺带修复**:`scene_render_avatar.py` 自 fd01988 起漏 `import asyncio`→`_action_end_state` kf2v 尾帧 LLM 拆解一直静默退化,已补(见 memory scene-render-asyncio-latent-bug);`GateResult` import 提顶层消 ruff F821 误报。相关面 409 tests passed,无回归。
- **部署域名迁移 hevi.uex.hk → hevi.kanpan.co(2026-07-15,`b8d6ba1`)** — cloudflared/CORS/web 构建参数全切;Dockerfile.api CJK 字体拆独立层;compose 挂 HF 缓存 + `/data/models/huggingface`(CLIP 身份向量 + sdxl_local 关键帧权重)。`up -d --build` 重建 cftunnel 栈,公网 web/api 均 200。**不需要 ssh-agent**(Dockerfile.api 是 `COPY .venv/`);CI test job 因 ssh-private-key secret 为空在 Setup SSH 步就红,与代码无关。
- **Tongjian pipeline L0–L8** — full 9-layer 资治通鉴→video pipeline, each layer + gate, committed (`a0478a7`…`e97e374`). Self-media explainer channel + Tongjian console shipped (`5306070`). json2video cloud provider for character-free scene backgrounds (`da92410`).
- **短剧创建入口生产事故排查 + 修复 2026-07-12(commits 9e09486/832a327/0d16260)** —
  soffy 在 hevi.kanpan.co 上真实测试时连续撞见两个真实 bug(不是显示问题):(1) 容器
  没有到 huggingface.co 的公网出口,建角色 Subject 算 CLIP 身份向量时联网校验请求
  无限重试,把 `_confirm_pipeline` 挂死。第一版修复(20s `asyncio.wait_for`)不够——
  超时只让调用方不再等,杀不掉 `asyncio.to_thread` 的后台线程,"僵尸重试线程"占满
  默认线程池,连不碰 CLIP 的 `dispatch_season` 都被拖累卡住半小时。真正修复:彻底
  去掉"本地缓存未命中就联网下载"这条路径,只读本地缓存,未命中直接降级为 None,
  不再有任何网络请求。已知副作用:这个容器里的 `identity_embedding` 会一直是
  None(容器本来就连不上网),要恢复需要把 CLIP 权重打进镜像,未做。(2) 阿里云
  qwen-image 服务端偶发内部 bug(`'DashscopeLogger' object has
  no attribute 'warning'`)导致某个角色参考图生成失败,直接拖垮整条派发到 FAILED,而
  前端只在 `AWAITING_CHARACTERS` 显示角色绑定/确认 UI,FAILED 时只剩"重新规划"(会
  丢掉已经跑通的 StoryGraph/SeasonPlan,逼用户重新出更贵的 LLM 调用)——修:建角色
  参考图加 3 次重试;每个角色建号成功立刻落进 `rec["bindings"]`(重试不会重建已成功
  的角色);`confirm` 端点放开 status=="FAILED" 且 story/plan 仍在时可重新调用;前端
  在这种"派发阶段失败"场景下也展示角色绑定+确认 UI,不再只剩重新规划。同时按 soffy
  要求加了派发进度可见性:后端逐步写 `rec["progress"]`(如"建角色参考图 2/3: 道士"),
  前端显示这句话 + "已轮询 N 次"心跳,不再是半小时不动的裸图标。`tests/test_shortdrama_router.py`
  13/13 过,全量 1020 测试过,tsc 干净。hevi.kanpan.co 已用两版修复分别 rebuild+重启,
  **每次容器重启都会清空内存里未完结的 run,soffy 需要重新走一遍手稿提交流程**。
- **Tongjian L6 画面风格可切换(卡通/水墨)2026-07-12** — soffy: 水墨风格现代观众/小孩不喜欢。查出 `hevi/tongjian/scene_render_avatar.py`(cloud_avatar 渲染路径)里"国画水墨"文案写死在 7 处 prompt 拼接点(旁白像描述、canonical 肖像、对白/旁白/场景 prompt、i2v motion prompt),`params.style` 此前只在其中一处生效、其余全被写死文案盖过。改成统一从 `style`(默认 `_DEFAULT_STYLE`=水墨)取词,所有拼接点改用同一个变量;顺带把只适合水墨的装饰性词("写意笔触,宣纸质感"、canonical 像上的"竖排题字与朱红印章")从公共函数里去掉,不再对所有风格都强加。前端 `TongjianConsole.tsx` 加"画面风格"预设选择器(国画水墨默认 / 卡通动画),点选自动填风格词输入框,仍可手写覆盖。**范围限定**:只对 `cloud_avatar`(云数字人)渲染模式生效——`sdxl_local`(本地静帧)走固定 SDXL LoRA 融合,`params.style` 在那条路径完全不生效(硬件已弃用,不值得为它换 LoRA),UI 里该模式下风格选择器禁用并有提示。`tests/test_tongjian_scene_render_avatar.py` 6/6 仍过(无用例断言具体文案字符串,未受影响);`tsc --noEmit` 干净;真实浏览器验证预设按钮渲染 + 点击卡通预设正确填充风格词输入框。未做真实视频生成对比(不花钱验证到 UI 层为止)。
- **HEVI-EXEC-01 M1** (vault MinIO+pgvector asset store, `2aa0ec8`).
- **HEVI-EXEC-01 M2** (identity pack pipeline, `6ce6796`) — 智伯/韩康子/段规 all `lifecycle=validated`, `stability_check=3/3`, vault `identity/*@0.1.2`. Built on local CPU, $0.00 spend.
- **Audio real-path bugs fixed** — vibevoice export monkeypatch in worker subprocess (`cff2722`), `reference_audio`→`voice_samples` kwarg translation (`976c4f1`), CosyVoice2 provider (`7a75596`). Real synthesis verified (non-silent, non-clipped audio).
- **Vidu Reference-to-Video provider** (`04217ac`) — real REST client, registered `video/vidu`. Mock-tested only; real API never called.
- **Env fixed:** ffmpeg/ffprobe + CJK font (wqy-zenhei) installed to `~/.local/` (no root). Tests 702 pass / 0 skip. **Re-do if this environment is rebuilt** — user-level installs, not persisted.

---

## 🚨 Needs Human

**★ 渲染层两洞修复 + 真实链路复验(2026-07-18 第二轮):① present/side_convention 解耦——
到位;② scene_id 长句/短名匹配——到位;但发现了①解耦之后仍然存在、根因不同的新轴线
不一致,是数据层(④分镜 blocking 文本与③.5 side_convention 互相矛盾)问题,不是渲染层
接线问题,优先级判定留 soffy 定。**

- **① present 解耦(`compute_shot_sides` 读 `SceneStage.axis.side_convention`,
  `_layout_col` 按"显式 blocking 文本 > side_hint > present 顺序兜底"三级判优先):
  机制本身验证正确。** 独立单测(`_layout_col`/`compute_shot_sides` 直接调用,不经渲染管线)
  证实 `side_hint` 已与"谁是说话人/lead 排序"完全解耦——不再受对白分支 present 重排影响。
- **但真实链路复验发现:SH003_01 与 SH003_05(同场,scene_ref=3)左右仍然反了,根因换了
  一个,不是①要修的那个洞。** SH003_01 两角色 blocking 都没显式"左/右"(老道士退到
  side_hint=right,王生因 blocking 文本"石阶中央"里的"中"字被 `_layout_col` 第一优先级
  误命中→画中,视觉上仍偏左于老道士,方向对);但 **SH003_05 的 blocking 文本显式写了
  "老道士:画面左侧"/"王生:画面右侧"——④分镜层这句话本身就和③.5 SceneStage 锁定的
  `side_convention`("王生恒在画左,老道士恒在画右")互相矛盾**,而 `_layout_col` 的优先级
  设计是"显式 blocking 最具体、优先级最高",于是 SH003_05 忠实按矛盾的 blocking 文本渲染,
  产出老道士画左/王生画右——跟 SH003_01 反了。
  - **这不是①那次改动引入的新 bug**,显式 blocking 优先于 side_convention 的判优先顺序在
    ①之前就是这样;①解决的是"没有显式 blocking 时的兜底选谁"(present 顺序 vs
    side_convention),这个子问题①确实解决了。这次撞见的是另一个更上游的问题:**④分镜层
    生成的 blocking 文本本身可能和③.5 场级 side_convention 不一致,没有校验/纠偏机制**。
  - **待 soffy 定:是否要把优先级反过来**(side_convention 是"恒"字面意思上的场级不变量,
    专门为防跳轴设计;如果它的优先级低于逐镜 blocking 文本,一旦 blocking 文本措辞和它冲突,
    防跳轴的设计目的就被架空——这次 SH003_05 就是活生生的例子),**或者在④分镜生成/L1 lint
    阶段加一道"blocking 左右词 vs side_convention 一致性"校验**(把问题挡在渲染层之前,而不是
    渲染层各退一步)。两条路都没做,渲染层这次没有再往深猜测/擅自改优先级。
  - 证据:`output/tasks/ce9bdace-36cb-45ad-96b1-68c29c2b113a/SH003_01_layout.png`、
    `SH003_05_layout.png`(同场,肉眼可见左右互换)。
- **② scene_id 长句/短名匹配:✓ 到位,真实链路 28/28 镜全部命中。** 用真实产集最终锁定数据
  (`v3_produce.json`,非中途快照)逐镜核对,`build_tongjian_inputs` 新的子串匹配对这一集
  100% 命中,`scene_bg_by_id` 正确传入,`SH003_01/05`、`SH005_01/02` 等镜的 `_layout.png`
  背景确认是真实崂山道观空景板(山门+石阶+云雾),不是纯灰。**排查过程中我自己中途一度得出
  "只有 2/7 场景组命中"的错误结论——那是拿了同一份材料早一次锁定(38 镜、被后续重锁定覆盖)
  的过期快照在核对,不是这次真实产集实际用的最终数据(28 镜)。已用最终数据复核纠正,
  不构成这次修复的真实结论,记录在此避免以后又被同一份过期快照误导。**
- **多人同框(INC-003 P0 主线,expected_character_count 统一判据):✓ 真实基础设施故障下
  确认正确工作。** 这次复验里 SH004_04 等镜撞见真实 img2img 崩溃 + 真实 qwen-image-edit
  免费额度墙(双重真实故障,非模拟),系统正确抛 `MultiCharKeyframeFallbackExhausted`、
  镜头显式失败(空 clip + degraded),没有静默退化成单人——修复在真实故障下按设计工作。

**SPEC-001 freeze decisions — all 4 settled 2026-07-11** (see `docs/specs/SPEC-001-shortdrama-eval.md` §6). Nothing pending here; LLM prerequisite resolved via `qwen_cloud` (the prior `e2e-local-llm-json-blocker` memory is now stale — updated with resolution).

**SPEC-001 G1 real run 2026-07-11 — check 阿里云百炼 billing console.** `scripts/g1_shortdrama_run.py --real` made 11+ real `happyhorse_1_1_maas_lock` video-gen calls (episode 0, 10 shots + 1 regenerate) before being killed for cost-control reasons — hevi's own `config_json.actual_usd` tracking is unpopulated (stays `0.0`), so there's no in-repo record of real dollars spent. If precise spend matters, check the workspace billing directly.

**`output/` 目录 dev/prod 混用,靠手工 chown 续命(2026-07-18 撞见)。** `hevi-cftunnel` 生产容器
以 root 身份把 `output/` bind-mount 到这台宿主机,子目录(如 `output/director_pipeline/<work_id>`)
留下 root:root 属主;本地 `uv run uvicorn`(soffy 用户)要在同一路径树下建自己的 work 目录时因
父目录属主不对而 `PermissionError`,只能靠 `sudo chown soffy:soffy output/director_pipeline` 一次性
续命,下次容器再写一个新 work 目录、下次本地再起一个新 work,又会撞同一个坑。**治本方案(未做)**:
本地开发与生产容器分用不同输出根路径(如 `output/` 只给容器/生产用,本地开发走 `output-dev/`,
经 settings/env 可配,不写死),而不是共享同一棵树靠手工 chown 来回续命——这本就是 local-dev 与
cloud-prod 该分离的东西,只是目前没分。

**Standing infra blockers** (any one unblocks GPU/cloud re-runs):
- Local GPU needs host reboot to recover (shared host — can't reboot without soffy).
- fal.ai account balance exhausted (2026-07-08, 403 Exhausted balance) — needs top-up.
- CosyVoice "default seed voice" chicken-and-egg is worked around (identity_pack default tts_fn now uses edge_tts), but真实高质量 default voice still needs a human voice sample if desired.
- **关键帧两条腿现均断 → 兜底抄定妆照成常态(2026-07-17 整改后会被 verdict 抓,但不会自动变好)**:本地 sdxl `require_gpu=True`(GPU 现状见上)+ 云端 qwen-image-edit `AllocationQuota.FreeTierOnly` 额度墙。任一活一条,自造导演路才谈得上真实画质验证;两条都断时 `1799dd8` 的整改只保证"坏片被判 degraded+返工+如实报 failed_shots",不保证出好片。Gap 1/2/3 与 F-0 的**画质效果全部待此解锁**(接线正确性已单测+真实产物证明)。
