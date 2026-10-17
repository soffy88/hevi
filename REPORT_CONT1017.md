# CONT-1017 验收报告：hevi 视频提示词「连续性 + 导演词表」升级

## 1. 任务概述与背景
hevi 原有 H3 提示词编译器（`hevi/prompt/h3_compiler.py`）仅具备基础的三段式镜头契约转换能力，实际在多镜生成时容易出现跨镜头穿帮：
- 场景文化带偏语言（如日式场景冒出日语台词/乱码字幕）
- 同一角色在各镜头之间音色质感跳变
- 角色外貌描述退化为短锚点，导致多角色共享特征或容貌漂移
- 道具手部冲突（如双手推轮椅同时持手提包）
- 跨镜头起止状态（start_state / end_state）断层跳变
- 剪辑/特效类技法（如跳切、眩晕变焦、甩镜等）误入文本生成提示词导致画面崩坏
- 无配乐镜头被自动填充默认情绪音乐

本次 CONT-1017 将“导演一部片前后不穿帮”所需的信息完整结构化并沉淀为 `hevi/prompt/continuity/` 独立子包，并提供跨平台编译适配、全片连续性校验、16项逐镜审片清单及演示示例。

---

## 2. 完成工作与特性说明

### 2.1 连续性核心数据结构 (`hevi/prompt/continuity/schemas.py`)
- **`FilmBible`**：整片圣经，包含片名、画幅、风格定性（is / is_not 列表，可输出成“不是X，而是Y”）、对白语言（默认 `zh-普通话`）、语言锁文案、画内文字白名单、类型预设、调色基准、故事日时间线、参考资产清单（带各主流平台上限）以及原生音频去留决策。
- **`VoiceCard`**：音色母卡，规范性别年龄、音高、语速、音色质感、口音与空间混响。
- **`CharacterCard`**：角色母卡，包含 S 号、姓名、脸/肤/眼/眉/鼻唇/发/服装/配饰完整外貌固定描述（逐字复用，杜绝短锚点）、VoiceCard 绑定及各故事日状态变化。
- **`SceneCard`**：场景母卡，包含场景固定描述、俯视文字站位坐标、180°主轴线与正反打视线约定、反打固定背景描述、布光方案、镜头参数、连续环境底噪与配乐策略（明确支持“无音乐”）。
- **`PropItem` / `PropLedger`**：道具账本，记录道具名称、持有人、携带/放置位置（左手/右手/双手/桌面/悬挂等）、起止状态与液位等物理细节。
- **`ShotDialogue` / `ShotContract`**：扩展镜头契约，整合景别、唯一运镜、构图法则、出入画方向、按秒 beats（内部计划）、动作对齐到台词某个词（match on action）、手部占用状态字典、台词与口型锁定等级、表演情绪刻度、起始/结束状态字典、负面约束与画内文字列表。
- **`GenerationLog`**：生成场记日志，记录模型版本、seed、参考资产文件、条次及选用/废弃标记。

### 2.2 导演词表 107 项与风险分级 (`hevi/prompt/continuity/vocab.py`)
严格收录来自 `filmvision.ai/learn` 的 107 个专业导演技法，划分为 6 大领域：
- **Shot Types (25 项)**：Close-Up, Extreme Close-Up, Medium, Medium Close-Up, Wide, Extreme Wide, Full, Cowboy, Two-Shot, Over-the-Shoulder, POV, Dutch Angle, Bird's Eye, Worm's Eye, Establishing, Insert, Cutaway, Reaction, Master, Tracking Shot Framing, Profile, Three-Quarter, Clean Single, Dirty Single, Split-Screen (post_only)。
- **Camera Movements (20 项)**：Dolly, Dolly Zoom (post_only), Pan, Tilt, Tracking, Crane, Steadicam, Handheld, Zoom, Push In, Pull Out, Arc, Whip Pan (post_only), Roll (post_only), Boom, Cable Cam, Drone, Slider, Jib, Follow。
- **Lighting (15 项)**：Three-Point, High-Key, Low-Key, Rembrandt, Silhouette, Chiaroscuro, Practical, Motivated, Natural, Backlight, Rim, Fill, Hard, Soft, Bounce。
- **Editing (20 项，全 post_only)**：Jump Cut, Match Cut, J-Cut, L-Cut, Cross Dissolve, Smash Cut, Montage, Parallel Editing, Cross-Cutting, Flash Cut, Freeze Frame, Slow Motion, Time-Lapse, Split Edit, Invisible Cut, Match on Action, Eyeline Match, Cut on Action, Establishing Cut, Cutaway。
- **Composition (12 项)**：Rule of Thirds, Leading Lines, Symmetry, Framing Within Frame, Depth of Field, Negative Space, Golden Ratio, Diagonal Lines, Foreground Interest, Balance, Triangular, Dynamic Symmetry。
- **Genres (15 项)**：Horror, Comedy, Drama, Thriller, Sci-Fi, Action, Romance, Documentary, Film Noir, Western, Musical, Mystery, War, Animation, Independent。
- **拦截机制**：所有 `post_only` 技法（共 24 项）严禁进入生成提示词正文，通过 `find_post_only_violations()` 自动拦截并强制留入剪辑单。

