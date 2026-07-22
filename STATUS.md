# Hevi · STATUS

> Canonical project status. Read at the start of any non-trivial task.
> Last updated: 2026-07-20
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
- **字段落地三件套——任何进 WorldBible/SceneScript 这类 schema 的新字段,不满足下面三件
  不算 done(2026-07-20 教训)。** ①schema 定义 ②被某处消费(lint/校验/中间 LLM prompt)
  ③**真正花钱调用 provider 的那条生成路径读到它**——三件必须**全部**满足,少第③件尤其
  容易被忽略,因为①②凑齐了看起来就像"已经在用了"。**血的教训**:SPEC-007 §6 六条字段
  (`no_cut_to`/`camera_movement`/`offscreen_trigger`/`beat_description`)当天上午建、
  下午系统排查才发现只有 `no_cut_to` 真正需要接生成端,其余三个当初设计就是"校验用标签,
  不进最终 prompt"(`camera_movement` 等字段的 schema 注释里其实写清楚了,只是没人在
  "这个字段算不算做完"这个问题上去读那句注释);`style_manifesto`/
  `identity_lock_sentence`/`negative_list` 更早就存在,同样的模式——字段存在 + 被中间
  步骤读过,制造"已经用上了"的错觉,`compile_multirole_prompt`(真正调 provider 的函数)
  实际完全没读。**加字段时的验收动作**:自问"这个字段的内容最终要不要出现在传给
  provider 的 prompt/参数里?"——要 → 加一个测试断言字段内容出现在传给 `gen_fn`/
  `provider` 调用的实参里(不是断言字段本身被正确赋值,那只验证了①②);只是校验/lint
  用、设计上就不该到生成端 → 在 schema 字段注释里显式写清楚(像 `camera_movement` 那样
  "标签本身不进最终 prompt"),不要留成默认状态的模糊断链,让下一次排查还要重新猜一遍。

---

## 🔄 In Progress

- **V1→V2 director-pipeline 原地升级 · 批C 真机验收完成(实付 $15.711),抓出并修了一个真 bug,
  2026-07-21。** 批A(后端路由换 V2:WorldBible→SceneScript→`produce_v2.py::run_v2_produce`)+
  批B(前端 WorldBible/SceneScript 人审面板)此前已完成、全绿。批C 走**真实 HTTP 端点**(自写
  `batchc_run.py`,新起 8124 实例跑当前工作树代码;注册测试用户 + 内部充 3000 credits 过预留闸门)从建
  work 一路到 produce,《王六郎》素材:
  - **四断言全过**:①WorldBible 字段(style_manifesto/identity_lock_sentence/negative_list)用这次真实
    world_bible 喂生产用 `compile_multirole_prompt`,三类全出现在真实 prompt(+日志 18 条真实 happyhorse
    请求);②14 段(G-FINAL 15,同量级)、`verify_no_duplicate_dialogue_renders` 0 违规、L5 六项真实产出
    3 pass/3 advisory 质量 fail(运镜/身份CLIP/色彩,与 G-FINAL 同类天花板)、dialogue 决策 native7/none4/
    fallback3;③actual_usd=$15.711 真实累加(非 V1 "估价抄一份"坑);④progress/stage 实时(2%→逐段→92%终审)。
    成片 `output/tasks/cd20c66d-a3b6-4388-8e6e-effe00a8dd75/final.mp4`(63.9s,抽帧目检真水墨、两角色可分、
    服装对得上设计,非黑非降级)。
  - **★ 真 bug 已修**:`produce_v2.py:531` 收尾调 `create_shot_state` 用 kwargs,但真实签名是
    `create_shot_state(self, data: dict)`(史上首个调用方,未暴露)→ TypeError。**成片已装配完成、
    update_task 已写 completed,却在最后一步崩被路由覆盖成 status=failed**——前端会把成功的产集显示成
    失败。已按 `director_pipeline.py:1181` 正确 dict 写法修好;`test_produce_v2.py` fake repo 加固成强制单
    dict 签名(kwargs 误用现在测试即报错)。全量 1512 passed,ruff 干净。
  - 误导性视频/配音引擎下拉框按 soffy 定改**只读展示**(`DirectorPipelineConsole.tsx`+globals.css)。
  - **成本超口头硬顶**:我说 ~$14.3(按 prepped 11 段算),实际全新剧本生成成 14 段+重掷 → $15.711;非失控
    (2× 尝试硬顶仍在,基数变大)。**待 soffy 定**:①bug 修复只做单测验证、没再花 ~$15 真机复跑坐实(可搭下次
    真实产集顺带验);②批A/B+只读改动+bug 修复**尚未 commit**;③L5 身份/色彩 advisory fail 是既有天花板,是否
    进一步治留 soffy 定。计划/记忆文件(`silly-roaming-treasure.md` / v1-v2 memory)因**根分区 `/` 100% 满
    写不进**,待清空间后补。

- **G1a 三家分晋整集讲解段(确定性后端全链)· 停在闸⓪ 讲解稿定稿,待 Wiki 签字,2026-07-21。**
  按 spec §14 G1a。**做到闸⓪ 硬门停,不自签越过进 N1–N9。**
  - **契约 schema 建成**:`hevi/tongjian/explainer_contract.py`——EpisodePlan/NarrationBeat/VisualFact/
    DualAccountFact **逐字投影 §3**(`history-contract-v0.1` 契约),validator 强制"不自造字段"(visual_intent/
    evidence_tier 枚举、accounts 恰好 2)。7 新测试。**G1b 换 KU 拉取时逐字段对拍的前置纪律。**
  - **N0 讲解稿 v0**:`output/g1a_sanjia_fenjin/narration_script_v0.md`——11 拍(索地→围晋阳→引水灌城→
    韩魏倒戈→智氏灭三家分晋→册封诸侯→臣光曰),逐源引用(R4/R8)、evidence tier(R9,B06 惨状语标 E3)、
    **对勘标记 1 处**(灌城之水 晋水/汾水,本集角标并陈**不建 S12**,等 F2)。模板预算:S5/S6/S7/S10 首用(按 G0-D 质量杆),
    S1/S2/S3 已建。总时长估 ~110s。
  - **VO voice pack v0 样音两版**送审:`vo_v0_sample_yunjian_纪录片深沉.mp3`(27s)/`vo_v0_sample_yunyang_新闻权威.mp3`(25s),
    单声,`edge_tts` rate-8%/pitch-2Hz。闸⓪ 选一版。
  - **计量**:闸⓪ 工时 **315s(5.2min)**(含一次性契约 schema 首建,后续集次不再含),台账 `g1a_labor_ledger.md`。
    生成成本地图镜确定性后端=$0。
  - **待闸⓪ 签字**:讲解稿文本/对勘处理/VO 选版/R8·R9 处理。**签字后方进 N1–N9。**

- **G0 三家分晋核验(纸雕地图讲解线)· soffy 四裁决执行完,G0 判"不过——门抓出真缺陷",2026-07-21。**
  完整报告 `output/g0_sanjia_fenjin/g0_verify_report.md`(三轮)。
  - **B1=1.0000 是测量事故**:`video/S*_end.png` 与目标关键帧 `keyframes/S*_frame_b.png` **md5 字节相同**
    (存了关键帧拷贝当末帧,同帧自比)。抽 mp4 真实末帧重测 SSIM S1=0.798/S2=0.486/S3=0.796;末段相邻帧
    SSIM 无向下尖峰 → **硬拼假说否掉,是真插值平滑收敛**。
  - **★ 头号发现:i2v(dashscope wan keyframe_pair)不保小面积多色区。** B1 拆 B1a(坐标锚定结构判,主判)+
    B1b(全局 SSIM 护栏)。B1a 用矢量质心免费坐标采样真实末帧色相:**S2/S3(transform)中央韩赵魏三小块塌成
    单色红(赵蓝/魏绿丢失),三家分晋核心语义成片里不可辨;只 S1(near_static 单一晋红块)PASS**。B1b SSIM 0.796
    会放过 S3,B1a 抓住——坐实"守状态不守像素"。可靠区=大色块/单主体,不可靠区=细分多色。
  - **B2**:删 ±1 容差,S3 记 FAIL。"第4块"=自建地图画的整幅战国八国全图的周边国(楚/秦/燕/齐),韩赵魏是中央最小三块。
    根因=**断言实现偏离规格**(spec 是范围限定 VLM 问句,实现成无范围面积计数);"代理≠规格"立为独立技术债(B1/B2/A2/A3 四条)。
  - **A2**:装 easyocr(sudo 不可用→非 tesseract),9 帧零文字合法通过(渲染丢了 SVG 文字层)。
  - **建成**:`hevi/tongjian/force_colors.py`(勢力色注册表,唯一色源,§6.2;魏深绿→赭黄`#d8b020`修撞色)+
    `hevi/tongjian/map_state.py`(MapState schema + 确定性 svg/png 渲染 + `centroid_targets` 坐标锚定原语)。
    17 新测试绿,全量 1503 collect 无破坏。
  - **Q5 全环工时实测=382s(6.4min)**:资料查证87/坐标编制173/校对+R1+修正122;旧 `timing.json` 0.001s(=拼字符串
    墙钟)作废。产真实可复用资产 `output/mapstate_registry/cn_260bc_changping.*`(前260 长平前夕,与453边界实质不同)。
  - **spec 落仓**:`docs/specs/HEVI-EXPLAINER-PIPELINE-SPEC-001.md`(soffy 贴的源无关重构版全文)。
  - **G0 不判过**:B1(S2/S3)+B2(S3)门判据不满足——不是没做完,是门抓出 i2v 分治色塌的真缺陷。**待 soffy 裁方向**:
    ①图解分治脱离 i2v 走确定性分层揭示动画(render_map_state_png+装配,零 provider 零色塌,证据最硬)②或 i2v 加锁色层。
    **回填 §8/§10**:A2 可落 / A3 标注待换 CLIP 重标 / **B1b 阻塞**(无合格 transform 样本,遵"禁 n=3 拍")。三份重叠 spec 合并待定。

