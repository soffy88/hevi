# AI 多镜叙事短片：连续性（防穿帮）前期文档与提示词补缺报告
日期：2026-10-17｜范围：Muse/Seedance、Kling、Veo、Hailuo、Sora、Grok Imagine、Runway；传统场记实践

> 层级缩写：【圣】整片圣经 ｜【场】场景卡 ｜【角】角色卡 ｜【镜】每镜契约 ｜【审】生成后审片

---

## 0. 先要修正的一点：已知缺口里“负面词进正文”和“按秒动作”要按平台改写
- **负面词**：Runway 明确说不支持否定式写法，写了可能得到相反结果，要改成肯定句（“Locked camera”而不是“No camera movement”）。Veo 有独立的 `negativePrompt` 参数；Seedance 官方用“约束词”（如 keep it subtitle-free）。所以负面词应放在**平台适配层**，而不是一律写进正文。
  来源：https://help.runwayml.com/hc/en-us/articles/39789879462419-Gen-4-Video-Prompting-Guide ｜ https://cloud.google.com/vertex-ai/generative-ai/docs/video/generate-videos-from-text ｜ https://doc.cocostudio.io/dreamina-seedance-2-0-series-prompt-guide-2238042m0
- **秒级时间码**：Seedance 2.0 官方指南明说精确时间（如 0–3 秒）不稳定，强行限定时长可能导致生成异常，建议写成 Shot 1/2/3 的先后顺序。Sora 指南则建议用“节拍/步数”来写（“走四步，停顿，最后一秒拉窗帘”）。
  → 0–3/3–7/7–10 秒保留为内部计划，提交给模型时改写成“顺序＋节拍数”。
  来源：上述 Seedance 链接 ｜ https://developers.openai.com/cookbook/examples/sora/sora2_prompting_guide
- **台词引号**：Veo 官方建议说话人后用冒号、**不要加引号**，否则模型可能把台词渲染成画面文字。Sora、Kling 的示例则用引号。
  → 引号规则也属于平台适配层。来源：https://docs.cloud.google.com/vertex-ai/generative-ai/docs/video/best-practice

## (a) 已知缺口之外还缺的项目

