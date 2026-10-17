# MANGA 单元：剧情→漫画分镜 + 3D 房间背景抽卡 + OSM 实景街区背景（clean-room，纯 CPU）
参考（只看公开页面的功能，不抓取、不复制其 JS 代码，代码无开源许可）：oyasumi-gamedev 的 comicalizer（剧情→分镜/机位/姿势/对白框/效果线/背景）、namegacha（分镜里自动摆人物轮廓）、haikeigacha（房间 3D 背景抽卡）、rokehan（OSM+高程→3D 街区→漫画线稿与网点）。
worktree：/data/soffy/projects/hevi-manga，分支 feat/manga-name，基于 ac09c747。3D 渲染方式参考 /data/soffy/projects/hevi-scene3d 的 Three.js + Playwright SwiftShader 做法（只读，复制思路，不要改那个目录）。three.js 是 MIT，可以 vendor。

## M1 分镜生成器（namegen）
- 输入：剧情文本（可接 huobao 的 storyboard breaker 输出，或 Hevi 的 drama/comic 剧本）。
- 输出：每页的分镜 JSON 和 PNG/SVG。分镜 JSON 包括：
  - 格子布局：B5、4:5、1:1、9:16 四种比例；阅读方向可选右→左或左→右；按 seed 生成，支持「变异度」参数。
  - 每格的机位：景别、俯仰、镜头 mm、倾斜。
  - 人物：站位和简易人偶姿势，提供 idle/walk/run/wave/sit/point 六种。
  - 对白框：形状随情绪变化，文字只取剧本原句。
  - 效果线：集中线、速度线、网点。
- 诊断叠层：阅读顺序编号、视线箭头、对话轴（180° 规则）。必须有 180° 越轴检查闸门。
- 同 seed 重复生成，结果逐字节一致。

## M2 房间背景抽卡（roomgacha）
- 程序化房间：先把地面划成网格，给每格指定属性（区域/通道/高差）；墙边可放窗和门。家具全部由箱体和圆柱的生成器组合而成：桌、椅、床、柜、书架、沙发、讲台、课桌阵列。
- 场景至少三种：教室、自己的房间、客厅。提供「生活感/凌乱度」参数。
- 渲染风格：漫画线稿（法线和深度边缘检测）+ 网点阴影 + 可选固有色。光源方位可调。
- 导出：PNG（长边 2400/3600）、透明纸面线稿、GLB。
- 可以直接作为 M1 某一格的背景；人物站在地面上，用同一相机渲染。

## M3 OSM 实景街区（locscout）
- 输入：经纬度，或 OSM/Google Maps 链接。范围 200m–1km。
- 数据来源：
  - 建筑、道路、河流取自 Overpass API。走主机代理 127.0.0.1:7890，结果缓存到 worktree 的 data/osm_cache/；请求失败要报错，不允许假成功。
  - 建筑高度：优先用 OSM 里的 height 或 building:levels；没有就按用途和面积估算，带 seed。
  - 地形高程用 AWS Terrain Tiles。
- 渲染：同一套漫画线稿和网点风格，相机放在人眼高度 1.55m。可加树、白线、电线杆。
- 每张图右下角必须自动加上「© OpenStreetMap contributors」（ODbL 要求），并在 docs 里注明许可。
- E2E 地点固定两个：上海武康路一带（31.2075,121.4380）和东京下北泽（35.6614,139.6680）。各出 1 张白天、1 张傍晚。

## M4 接入 Hevi
- comic_narration / drama 线新增 background_source 选项：roomgacha、locscout、keyframe。
- 能力注册：按 CAPABILITY_CONTRACT.md 注册 manga.name_layout、manga.room_bg、manga.location_bg 三个能力。
- 动态化：每格可生成 2–4 秒的推拉或横摇镜头 mp4，相机在 3D 里移动，线稿逐帧渲染。这样 talkcraft、zero 等线也能当 B-roll 用。

## E2E
用 huobao 风格写一段约 1 页的短剧情：《小狐狸在下北泽找星星》，2 个角色，6–8 格。
- 背景要求：至少 2 格用 roomgacha，至少 2 格用 locscout 的下北泽。
- 交付：
  - 分镜页 PNG（9:16 和 B5 各一张）；
  - 3 段动态镜头 mp4；
  - 质检报告，包括 sha256、ffprobe 结果、越轴检查、文字是否越界、OSM 署名是否存在。

## 测试
pytest 覆盖以下各项：
- 同 seed 复现；
- 越轴闸门能抓到问题；
- 对白文字必须是剧本原句的子串；
- OSM 缓存缺失加离线时明确报错；
- 署名像素存在；
- 删掉产物后测试会失败；
- 3O lint 不新增失败。

## 规则
- 纯 CPU；不调用付费 API；不 push。
- 只改本 worktree；不删 worktree 外任何文件；不清理磁盘。/data 剩余空间小于 5G 时写 DISK_FULL_NOTE.md 并停止。
- 中间帧用完即删，仅限本 worktree 内自己生成的。
- 长时间的 E2E 用 nohup setsid 后台跑并轮询。
- 内存紧张：渲染单进程，Playwright 用完就关。
- 完成后在 MANGA_DONE.md 最后一行写 DONE MANGA-R1。

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；所有 python 设 PYTHONPATH=/data/soffy/projects/hevi-manga；不 push；不调付费 API；不要把 lint 日志提交进仓库。完成后在 MANGA_DONE.md 最后一行写 DONE MANGA-R1。

## 产品方向（2026-10-14 追加，优先级最高）
阅读 KIDS_ANIME_DIRECTION.md：Hevi 以幼儿（2–6 岁）有营养的动漫故事片为主。本单元的样片、配色、台词、节奏都要符合其中的内容要求和 kids_gate 安全闸门（镜头≥2.5s、闪烁≤3Hz、-16 LUFS、无惊吓/暴力、字幕大号）。manga 单元改为彩色绘本风为主，黑白网点只作可选项；E2E 剧情改成幼儿向。huobao 增加 kids 模式（剧本改写时加入成长主题与重复句式）。