### 2.3 多平台连续性提示词编译器 (`hevi/prompt/continuity/compiler.py`)
实现 `compile_continuity_prompt(bible, scene, characters, props, shot, platform)`：
- 每镜统一输出：风格定性（“不是X，而是Y”）、语言锁（防日语与乱码）、每个角色完整固定描述（修复共享 anchor 穿帮）、角色音色卡、镜头语言组合（景别/角度/焦段/唯一运镜）、光线调色基准、道具与手部占用、动作弧与动作对齐、对白与口型锁定、环境底噪与配乐策略、全片一致性条款以及尾帧衔接状态。
- **平台专属适配**：
  - `h3`：保留标准三段式协议输出（`integrated_multimodal_description`, `overall_soundscape`, `non_diegetic_music`）与 `<d>[Chinese] 对白</d>`；
  - `veo`：台词采用 `说话人：台词` 严格不加引号，负面词输出至独立 `negative_prompt` 参数；
  - `seedance` / `muse`：内部秒级时间码自动转换为“先…再…最后…”顺序节拍，提供规范约束词；
  - `runway`：全面禁止否定句写法，全部转写为纯肯定句表达（如“锁定普通话清晰发声；画面纯净无文字”）；
  - `generic`：通用专业电影影视提示词规范。
- **无配乐支持**：当 `music_policy="无音乐"` 时，明确输出“无音乐”，绝不自动塞入默认 BGM。

### 2.4 全片连续性校验器 (`hevi/prompt/continuity/validator.py`)
实现 `validate_film(bible, scenes, characters, props, shots, prompts)`，返回违规列表：
1. **一镜多运镜**：拦截复合运镜（如 `Dolly, Pan`）；
2. **post_only 技法进入生成提示词**：拦截眩晕变焦、甩镜、跳切、叠化等进入生成提示词；
3. **道具手部冲突**：拦截“双手推轮椅同时手持手提包”、双重单手占用等生理不可能动作；
4. **状态衔接穿帮**：检查相邻镜头 `shots[i].start_state == shots[i-1].end_state`；
5. **对白超时长预算**：拦截 4 秒短镜头塞入 >2 句或超 25 字等超时长对白；
6. **角色描述非逐字一致**：拦截短锚点，确保母卡完整描述逐字复用；
7. **缺语言锁**：拦截未配置普通话及未显式禁止外语/字幕的配置；
8. **画内文字不在白名单**：拦截画面中出现的未经白名单许可的文字。

### 2.5 逐镜 16 项审片清单 (`hevi/prompt/continuity/checklist.py`)
实现 `review_checklist(shot)`，基于 `research.md` 工业级场记标准输出 16 项逐镜复核清单：
1. 脸和身形
2. 服装
3. 道具和手
4. 视线和轴线
5. 出入画方向
6. 剪辑点动作匹配（标注 `vlm_screenable=True`，适合视觉模型初筛）
7. 光线
8. 背景和布景（标注 `vlm_screenable=True`）
9. 语言
10. 音色（标注 `vlm_screenable=True`）
11. 口型
12. 画面文字
13. 物理肢体
14. 表演情绪（标注 `vlm_screenable=True`）
15. 声音
16. 场记记录

### 2.6 演示示例 (`examples/continuity_wedding_demo.py`)
构造“婚宴致辞 + 闪回推轮椅”两场景两镜头：
- 真实演示校验器准确拦截“双手推轮椅同时手持手提包”手部冲突、复合运镜与状态断层；
- 修复冲突后重新校验，验证 0 errors 完全合规；
- 输出 H3、Seedance、Veo、Runway、Generic 五大平台适配提示词及 16 项审片清单。

---

## 3. 文件清单

| 文件路径 | 状态 | 说明 |
|---|---|---|
| `hevi/prompt/continuity/__init__.py` | 新增 | 连续性子包导出接口 |
| `hevi/prompt/continuity/schemas.py` | 新增 | FilmBible, CharacterCard, SceneCard, PropLedger, ShotContract 等 |
| `hevi/prompt/continuity/vocab.py` | 新增 | Filmvision 107 项导演词表与 post_only 风险过滤 |
| `hevi/prompt/continuity/compiler.py` | 新增 | 跨平台连续性提示词编译器与 ContinuityRender |
| `hevi/prompt/continuity/validator.py` | 新增 | 8 项严格连续性与导演纪律校验器 validate_film |
| `hevi/prompt/continuity/checklist.py` | 新增 | 16 项逐镜防穿帮审片清单生成器 |
| `examples/continuity_wedding_demo.py` | 新增 | 婚宴致辞+闪回推轮椅完整演示脚本 |
| `tests/test_continuity.py` | 新增 | 12 项端到端单测（真实调用无 mock） |
| `REPORT_CONT1017.md` | 新增 | 任务总结与验收报告 |

---

## 4. 测试与验证结果

### 4.1 基线测试
执行命令：
```bash
/data/soffy/projects/hevi/.venv/bin/python -m pytest tests/test_h3_compiler.py tests/test_h3_shot_discipline.py tests/test_prompt_engineering.py tests/test_shot_prompt.py
```
- 结果：**73 passed in 7.00s**（无失败，基线正常）。

### 4.2 现状测试（包含新增模块与全套回归）
执行命令：
```bash
/data/soffy/projects/hevi/.venv/bin/python -m pytest tests/test_h3_compiler.py tests/test_h3_shot_discipline.py tests/test_prompt_engineering.py tests/test_shot_prompt.py tests/test_continuity.py
```
- 结果：**85 passed in 6.03s**
- 差异：+12 个新增测试，73 个基线测试全部继续保持通过，0 回归，0 告警新增。

### 4.3 演示脚本独立运行验证
执行命令：
```bash
/data/soffy/projects/hevi/.venv/bin/python examples/continuity_wedding_demo.py
```
- 结果：正常运行到底，准确展示穿帮捕获（6 项违规）、修复验证（0 errors PASS）、多平台提示词生成与 16 项审片清单输出。

---

## 5. 未完成项
- 无未完成项。全部 BRIEF_CONT1017.md 规定范围内工作均已高质量交付并验证。

CONT1017 DONE