| # | 补缺项 | 解决的穿帮 | 层级 | 字段示例 | 来源 |
|---|---|---|---|---|---|
| 1 | **故事日/时间线表** | 伤口、血、脏污、汗、衣服破损、发型湿干在不同场次之间倒退或跳变；场景时段错乱 | 【圣】→【场】 | `故事日:D2 / 时段:傍晚17:30 / 距上场:+20分钟 / 伤:左眉角新伤未包扎 / 衣:白衬衫袖口溅泥` | https://www.dfirentals.com/news/what-does-a-script-supervisor-do ；https://storiara.com/glossary/continuity-report |
| 2 | **动作对齐到台词里的某个词（match on action）** | 剪辑点两侧，拿杯、起身、转头的时机对不上 | 【镜】 | `说到“算了”时右手放下杯子；起身动作从上一镜尾帧的半蹲姿态接续` | DFI（同上）；https://scripttoscreen.co.uk/continuity-errors-in-editing |
| 3 | **手部占用＋哪只手** | 道具换手、凭空出现或消失（道具账本只管物品状态，不管手） | 【镜】 | `左手:空 / 右手:茶杯(七分满) / 肩:黑包挎右肩` | https://scripttoscreen.co.uk/script-continuity-supervisor-real-job |
| 4 | **视线数值化＋场景俯视站位图** | 正反打时两人看向同一侧；视线高度不一致（坐着和站着） | 【场】站位图＋【镜】视线 | `A坐画左，视线画右偏15°、略仰；B站画右，视线画左、俯视` | DFI（同上）；创作者实践：https://github.com/Nagacash/character-continuity-skill/blob/main/skills/character-continuity/SKILL.md （证据弱） |
| 5 | **出入画方向** | 人物从画右出、下一镜又从画右进，或行进方向反了（轴线锁定一般只管对话轴） | 【场】【镜】 | `本镜从画右出画 → 下一镜从画左入画` | DFI（同上） |
| 6 | **反打/四面墙场景参考** | 反打镜头里出现从没设计过的背景，窗户、门的位置凭空变化 | 【场】 | `场景参考图：正向背景×1、反向背景×1、俯视平面图×1` | Seedance 建议为每条生成配 1 张场景图；Nagacash 提到的“反打陷阱”（证据弱） |
| 7 | **参考资产分工表＋数量上限** | 参考图太多导致特征优先级混乱、脸串到别人身上 | 【镜】 | `@图1=阿明脸, @图2=阿明全身, @图3=客厅, @音频1=阿明音色`；Seedance 建议总共 4–5 个；Sora 每条最多 2 个角色；Veo 最多 3 张参考图；Grok 1.5 最多 14 图＋3 个声音 | Seedance（同上）；Sora cookbook；https://ai.google.dev/gemini-api/docs/veo ；https://docs.x.ai/developers/model-capabilities/video/reference-to-video |
| 8 | **说话人入画/画外标记＋口型锁定等级** | 画外台词却有人张嘴；两人同框时台词串到另一人嘴上 | 【镜】 | `说话人:B(入画,正脸,口型锁定) / A:背对镜头,不得开口`；口型锁定的镜头后期不能自由换台词，非锁定（背影、画外）的可以 | 场记“直线/波浪线”惯例：DFI；一镜一说话人：https://openmicrodrama.com/guides/lip-sync-and-dubbing （创作者）；Sora 建议说话人标签保持一致 |
| 9 | **台词时长预算** | 台词塞不进片段时长，导致无声或口型崩 | 【镜】 | Sora：4 秒放 1–2 句短句，8 秒可多几句；Google Flow：台词放不进 8 秒时模型更可能不出声 | Sora cookbook；https://blog.google/innovation-and-ai/products/flow-video-tips/ |
| 10 | **画内文字白名单＋禁止字幕** | 乱码字幕、招牌或手机屏乱字 | 【圣】总则＋【镜】 | `画内文字:仅招牌“和记”二字 / 无字幕、无水印、无logo` | Veo 字幕问题：https://www.technologyreview.com/2025/07/15/1120156/googles-generative-video-model-veo-3-has-a-subtitles-problem/ ；Seedance 约束词（同上） |
| 11 | **表演情绪刻度** | 全景里在笑，同一时刻的近景却在哭 | 【场】按节拍＋【镜】 | `情绪:3/10 压抑→5/10 崩边；同一时刻各镜头一致` | https://theconversation.com/how-script-supervisors-keep-film-continuity-and-coffee-cups-and-cigarettes-in-check-127911 |
| 12 | **覆盖清单＋桥接镜头** | 越轴或穿帮之后没有镜头可以救 | 【场】 | `必拍:全景/A单/B单/手部插入/空镜×1(用于越轴桥接)` | DFI（同上） |
| 13 | **动作复杂度预算** | 物理上做不到的动作；一镜多个运镜导致画面不稳 | 【镜】 | `一镜一个运镜；动作慢、小、连续；不写冲刺、翻滚` | Seedance（同上）；Veo 最佳实践（一条一个场景）；Sora（一个运镜＋一个主体动作） |
| 14 | **原生音频去留决策＋空间声匹配** | 后期配音“漂”在画面上，场景之间底噪断掉 | 【圣】声音方案＋【场】 | `原生音频:仅作口型参考，全部替换 / 每场景铺一条连续底噪 / 配音加该房间的混响` | https://www.filmsound.org/QA/vocabulary.htm ；https://www.premiumbeat.com/blog/audio-editing-tip-matching-adr-and-location-audio-in-post/ ；https://www.britannica.com/technology/motion-picture-technology/Sound-editing |
| 15 | **生成日志（相当于场记单＋圈选条）** | 重新生成时无法复现；不知道哪一条是选用条 | 【审】 | `镜号/模型版本/seed/参考文件名/提示词版本/条次/选用✓/废弃原因` | Veo 同 seed 有助一致：Google best-practice（同上）；Hailuo 建议按文件名管理主体：https://hailuoai.video/pages/knowledge/consistent-ai-characters-s2v-guide |
| 16 | **片长计时** | 拼起来超出 3–5 分钟，或节奏塌掉 | 【圣】 | `每场估时；累计/目标 4:00` | DFI（同上） |
| 17 | **调色后期管线**（与提示词里的光线锁互补） | 不同生成之间色温、反差跳变 | 【审】 | 选 1 条 hero 镜头 → 其他镜头做 Shot Match → 统一一个 LUT 和一层颗粒；按模型分组 | https://www.blackmagicdesign.com/products/davinciresolve/color ；https://larryjordan.com/articles/how-to-color-match-clips-in-davinci-resolve-20/ ；https://hackernoon.com/how-to-color-match-ai-video-clips-when-every-model-grades-differently |

补充一条约束（未独立核实，按平台确认）：Seedance 的首尾帧模式据称不能和参考图混用（https://seedanceart.com/blog/seedance-2-0-multimodal-video-generation-guide ）。Grok 1.5 官方文档则允许首帧和参考图同时使用。所以每镜要写明用哪种“模式”。

