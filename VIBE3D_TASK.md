# VIBE3D-R1：内化《3D Vibe Coding 手册》到 Scene3D 线（幼儿动画短片优先）
来源：用户 2026-10-15 21:39 发来 https://github.com/alchaincyf/3d-vibe-coding-handbook （花叔，littleprince.dev 同作者；386 页手册 + 6 demo + 11 工具脚本 + 11 资源包，CC BY-NC-SA 4.0；目前非商业，用户已说许可暂不管，但必须保留署名 ATTRIBUTION）。
worktree /data/soffy/projects/hevi-vibe3d，分支 feat/scene3d-vibe（基于已 push 的 closure，已含 scene3d R1D）。先读现有 hevi scene3d 线（Three.js + Playwright SwiftShader CPU）、audit/scene3d/SCENE3D_R2_PLAN.md、KIDS_ANIME_DIRECTION.md、CAPABILITY_CONTRACT.md。

## 获取（host 上 github 被墙，用 ghfast.top 或 127.0.0.1:7890 代理）
- clone 仓库到 /data/soffy/refs/3d-vibe-coding-handbook（只读参考）。
- 从 Releases 下载资源包：01 样例三件套、03 巴黎512+植被街具、05 绑骨与动画、07 小王子/游乐园设计图与提示词、11 工具脚本（共约 80MB；不要下 04 的 8K 原档）。逐个校验 SHA256。放 /data/soffy/refs/3d-vibe-assets/，仓库里只登记清单+署名，不提交大文件（必要的小 GLB ≤5MB 可进 assets/ 并写 ATTRIBUTION）。
- 禁止调用 Tripo / GPT 等付费 API（书里的图生 3D 只作方法参考）。

## 交付
A. 方法内化：通读手册，提炼成 docs/SCENE3D_VIBE_RULES.md —— §03 生成后处理、§04 减面/重拓扑下限、§05 材质贴图档、§06 绑骨与动画、§17 批量流水线、附录B 踩坑索引（按症状），只写对 Hevi CPU 渲染有用的条目，每条注明章节。
B. GLB 资产管线（hevi/scene3d/assets_pipeline）：用其工具脚本思路（gltf-transform）做导入 → 校验（三角面/顶点/贴图尺寸/体积/骨骼与动画剪辑清单）→ 按 CPU 预算自动减面+贴图降到 512/1K → 缓存；资产清单 JSON（来源、许可、署名、规格）。CPU SwiftShader 下单帧渲染时间要有预算门。
C. 动画角色：接入资源包 05 的带骨骼 GLB，AnimationMixer 按确定性时间步驱动（不依赖实时时钟），支持 walk/idle 切换与沿路径行走；同 seed sha256 一致。
D. 场景模板（至少 3 个，幼儿向、非写实、暖色）：小星球（参考小王子星球设计图的构图与配色，自己搭场景，不复制其网页代码）、小镇街道（用巴黎 512 街具/植被资产）、游乐园一角；每个模板含相机路径预设（环绕/推近/跟随）、主光一致、轮廓清晰。
E. 接导演层与分镜：模板与相机路径可被 ShotSpec 调用；注册 capability scene3d_asset_import、scene3d_template、scene3d_character_anim，GET /api/capabilities 可见；非法参数拒绝；串 kids_gate 与布局门。
F. 样片：2 支幼儿 3D 小短片 10–20 秒，1080p（16:9 与 9:16 各一），角色真的在走/有骨骼动作（抽帧可见肢体位移）、CosyVoice 中文旁白 + 字幕、CPU 单进程渲染。附与现有 scene3d R1D 星海/狐狸样片的对照帧。产物与 REPORT.md 在 audit/vibe3d/。
G. pytest 真实运行（禁止 mock 渲染）：JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=<worktree>，Python /data/soffy/projects/hevi/.venv/bin/python；3O lint 失败数 ≤ 基线 4。

## 完成
提交到 feat/scene3d-vibe（不 push）。VIBE3D_DONE.md：做了什么、测试命令与实测数字（渲染耗时/帧、资产减面前后面数、sha256）、样片路径、已知限制，最后一行 `DONE VIBE3D-R1`。

## 安全规则
只改本 worktree 和 /data/soffy/refs 下的新目录；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；CPU-only，同时只渲染一个；不调付费 API；不动生产容器；不 push；禁止 mock。
