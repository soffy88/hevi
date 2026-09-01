---
name: ai-short-drama-screenwriter
version: "0.1.0"
description: 编写或修订中文短剧单集剧本；输出 script-only Markdown/JSON，并在交接前做场景、人物和可拍性检查，不生成分镜或视频提示词。
argument-hint: "--premise <梗概> [--raw-text <原文>]"
allowed-tools: Bash, Read
homepage: https://github.com/soffy88/hevi
license: MIT
user-invocable: true
---

# /ai-short-drama-screenwriter

短剧编剧入口：把创作简报或作者原文变成一份可表演、可拍摄的单集剧本。
本技能只负责剧本和剧本审核；审核通过后才把结果交给 storyboard/video-prompts。

## 调用

```bash
cd "$HEVI_ROOT" && uv run python -m hevi.skills.shortdrama_screenwriter_cli \
  --premise "一个外卖员发现订单地址是自己失踪多年的家" \
  --title "地址" --out-dir .hevi_shortdrama
```

也可直接调用 HTTP：`POST /api/shortdrama/writer/draft`，再用
`POST /api/shortdrama/writer/review` 审核保存后的 screenplay JSON。

## 工作流

1. 锁定本集承诺、主角当前目标、阻力、当集回报和退出状态。
2. 形成“因为 → 行动 → 结果 → 下一股压力”，只保留改变信息、关系、风险或物理状态的场景。
3. 用 `INT/EXT · 地点 · 时间` 场景标题区分动作、旁白和对白；对白保持人物争取、回避、试探或施压。
4. 每个场景至少有一个可拍动作或明确的叙述事实；人物出场表与对白人物保持一致。
5. 运行 review，查看缺地点、无可拍动作、静场和人物未列出等 findings。
6. script-only 请求不得输出 shot list、视频 prompt、素材 URL 或已经渲染的成片。

## 交接契约

输出包含：`screenplay`、`markdown`、`review` 和 `scope=script-only`。
只有 `review.passed=true` 才建议交给 storyboard/video-prompts；所有输入未提供的地点、外观、道具
或情节必须标为“待定”，不能擅自补造关键事实。
