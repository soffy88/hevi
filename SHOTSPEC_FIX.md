# SHOTSPEC_FIX — 第 2 轮独立核验(R2):不通过

核验对象:worktree `/data/soffy/projects/hevi-shotspec`,分支 `feat/shot-spec`,HEAD `2802d10a`(DONE SHOTSPEC-R2)。
核验时间:2026-10-14 服务器 UTC 04:55–05:10。核验脚本在 `/tmp/vfy_ss2/vfy_ss2.py`、`/tmp/vfy_ss2/ss_extra.py`,回归脚本 `/tmp/vfy_ss2/reg.py`,结果在 `/tmp/vfy_ss2/out/report_*.json`。素材用的是真实 stock 视频(hevi-omfootage/hevi-remotion/public/stock),输出 540x960 30fps。

## 已通过(保持,不要退化)
- pytest:`test_shot_spec_api + test_shot_spec_render + test_xfade_pack` 共 **276 passed**(以 soffy 身份跑,JWT_SECRET=test-only)。3O lint 失败项仍是基线那 4 项,没有新增。
- style 枚举:10 个值(blur/cool/mono/noir/sepia/sharpen/sketch/soft/vignette/warm)都有滤镜;`noir_test_style`、`cinematic`、`WARM`、空串都返回 422。每个值的镜中段帧和无 style 相比 SSIM 都 < 0.98(blur 0.765、cool 0.962、mono 0.983 但通道偏移 9.95、noir 0.959、sepia 0.949、sharpen 0.959、sketch 0.010、soft 0.922、vignette 0.896、warm 0.955),镜0 帧不变。
- duration:4 镜,时长依次为 1.5(裁)、4.0(补帧)、默认 3.0、2.2,接缝依次 dissolve/cut/fade。期望 9.7s/291 帧,实测 **9.700000s / 291 帧,误差 0 帧**。补帧段不是黑帧(均值 131.7)。
- sfx onset:4 个 cue 误差 0.000/0.006/0.010/0.020s,全部 ≤0.1s。
- 出片入口:先用真实 API `PATCH` 镜1 `{effect:mono,duration:2.0}`、镜2 `{style:sepia}`,再走 `render_graph_episode_artifact` 出片(clip 文件按 omodul 的命名 `shot_000N_v1.mp4`)。成片 7.000s/210 帧(无 spec 时 8.0s)。镜1 中段 |U−128|=0.054,镜2 有明显 sepia 偏色,contact sheet 亲眼确认。非 demo 调用点有 3 处(longvideo_orchestrator ×2、graph_render ×1)。
- 回归(用 R1 的脚本,1080x1920,5 镜):总时长 13.5s;sfx 误差 0/0.010/0.012/0.016/0.018s;warm R/B 1.050→1.610;mono |U−128| 0.0086;vignette 四角亮度 ×0.41;wipeleft/cut/ink/fade 接缝正常;API 的 422/404 全对。

## 阻断问题

### Q1 大部分 overlay/style 模板的"渲染"是占位滤镜,用来凑 framemd5 差异(P1 换了个形式又出现)
`shot_spec_render.template_filter()` 里有关键词兜底和"4. 保底"分支,注释原文是「产生确定性微饱和调整(保证成片有 framemd5 差异)」。逐个枚举 161 个可渲染模板,在 90 个非纯转场模板中,大约 80 个拿到的是跟模板语义无关的通用滤镜:
- `sfx:chime/ding/impact/pop/whoosh` 是**音效**模板,却渲染成一圈 2px 白色细框(`drawbox … white@0.3:t=2`),没有任何音频。
- `tc:number-counter`、`bar-chart-growth`、`chart-grow`、`line-chart-story-draw`、`metric-with-sparkline`、`number-slab-pop`、`numbered-step-stack` 渲染成一个空的半透明黑块,没有数字也没有图表。
- `tc:typewriter-reveal`、`word-slot-cycle`、`flying-words`、`per-character-rise`、`chat-message-flow` 等 26 个文字/UI 动画模板渲染成 `eq=saturation=1.2:contrast=1.05`,肉眼几乎看不出来(实测 SSIM 0.98)。
- 12 个 title/card 模板只是 `eq=brightness=0.04:contrast=1.12`;6 个 gallery/grid 模板是 `eq=saturation=1.25`。
- arrow/route/callout/timeline 类模板是一条青色色块;highlighter/underline/ellipse 类是一条黄色色块。
- `slow-push-in/slow-pull-reveal/orbit-drift/tilt-3d-page` 只是静态裁 4%,没有运动。
证据:`template_sheet.png`(依次为:无模板 | number-counter 空黑块 | sfx:chime 细白框 | word-slot-cycle | typewriter-reveal 与原图几乎一样 | map-route-pin 青色条 | crash-zoom 放大)。
后果:API 接受模板,成片却不呈现这个模板,和 R1 的 P1 是同一类问题,只是能骗过 framemd5 测试。

