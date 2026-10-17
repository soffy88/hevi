# 任务：hevi 视频提示词「连续性 + 导演词表」升级（CONT-1017）

## 目标
hevi 现有 H3 提示词编译器（hevi/prompt/h3_compiler.py）只有【场景】【人物】【动作】【对白】+环境声+配乐。实际生成婚宴短片时出现：中途冒日语、各段人声音色不同、新郎推轮椅时手提包掉了、风格/光线跳变。要把“导演一部片前后不穿帮”所需的信息结构化进 hevi，并让编译器按平台输出。

## 先读
- hevi/prompt/h3_compiler.py、hevi/prompt/negative_clause.py、hevi/prompt/style_presets.py、hevi/director/pipeline_schemas.py（ShotListItem）
- tests/test_h3_compiler.py、tests/test_h3_shot_discipline.py
- 本目录 research.md（连续性实证研究，含来源）和下方需求

## 要做（新代码放 hevi/prompt/continuity/ 子包，尽量不破坏现有接口；现有函数保持向后兼容）
1. **数据结构（pydantic 或 dataclass）**
   - FilmBible：片名、画幅、风格定性（is / is_not 列表，输出成“不是X，而是Y”）、对白语言 language（默认 zh-普通话）、language_lock 文案、画内文字白名单、genre_preset、调色基准、故事日/时间线表、片长目标、参考资产清单（含平台数量上限）、原生音频去留策略。
   - CharacterCard：S号、名字、完整外貌固定描述（脸/肤/眼/眉/鼻唇/发/服装/配饰，逐字复用，禁止只给短锚点）、voice_card（性别年龄、音高、语速、音色质感、口音、空间混响）、按故事日的状态变化（伤、脏、湿、换装）。
   - SceneCard：场景固定描述、俯视站位图（文字坐标）、轴线、反打方向背景描述、lighting（来自词表+主光方向+色温+调色）、lens（焦段/光圈/机位高度）、固定环境底噪一句、配乐策略（含明确“无音乐”）。
   - PropLedger：道具名、持有人、左/右手/背/斜挎/桌面、起始状态、结束状态、液位等。
   - ShotContract（扩展现有 ShotListItem 的信息，不改其原 schema 也行）：shot_type、camera_move（每镜只允许一种）、composition、transition_in/out（来自词表）、视线角度、出入画方向、按秒 beats（内部）、动作对齐到台词某个词、手部占用、对白（说话人、画内/画外、口型锁定、字数→时长预算）、情绪刻度、start_state / end_state（下一镜 start_state 必须等于上一镜 end_state）、负面/约束。
   - GenerationLog：模型版本、seed、参考文件、条次、是否选用。
2. **导演词表 vocab**：filmvision.ai/learn 的 107 项（Shot Types 25、Camera Movements 20、Lighting 15、Editing 20、Composition 12、Genres 15，英文名见下方附录），每项给：id、英文名、中文名、一句中文提示词写法、ai_risk（stable / caution / post_only）、所属字段。post_only（dolly zoom、whip pan、roll、split-screen、freeze frame、flash cut、cross dissolve、jump cut、parallel editing、cross-cutting、montage、slow motion、time-lapse、smash cut、invisible cut、split edit、J/L cut 等剪辑类）只能进剪辑单，不得进生成提示词。
3. **编译器升级**：新函数 compile_continuity_prompt(bible, scene, characters, props, shot, platform)：
   - 每镜输出：风格定性 + 语言锁（“全部对白与背景人声只说普通话，禁止日语或其他语言；画面不出现文字”，场景文化不能带偏语言）+ 本镜每个角色的完整固定描述（修掉现有 character_block 所有角色共用一个 anchor 的问题）+ 音色卡 + 【镜头】（景别/角度/焦段/机位/唯一运镜）+【光线调色】+ 道具与手部状态 + 动作 + 对白 + 环境声/配乐 + 一致性条款（同脸同服装同光线同机位）+ 结束状态与衔接。
   - platform 适配：h3（保留现三段式与 <d>[Chinese]）、seedance/muse（不写精确秒数，改“先…再…最后…”顺序节拍；约束词写法）、veo（台词“说话人：台词”不加引号；负面词放独立字段）、runway（不用否定句，改肯定写法）、generic。
   - 无配乐段输出“无音乐”，不再自动加默认配乐。
4. **校验器** validate_film(...) 返回错误列表：一镜多运镜；post_only 技法进了生成提示词；道具手部冲突（如双手推轮椅同时手提包）；start_state≠上一镜 end_state；对白超时长预算（约 4 秒 1–2 句短句）；角色描述非逐字一致；缺语言锁；画内文字不在白名单。
5. **审片清单生成** review_checklist(shot)：research.md 里的 16 项。
6. **示例**：examples/continuity_wedding_demo.py 用“婚宴致辞+闪回推轮椅”的 2–3 镜构造数据，打印各平台输出，演示校验器能抓到“推轮椅掉包”冲突。