- **G0-D 确定性后端切片(soffy 裁 G0=FAIL 后接手,2026-07-21)。** G0 判 FAIL(失败分类=后端不适配),
  验收移交 G0-D:S1/S2/S3 全用 `render_map_state_png` 分层 + 装配层动画重制,后端二选一对照。
  已落:①spec §9 加 `render_backend∈{deterministic_layers,i2v_keyframe_pair}`(地图默认确定性,i2v 需逐模板证据授权);
  §10 B1 拆 B1a(主判,坐标锚定)/B1b(护栏,收窄为 i2v 专属,不阻塞确定性);§15 删内嵌 hex 改引用 force_colors。
  ②`docs/specs/provider-capability-matrix.md`(Wan-2.1 正式条目:真插值✓/尾部稳✓/near_static可用/小多色区transform不可用)。
  ③撞色"非相邻可接受"升为 checker 规则:`map_state.adjacency()` 邻接图 + `clashes()` 复判留痕 + `blocking_clashes()`。
  ④`hevi/tongjian/map_anim.py` 动画引擎(2.5D层深+接触阴影+回弹缓动+云漂,零provider零色塌)+ `sandbox/g0d_453_mapstates.py`。
  **材质关已突破 + S1/S3 出片**(`output/g0d_deterministic/`):
  - S1 `jin_453bc_unified_establish.mp4`(4s):势力纸片错峰滑入(晋压轴落)+ 回弹 + 接触阴影 + 云漂。
  - S3 `jin_453bc_split_tear.mp4`(5s):**三家分晋签名镜**——晋淡出,韩红/赵蓝/魏赭黄三块沿径向撕开抬起、
    三色清晰分离(正是 i2v 塌成一坨红做不到的,确定性 by construction 保色)。
  - 材质:**撕边(deckle 锯齿 + 撕纸白芯) + 有机纸纤维 fbm 纹理 + 桌面暗角 + 2.5D 接触阴影**——
    B5"纸质 vs 平矢量"现判纸质(v1 平矢量→v3 纸雕)。层按 (state_id,force_id,size) 缓存,确定性逐帧不抖。
  - **B1a/B2 构建期恒绿留证**:`tests/test_map_state.py::test_b1a_by_construction_deterministic_backend`
    (渲 split 图,质心采到就是注册色族 红/蓝/金)——永久回归,对照 i2v S2/S3 塌色。
  - S2 `jin_453bc_unified_fissure.mp4`(4s):**裂线隐现**——统一晋块上暗裂纹带微红预示沿未来韩赵魏边界蔓延(crack propagate)。
  - **并排对比条已出**(`output/g0d_deterministic/compare/`):S1(i2v vs 确定性,材质对照)+ **S3(i2v 塌单色红 vs 确定性三色分离)**——
    后者是"为什么确定性后端"的决定性证据(该 ffmpeg 无 drawtext,纯 hstack,左 i2v/右确定性)。
  - **G0-D 三镜 + 两对比条视觉交付齐**。
  - **★ G0-D 通过(Wiki 目检签字 2026-07-21)**:材质三问闭环(纸质感读作纸雕 / 与 i2v 并排无档次落差,S3 三色保真处更优 / Wiki 签字)。
    **`deterministic_layers` 就此成为地图/图解轨的验证后端**;能力矩阵已回填。G0 全弧闭合:G0(探针)FAIL→换后端→G0-D(确定性)PASS。
    **下一门 = G1a**(整集讲解段,手工装配同形 VisualFact,端到端跑通 + 人工分钟/成本首基线),按 spec §14,未启。
  - **残留撞色**:453 图 秦/楚(38.4,相邻,土色)+ 赵/燕(蓝,相邻)——非焦点(韩赵魏焦点色干净),待注册表决。
  **★ Q5 转正(Wiki 签字 2026-07-21)**:三张校对图目检通过,**382s = 地图轨单图全环工时基线**(回填 spec §16/§4.6);
  agent 自校可信度记首个数据点(agent R1 自校 vs Wiki 目检一致 1/1,台账 `output/mapstate_registry/agent_selfcheck_ledger.md`);
  纪律不变——通过率攒够前每张新图 Wiki 抽检、抽检工时进预算。

