# MOTIONDIR-R1：Hevi 动效导演层（把"写动画代码"升级成"可复现的动效导演系统"）
来源：用户 2026-10-15 转来的文章（awesome-ai-motion 作者）核心观点：神作=参考+分镜+节拍+物理+分层渲染+音效+自检，一整套制作链；高级感来自删自由度、加约束，而不是加特效。

## 准备
1. 在 /data/soffy/projects 下用 `sudo -u soffy git -C /data/soffy/projects/hevi worktree add -b feat/motion-director /data/soffy/projects/hevi-motiondir origin/closure/3o-v3-architecture-creative-baseline`（先 fetch；主 checkout 不得修改）。
2. 先读：本仓已有 amrules（闭式弹簧+规则卡+lint，已合入）、aimotion 模板/转场、artmotion、shotspec（ShotSpec + capability 字段）、dirstyle、sfxbad、omquality、kids_gate；参考库 /data/soffy/refs/awesome-ai-motion（只学规则，不 vendor 作者作品代码）。复制 /data/soffy/projects/hevi-anatomy/KIDS_ANIME_DIRECTION.md 和 CAPABILITY_CONTRACT.md 到 worktree 并遵守。不重造已有模块，在其上加导演层。

## 要交付（产品定位：2–6 岁幼儿教育动画短片）
A. MotionBrief 数据模型 + 自动补全：从一句话需求生成完整导演层 brief：观众/核心信息、分镜（起势→发展→收束，每镜一个主任务和时长）、主体/次主体/背景、前中后景、每个元素独立运动轨迹、物理事件、主光方向、拍点、BGM/SFX 事件、禁止项（居中大字、霓虹渐变、全体同步淡入、整幅抖动等）、验收标准。可以用规则+模板补全（不调付费 API），产出 JSON，可人工改后再渲染。
B. 拍点网格：BPM×fps → 帧级拍点；重动作吸附重拍，允许微偏移（预备略早、撞击准拍、碎屑略晚）。
C. 运动语言库（纯函数，确定性）：预备→拉伸→冲击→压扁→过冲→回稳→次级响应；形变由速度/冲量推导，不是随机 easing；上一段末速度接续下一段初速度。物理：重力抛物线、碰撞连锁、弹跳滚动惯性、弹簧、软体、漂浮、水波/粒子聚散（选 ≥8 种实现）。
D. 错相编排器：主体先动，次层/相机/阴影/文字各自延迟若干帧；同一时刻只有一个主事件。
E. SFX 从运动长出：速度峰→whoosh，冲量→impact，接触帧→点击/落地；BGM 在主讲/台词处自动避让（ducking）。音效用本地合成或仓内已有素材库，最终音轨仍需过 kids_gate 响度（-16±1 LUFS，真峰值 ≤-1.5 dBTP），音量对幼儿温和。
F. 自动自检门（任一失败拒绝出片，给出可读原因）：
   - PPT 同步检测：同一时刻 ≥N 个层共用同一进度曲线 → FAIL；
   - 静止冻结：关键物体静止时高光/受光面/阴影也完全不动 → 警告/FAIL；
   - 主光方向一致性；
   - 拍点对齐率（重动作与重拍偏差）；
   - 禁止项命中；
   - 再串接 kids_gate、现有 omquality/布局重叠门。
G. 逐帧审片 HTML：输入渲染结果，生成单文件 HTML，可逐帧拖动、显示每帧的拍点/事件/层轨迹曲线/自检告警。
H. 注册 capability `motion_director`（registry + ShotSpec 可调用 + GET /api/capabilities 可见）；非法参数拒绝。
I. 样片：至少 3 支 6–12 秒幼儿主题（例如"小球学弹跳""水滴落进小水塘""积木搭高又倒下"），16:9 与 9:16 各一，1080p 30fps，CPU 渲染；另做同一 brief 的"无导演层基线"对比版，自检报告应显示基线 FAIL、导演版 PASS。同 seed 渲染 sha256 一致。产物和 REPORT.md 放 audit/motiondir/（只提交小体积合法产物）。
J. pytest 必须真实运行渲染/计算，禁止 mock 掉渲染和自检；JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=<worktree>，Python /data/soffy/projects/hevi/.venv/bin/python；3O lint（scripts/ci/run_3o_v3_lint.py）失败数 ≤ 基线 4。

## 完成
提交到 feat/motion-director（不 push）。写 MOTIONDIR_DONE.md：做了什么、测试命令与结果、样片路径、已知限制，最后一行 `DONE MOTIONDIR-R1`。

## 安全
只在 worktree 内写；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；CPU-only，同时只渲染一个；不调付费 API；不动生产容器/服务；不 push。不询问，长任务 nohup setsid 起再轮询。

## 范围扩大（用户 2026-10-15 13:02："这篇不止应用于动画"）——以此为准
导演层不是动画专用，而是 Hevi 所有产品线共用的「制作链」层：参考 → 分镜 → 主次/景深 → 节拍 → 物理/运动 → 光 → 声 → 自检。
1. MotionBrief 改为线路无关的 DirectorBrief（保留 motion 子结构）；同一 schema 能描述：讲解/科普（talkcraft、archify、anatomy）、手绘线、火柴人、3D 短片（scene3d）、漫剧/短剧（drama/comic/manga）、纪录混剪（omfootage/documentary_montage）、口播数字人、品牌/产品片。
2. 每条线做一个薄适配器：把 DirectorBrief 翻译成该线已有的输入（ShotSpec、分镜、模板参数、相机、SFX 事件），不重写各线。至少接通 4 条线：一条讲解类、一条角色叙事类（漫剧或手绘）、一条 3D 或 anatomy、一条实拍/素材混剪类。
3. 参考优先：brief 必须能挂参考（dirstyle 导演风格库、awesome-ai-motion 规则卡、用户给的参考视频/图），参考的约束写进禁止项和验收标准。
4. 自检门做成全线通用的出片前闸门（director_check）：PPT 同步、静止冻结、主光一致、拍点对齐、禁止项、主次层次（同一时刻只有一个主事件）、声画对齐（SFX 落在接触/切换帧、BGM 给人声让路），再串 kids_gate / omquality / 布局门。任何线都能调用；不适用的检查项自动跳过并在报告里写明原因。
5. 逐帧审片 HTML 对任何线的成片都能用。
6. capability 注册三个：director_brief（生成/补全）、director_check（自检）、motion_director（运动/物理/拍点渲染）。都要能被 ShotSpec 和 GET /api/capabilities 调到。
7. 样片改为：至少 3 条不同产品线各一支（6–12 秒，1080p，16:9 和 9:16 各至少一支），每支配「无导演层基线」对照，自检报告应显示基线 FAIL、导演版 PASS。