## 验收
- 新增单测（真实调用、不 mock）覆盖：每平台输出差异、语言锁存在、角色描述逐字、道具冲突被抓、状态交接校验、post_only 被拦、无音乐段不加配乐、多角色各自描述。
- 回归：tests/test_h3_compiler.py tests/test_h3_shot_discipline.py tests/test_prompt_engineering.py tests/test_shot_prompt.py 无新增失败（先跑一遍记录基线）。
- python 用 /data/soffy/projects/hevi/.venv/bin/python，在本 worktree 目录下运行 pytest。

## 规则
CPU-only，不调付费 API，不 push、不 merge、不部署；不删 worktree 外文件；每步 commit。
最后写 REPORT_CONT1017.md：做了什么、文件清单、测试结果（基线 vs 现在）、未完成项；最后一行 `CONT1017 DONE` 或 `CONT1017 BLOCKED`。

## 附录：filmvision 107 项
Shot Types: Close-Up, Extreme Close-Up, Medium, Medium Close-Up, Wide, Extreme Wide, Full, Cowboy, Two-Shot, Over-the-Shoulder, POV, Dutch Angle, Bird's Eye, Worm's Eye, Establishing, Insert, Cutaway, Reaction, Master, Tracking Shot Framing, Profile, Three-Quarter, Clean Single, Dirty Single, Split-Screen
Camera Movements: Dolly, Dolly Zoom, Pan, Tilt, Tracking, Crane, Steadicam, Handheld, Zoom, Push In, Pull Out, Arc, Whip Pan, Roll, Boom, Cable Cam, Drone, Slider, Jib, Follow
Lighting: Three-Point, High-Key, Low-Key, Rembrandt, Silhouette, Chiaroscuro, Practical, Motivated, Natural, Backlight, Rim, Fill, Hard, Soft, Bounce
Editing: Jump Cut, Match Cut, J-Cut, L-Cut, Cross Dissolve, Smash Cut, Montage, Parallel Editing, Cross-Cutting, Flash Cut, Freeze Frame, Slow Motion, Time-Lapse, Split Edit, Invisible Cut, Match on Action, Eyeline Match, Cut on Action, Establishing Cut, Cutaway
Composition: Rule of Thirds, Leading Lines, Symmetry, Framing Within Frame, Depth of Field, Negative Space, Golden Ratio, Diagonal Lines, Foreground Interest, Balance, Triangular, Dynamic Symmetry
Genres: Horror, Comedy, Drama, Thriller, Sci-Fi, Action, Romance, Documentary, Film Noir, Western, Musical, Mystery, War, Animation, Independent

## 复核问题（Hark 复核 2026-10-17 15:30，必须修完再写 DONE）
用修改版 demo 把 Shot-02（闪回推轮椅）各平台完整 prompt 打出来后发现：
1. **闪回换装自相矛盾**：【人物】完整固定描述里写死婚礼服装（李明“深灰定制西装+领结+襟花”，苏晴“米白露肩婚纱+珍珠耳钉”），后面又追加【当日状态：浅蓝针织衫/病服外套】。同一镜给模型两套服装＝必穿帮。要求：CharacterCard 把“不变的身体特征（脸/肤/眼/眉/鼻唇/发质/疤痕）”与“按故事日的服装配饰”分开；编译时只输出本镜所在故事日的那一套服装，不出现别的故事日服装。加单测：闪回镜头 prompt 不含婚礼服装词。
2. **音色卡混响写死在角色上**：闪回室外花园仍输出“中等宴会厅空间混响”。空间混响应来自 SceneCard（或按场景覆盖），音色本体（音高/语速/质感/口音）跨镜不变。加单测。
3. **runway 仍是否定写法**：输出“保持完全无字幕、无文字、无水印的干净画面”，“无耳环戒指”等。brief 要求 runway 全部肯定句；改成“画面干净纯净，只呈现人物与场景”之类，角色描述里的“无X”在 runway 下也要改写或省略。加单测：runway 输出不含“无/不要/禁止/严禁/避免/没有”否定词（“无音乐”字段除外，或改为“仅环境声”）。
4. **post_only 中文同义词漏拦**：find_post_only_violations("眩晕变焦") 返回空（只认“滑动变焦”）。给 post_only 项加常见中文别名（眩晕变焦/希区柯克变焦、甩镜头、急摇、叠化、慢动作、延时摄影、定格、蒙太奇、平行剪辑等）。加单测。
5. 小问题：seedance 动作行出现“。。”双句号；道具“女式黑皮手提包 持有人:折叠轮椅”应写为持有人李明/放置于轮椅右把手挂钩。
6. demo 增加 Shot-02 的完整各平台 prompt 输出（不要只打前 4 行），REPORT 的“未完成项”如实写。