- **style-lock(SPEC-007 缺口④)第一步能力摸查,report 停,方案未定,2026-07-20。**
  只摸能力不写实现,零管线代码改动,真实调用 2 次($1.15)+ 本地 VLM 12 次(免费)。
  **① happyhorse-1.1-r2v 原生风格参考能力:不支持。** 官方文档(WebFetch 直查)确认
  `parameters` 只有 resolution/ratio/duration/watermark/seed,`media` 每项只有
  `type`/`url`,**没有 style_reference/style_strength/style_weight 这类字段**;多张
  参考图的角色区分完全靠 prompt 文本里的 `[Image N]` 标签,不是结构化字段——这点原文
  也确认了。hevi 自己 2026-07-13(SPEC-002 B2)已经加过 `style_reference_image` 参数,
  但只是把第二张图无差别塞进同一个 `reference_images` 数组,从没配文本标签说明"这张是
  风格用",而且从未真机验证过、也没往这次 G-FINAL 用的 `multirole_reference.py` 路径接。
  **实测(s7 骨架,固定 seed=424242,唯一变量=是否加风格锚)**:A(无锚)身份分
  {许渔夫0.727,妇人0.654};B(+s1 真实末帧当锚,prompt 里加 `[Image N]` 风格声明)身份分
  {许渔夫0.734,妇人0.702}——**身份没有被打架,B 反而略高(单样本,噪声量级)**。但风格
  这边是负结果:RGB 均值距锚点距离 A=18.2 vs B=30.1(B 反而更远),VLM 判定风格锚 vs A
  和风格锚 vs B 给出**完全相同**的"写实感/卡通感"结论——加了这张图,风格没有可观测的
  收敛。**结论:原生不支持,这次实测的"裸图+文本标签"路数没验证出效果,不是"身份风格
  打架"死的,是"根本没起作用"死的。**
  - **② 备选路 a(style token 显式化)排查结果比预期更严重:不是稀释,是压根没有。**
    `world_bible.json.visual.style_manifesto` 有一大段详细风格宣言(水墨渗染质感/留白
    构图/青灰暗部等),`hevi/director/generation_packet.py` 确实会把它拼进 prompt——
    但那个模块**从建成起就没接入真实渲染调用**(模块自己的 docstring 写着"供人工审阅,
    不接入渲染调用",批2 已记录过这个缺口)。G-FINAL 真正用来发起生成的
    `multirole_reference.py::compile_multirole_prompt` 完全不读 `style_manifesto`,
    s1/s7 的真实 `narrative_text` 也都零风格词——两段一个字没差,漂移不是"越往后风格词
    越少",是"从第一段起就没有风格词,靠的是参考图碰运气"。**这条路可行性判断:高**——
    加一句风格宣言进每段 prompt 是纯文本改动,零额外调用零额外成本,机制上没有不确定性
    (不像①要赌图像风格迁移能不能生效),是目前证据最硬的候选。
  - **② 备选路 b(VLM 风格抽查)不成立,复用 L5 那套二元判定拿不到可用信号。** 对 12
    个真实 clip 各自末帧(已有产物,零新增花费)跟 s1 两两比对,11 对**全部**判
    `same_style=True`——包括 3 对(s5/s9/s10)VLM 自己给出的文字描述明明写着"写实感"vs
    "卡通感"、自相矛盾。本地小模型(qwen2.5vl)的布尔判定字段不可靠,但**自由文本描述
    本身看起来有真实信号**(11 对里 3 对正确抓出卡通/写实差异)——如果以后想用这条路,
    要改成"比对自由文本描述"而不是直接信任布尔字段,现在测的这版(照抄 L5 判定方式)
    不能直接用。
  - **成本量级**:①(裸图风格锚)生产环境零额外调用(同一次生成塞多一张参考图,按秒计
    价不受图数影响)但没测出效果,继续迭代验证需要每版本 1-2 次真实调用($0.5-0.7/次)。
    ②a(style_manifesto 文本注入)零额外调用零额外成本,验证收敛效果仍需真机重跑抽查。
    ②b(VLM 抽查)本地免费但技术路线本身需要重新设计(布尔判定→文本比对)才可能可用。
  - 产物:`/tmp/.../scratchpad/style_probe/`(A/B 真实产物 + 帧 + `analysis.json` +
    `vlm_style_check.json`,scratchpad 临时目录,未落 `output/`)。
  - **红线遵守确认**:未改动任何 `hevi/` 现有文件,真实调用 2 次(预留 3 未用)。
    **停在这里,方案设计等 soffy 核完这份摸查结果再定。**
  - 验收基线预告(soffy 已定,设计阶段用):最终方案用同一 canon 重跑 G-FINAL 那 12
    段,s1→s7 风格漂移肉眼可见收敛,测量样本沿用现成的,不用新拍。

- **style-lock ②a 落地:`compile_multirole_prompt` 接入 `world_bible.visual.
  style_manifesto`,真机验证 + 系统性断链排查,2026-07-20。** soffy 拍板只做②a(零成本
  文本注入),不做①裸图锚(摸查阶段已测出无收敛)、不做②b VLM 抽查(布尔判定不可靠,
  要重新设计)。
  - **★ 根因结论(soffy 要求明确记录)**:画风漂移的根因是**风格词从未进入真实生成
    路径,不是 provider 能力问题**——`world_bible.visual.style_manifesto`(水墨渗染/
    留白构图/暗部色调的详细风格宣言)一直存在于数据里,也被 `generation_packet.py`
    读取过,但那个模块自己 docstring 就写明"不接入渲染调用"。真正发起真实付费生成的
    `multirole_reference.py::compile_multirole_prompt` 从建成起就没读过这个字段——
    不是"漂移因为风格词被后面场次稀释",是"从第一段起就没有风格词,靠参考图碰运气,
    运气从 s1 到 s7 一路变差"。
  - **实现**:`compile_multirole_prompt`/`generate_multirole_segment` 加
    `world_bible: WorldBible | None = None` 参数(镜像 `scene_script.py` 消费
    `world_bible.visual.camera_persona` 的既定写法,不是新发明一套接口),有
    `style_manifesto` 时在每段 `action_text` 前统一插一句风格宣言;`world_bible=None`
    或 `style_manifesto` 为空 → 原样不插,零行为变化。4 个新测试,`uv run pytest -q`
    全量 1482 passed,`ruff check` 干净。
  - **真机验证(soffy 定,~$1.2,实付 $1.15,2 次真实调用)**:复用已有真实产物做对照
    (零新增花费)——`s1_before`=G-FINAL 真实产物、`s7_before`=摸查阶段已付费的
    无风格锚版本;`s1_after`/`s7_after`=这次新生成,加了 `style_manifesto`,固定
    seed=424242。**人眼直接看关键帧才是这次最可信的信号**(RGB/VLM 指标在摸查阶段
    已经证明弱/不可靠,这次结果印证了这一点):`s7_after` 肉眼明显更朦胧氤氲、更接近
    水墨渲染质感,山影/柳枝的空气透视感、袍子的笔触感都比 `s7_before`(锐利高光的
    CG 质感)更贴近 `s1` 家族——**这是一次真实、肉眼可辨的收敛**,不是指标噪声。
    RGB 距离指标只从 16.9 降到 15.9(几乎不显著)、VLM 判定加词前后完全一样(已知
    该本地 VLM 布尔判定不可靠,这次又印证了一遍)——**两个自动化指标都没抓住这次人眼
    看得很清楚的真实变化,指标本身的局限比这次改动的效果更值得记一笔**。
  - **诚实记两个瑕疵,不是隐瞒**:①身份分 `s1_after` 相比 `s1_before` 明显下降(许渔夫
    0.811→0.535、王六郎 0.748→0.638,都跌破 0.65 阈值),但人眼复核两个角色的长相/
    服装设计看着还是同一个人,更像是 `s1_after` 里王六郎站得更靠后、脸更小,人脸裁剪
    启发式(`subject_embed` 的上半身/居中裁剪)在这种构图下失真,不是有把握断言"风格词
    真的干扰了身份"——单样本、构图有变量没控制住,不能下定论,只能如实记这个数字。
    ②`s7_before` 来自摸查阶段的 `style_lock_probe.py`,那个脚本没显式传 `ratio`,
    落到 `alibaba_maas_reference_generate` 的默认值 `16:9`(横版),而 `s1_before`/
    `s1_after`/`s7_after` 都是生产默认的 `9:16`(竖版)——**这次 s7 前后对照的画幅不
    一致**,是这次验证方法上的一个真实缺陷(不是新发现,是我自己上一轮摸查脚本漏传
    参数),RGB/构图类指标的绝对值因此不能太当真,人眼判断受画幅影响较小,权重更高。
  - **系统性断链排查(soffy 要求,"这和之前 compose 没接 visual_style 链是同一类洞,
    该系统排查还有多少这类断链")**:全量核对 WorldBible/SceneScript 每个字段,
    只有 `narrative_text`/`dialogue`/`blocking.initial_positions`/(现在加上)
    `style_manifesto` 四类信息真正到达 `compile_multirole_prompt`。**其余全部断链**,
    模式统一:要么止步于 `generation_packet.py`(已知不接渲染),要么只喂给上游另一个
    LLM 调用当"写作指导"、只有那个 LLM 的**转述/paraphrase**能存活到下一步,原文本身
    从不出现在真实 prompt 里。断链清单(按对当前质量问题的相关性排序,不是修复优先级,
    修复优先级留给 soffy 定):
    - **`visual.negative_list` / `world[].negative_list`**——V2 这条路径**从来没有
      发送过任何负向 prompt**,只在 `generation_packet.py` 出现过。
    - **`SceneScript.no_cut_to`(批1补齐刚建的禁切清单)/ `camera_movement` /
      `offscreen_trigger` / `beat_description`**——这批 2026-07-20 当天刚做的§6
      六条新字段,全部只喂给 lint 或喂给"下一场"的 LLM prompt 当上下文,**没有一个
      到达真实生成调用**;`cut_style.py::classify_seam_cut_style` 在 `hevi/` 生产
      代码里零调用方(只有这次 G-FINAL 装配阶段的 scratchpad 脚本手动调过)。
    - **`characters[].identity_lock_sentence`**——LLM 生成的"身份锁定句",目前只喂
      给 Scene Script 生成 LLM 当写作指导,从不出现在真实生成 prompt 里;形态上跟
      `style_manifesto` 是同一类"随手就能接"的候选。
    - **`characters[].source_design_ref` / `world[].source_design_ref`**——纯写入,
      从未被任何代码读取过。
    - **`sound.ambient_soundscape_text` / `sound.music_stance_text` /
      `sound.negative_list`**——V2 全声音卷零消费,不只是没到生成端,是哪都没到。
    - `visual.camera_persona.behavior_derivation_text` 只喂给 Scene Script LLM 当
      写作规则,真实 prompt 里只留得下 LLM 转述后的 `camera_movement` 文本本身——
      而 `camera_movement` 恰好也是上面那条"没到达真实调用"的断链,等于两层都断了。
    - `SceneScriptSegment.handoff_out/handoff_in` 只用于场间 LLM 续写上下文,真实
      生成的段间连续性完全靠 `continuity_reference_path` 这张图,不靠这两个文本字段。
    - **不是断链,是设计如此**:`assumed_details`(四类,人审用)、
      `source_design_ref`(纯 bookkeeping,虽未读但本来就没打算被生成端读)不算缺口。
  - 产物:`/tmp/.../scratchpad/style_probe/`(s1/s7 前后 4 版真实视频+帧+
    `validate_analysis.json`)。
  - **不做的事(soffy 明确划的边界,这次没碰)**:①裸图风格锚、②b VLM 抽查重新设计、
    上面断链清单里任何一条的修复——这次只做②a 这一条,连带做了 soffy 要求的系统排查。

- **系统性断链批3:①identity_lock_sentence ②negative_list+no_cut_to 接进真实生成路径,
  §6 四字段逐条判定,真机验证三者合力效果,2026-07-20。** soffy 按危害排序批准三批修复,
  前两批零/低成本:
  - **①身份锁定句**(零成本,跟 style_manifesto 同型):`world_bible.characters[].
    identity_lock_sentence` 按角色名匹配,拼进该角色自己的 `[Image N]` 声明行。
  - **②负面约束**:先查证 happyhorse-1.1-r2v 是否支持 `negative_prompt`——官方文档
    (WebFetch 直查)确认 **`input` 对象只有 `prompt`/`media` 两个字段,不支持**
    (跟 style_reference 一样,查证不是猜)。既然没有独立通道,负面约束只能塞进同一条
    prompt——但图像/视频生成模型对否定句遵从度弱于正面描述是已知问题,所以新增
    `positive_rephrase_negatives`(一次文本 LLM 调用,把"绝不出现X"这类改写成正面陈述)
    再拼进 prompt。真机验证顺带确认了调用链路(日志能看到先打一次 `chat/completions`
    改写、再打视频生成提交,两步都成功)。LLM 改写失败 → best-effort 退化成直接拼接
    原始负面短语(不阻断真实付费生成,不是硬门槛)。**范围披露**:这次只接了
    `visual.negative_list`(全局)+ 调用方传入的场级 `no_cut_to`,**没接
    `world[].negative_list`**(逐地点年代准确性负面清单)——`compile_multirole_prompt`
    目前没有"当前场景对应哪个地点"这个信号,留作已知缺口,不是漏掉不说。
  - **③ §6 四字段逐条判定(soffy 要求"别全接,先分清哪些该到生成哪些校验够了")**:回查
    这四个字段自己当天写的 schema 注释——`camera_movement`/`offscreen_trigger`/
    `beat_description` 三个的注释原文就写着"标签本身不进最终prompt"/"不是要拆出一个
    新的权威字段",**从设计之初就是供 lint 校验用的粗粒度标签,narrative_text 才是权威
    描述,不接是按设计如此,不是断链,这次不动**。只有 `no_cut_to` 的注释写"防模型
    自由发挥"——措辞本身就是冲着约束生成模型去的,不接才是真断链,这次接了(见②)。
  - **实现**:`compile_multirole_prompt` 新增 `negative_constraints_text: str = ""`
    参数(纯字符串拼接,函数本身保持同步纯函数,不做 LLM 调用);`generate_multirole_
    segment` 新增 `no_cut_to`/`rephrase_llm` 参数,组合 `world_bible.visual.
    negative_list` + `no_cut_to` 调 `positive_rephrase_negatives`,结果传给
    `compile_multirole_prompt`。12 个新测试,`uv run pytest -q` 全量 1493 passed
    (另 1 个 `test_queue.py` 并发测试单独重跑通过,确认是既有 flaky,与本次改动无关),
    `ruff check` 干净。
  - **真机验证(soffy 定,~$1.2,实付 $1.15,2 次真实调用,用真实生产函数
    `generate_multirole_segment` 不绕过)**:三个字段同时在场,同 seed=424242 复跑 s1/s7。
    **身份分全面回到阈值以上、甚至是三轮测试里最好的一批**:s1 许渔夫 0.780/王六郎
    0.712(此前只加 style_manifesto 那轮跌到 0.535/0.638,跌破阈值;这轮回升,推测
    identity_lock_sentence 把因为大段风格文本被稀释的身份注意力重新锚回去了,单样本,
    推测不是定论);s7 许渔夫 0.862/妇人 0.745(三轮里最高)。**人眼复核**:两帧的朦胧
    氤氲水墨质感、暮色蓝调、笔触感,跟只加 style_manifesto 那轮相比更进一步,s7 跟 s1
    的画风家族感明显更接近,人物身份清晰可辨。
  - 产物:`/tmp/.../scratchpad/style_probe/`(`s1_sg001_with_all_fixes.mp4`/
    `s7_sg001_with_all_fixes.mp4` + 对应帧)。

- **本地 GPU 采购决策清单(暂不采购),2026-07-20。**
  Wan2.2-TI2V-5B 阶段0 裸模型验证(ComfyUI 独立部署 + GGUF Q4_K_M,零花费,详见
  `output/wan22_phase0/`)跑通:5B 本身画质/身份保真过关(中文 prompt 尤佳),但共享
  3080 上单条 5s i2v 耗时 20.5-23.3min(显存打满触发 VAE 解码 OOM 退化成 tiled 模式,
  吃掉过半时间)。评估了 RTX 5060 Ti 16GB 独占的可行性(驱动/兼容性/耗时重估全部有
  依据,非拍脑袋),soffy 定了两条:
  - **本地卡定位 = 量产阶段的补充通道,不是当前迭代阶段的解**——当前瓶颈是方法未定
    (SPEC-007 批1-3 未建、G-FINAL 未跑),不是算力。迭代阶段继续用云端(happyhorse
    r2v 等付费 provider)秒级出片,不被本地卡的分钟级耗时拖慢判断节奏。
  - **暂不采购。触发条件 = G-FINAL 通过 + 定量产 + 常规段选定走本地。** 届时按"要不要
    LTX 完整能力"二选一:
    - 要 → 24G 3090
    - 不要 → 3080 20G 魔改(Ampere 同架构、零适配成本,能跑 14B 不 offload;但**必须
      认准 4090 散热模组 + 有质保的卖家**,魔改卡的散热/质保是主要风险,不是显存本身)
    - **5060 Ti 出局的理由**:Blackwell 架构适配坑还不少(server 驱动分支不支持消费级
      卡、部分社区反馈的 GGUF 显存回归问题等,详见评估记录),原始算力还比 3080 低
      ~26%——除非"全新卡+官方质保"是硬性需求,否则综合劣于 3080 20G 魔改。

- **SPEC-006 V2(文档优先架构)· 垂直切片 ①②③ 已实现并真机验证,2026-07-19。**
  病理来自 INC-004 终局验收(下条 L4 记录)的实锤:V1"结构化优先"抽取必然有损,免费本地路径
  即便 verdict 判定 `passed` 也可能跟剧本 blocking 完全脱节。用户带来 SPEC-006(文档见
  聊天记录,未落 `docs/specs/` md,以代码 docstring 为准):**创作文档优先,结构(现有
  SceneStageSet/ShotList)降级为文档的校验影子**,五级决策顺序/全部 lint/verdict/Subject
  资产工厂/L4 路由全部保留,只换③④两级信息载体。
  - 新增(全部新文件,未改动任何现有代码):`hevi/director/pipeline_schemas.py` 追加
    `WorldBible`/`SceneScript`/`GenerationPacket` 等 schema;`world_bible.py::
    generate_world_bible_draft`(①四卷,角色卷/世界卷回源 `material_text` 原始素材重新
    提炼,不从已压缩的 DesignList 字段反向膨胀);`scene_script.py::
    generate_scene_script_draft`(②逐段时间轴,动作+摄像机行为一体,摄像机人格从 World
    Bible 派生);`scene_stage_extract.py::extract_scene_stage_from_script`(时间轴→
    SceneStage 结构影子,确定性部分镜像 `scene_stage.py` 的 `_derive_beats` 等,推断部分
    用"抽取口吻"LLM prompt,产出可直接喂现有 `lint_scene_stage()`);
    `generation_packet.py`(③贪心分段+文档切片拼装 prompt,不接渲染管线)。
  - **真机验证(崂山道士 scene_no=3,复用 v3_produce.json 快照,~$0.005 纯文本 LLM 调用)**:
    World Bible 密度达标(服装逐件、场景细到"三片枯耐冬花瓣、七粒松子壳",Camera Persona
    选了 static_watch 并给出可执行的机位/焦距/景深规则);Scene Script 3 段真正做到"动作+
    摄像机行为一体",无拆分痕迹;**lint 探针决定性证据**——抽取出的 `side_convention`
    ("王生恒在画左，老道士恒在画右")与既有 6 条 lint 结合,抓出跟本 session 早前 side_
    convention 真机修复撞见的**同一类**矛盾(SH003_05 blocking 写反),证明"结构是文档的
    校验影子"路径可行,抽取产物能被未改动的 `lint_scene_stage()` 消费出有意义结果。
  - **★ 已发现问题①的真相更正(2026-07-19 复核)**:上一版记录误判声音卷"凭空引用不存在
    的台词'你可知……'是幻觉"——查证 `material_text` 全文后发现这句话(以及"须发无风自动")
    **真实存在于原始素材里**,只是分布在 screenplay scene 5/6(这次只取了 scene_no=3)。
    World Bible 是全局卷,回源全片素材,自然会引用其他场次的真实情节当例证——**不是幻觉,
    是我自己核对范围不完整导致的误判**,已更正。加了 `assumed_details: list[str]` 字段
    (`WorldBible` 四卷通用)后重新生成,LLM 能如实自报几十条真正的推测细节(道袍补丁位置、
    簪子材质这类),人审通过,没有发现需要删除的编造内容。
  - **仍存的真问题(留 backlog,不这次修)**:原始 `ScreenplayDialogueLine.text` 混杂
    "台词+舞台指示"(如"（语调平缓，目光未离王生眼睛）"),Scene Script 生成器把舞台指示
    转成 narrative_text 里的动作描写、`dialogue.text` 只留纯台词是合理行为,但跟原始台词
    不逐字相等——验证脚本的断言已改成"去舞台指示后包含匹配"绕过(2026-07-19 soffy 定),
    完整的逐字契约仍是已知风险点。
  - **★★ ④真跑 + ⑤人眼判,2026-07-19,soffy 批准 ~$5.26,实付 $5.24。** 排查发现"崂山
    跪求"整场戏横跨 screenplay scene_no 1-6(V1 对应 SH001~SH006 共 28 镜/约 150s),不是
    单场 scene_no=3——免费重新跑①②③覆盖完整 6 场(复用已人审的 World Bible,不重新生成),
    Scene Script 拼接后 23 段/57.6s,按 10-15s 分组出 5 个 Generation Packet,对应这场戏
    的 5 个戏剧节拍(求道→拒绝→明志→松口→点题)。lint 探针在完整范围下产出 23 条发现,
    跟单场验证的结论一致。选 3 个连续情绪转折包(拒绝/明志/松口,37.6s)真实路由
    `happyhorse_1_1_maas_reference_to_video`,3 段全部成功,实付 $5.24(与估算几乎一致)。
    **人眼判结论:V2 完胜**——环境空镜(太清宫匾额、九纵七横门钉、石狮、朱漆斑驳)与人物
    镜头交替剪辑,王生左颊旧疤这类身份细节清晰保持,运镜风格(匀速平移/推拉支点式构图)体现
    了 Camera Persona 设计;对比同一场戏 V1 纯字段拼装版本(`output/inc003_sh003_real_
    scene/SH003_02_clip.mp4`——老道士手持原文根本没提过的灯笼,人物虚化摄影棚背景,姿态
    与设定完全脱节),视觉语言统一性有本质差距,直接印证"文档优先"假设成立。
  - 产物:`output/inc005_v2_vertical_slice/`(单场验证)、`output/inc005_v2_full_span/`
    (完整 6 场,含 `l4_real_run/` 3 段真实生成视频 + 抽帧)。全量 1395 passed(零回归)。
  - **本轮 SPEC-006 V2 垂直切片(①②③④⑤全部完成)总花费:$5.24。** 下一步(未决定,需
    soffy 定):是否逐条产线迁移(通鉴/短剧),还是先补 backlog(逐字契约、Screenplay 生成
    阶段本身是否也丢信息——这次撞见"你可知"那两句台词分布在 scene 5/6 但 SH003 只覆盖到
    scene 3,说明 V1 的 shot_list 切分本身可能也不是完整对应"一场戏"的自然边界)。

- **INC-004 第4步 L4 质量关键镜路由 · 最小验证:两镜真跑,三条断言全部清楚过,
  2026-07-19,实付约 $1.44。** 结论:**L4 路由值得建**——本地 compose 路(第2、3步)到顶的
  问题,旗舰 provider 两次生成两次过,而且没有另建新链路,直接复用本轮会话已经真实付费
  验证过多次的 `happyhorse-1.1-r2v` 底层模型(`hevi.video.alibaba_maas_service.
  happyhorse_1_1_maas_reference_to_video`),只是把参考图从 1 张改成 2 张。
  - **① `quality_tier: standard|key` 字段 + 纯规则判定器**(`hevi.director.shot_list.
    classify_quality_tier`,不上 LLM):≥2 人同框且 blocking 出现"伏地/跪/俯视/搀扶"这类
    姿态落差词 → key;clean_single 且 visual_prompt(§F"⑤氛围情绪"那一项)带强情绪词 →
    key;其余 standard,判据说不准宁可漏标。13 个新测试,全量 1389 passed,ruff 干净。
  - **② provider 选型:原计划的可灵/Seedance 两条都走不通,改用 ALIBABA_MAAS 家族里一个
    之前没注意到的能力**——查代码发现 `alibaba_maas_reference_generate`(1-9 张参考图,
    `happyhorse-1.1-r2v` 模型)其实就是本轮会话一直在用的 `happyhorse_1_1_maas_lock` 的
    底层实现(`_lock` 只是把参考图数量锁定成 1 张的窄接口),同一条已反复验证过的代码路径,
    只需把参考图从 1 张扩到 2 张——不是新接入,是把已知能用的东西喂两张图。可灵
    (`oprim.kling_v2_generate`)查证是纯文生视频、没有参考图参数;Seedance 这个代码库压根
    没接过。定价同价:$0.14/s(与 `happyhorse_1_1_maas_lock` 一致,已用实付验证过)。
  - **③ 真跑两镜——三条断言全部清楚过:**
    - **SH003_01**(`output/inc004_l4_real_test/SH003_01_l4_happyhorse_r2v.mp4`,5.16s,
      约 $0.72)。**断言①(伏地是伏地,成年人不是小孩不是坐姿):清楚地过。** 前景人物
      双手撑地、额头俯低贴近石阶,标准叩拜/匍匐姿态,成年男性体态比例完全正常——跟
      第2、3步"本地 compose 路怎么调都只出'缩小站姿'或读成小孩"的天花板形成鲜明对比。
      **断言③(画风同调性):清楚地过,且观感明显超出预期**,写实质感、光影、环境融合
      (石阶/山门/松林雾气)完全在线,布料细节比本地单人 SDXL 镜更精细,直接能剪进同一
      场戏。**断言②(老道士身份):清楚地过**(白发髻+发簪、雪白长须、同色系素灰道袍,
      跟 canon 逐项对得上);**王生因这一镜"额头触地"的姿态本身看不见脸,当时没法判**。
    - **SH003_05 补测**(对白镜,王生仰面露脸,`output/inc004_l4_real_test/
      SH003_05_l4_happyhorse_r2v.mp4`,5.16s,约 $0.72)。**唯一考点——断言②王生身份:
      清楚地过。** 肉眼比对:发型/发带、**脸颊那道疤(canon 上最具辨识度的细节)**、
      脸型五官、破损磨边的灰褐色道袍,逐项跟 canon 对上,是同一个人。CLIP 身份间距
      (只看相对值)王生 0.71、老道士 0.77,两个都明显高于这同一镜在旧本地 compose 路
      测出的 0.60(即真机验收撞见"画风崩+身份掉线"那次的分数)——量化信号和肉眼判断
      方向一致。老道士这次不是考点,顺带也对得上。
  - **三条断言(伏地对/身份对/画风对)在这两镜上全部拿到清楚的"过",没有还悬着的分支。**
  - **下一步(未做,留 soffy 定)**:要不要正式建 L4 路由架构(能力矩阵加列、成本核算、
    批量接入)——soffy 已定这些等一镜验完再动,现在验完了,动不动、怎么动,留 soffy 定。

- **INC-004 第3步 ControlNet openpose 最小验证:干净复验完成,结论落在"还是崩"这一支——
  本地 SDXL compose 路对这种复杂多人姿态到顶了,该进 L4 质量关键镜路由,2026-07-19。**
  不建骨架库,手做两副骨架(伏地跪拜/站立俯视),接 `StableDiffusionXLControlNetImg2ImgPipeline`
  (`xinsir/controlnet-openpose-sdxl-1.0`),复用第2步已修好的 `_compose_layout_base` 几何
  (位置/高度层次保留)当 img2img `image=`,骨架当 `control_image=`,只测 SH003_01。
  - **VRAM:装得下,但真的"勉强"。** 三次真机结果横跨两个极端:GPU 基本空闲时峰值稳定
    **8.51 GB**(三次测得的峰值完全一致),10GB 卡内能成功出片;GPU 被同卡其它租户占用
    ~8-9GB 时直接 **CUDA OOM**。同一份代码,纯粹看"这一刻卡上还剩多少"。这正是
    `_sdxl_worker.py` 里那条尘封已久的可行性注释早就写明的结论("genuinely marginal, real
    OOM risk"),这次真机验证坐实,不是猜测。**顺手把这条教训落成了生产代码**:
    `sdxl_local_service.check_gpu_available()` 现在顺带查空闲显存,默认 <9GB 直接快速失败、
    不进模型加载(门槛按这次实测的 8.51GB 峰值 + 余量定),不用再跑到加载中途才 OOM。5 个
    新测试,全量 1382 passed,ruff 干净。真机验证过这条检查本身也生效:等 GPU 窗口期间
    脚本自己被这条检查挡过两次(空闲 7465MiB/1029MiB 时),直接快速失败,没有浪费一次模型
    加载时间去确认"卡不够用"。
  - **验证脚本自己的一个 bug 也修了**:手画骨架的落位公式误乘了一次 2(`half_w * 2`),把
    老道士(满高站姿)的骨架宽度画成预期的两倍,右半身超出画布边界——已修正。修完等到一个
    真正空闲的窗口(9.87GB 空闲、0% 占用),同一个 pipe/同一个 seed/同一份 prompt/同一张
    control image,只挪 `controlnet_conditioning_scale`(0.6→0.5)跑了干净的两组对照。
  - **信号①(骨架 bug 修好后,scale=0.6,姿态对不对):不对,还是没有变成"匍匐哀求的成年
    人"。** 王生依然是"缩小的坐/跪姿人物",没有清晰的前倾低头轮廓——骨架 bug 本身不是
    上次结果"姿态不像伏地"的主因,修完这条信号仍然是负的。
  - **信号②(scale 0.6→0.5,身份回没回来):没有——两张图里的王生几乎是同一张脸**(哈希
    确认是两次独立生成,不是缓存复用),仍然读成另一个人(五官/发型偏女性化特征),降
    conditioning_scale 这个杠杆没能把身份拉回来。
  - **两个信号都是负的,对照 soffy 定的三分支判据,这次落在"还是崩"那一支——是干净的结论,
    不是失败**:本地 SDXL 这条 compose 路(几何合成底图 + img2img + ControlNet 骨架条件)
    对"多人+复杂姿态差异(伏地 vs 居高)+ 身份保真"这三件事同时要求,已经到顶——单独两两
    组合能做(多人+身份、多人+姿态粗略层次),三个一起就顶不住。**没有继续调
    controlnet_conditioning_scale 以外的其它旋钮(如 img2img strength、多个随机种子/
    prompt 变体撞大运)**,那些大概率是同一个天花板下的边际调整,不是真正解法。
  - **下一步方向(未做,留 soffy 定)**:按 soffy 自己定的判据,这个结论指向"这镜该进 L4
    质量关键镜路由(买旗舰 provider)",而不是继续在本地 compose 路上加码。
  - 产物:`output/inc004_controlnet_probe/`(`layout_base.png`/`control_pose_v2.png`/
    `SH003_01_kf_controlnet_v2_scale0.6.png`/`SH003_01_kf_controlnet_v2_scale0.5.png` 是
    骨架 bug 修复后的干净复验产物;`control_pose.png`/`SH003_01_kf_controlnet.png` 是
    修 bug 前的产物,留作对照)。

- **INC-004 第2步(compose 画风+姿态)查完先修了①②,免费本地复验:①确认修好,②几何差有了
  但撞见新的具体问题——不是"够不够"的问题,是"用错了近似",2026-07-19。**
  - **查①(画风)结论:`style` 其实早接了**,compose 分支和单人 IP-Adapter 分支调用
    `_local_kf_prompt(style, ...)` 完全同源,doc 原来"大概率没接"的猜测读代码后不成立。
    真正的机制性原因是 compose 的 img2img `init_image`(`_compose_layout_base` 拼出来的
    贴纸式合成图)起点质感本身就"贴纸感",不是接线问题——strength 也不是主因(compose 现在
    的 0.55 比单人默认的 0.45 还高,起点图更花哨反而更难被文本"重皮")。
  - **查②(姿态)结论:两条分支不对称**——非对白分支早接了 `_blocking_hint`,对白分支
    (SH003_05 走的那条)漏了,已修对称。**但更根本的问题是 `_compose_layout_base` 的几何
    完全没有姿态层次**:每个角色用同一个 `fig_h`(画布 78%)+ 同一条脚底基线,不管 blocking
    写"伏地"还是"居高俯视"永远同高同线——SH003_01(非对白,文本早就进了)照样渲成额头相抵,
    证明"文本给了模型不听"是真实发生的,根子在起点图跟文本自相矛盾。
  - **两处都修了**:①对白分支补上 `_blocking_hint`(跟非对白分支对称);②`_compose_layout_
    base` 新增 `_posture_scale`(伏地/跪/趴/俯首/叩首→0.45,坐/蹲→0.7,其余 1.0,关键词
    取自实测 blocking 文本),配合脚底贴底逻辑,矮个体自然整体下沉。回归 4 个新测试(2 处
    geometry + 1 处 dialogue 分支文本接线 + 1 处 posture_scale 关键词档位),全量 1377
    passed,ruff 干净。
  - **免费本地复验**(SH003_01/05 两个已知失败样本,真实产集数据+真实 Subject3D 资产,
    只打桩三个视频函数):**几何差确实出来了**——`_layout.png` 里王生(伏地/跪)明显更矮更
    靠下、老道士(居高/站姿)维持满高,高度/位置层次肉眼可见,不再是同高同线。**但
    img2img 重绘出的 `_kf.png` 暴露了一个没预料到的新问题:王生被渲成了一个圆脸小身材的
    "小孩"，不是"匍匐哀求的成年人"**——纯比例缩放一个站立姿态的 Subject3D 裁切图,视觉上
    读出来的不是"身形放低",是"整个人变小=变成小孩"(人眼对"缩小的成年人轮廓"天然会读成
    儿童比例,这是人体比例感知的问题,不是这次改动特有的 bug)。这跟"伏地渲成蹲"是同一类
    问题——**几何层次的信号给对了,细节(到底是谁、什么年龄体态)还是崩的**,而且换了一种
    新的崩法(从"额头相抵的亲密感"变成"大人站在小孩面前"这种更违和的关系)。
  - **对照 soffy 定的判据("高度差有了但姿态细节仍崩→那才上骨架"):这次符合"细节仍崩"这一
    分支。** 且进一步看,根子可能比"ControlNet 能不能解决"更前置一层:四个 Subject3D 视图
    (front/back/left/right)全部是**站立姿态**,没有任何一个是躺卧/跪伏姿态的原始渲染——
    纯几何缩放不可能从"站立轮廓"凭空造出"卧姿轮廓",不管缩放公式怎么调都只是"更小的站立
    姿态",这才是读成"小孩"而不是"伏地"的根本原因。ControlNet openpose 骨架能不能绕开这个
    限制(给 img2img 一个真正的卧姿骨架条件,而不是缩放后的站立轮廓)是它区别于纯几何缩放
    的关键,值得作为下一步验证的具体问题,而不是泛泛"上 ControlNet 应该更好"。
  - 顺带看画风(不刻意修,只观察):背景融合观感和之前差不多,没有因为几何改动明显变好或
    变差——贴纸感主要还是 init_image 本身质感的问题,跟这次的姿态修复是两件事。
  - **strength A/B 调参明确不做**(soffy 定,机制 `_compose_strength_for_style` 留着,
    现有档位仍是占位值,没有真调过)。
  - **未做:ControlNet openpose 骨架**——按 soffy 定的判据,这次复验结果指向"该上了",但
    没有未经确认就动手(中等工作量,需要建姿态骨架库),留 soffy 定是否现在开始。

- **INC-004 多人电影观感 · 第1步(镜头类型约束)已实现+真机验收(免费),2026-07-19。**
  spec 见 soffy 提供的 INC-004 文档(未落 `docs/specs/`,对话记录里)。病理:$2.9 真机小场景
  验收(见上方 ✅ Done · INC-003 小场景真机验收)发现"单人像跳来跳去"是两层病叠加——病1
  (④分镜只切 clean_single 轮播,没有 master/OTS/two_shot 这些让观众感知"两人同处一室"的
  镜头类型,更根本)+ 病2(双人镜 compose 渲染画风/姿态跑偏,已记 backlog)。第1步先治病1,
  免费(纯文本层,不碰渲染):
  - `ShotListItem` 加 `shot_type`(master/two_shot/ots/clean_single/insert)+
    `ots_foreground`(仅 ots 填,前景/背对镜头那个角色名)——`hevi/director/pipeline_schemas.py`。
  - ④分镜 `_SHOT_LIST_PROMPT`(`hevi/director/shot_list.py`)加 coverage 硬性要求:对话戏
    (出场人物≥2 且含对白)开场必须 master/two_shot、对白主体用 ots 正反打而非 clean_single
    轮播、clean_single 只留给情绪峰值、每 4-5 镜回一次 two_shot/master。解析侧对未识别的
    shot_type/编造的 ots_foreground 人名做兜底丢弃(不硬塞、不发明角色)。
  - `scene_stage_lint.py` 新增 **L6 对话戏 coverage 配比**(六条 lint 里第六条,只对"出场
    人物≥2 且含对白"的场次生效):L6a 开场非 master/two_shot(error)、L6b clean_single
    占比>40%(warn)、L6c 相邻 clean_single 且说话人不同=单人轮播反打(warn,建议改 ots)、
    L6d 连续 5 镜无 two_shot/master(warn)。
  - **G-C1 真机验收(免费,文本 LLM 调用,复用真实锁定过的 screenplay/design_list——
    v3_produce.json,work_id=021401f3,只重新跑④分镜这一层):** 崂山戏(求收留+被拒两场,
    王生/老道士 2 人对话)连跑 3 次真实 qwen_cloud 采样,**3/3 干净**——L6 findings 全部
    0,shot_type 分布每次都健康(master 2-4/two_shot 2-4/ots 3-4/clean_single 恒为 1),
    关键对白(王生"求仙师收留"、老道士"尘心未净")3/3 都被正确保留在某个镜头里,没有因为
    新增 coverage 指令而丢词。跟真机验收撞见的原始 shot_list(SH003 组:master=0/two_shot=
    0/ots=0,5 镜清一色 clean_single/insert)形成鲜明对比,证明这条 prompt 改动确实在起
    作用,不是纸面指令。
  - 回归:2 处 schema 测试 + 4 处④分镜 shot_type 解析测试 + 10 处 L6 lint 测试,全量
    1370 passed,ruff 干净。
  - **未做(按 INC-004 doc 明确的"复跑决策点"停在这里,不擅自往下走):** 第2步(compose
    画风+姿态修复,backlog 已记两条)、第3步(OTS 过肩渲染能力)、第4步(L4 扩质量关键镜买
    旗舰)全部**未开始**——doc 要求做完 1+2 先花一次真钱重跑崂山戏、人眼判断,再决定 3/4
    投多深。这次只做了免费的第1步 + 免费验收,没有花钱重渲证明"分镜切对了+画风修好了"
    叠加起来是不是真的解决观感问题——那是下一步的事,需要先做第2步。

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

- **SPEC-007 批1:装配层四件套 + QC 收拢,从 scratchpad 迁回正式源码 + 测试,2026-07-20。**
  上一轮在 scratchpad(`inc006_v2_l3l5_system.py`)验证过的四件事(段级 QC / 跨段色彩匹配 /
  音频主导装配 / L5 终审)这次落成可复用代码,全程零花费(纯 ffmpeg + 已有 CLIP + 已有本地
  VLM,不碰视频生成 GPU),不重跑真机(那是已花掉的 $5.49 素材,结论已经成立不用再买一遍):
  - `hevi/director/segment_qc.py`(①CLIP 身份 + 真实 TTS 台词时长 → `retake_tier`,复用
    `verdict_checks.py::ShotVerdict` 的五档词汇但不在原地扩展——V1 绑定 `cloud_avatar`/
    `shot_id`,V2 走 `segment_id`)
  - `hevi/assembly/color_match.py`(②跨段 RGB 增益校色,独立于 `assembler.py` 已有的
    `color_normalize` 亮度专用校正,两者正交不叠加)
  - `hevi/assembly/dialogue_track.py`(③对白主轨 J/L-cut adelay+amix + 环境床 acrossfade,
    手法抄 `hevi/tongjian/assemble.py::mix_sfx_master`/`mix_bgm_master` 但脱离 `MusicPlan`
    绑定,产物喂给既有 `assemble_longvideo(narration_audio=..., bgm_path=...)`,不重新拼
    视频/duck/mux)
  - `hevi/director/final_review.py`(④接缝两两比对——本地小 VLM 处理 6 图网格实测退化成
    乱码的坑记在这里,改两两比对+重试,重试耗尽显式记 `unverified` 不默认判通过——+ 六项
    清单 code 合成)
  - 4 个新测试文件(`tests/test_segment_qc.py`/`test_color_match.py`/`test_dialogue_track.py`/
    `test_final_review.py`,19 个 case 全绿),`uv run pytest -q` 全量 1413 passed,`ruff
    check` 新文件干净,没有改动任何既有文件一行代码。
  - **范围边界**:多角色 `reference_role` 生成端接线(上一轮"多角色同框"验证过的能力)不在
    这批,留后续批次——装配/QC 层跟生成端两条线不混。

- **G-FINAL 前置修复:Screenplay 节拍边界 + 运镜 lint 重新定义,2026-07-20。** 用《王六郎》
  "投水相救"场免费跑 V2 文档管线选材验证时,连续两轮撞见真问题——①Screenplay 自审步骤
  (`hevi/director/screenplay.py::_REVIEW_PROMPT`)系统性过度拆分,收紧素材场次数反而
  15→17(证明不是素材篇幅问题);②`lint_camera_movement_variety` 相邻段"运镜标签不能雷同"
  这条规则在平静内省戏上 100% 假警报(16/16、14/14 两轮全撞车)。soffy 诊断根因 +定修法:
  - ①根因是 `_REVIEW_PROMPT` 只有"拆分"指令没有"合并"指令,是单向棘轮,而且没把"戏剧
    节拍"和"节拍内部的表演细节(喉结滚动/指节泛白这类)"分清楚。两个 prompt
    (`_SCREENPLAY_PROMPT`+`_REVIEW_PROMPT`)都加了同一份节拍边界定义,`_REVIEW_PROMPT`
    额外加明确的**合并授权**。**不是加数字上限**(治标会误伤真正多节拍的场景)。
  - ②真正该抓的不是"标签不能连续相同"而是"无意义的重复推拉"(第一轮链式生成真机撞见的
    真实病)。`lint_camera_movement_variety`(`scene_script.py:333`)重写:连续 push-in
    重复→`[警告]`;非 push-in 重复但有客观信号(说话人变化/`offscreen_trigger`非空)显示
    该有转折→`[提示]`软提醒;平静戏连续静态且无信号→不报。
  - `tests/test_scene_script.py` 追加 6 个新 case(这个 lint 之前零覆盖,重写了该补),
    `uv run pytest -q` 全量 1445 passed。
  - **免费复验(核心验收)**:同一段素材第三轮重跑——Screenplay 自审 14 场→14 场(前两轮
    15/17,不再膨胀);运镜 lint 从 16/16 全 `[警告]` 假警报降到 7 条 `[提示]`(全部对应
    真实的说话人切换信号,零假警报);顺带发现一个真实但不相关的问题——
    `lint_beat_and_dialogue_boundary` 报出 4 段语句边界装不下台词(生成前字数估算 lint
    在做它该做的事,留给后续批次处理,这轮不修)。最终报价:15 段(1 段因真实 SSL 网络
    瞬断触发确定性兜底拆成 2 段,基础设施抖动不是回归)、61s、基础 $8.54、+30% 重掷
    $11.10、+50% $12.81——落在 soffy 定的 ~$8-12 区间,范围也终于是"单场景为主"(14 场
    全在同一地点"青石渡口·河岸柳堤"的一夜到次日到又一夜,不再横跨全故事)。
  - G-FINAL 真机验证待 soffy 最终拍板后开跑。

- **SPEC-007 批2:多角色 reference_role 生成端迁回正式源码,2026-07-20。** 上一轮 scratchpad
  验证过($0.72 真钱,无融合脸)的标杆做法(happyhorse-1.1-r2v `[Image N]` 索引语法 + 空景板/
  canon/落位显式声明)这次落成 `hevi/director/multirole_reference.py`:`requires_multirole_
  reference`(§1 第8b 步路由判据本体,≥2 角色触发)、`compile_multirole_prompt`(泛化成吃真实
  `SceneStage.blocking.initial_positions`,不再是 scratchpad 那版硬编码 scene2)、
  `build_reference_images`、`generate_multirole_segment`(V2 层第一个真正发起生成请求的
  代码——`generation_packet.py` 明确"不接入渲染调用",这条线上原本空着这一环)。明确不碰
  V1 已有的多角色 L4 分支(`scene_render_avatar.py:1390-1439`,已生产验收,没有 `[Image N]`
  但不需要为了 V2 概念去动它)。9 个新测试(`tests/test_multirole_reference.py`,`gen_fn`
  显式参数注入 `AsyncMock`,不碰真实网络/GPU),`uv run pytest -q` 全量 1439 passed。**不
  重新花钱验证**——能力已经真机证明过,这轮纯代码迁移。至此 SPEC-007 批1-2 全部清零,
  G-FINAL 前只剩选材+报价(soffy 另行决定)。

- **SPEC-007 批1 补齐:句边界硬校验 + J/L-cut 算法化 + §6 六条 + 段边界双约束,2026-07-20。**
  soffy 纠正上一条记录里两处"半 done"不算完成(音频主导装配没有真实硬约束、J/L-cut 只有
  混音机制没有决策算法),这次补齐,批1 才真正闭环。全程零花费(prompt/schema/纯函数改动,
  不调用付费 API):
  - `hevi/assembly/dialogue_track.py` 追加 `find_cut_point_violations`/`resolve_cut_points`
    ——装配时校验真实剪辑点没落进真实 dialogue 音频窗口(含安全边距),找不到附近安全间隙
    (`max_search_ms` 范围内)就抛 `ValueError`,不静默放过。跟生成前的
    `lint_dialogue_segment_alignment`(字数估算)是两个阶段两回事,不合并。
  - `hevi/director/cut_style.py`(新文件):`classify_seam_cut_style` 废掉 scratchpad 那版
    场景专属硬编码常数,改按 `SceneScriptSegment` 的说话人延续/反应镜头标签自动判 J/L-cut,
    L 优先于 J。
  - `pipeline_schemas.py` 加三个字段:`SceneScriptSegment.offscreen_trigger`(§6.4 画外事件
    触发源)、`SceneScriptSegment.beat_description`(节拍边界的可查代理)、
    `SceneScript.no_cut_to`(§6.3 场级禁切清单)。
  - `scene_script.py::_SCENE_SCRIPT_PROMPT` 并入 §6 全部六条写作规则(首帧契约分时衰减/
    有掩护景别变化/禁切清单/画外事件/人类迟滞+Persona收尾/运动预算显式分配),
    `generate_scene_script_draft` 加 `prev_no_cut_to` 参数逐场传递禁切清单(镜像既有
    `prev_handoff_out`/`prev_camera_movement` 模式)。新增 `lint_beat_and_dialogue_
    boundary`(戏剧节拍∩语句边界双约束,分别报告缺哪一个条件)。
  - 3 个新/改测试文件(`tests/test_cut_style.py` 新建、`test_scene_script.py` 新建——这个
    模块此前零测试覆盖、`test_dialogue_track.py` 追加),17 个新 case 全绿,`uv run pytest -q`
    全量 1430 passed,`ruff check` 干净。
  - **不做真机验证**:这批全是 prompt 文本/schema/纯函数改动,prompt 措辞是否真的让 LLM
    写出更好的 handoff/禁切遵守情况,要等下次真跑场景时才能看到。
  - **明确不动**:批2(scratchpad→hevi 迁移 reference_role)、多版本策略,留到 G-FINAL 前。

- **G-FINAL:《王六郎》"投水相救"场全链真机终验,停在 10/15 段,阶段2-4(色彩匹配+装配+L5)
  跑通,产出阶段性成片,2026-07-20。** 阶段1(真花钱)15 段生成到第 11 段撞见 provider
  内容审核误判(`DataInspectionFailed`,台词"为何？那妇人……分明已溺！"被误杀,判断是
  false positive)且已接近 $12.81 硬顶(10/15 段实付 $12.08)。soffy 选 B:**停在 10/15,不
  补跑第11段和剩余5段**——核心信息(身份一致性/三人同框/链式末帧条件传递)已经买到真实验证,
  剩下的是重复验证不是新信息。但先处理两处真缺陷再装配:
  - **s3_sg002 拆段重生成($2.57)**:王六郎"我本是鬼"独白 TTS 实测 15.4s,超过
    happyhorse-1.1-r2v provider 15s 硬顶——结构性问题,重掷解决不了。回 Scene Script 层
    在原文已有的破折号停顿处机械拆成 sg002a/sg002b(不新编内容,两段合起来逐字等于原台词),
    免费重验 lint(干净),只对这两小段真实重新生成(sg001 不动,链式末帧接续在 sg001 真实
    末帧之后)。
  - **s2 超时判定为可接受**:重试后台词实际只差 0.28s(TTS 3.9s+0.5s 安全边距=4.4s 需要
    vs provider 实际返回 4.12s)——provider 不保证严格按 requested_duration 返回,这是已知
    quirk,不值再花钱重生成。
  - **阶段2-4(全免费)**:12 个真实最终片段(s3_sg002 替换为 sg002a+sg002b)→ ①以 s1_sg001
    为基准 `match_color_to_reference` 校正其余 11 段(增益均在 [0.87,1.34],未触
    clamp 边界)②`classify_seam_cut_style` 逐接缝判 J/L-cut → `build_dialogue_track`+
    `build_ambient_bed` → `find_cut_point_violations` 剪辑点硬校验(报出 6 处会切进对白
    窗口的剪辑点,已知晓未自动改点——`resolve_cut_points` 存在但这轮只报告不自动纠偏)→
    `assemble_longvideo` 出片 ③`review_seam` 11 个接缝两两比对(本地 VLM,首次跑漏了
    `register_all_providers()` 导致 11/11 `unverified`,补上后全部拿到有效判定,0
    unverified)+ `synthesize_final_checklist` 六项清单:5/6 项 `passed`,唯一未过是
    "运镜多样性"(4 处 `[提示]` 软提示级发现,非 `[警告]`,`synthesize_final_checklist`
    目前不区分提示/警告级别,一律计入 `passed=False`——这本身是清单粒度的已知简化,
    不是这次的新问题)。
  - 成片:`output/gfinal_wangliulang/final/laoshan_wangliulang_10seg_final.mp4`(65.25s)。
    关键帧抽查确认身份一致性保持、三人同框段落到位;肉眼也看到明显的**跨段画风漂移**
    (下面①),留给 soffy 最终"能看完不尴尬"判断,不自行宣布通过。
  - **三条新发现记为 SPEC-007 新缺口/新约束,G-FINAL 后优先修**(soffy 定,不是这次现修):
    1. **④跨段画风漂移**——色彩匹配(RGB 增益)之上还缺一层"跨段风格锁定"。真机可见
       s1 工笔写实风漂移到 s7 卡通渲染风(同一份角色 canon、同一份 prompt 骨架,风格仍然
       漂移),`match_color_to_reference` 只管色调不管画风本身,管不了这个。SPEC-007 §1
       第13步之外的新缺口。
    2. **②provider 时长上限感知**——Scene Script 分段生成时必须加 lint:台词 TTS 预估
       时长 > provider 硬顶(happyhorse-1.1-r2v 是 15s)→ 强制在 Scene Script 层拆段,
       不能指望生成后重掷解决(s3_sg002 就是重掷完全救不回来的结构性案例)。这是既有
       "段边界=语句边界"约束(`lint_beat_and_dialogue_boundary`)的**时长版**,现在只
       校验语句完整性没校验绝对时长上限。
    3. **③lint 前置阻断**——目前 lint 未过的段仍然会被送进付费生成(这次真机白烧
       $1.74:s1/s3_sg002/s5 三段在免费 `lint_dialogue_segment_alignment` 阶段已经标记
       过,但阶段1 执行脚本没有据此拦截,各自浪费一次注定失败的 try0)。要做成硬闸门——
       "契约未满足不交付"原则(`史实红线`那类)的又一应用场景:lint 未过 → 不许进入
       付费生成分支,不是生成完再靠 QC 重掷兜底。
  - 产物:`output/gfinal_wangliulang/`(`chain_run/` 12 段真实素材、`final/` 阶段2-4
    全部产物 + `seam_reviews.json` + `l5_checklist.json` + `color_report.json`)。

- **G-FINAL 后续:双轨回声真机诊断 + 装配层原声优先改造,2026-07-20。** soffy 听成片怀疑
  台词有回声/双人声,带着"1. 原声轨听有没有真人开口 2. script JSON 里同一句台词是否出现
  在两个都会进音频渲染的字段 3. TTS 铺轨时点 vs 人物实际开口时点量偏移"三个具体问题来查,
  ASR(faster-whisper)+ 数据走查全部实锤:
  - **H-A 确认**:`multirole_reference.py::_action_text` 把 `dialogue[].text` 逐字拼进
    生成 prompt(`台词:{character}对{target}说:'{text}'`),happyhorse-1.1-r2v 据此渲染出
    带口型的真人语音直接烧进原始 clip 音轨——provider 不是哑片。同一句台词又单独走
    edge-tts 合成一份独立 TTS,过去的装配脚本两条都留了:`build_ambient_bed` 直接拿带
    原声台词的整条 AAC 当"环境音"喂进去,加上独立 TTS 铺的 `dialogue_track`,成片里同一句
    台词被念了两遍。s1/s2 实测偏移约 0.9-1.0s(不是 soffy 感知的"2秒"那个量级,但方向一致,
    两个样本量太小不能断言恒定)。
  - **音色/发音质量验证(第2步,先做的小成本核查)**:装 `resemblyzer`(d-vector 音色代理,
    预训练权重打包在包里不用联网)+ `faster-whisper` ASR + `opencc`/`pypinyin` 做拼音级
    发音错误率(过滤 ASR 同音字混淆,只留真发音错误)。7 段有台词的原声实测:王六郎(5 段)
    内部音色相似度均值 0.868,紧密聚在一起无漂移;**许渔夫只有 2 段且相似度仅 0.593,
    低于跨角色基线 0.673**——警示信号,样本太薄不能单凭这个下结论。拼音级发音错误率 5/7
    段为 0,provider 发音基本准,字符级 CER 看着高(19-32%)几乎全是 ASR 同音字混淆(如
    "许兄"听成"徐兄"),不是真发音问题。
  - **装配层改造(soffy 拍板,原声为对白权威源,TTS 降级为逐段 fallback)**:新增
    `hevi/audio/voice_embed.py`(镜像 `subject_embed.py` 套路的 resemblyzer 封装)+
    `hevi/assembly/native_dialogue.py`(`probe_native_dialogue` ASR 测开口窗口、
    `decide_dialogue_source` 拼音错误率+音色相似度两道闸门决定 native/fallback、
    `extract_native_dialogue_audio`/`strip_dialogue_from_track` 从原声轨切对白/剥离
    人声出干净环境床、`CharacterVoiceRegistry` 每角色从已确认 native 段动态攒参考音色)。
    `build_ambient_bed` 的硬约束在文档里显式钉死:入参必须是已经不含台词的纯环境音,不能
    再直接喂 provider 原始整条 AAC。**QC 探测阶段的 `_qc_tts_*.mp3` 保留探测职能不动,
    装配脚本改成 fallback 时现场独立合成新文件**——探测件/成片件混用正是双轨并存的直接
    通道,这次职能拆开。24 个新测试(`tests/test_native_dialogue.py`/`test_voice_embed.py`),
    `uv run pytest -q` 全量 1468 passed,`ruff check` 干净。
  - **真机撞见一个数据卫生 bug(自己这次会话早前引入的)**:s3_sg002a 的 `dialogue[].text`
    还留着"（酒气混着水腥味，字字缓而沉）"这段舞台指示(手动机械拆句时没剥干净),
    `pinyin_error_rate` 一开始把这段没被念出来的指示文本也当"应该说的话"去比,把 PER
    算爆到 36.4%、误判成 fallback。ASR 实测 provider 根本没念这段指示(只念了纯台词),
    加 `_strip_stage_directions` 正则防御性剥离 + 补测试用例,顺手把 `scene_script_3.json`/
    `all_segments_flat.json` 里这条脏数据也清了(舞台指示已经在 `narrative_text` 里,
    `dialogue.text` 只留纯台词是既定约定)。
  - **`uv sync` 意外发现**:装新依赖跑 `uv sync` 时差点把 venv 里游离的 `peft==0.19.1`
    当无主包清掉——`_sdxl_worker.py`/`_sdxl_batch_worker.py::load_lora_weights`(国风水墨
    LoRA)需要它,但它从没被声明进 `pyproject.toml`,只是之前哪次会话 ad-hoc 装的。已补
    `peft>=0.19` 声明,不是这次改动引入的问题,是顺手补的既有缺口。
  - **v2 真机重跑结果**(12 段原始真实素材,零新增花费):对白来源统计 native=6,
    fallback=1(仅 s4_sg001,许渔夫音色相似度 0.606 低于阈值,自动判定不可信、独立现合成
    TTS 补上,不是静默用了可能不一致的原声)。剪辑点硬校验仍报出 6 处会切进对白窗口的点
    (跟 v1 数量一致,`resolve_cut_points` 这轮仍只报告未自动纠偏)。
  - 成片:`output/gfinal_wangliulang/final/laoshan_wangliulang_10seg_final_v2.mp4`
    (65.25s)。L5 视觉终审沿用 v1 产物(纯接缝比对,音频改动不影响关键帧,没有重新调 VLM)。
    `dialogue_source_decisions.json` 记录每段的 source/reason/per/voice_sim,供人审时对照。
  - **第3步(soffy 不等前两步验收、当场追加):出片后硬闸门,独立核验成片音轨里每句台词
    只被渲染一次。** `verify_no_duplicate_dialogue_renders`/`assert_no_duplicate_dialogue_
    renders`——ASR 转写成片最终混出来的那条音轨,`_find_line_occurrences` 逐句核对:
    每个 ASR cue **先各自单独**判是否已经是这句台词的完整渲染(不管离别的 cue 多近,两次
    挨得很近的独立渲染也要抓出来),只有单独不够格的碎片(同一次开口被停顿切碎)才允许
    先合并再判一次——这道顺序是踩过坑改出来的:第一版先全局按时间间隔合并再逐句比对,
    直接拿 v1 那次真实回声 bug(原声 + 独立 TTS 相差仅 0.9-1.0s)一测,由于间隔小于合并
    阈值被误并成一段,**完全测不出来**,倒逼改成"先看单独够不够格"的顺序。已接入 v2
    装配脚本,出片后立即跑,`assert` 版本干净通过(7 句台词各自唯一)。
  - **诚实记一条已知边界,不是隐瞒**:即使改完顺序,这道闸对 v1 那次真实 bug 依然**测不
    出来**——两条音轨挨得太近,单说话人 ASR 没能拆成两个干净 cue,而是转写成一整段内部的
    口吃式重复("……可明日就要别了，就要别了别……"),不落在任何单个 cue 边界上,现在的
    逐 cue 比对天然抓不住"融进同一段转写里的内部重复"。这道闸能可靠抓的是"两次界限分明
    的独立渲染"(装配逻辑 bug 把 native cue 和 fallback cue 都塞进了 dialogue_track这类),
    抓不住"两个音源真实叠在一起糊成一段"的声学层面重叠——那需要能量/指纹级检测(比如验证
    `strip_dialogue_from_track` 产出的环境床在已知对白窗口内是否真的接近静音),这次没做,
    是明确的已知缺口。v1 那个具体 bug 已经被②的原声优先架构从根上堵死(每段只选一个音源,
    不会真的两个同时播),这道闸是防"以后又出现新的重复渲染成因"的第二道防线,不是重新
    验证 v1 那个已经结构性修复的旧 bug——两件事分开记,免得以后有人以为这道闸能查出跟
    v1 同一种问题。
  - `hevi/assembly/native_dialogue.py` 追加 `_find_line_occurrences`/
    `verify_no_duplicate_dialogue_renders`/`assert_no_duplicate_dialogue_renders`/
    `DuplicateDialogueError`,7 个新测试(含专门验证"挨得近也要抓出来"的回归用例),
    `uv run pytest -q` 全量 1477 passed,`ruff check` 干净。
  - **SPEC-007 backlog(soffy 定,低成本、不阻塞,真出现新的声学混叠病因再启用)**:
    声学混叠这个盲区有两个候选的廉价补强,都还没做:①**n-gram 重复启发式**——这次真机
    转写本身就留了指纹,同一短语在小时间窗口内紧邻重复出现("……可明日就要别了，就要
    别了别……"),扫 ASR 全文找这种紧邻重复的 n-gram 可以当一个便宜的"疑似混叠"软提示
    (不硬判,不影响这道闸现有的硬拦截逻辑)。②**能量/频谱异常检测**——双声叠加段的能量
    特征跟单声不同,理论上可判,没验证过具体做法。两条都记 backlog,不现在做。
  - **v1 真实失败样本已经切片留档**:`tests/fixtures/audio/g_final_v1_acoustic_blend_
    sample.wav`(240KB,从 v1 真实成片切出的 7.6s 片段,含那句真实的口吃重复)+
    `tests/test_native_dialogue_regression.py`——不是普通单测,是把"这道闸抓不住这个
    真实样本"这个已知边界钉成可复测的回归资产,断言现在是 `violations == []`。以后谁
    想堵上①②这类盲区,改完代码先拿这个真实样本跑一遍:还是测不出来说明边界没漂移;
    测出来了说明检测能力真的提升了,那就更新这个测试的断言和 docstring,**不要删 fixture
    或删测试**——这是目前唯一一份"真实撞见、闸抓不住"的实物,删了以后就再造不出一模一样
    的真实样本了。`output/gfinal_wangliulang/final/laoshan_wangliulang_10seg_final.mp4`
    (完整版 v1 成片)也保留不删,fixture 只是从它身上切下来的关键片段。
  - **语音这条线全链闭环**:soffy 耳朵听出回声(发现)→ ASR+ 数据走查实锤双音源
    同时被渲染(定性,H-A)→ 装配层原声优先改造,只认一个权威音源(结构修复)→ 出片后
    独立 ASR 核验闸门(纵深防御)→ 声学混叠这类闸门测不到的失败形态如实建档 + 真实样本
    留作回归资产(边界老实交代,不是隐瞒)。1477 测试绿(+ 回归样本 1 个共 1478),
    v2 成片 7/7 台词各自唯一,零新增花费。下一轮主目标转 style-lock(见上面④跨段画风
    漂移那条新缺口)。

- **INC-003 真机小场景验收:一场戏(5 镜)真花钱跑通,①②③④单项全过,但叠加暴露出①②③④
  各自验证时看不到的新问题(2026-07-18,~$2.86)。** 之前①朝向②多人③场事实④对白都是分开
  验证过的能力,这次头一回让它们在同一场真实小戏里叠加:SH003 组(王生求收留被拒,2 人,
  1 场景,5 镜,含 1 句真实对白),真实 happyhorse/i2v/kf2v 全部不打桩,复用真实产集最终
  锁定数据(`v3_produce.json`)+ 真实 Subject3D/空景板资产,产物 `output/inc003_sh003_
  real_scene/`(`final.mp4` 28.2s,已用真实装配层 `assemble_longvideo` 拼接+转场)。
  **这本身证明了整机测试的价值**:单独验证四个能力时,没有一项会暴露下面这两个问题——
  它们只在"拼成一场戏"这一步才现形。
  - **①②③④ 逐项确认:结构层面全部成立。** 双人镜(SH003_01/05)两人都在,没退化成单人;
    王生(黑发)恒画左、老道士(白发)恒画右,背景五镜连续一致(真实空景板,不是灰);
    双人对视朝向相对;SH003_05 真实过 happyhorse,有声轨、时长跟台词匹配。
  - **⑤(这次真正要买的新信息)不是一场戏——原因不是技术断裂,是双人镜跟单人镜像两部
    不同调性的戏剪在一起。** 肉眼核对关键帧+实际视频帧:单人镜(02/03/04)干净写实历史
    正剧风格;双人镜(01/05)渲成软萌卡通娃娃风、两人额头相抵温柔亲昵——跟剧本"王生伏地
    哀求、老道士居高拒绝"的压迫感/权力不对等完全不符。CLIP 一致性分吻合这个观察
    (01/05 均 0.60,阈值 0.75,判定失败),**这次低分是真问题,不是"多人镜对单人 canon
    天然低分"那种此前撞见过的假警报**——肉眼和分数这次是同一件事的两个信号。
  - 详细拆解、优先级、下一步方向记在下方 Needs Human(soffy 明确要求先记 backlog,不现在修)。

- **INC-003 渲染层第三轮:side_convention 优先级 + L5 落位契约 lint(2026-07-18,soffy 决策
  已实现并真机复验)。** 上一轮发现 SH003_01/SH003_05 左右反了,根因是④分镜 blocking 文本
  ("老道士:画面左侧")跟③.5 SceneStage.side_convention("王生恒在画左")互相矛盾,而
  `_layout_col` 当时判"显式 blocking 最具体、优先级最高"——矛盾发生时忠实渲染出矛盾画面,
  side_convention 形同虚设。soffy 决策:①优先级反过来(side_convention > blocking 文字,
  SPEC-004 上游③.5 约束下游④、"恒"是承诺不能被 LLM 措辞毁约)②同时加一条上游 lint(不是
  只压不曝光)。两条都做了:
  - `hevi/tongjian/scene_render_avatar._layout_col`:优先级改成 `side_hint`(来自
    `SceneStage.axis.side_convention`)> 显式 blocking 文本 > present 顺序兜底。
  - `hevi/director/scene_stage_lint.py` 新增 **L5 落位契约**:`_lint_side_convention_conflicts`
    ——④分镜锁定时若某角色 blocking 写的左右跟同场 side_convention 矛盾,报 finding(带
    shot_id/角色名/矛盾双方)。这是"查产出对不对"而非"查计划齐不齐"的第一条 lint(L1-L4 都是
    后者)。复用 `scene_stage._parse_side_convention` 同一份解析逻辑,跟渲染层判据不会各说各话。
  - **真机复验**(重放 v3_produce.json 的真实最终锁定数据,零花费):优先级反转后
    SH003_01/SH003_05 王生恒画左、老道士恒画右,不再跳轴(`output/inc003_v3_scene_check2/
    SH003_0{1,5}_layout.png`,已核对肉眼一致,产物用完即删)。L5 lint 跑同一份真实数据,
    精确报出 `SH003_05`(soffy 点名的那对)+ 额外发现 `SH005_05` 也是同一种矛盾(此前不知道)——
    证明 lint 在真实数据上确实能揪出"LLM 写反了"而不是漏报。
  - 副作用(顺带修好,非目标):SH003_01 里王生的 blocking 文本"石阶中央"曾被 `_layout_col`
    的"中"关键词误命中(描述"哪级台阶"被误读成"画面居中"指令),新优先级下 side_hint 直接
    生效、不再被这个假阳性带偏。
  - 回归:6 个新测试(`_layout_col`/`_compose_layout_base` 侧 2 个 + L5 lint 侧 4 个),全量
    1355 passed。
  - **导演流水线四个核心能力(对白/朝向/多人/场事实)在真实链路的复验状态:全部到位**——
    这是这一轮(INC-003 P0 + 两洞 + 优先级反转)以来第一次可以这么说,前提是"场事实"里
    "背景真实"(② scene_id 匹配)和"左右不跳轴"(① + 优先级反转 + L5)都已用真实产集最终
    数据核对过,不是中途快照或手工单点验证。

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

**★ INC-003 小场景真机验收(2026-07-18)暴露的两个多人 compose 质量问题 + 一个 verdict 归因
问题——只记 backlog,不现在修(soffy 明确要求)。** 三条按主次排序:

1. **画风不一致(可修)。** compose 路径(几何拼底图 → img2img/qwen-image-edit 重绘)风格
   保真度不够——单人 IP-Adapter 锁脸路稳定输出写实历史正剧风格,双人 compose 重绘路跑偏成
   软萌卡通风,跟同一集里单人镜完全不是一个调性。
   - 近期方向:查 compose 分支的 prompt 拼接有没有接上 `visual_style`(INC-001 §F.4 那条
     风格继承链路)——先确认是不是"压根没传风格约束词进 compose 这条路",不是先猜measures。
   - 根治方向:阶段2 ControlNet+IP-Adapter 共存(compose→img2img 本来就是它的"次优近似",
     代码注释早就写过,这次真机撞见的正是这个近似的代价)。
2. **★ 情绪/权力关系丢失(可能比①更难,优先级更高,因为是"演错了戏"不是"画丑了")。**
   双人镜把"王生伏地哀求、老道士居高俯视拒绝"这组权力不对等的构图,渲成了"两人额头相抵、
   温柔亲昵"——不只是画风问题,是 blocking 里的姿态/权力信息(伏地 vs 居高)在 compose
   重绘这一步丢了,重绘只保住了"两人在场"这个最粗粒度的事实。
   - **先确认,不要先猜**:`_compose_layout_base`/`_edit_keyframe` 传给 img2img/qwen-edit
     的 instruction 里,到底有没有把 `shot.blocking` 的姿态描述("伏地""居高俯视"这类)
     编进 prompt?还是这条路径实际只喂了 Subject3D 视图 + 走位左右位置,姿态信息在从
     blocking 文本到 compose prompt 的路上就被丢了?查清楚是"没编进去"还是"编进去了但
     img2img/qwen-edit 没听懂",这两种情况后续修法不一样。
   - 风格约束词(①的修法)解决不了这条——姿态/权力关系是内容层问题,不是风格层问题,
     不要指望①顺带修好②。
3. **verdict 的 `coarse_diagnosis`("参考图角色错配")是占位符,不是真实归因。**
   `hevi/verdict/scorecard.py::coarse_diagnosis` 目前只有一个信号(身份匹配分),任何
   failed 都固定贴"参考图角色错配"这个标签(见函数注释"目前 Scorecard 只有身份匹配这一个
   信号...其余分类需要 VLM/风格向量等尚未接入的信号")。这次巧合是低分和肉眼看到的真问题
   对上了(①②),但标签本身("参考图角色错配"，字面意思是"用错了参考图")跟真根因(风格
   跑偏+姿态丢失)完全不是一回事——**如果以后真出现参考图张冠李戴的 bug,这条 verdict 会
   打出一模一样的标签,没法靠标签区分**。记一条:verdict 需要真实归因(#29 提过的完整
   taxonomy),不是靠现在这种"failed 就固定贴一个标签"的占位符。

产物:`output/inc003_sh003_real_scene/`(`final.mp4` + 5 镜 `_kf.png`/`_clip.mp4`),
真实花费 ~$2.86(happyhorse 1 次精确计价 $0.14/s,其余 4 个 wan i2v/kf2v 镜无 pricing_table
专门条目,按同网关 wan_2_7_maas $0.10/s 类比估算,非核实账单价)。

**★ 2026-07-19 INC-004 终局验收(L4 路由后 SH003 全场重跑)给①②③补了一组新实锤证据。**
L4 路(SH003_01/05,quality_tier=key)本身效果好:同一石阶山门场景,写实全景,姿态构图
(伏地/居高俯视、跪坐仰面)跟剧本 blocking 对得上,两镜之间光线/风格高度一致,像同一场戏,
真实花费 $2.98(与估算一致)。**但整场戏拼起来仍不连贯**——问题不在 L4,在中间三镜
(SH003_02/03/04,standard 档,走本地免费 sdxl):这次显存/额度都够用、sdxl 真的生成了新图、
verdict 判定 `passed=True`/`degraded=False`、consistency 分数不低,**但抽帧肉眼检查发现
生成内容是摄影棚纯色背景人像特写,跟 01/05 的电影感全景实拍完全是两种视觉语境**,且构图
跟剧本 blocking 完全脱节的例子:SH003_03 剧本"双膝跪撑、上身前倾"哀求姿态,生成的是笔直
站立正脸像;SH003_04 剧本"仅手部入镜",生成的是标准正脸特写,压根没听懂景别要求。
这是"免费本地路径独立生成"(不是 compose 那条路)撞见同一类①②问题的实锤,并且直接印证
③——consistency_score 只测身份匹配,不测构图/景别/姿态,所以"verdict passed"完全不等于
"这镜是对的"。**仍是记 backlog,不在这次 L4 任务范围内顺手修**(①②③本身已经排了优先级)。
产物:`output/inc004_sh003_l4_final/`(`final.mp4` 5 镜共 35s + `_coherence_check/` 抽帧)。

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
  - **2026-07-19 再次撞见,直接挡了 INC-004 终局验收**:SH003 全场重跑(L4 路由架构落地后)两腿同时断——本地空闲显存 7465MiB < 9000MiB 阈值(共享卡被其它租户占,VRAM 前置检查正确快速失败,非 bug)+ qwen-image-edit 仍是同一个 `FreeTierOnly` 额度墙,3/5 镜(SH003_02/03/04,standard 档,跟 L4 无关)全部退化成定妆照静帧,拼不出"整场戏连不连贯"的真实答案。L4 本身(SH003_01/SH003_05 走旗舰路)验证通过——成本 $2.98 对得上估算,SH003_05 身份分 0.60→0.75。**soffy 选择先解这个额度墙**:需要人去阿里云百炼控制台把 qwen-image-edit 从"仅使用免费额度"模式关掉,或补上付费信息(见下方错误原文)——这是账户设置/付费操作,不是能从 CLI 侧修的代码问题。解除后重跑 SH003_02/03/04(~$1.5,已有 5 镜数据不用重建)才能拿到 INC-004 终局问题的真实答案。
    - 原始错误:`{"code":"AllocationQuota.FreeTierOnly","message":"The free quota has been exhausted. To continue accessing the model on a paid basis, please complete your payment information (or disable the \"use free quota only\" mode)."}`