**验收标准**
1. 删掉 `template_filter` 里的"保底"分支和通用关键词兜底(title/text/card、gallery/grid、chart/metric/number、arrow/callout/route、bracket/frame、pull/push/orbit、code/terminal 映射到 curves 等),任何模板都不允许落到通用滤镜上。
2. 每个被接受的模板必须有**语义对应**的装配期动作,并且有一张对照表 `TEMPLATE_RENDER_MAP`(id → 动作,写清理由)。现在可以留下:71 个转场(xfade token 映射)、`crash-zoom-punch`、`focus-dim-spotlight`、`pencil-sketch-draw`/`outline-box-title`(edgedetect)、blur 类、`motion-blur-slam-in`(tmix)、`corner-bracket-frame`。push/pull 类如果要保留,必须是真运动(用 zoompan/随时间变化的 crop,首帧和末帧要不同)。
3. `sfx:*` 模板要么映射成音效(并入 `build_sfx_mixdown_filter`,onset 误差 ±0.1s),要么返回 422。
4. 其余模板(文字动画、图表、计数、UI 剧场、箭头、标注等)在 ShotSpec 校验里返回 **422「装配期不可渲染」**,等以后有真实 overlay 渲染器再放开。
5. 测试:`test_no_generic_template_fallback`,对 `valid_template_ids()` 里每个被接受的 id,断言它在 `TEMPLATE_RENDER_MAP` 里有显式条目,并且 filter 不属于下面这几个通用串:`eq=saturation=1.2:contrast=1.05`、`eq=brightness=0.04:contrast=1.12`、`eq=saturation=1.25`、`drawbox=x=30:y=30:w=iw-60:h=ih-60:color=white@0.3:t=2`。

### Q2 重新出片会把存好的 spec 清空(spec 存不住)
`TaskService.regenerate_task_shots`(task_service.py 约 2497–2500 行)和约 1125 行都是先 `delete_shots`,再 `_persist_shots`。`_persist_shots` 写入的 `selection_json` 只透传了 retry_count,没有带 `shot_spec`。
实测:用真实的 `TaskService._persist_shots` 跑一遍 delete+persist,各镜是否有 spec 从 `[F,T,T]` 变成 `[F,F,F]`。也就是说,用户 PATCH 的 spec 只在下一次 regenerate 生效一次,之后就丢了,再 regenerate 时不会再生效,GET 也读不回来。
**验收标准**:按 shot_index 把旧的 `selection_json["shot_spec"]` 带进新行,做法和 retry_count 一样。集成测试流程:API PATCH,走 `regenerate_task_shots`(或它的装配路径)出片,GET 仍能读回 spec;再出一次片,spec 依然生效(镜中段 mono |U−128|<2)。

## 非阻断(建议一起改)
- 61 个只作用于接缝的转场模板放在第 1 镜(index 0)时会被接受,但完全不起作用(实测 framemd5 和基线完全相同)。这和 transition_in 在第 1 镜被忽略的行为一致。建议 PATCH/PUT 对 shot_index 0 的纯转场模板返回 422,或者在响应里给出警告。
- `longvideo_orchestrator.py:1086` 的"统一规格硬切"兜底路径现在也传了 `shot_specs=_full_specs`,所以 spec 的转场/模板滤镜会重新进入兜底路径,`transition="cut"` 会被 seam_transitions 覆盖。如果第一次失败就是 spec 滤镜引起的,兜底也会再失败。建议兜底路径不传 spec,或者只保留 duration/effect。
- 已经知道:编码后成片的 framemd5 受 x264 码控影响,差异会从接缝前约 0.13–0.27s 开始,一直延续到后面的镜头。所以"其它镜逐帧相同"建议改用 SSIM 判断(实测镜0 1.000、镜2 0.990),不要用 md5。

遵守 SHOTSPEC_TASK.md 的禁改清单(`hevi/fx/*`、`xfade_transitions.py`、dirstyle、style_presets 等)。所有 python 都设 `PYTHONPATH=$(pwd)`。不要 push。
完成后在 SHOTSPEC_DONE.md 末尾写 R3 的验收证据,最后一行写 `DONE SHOTSPEC-R3`,然后 commit。

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；所有 python 设 PYTHONPATH=/data/soffy/projects/hevi-shotspec；不 push；不调付费 API；不要把 lint 日志提交进仓库。完成后在 SHOTSPEC_DONE.md 最后一行写 DONE SHOTSPEC-R3。
