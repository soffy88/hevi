# DIRSTYLE_FIX r1 — 主审独立复核不通过（2026-10-13 08:3x CST）

worktree /data/soffy/projects/hevi-dirstyle，分支 feat/director-styles，当前 HEAD 47699940。
DIRSTYLE_TASK.md / DIRSTYLE_TASK_ADD1.md 全部规则继续有效：CPU-only、无付费 API、禁止 mock、不删数据、**不 push、不合并**、3O lint 只允许既有 4 项基线失败、DONE 如实。在已有提交上继续，不要推翻已完成的风格库。不要询问，直接执行。
运行 pytest/ffmpeg 时 PATH 必须含 /home/soffy/.local/bin（ffmpeg 在那里；sudo/systemd 会丢 PATH，否则 grade 测试 8 个 ERROR: No such file 'ffmpeg'）。

## 未完成（r1c 中断，单元退出时什么都没交）
- U1 未提交：heartbeat5.py、export_flow_pack.py、flow_pack_60s/*、tests/test_heartbeat5.py、flow_pack_30s/（30s 包要么修好后一起提交，要么删除）。
- U2 缺 tests/test_flow_pack.py（见 F 节断言）。
- U3 缺 9:16 火柴人 CPU 样片（record.json / SHA256SUMS / contact_sheet 都没有火柴人行）。
- U4 DIRSTYLE_DONE.md 没有「ADD1」节。

## 阻断 B — 导演风格样片（output/dirstyle_e2e/*.mp4）
- B1 王家卫调色与源片几乎无差别（contact sheet 肉眼看不出）。要做出可辨识的王家卫：偏青绿/琥珀分离、高饱和、暖高光、抽帧/叠帧拖影（step-printing，可用 tmix/minterpolate/帧混合）、轻颗粒。加测试：每个风格成片中间帧与源片的 signalstats（YAVG/UAVG/VAVG/SATAVG）至少一项差异超过明确阈值，王家卫必须过。
- B2 四个风格全部是同一个 16:9 上下黑边构图塞进 9:16，等于只改了比例标签。**禁止硬裁切丢画面主体**，但每个风格必须有自己的 9:16 重构图（例：韦斯=绝对居中对称 + 上下粉彩色块/画框分区；芬奇=主体偏上三分之一 + 大面积暗部负空间 + 缓慢推镜；王家卫=偏心构图 + 拖影 + 前景遮挡/霓虹色带；张艺谋=大色块铺满 + 主体落竖向中轴）。可用模糊/色场背景 + 前景画面不同位置/尺寸/缓推缓移（Ken Burns）实现，构图参数写进各风格 JSON 的 9:16 规则并由 grade 管线读取。加测试：四个风格 9:16 成片的主体画面 bbox（位置或尺寸）互不相同。
- B3 源片自带烧录字幕和「SHOT 02 …」水印（来自 hevi-omlines 的 director_pipeline.mp4 成片）。换成**干净源素材**（无烧录字幕、无水印、无字卡）：在仓库/兄弟 worktree 的原始素材里找（例如 omfootage/omlines 下载的原始 NASA/Archive 片段，或仓库 assets），抽帧亲自确认无文字后再用；record.json 写明来源与许可。字幕只由本管线 _subbed 版本叠加。
- B4 contact_sheet.png 里中文标签全是豆腐块。用系统 CJK 字体（/usr/share/fonts/opentype/noto/NotoSerifCJK-*.ttc 或 fc-list :lang=zh 查到的 Noto Sans CJK）。
- B5 所有叠加文字（字幕、标签）必须完整在画面/安全区内，不出框、不截断。

## 阻断 F — 60s 提示词包（flow_pack_60s/pack.md|json）
- F1 每段 3 个节拍 [0–3s][3–7s][7–10s] 现在都是把同一句旁白复制 3 遍。节拍必须是**各不相同的画面动作描述**（火柴人在做什么、镜头/构图怎么变），旁白单独放音频字段。
- F2 旁白字数不达标：现在每段只有一句 ~10 字。按每 10s 段约 45–60 汉字（英文 20–25 词）缩放；只重组/改写输入素材，不编造事实/数字/引语。素材不够长就换一段更长的真实中文通用常识文。
- F3 编译后的生成提示词同时塞进了 16:9 和 9:16 两套构图规则（含 "stage action across left, center, and right / lateral tracking / mechanical horizontal track"）。9:16 包只能出现 9:16 构图句；导演的横向运动要翻译成竖向（如机械竖向升降/上下摇）。测试：9:16 包的提示词不含 "16:9"、"left, center, and right"、"lateral"、"horizontal track"。
- F4 配色冲突：火柴人 1A 自带 "vivid red, electric blue, warm gold"，再叠加韦斯 "pastel pink / mustard yellow / mint green / sky blue"，总计 7 色，违反「≤3 强调色」。规则：画风维度定底色与线条（白底黑线），导演维度只贡献 ≤3 个强调色（取导演配色前 3），最终提示词里只出现一组 ≤3 强调色，用普通颜色词。另外 "high lightness, low contrast" 之类与白底黑线不冲突可留，"layered front-to-back depth" 与 1A 负面 "3D depth" 冲突要消解。
- F5 连续性锁定块缺具体配音档案：只有一句泛泛说明。锁定块里要有逐字冻结的配音档案（性别/年龄感、口音、音色、语速、录音处理等具体值），并且**每段都逐字重复**。
- F6 缺段间衔接：每段要写「结尾画面」和「开头画面」，且 段 i 结尾画面 == 段 i+1 开头画面（逐字一致或明确引用同一描述）。
- F7 Director Proposal 的 Core message 为空；补上（从素材提炼，不编造）。
- F8 tests/test_flow_pack.py：断言 6 段×3 节拍且三节拍互不相同；每段含完整锁定块原文（含配音档案）；段间首尾衔接相等；9:16 包无 16:9 构图词；强调色 ≤3 且无 hex/RGB；无写实词、无导演名；旁白每段汉字数在 45–60（允许 ±10%）；产出中的数字都出现在输入里；pack.json 与 pack.md 段数一致；导出函数不发任何网络请求（可 monkeypatch socket 断言不被调用——这不是 mock 产出）。

## 阻断 S — 火柴人 9:16 CPU 样片
- S1 1080×1920，10–30s，PIL/SVG→帧/Remotion/manim 任一 CPU 方式；内容是 5 段心跳结构短稿；有可见动作（不是静态图），火柴人符合 stickman_1a_light DNA（空心圆头、五条连接线、等宽线、无手脚形状）。本地 TTS（piper 等）配音可选；字幕用 CJK 字体，在安全区内不出框。长任务 nohup setsid。
- S2 补进 record.json、SHA256SUMS、contact_sheet.png（多一行）。

## 其它
- DONE 里日期写错为「2026-08-12」，改成真实日期（2026-10-13 CST）。DONE 追加「ADD1」+「FIX r1」节：接口、文件、测试命令与结果、所有成片 ffprobe+sha256、提示词包路径、已知限制。如实写，不自评通过。
- 保留 third_party/stickman-video-director/LICENSE（MIT）与 THIRD_PARTY_NOTICES 登记。
- 阶段性 git commit（只 add 自己的文件），**不 push**。最后跑：所有 dirstyle/heartbeat/flow 测试 + scripts/ci/run_3o_v3_lint.py（只允许基线 4 项）。
