# hevi-remotion 渲染契约(3O 内化 Phase C)

> 来源: gnipbao/story-to-handdrawn-video 的 DESIGN.md(rendering contract)+
> Vincentwei1021/video-shotcraft 的 aesthetic-rules 节奏准则。
> 状态: 契约文档;执行入口 `hevi/assembly/remotion_render_workflow.py`
> (3O 三件套签名,契约项在渲染前确定性校验,不花钱)。

## 1. 画布(Canvas)

- 默认 1080×1440(3:4 竖屏)/ 1920×1080(横屏),30fps,白/品牌底色由 StylePack 定。
- **字幕在上安全区**,插图/页面纹理用 `contain`,**永不 `cover` 裁剪**。
- 契约校验项: `safe_area`。

## 2. 动效(Motion)

- 直切模式:内容按拍揭示;无相机抖动/弹跳(纪实风格明确追求时单独注记并 allow)。
- **One-Move Rule**:每镜头只允许一个可见动作节拍 + 一个主要运镜。
- **呼吸准则**:关键信息落定后静止 ≥1s;品牌字标 hold 满 1 秒;批量入场收尾 0.5s。
- 契约校验项: `one_move_per_shot` / `no_unwanted_shake`。

## 3. 音频(Audio)

- **默认静音画面轨**:配音/音乐是后期工序(交付 MP4 画面轨,方便客户后期配音)。
- 配 BGM 的片:终渲固定交付两版(带 BGM + 无 BGM 保留 SFX),靠 `bgm` inputProp 同时间线渲出。
- 契约校验项: `silent_by_default`。

## 4. 资产(Assets)

- 输入母版(图片/音频/字幕)复制到**内容寻址产物目录**,只读消费。
- 渲染产物(帧/成片)是**可丢弃的运行时输出**。
- 数据按风险口径处理:客户/个人/内部/密钥一律虚构或脱敏,采集前冻结。
- 契约校验项: `disposable_outputs`。

## 5. 校验与执行

`RemotionConfig.enforce_contract=True` 时,`remotion_render_workflow` 渲染前先跑
`check_render_contract()`:违反契约 → status=failed(不花钱)。headless 环境三堵墙
(来自 shotcraft 实测):`--concurrency=1`(低核)、chrome-headless-shell(旧 headless
已移除)、本地浏览器路径(remotion.media 被墙时)。