## (b) 生成后逐镜审片清单
1. **脸和身形**：与定妆图并排比对，五官、发际线、痣或疤都在。宁可要“更像本人”的那条，也不要“更清晰”的那条。
2. **服装**：扣子、拉链、袖口卷起、破损和脏污与故事日一致；配饰（耳环、手表）在不在。
3. **道具和手**：在哪只手、液位、烟的长度、是否凭空出现或消失。和上一镜尾帧、下一镜首帧对照。
4. **视线和轴线**：正反打视线方向相反、高度匹配；没有无理由越轴。
5. **出入画方向**和行进方向连贯。
6. **剪辑点动作匹配**：动作发生在台词的同一个词上；姿态能接上。
7. **光线**：主光方向、时段、色温和场景卡一致；同一场内不跳。
8. **背景和布景**：窗、门、家具位置；反打背景和场景参考一致。
9. **语言**：每句台词是指定语言，没有被场景文化带偏（比如日式场景冒出日语）；口音一致。
10. **音色**：与角色音色卡一致。把同一角色的所有台词按角色连起来听一遍。
11. **口型**：说话人对；画外台词没有人张嘴；台词完整、没有被截断。
12. **画面文字**：没有字幕、乱码、水印；白名单里的文字正确。
13. **物理**：没有多余的手指或肢体、穿模、漂浮、凭空变形。
14. **表演情绪**和相邻镜头的情绪刻度一致。
15. **声音**：环境底噪连续，没有突然静音；配乐没有被模型私自加进来。
16. **记录**：在生成日志里标“选用/废弃＋原因”，同时更新道具和伤情账本，作为下一镜的状态交接。
（6、8、10、14 适合先拿 Gemini 一类视觉模型粗筛，再由人工复核。Google 官方建议把 Gemini 当作“第二双眼睛”：上面的 Veo best-practice 链接。）

## (c) 最值得采用的工作流做法
1. **先出多角度定妆图并入库，可行时绑定声音**（证据：强，多家官方文档）。Kling 3.0 用 2–4 张参考图或一段视频建 Element，可以绑定音色，绑定后提示词里不要再写音色；Veo 用 Ingredients 参考图；Sora 用 Characters API（2–4 秒视频）；Grok 1.5 支持 3 个声音参考。
   https://kling.ai/quickstart/klingai-video-3-model-user-guide ｜ https://blog.google/innovation-and-ai/technology/ai/veo-3-1-ingredients-to-video/ ｜ Sora cookbook ｜ https://docs.x.ai/developers/model-capabilities/video/overview
2. **角色描述和声音描述逐字复用，并固定 seed**（证据：强，但仅限 Veo 官方；seed 在其他平台的效果没有证实）。官方原话是把未改动的完整描述复制粘贴进每个场景，只改动作和场景部分。来源：Google best-practice。
3. **同一连续动作才用“尾帧→下一镜首帧”或 extend；跨场景改用参考图**（证据：功能存在有官方依据，跨场景效果属中等）。Veo、Grok 支持首尾帧和关键帧；Sora 的 extend 会用整段原片做上下文；Seedance 官方建议：同场景对话用延长，动作戏或剧情转折分段拼接。
4. **对白音色统一在后期做**（证据：中，创作者实测）。做法一：画面出完后，把某个角色的整条人声轨一次性过 ElevenLabs Voice Changer，再贴回去。做法二：先出音频，再用音频参考驱动口型（Seedance、Grok、Kling 都支持音频或声音参考）。反面证据：有创作者用第三方口型工具重新对口型，效果很差。所以优先让模型直接吃音频参考，事后改口型放在最后考虑。
   https://ai-for-real-life.beehiiv.com/p/the-secret-to-consistent-characters-in-veo-3-and-how-to-fix-the-voices-too ｜ https://invideo.io/faq/how-do-you-keep-the-same-voice-consistent-across-all/ ｜ https://pranshum.com/blog/video-ai-lessons/
5. **调色在后期统一，不只靠提示词**（证据：中偏强，有 Resolve 官方功能，加多篇实操）。先中和偏色，再匹配 hero 镜头，最后统一风格。LUT 不能修几何形状或服装上的穿帮。https://ciaro.pro/blog/davinci-resolve-editing-software-ai-film-workflow

## 证据强度说明
- 官方文档：Google Veo、OpenAI Sora、Kling、Runway、xAI、MiniMax、Seedance（COCO 托管的 Dreamina 指南，属于转载的官方指南）。
- 创作者或二手来源：OpenMicroDrama、Nagacash 技能、beehiiv、hackernoon、invideo。
- 场记实践来源：DFI Rentals、Storiara、Script to Screen、The Conversation、filmsound.org、Britannica。
