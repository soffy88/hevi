---
name: hevi-media
version: "0.1.0"
description: Media OS for hevi — resolve any media need (bgm, sfx, image, icon, logo, voice, grade, lut, video) into a frozen local file + ledger record; reuse across projects. One verb: resolve.
argument-hint: "resolve --type <t> --intent \"<描述>\""
allowed-tools: Bash, Read
homepage: https://github.com/helios-plat/hevi
license: MIT
user-invocable: true
---

# /hevi-media

媒体台账技能：任何媒体需求都归一为一个 `resolve` 动词，产出**冻结的本地文件路径 + 台账记录**。复用优先，供应链依次为：本地库 → 素材检索 → 生成。核心引擎为 `hevi/sourcing/media_use.py`。

## 前置

`HEVI_ROOT` 指向 hevi 仓库根目录（见 hevi-watch）。调用前确认该目录存在，并优先使用项目已有的 ledger；不要为同一项目随意创建多个台账。

## 调用

```bash
cd "$HEVI_ROOT" && uv run python -m hevi.skills.media_cli resolve \
  --type bgm --intent "温暖背景钢琴" [--ledger <path>]
```

`--type` 必须是：`bgm` / `sfx` / `image` / `icon` / `logo` / `voice` / `grade` / `lut` / `video`。

## 执行流程

1. 将用户需求压缩为明确、可检索的 intent；保留语言、情绪、时长、尺寸、格式、版权或风格等关键约束，不擅自放宽约束。
2. 先用现有 ledger 按 `type + intent` 复用；命中时不得重复下载或生成。
3. 按本地库 → stock → generate 选择已配置且适合该类型的 provider。CLI 缺省为空 provider 链是正常的；不可凭空声称已检索或生成。需要组装 provider 时，调用 `hevi.sourcing.media_use.resolve_media`，而不是绕过台账自行保存结果。
4. 执行 `resolve` 后核验：文件路径存在、位于允许的本地输出位置、文件可读且与请求类型匹配；同时保留台账记录。必要时读取项目实现确认实际输出字段。
5. 只向上游返回冻结本地文件路径、类型和台账记录（或其路径）；不要返回搜索结果 URL 作为交付物。

## 真实 provider 链

| kind | hevi 现有零件 |
|---|---|
| local | `hevi.audio_library`（BGM/SFX 库） |
| stock | `hevi.sourcing.stock_search` / `browser_broll`（Pexels 等） |
| generate | edge-tts（voice）/ TTS 音乐 / 图生成 |
| grade / lut | `hevi.motion.color_grade`（预设、`.cube` 校验） |

台账 JSON 落盘后，后续带同一 `--ledger` 的相同 `type + intent` 应优先命中 reuse。冻结意味着交付文件不可依赖远程 URL；若 provider 只给 URL，必须先下载并登记本地副本。

## 失败纪律

- 找不到合适素材、provider 未配置、下载失败或校验失败时，明确报告失败原因和缺失条件；不得假装成功、返回未验证路径或把 URL 当作文件。
- 若约束互相冲突，先说明冲突；可调整时只提出最小的 intent 修改或 provider 切换建议。
- 不覆盖已有冻结文件；需要新版本时生成新的台账记录并保持旧记录可复用。