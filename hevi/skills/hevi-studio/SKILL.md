---
name: hevi-studio
version: "0.1.0"
description: Hevi 制片厂入口。列产线、填槽位、签发工单。历史现场 / 导演流水线 / 解说共用同一工具箱。
argument-hint: "<line-id> [--slot k=v]..."
allowed-tools: Bash, Read
homepage: https://github.com/soffy88/hevi
license: MIT
user-invocable: true
---

# /hevi-studio

把 hevi 当制片厂用:先选产线,再填槽,再排产。不要新开第四条管线。
默认只生成排产结果；明确加 `--execute` 才会执行真实渲染并校验本地产物。

## 产线

| id | 产品 | 交接 |
|---|---|---|
| `history_scene` | 历史现场 | tongjian L0–L8 |
| `director_pipeline` | 导演流水线(短剧) | shortdrama 整季派发 |
| `explainer` | 解说中心 | Remotion 装配 |
| `reference_adapt` | 参考片改编 | 先 watch 再交接解说 |
| `shorts_clip` | 拆条矩阵 | 写国内平台交接单 |
| `kinetic_promo` | 动效标题 | HyperFrames 构图 |

导演台 `/director` 是手动总控,不走本 skill 的自动排产。

## 调用

```bash
cd "$HEVI_ROOT" && uv run python -m hevi.skills.studio_cli lines
cd "$HEVI_ROOT" && uv run python -m hevi.skills.studio_cli tools
cd "$HEVI_ROOT" && uv run python -m hevi.skills.studio_cli run history_scene \
  --slot source_text="周纪一原文…" --slot source_name="三家分晋"
cd "$HEVI_ROOT" && uv run python -m hevi.skills.studio_cli run kinetic_promo --execute \
  --slot topic="新品片头" --output-dir output/studio/kinetic_promo
```

不加 `--execute` 时只做 intake / 研究 / 评分 / 脚本 / 资产 / 时间线 / 交接单,不烧 GPU。
加 `--execute` 时进入真实渲染器；只有本地文件、媒体探测、完整性和质量闸均通过才返回 `completed`。

## 工具(可单独调)

`research.plan` `research.brief` `watch.concepts` `script.quick` `material.rank`
`score.provider` `memory.remember` `memory.recall` `nle.edit_plan`
`publish.matrix` `delivery.preview` `asset.bind`

VideoAgent:`video.agent.plan` `video.agent.run` `video.evidence.index`
`video.evidence.search` `video.script.from_transcript` `video.summary` `video.qa`

HTTP:`GET /api/studio/lines` · `POST /api/studio/slates` · `GET /api/studio/tools`
VideoAgent:`POST /api/montage/video-agent/plan` · `POST /api/montage/video-agent/run`
Veya:`POST /api/studio/veya/produce` · `GET /api/studio/veya/capabilities`
日更:`POST /api/studio/daily/tick`

MCP:`hevi.produce_finished` `hevi.list_studio_lines` `hevi.tick_daily`

## 三条管线互借

通鉴 = 讲解(解说 cue) + 演绎(对白镜)。不要把能力锁在页面里。

| 能力 | 工具 | 谁可以调 |
|---|---|---|
| 看片 | `watch.video` | 通鉴 / 短剧 / 解说 |
| 史料闸 | `tongjian.l0` `tongjian.provenance` | 短剧手稿含史料时、解说 `source_text` |
| 讲解 cue | `explainer.cues` | 通鉴 mix 拆讲解段 |
| 代码画面 | `explainer.manim` | 通鉴讲解 / 短剧抽象镜 |
| 口型 | `avatar.compose` | 基础片 QC 后再叠,三线共用 |
| TTS | `tts.synth` | lux / voxcpm / edge / auto,不要各写分支 |
| 场面调度 | `director.scene_stage` | 通鉴场 / 解说多角色 |
| 一镜资产 | `shot.export` | 短剧镜可抽到解说/通鉴 |
| 配置冻结 | `profile.freeze` | AVP:SHA 不对就停 |
| 时间线重导出 | `nle.recut` | 改第三镜后 ffmpeg concat |
| 译制烧录 | `ingest.localize` | 外语源 → ASS 双语计划 |
| 拆条打分 | `clip.virality` | hook/情绪/金句,重叠去重 |
| 剪映草稿 | `nle.jianying_export` | 国内剪映可编辑交接包 |
| 风格存档 | `nle.style_archive` / `nle.style_apply` | 换素材复用剪辑风格 |

```bash
uv run python -m hevi.skills.explainer_cli "盐税" --source-text "智伯请地…"
```

## 组合纪律

- 角色/成片用 `asset.bind` / `shot.export` 登记后再跨线引用,不要复制 Subject。
- 试播时长必须过 `delivery.preview`(60–90s)。
- 国内分发走 `publish.matrix`(抖音/视频号/小红书/快手/B 站),写交接单,不假装已上传。
- `render_runtime` 在配方里锁定,禁止静默换 Remotion/ffmpeg。
