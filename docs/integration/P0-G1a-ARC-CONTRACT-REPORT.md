# P0 G1a 对拍记录 —— §8 契约 → tongjian 消费路径（2026-08-07）

> 承 `stratum/docs/history/AII-HISTORY-KU-SPEC-001.md` §8.4（契约先行）与
> `HISTORY-TEXTBOOK-MAINLINE-CC-SPEC-001.md` P0。本文是生产端 G1a 验证记录；
> G1b（真实 KU 实装后逐字段对拍）以 `contracts/sample.sanjiafenjin.json` 为基准。

## 1. 契约输入

| 字段 | 值 |
|---|---|
| contract_version | v0.1 |
| event | ev:jinyang-zhizhan 晋阳之战（智伯之亡）|
| accounts | 3（史记·赵世家 主述 / 资治通鉴·周纪一 并陈 / 战国策·赵策一 并陈）|
| conflicts | 1（cf:jinyang-independence，presentation_hint=主线+角标，独立见证 1.5）|
| registry_bundle | persons 4（智伯/赵襄子/韩康子/魏桓子）+ 地名/纪年 |

## 2. 组装（hevi/history_series/arc_adapter.py）

```
source_name : 历史现场·晋阳之战（智伯之亡）
raw_text(748字):
  主述 史记·赵世家原文（知伯益驕…盡并其地）（史记·赵世家 主述）
  （并陈）《资治通鉴·周纪一》智伯請地於韓康子…
  （并陈）《战国策·赵策一》知伯帥趙、韓、魏…
  [并陈角标] 三 account 非三重独立见证…实计约 1.5 独立见证…
layer_config.L1 : character_refs[4]（person_ref → names_by_source 别名）
```

6 个单测全过（tests/test_history_arc_adapter.py）：主述选择 / 并陈出处 / 冲突角标 / registry 注入 / 教材主述覆盖（D5）/ G1a 报告。

## 3. tongjian 消费结果（run 1a78ff86，pause_after=L2 验证）

| 层 | 结果 | 说明 |
|---|---|---|
| L0 章节理解 | **PASSED** | 文言 raw_text → ChapterIR，G0 门过 |
| L1 角色/立意 | **PASSED** | 角色推演；C003 缺档案降级提示（后续 character_sim 生成）|
| L2 剧本 | **DEGRADED** | 477 字 vs 目标 937 偏差 49%（本地 qwen3-8b 偏短）；非阻塞门禁哲学 → 到审核点 AWAITING_REVIEW |

剧本质量：18 行（旁白+对白），引语 Q04-Q08 带出处，角色齐全（智伯/韩康子/魏桓子/赵襄子/张孟谈），
constitution 完整（thesis「智伯之患，六君子的悲歌」+ logline + visual_style + act_structure）。

## 4. G1a 结论

- **消费路径跑通**：§8 契约（同形数据）→ arc_adapter → tongjian L0-L2 全消费正常；
  主述/并陈/角标/registry 全部落到剧本与 constitution。
- **待 G1b**：语料层 KU 实装后，逐字段对拍（para_ulid 从 null → 段落级 ULID 即「差异可解释」）；
  L2 字数偏差属 LLM 侧（opencode 或调参），非契约问题。
- **教材主述（D5）**：textbook_text 注入路径已实现并单测（主述=教材、古籍全并陈）；
  教材 KU 实装后接真实文本。

## 5. 出片验证（P0 退出条件 ✅ 2026-08-07 达成）

run `4c3e7502`（layer_config L0/L1/L2=opencode + HEVI_AUDIO_PROVIDER=edge_tts）全跑：

| 层 | 结果 |
|---|---|
| L0/L1 | PASSED |
| L2 | DEGRADED（172 字 vs 459，中文键兼容后已出剧本；非阻塞）|
| L3 配音 | PASSED（edge-tts 本机；容器 cosyvoice 不可达时经 HEVI_AUDIO_PROVIDER 切）|
| L4 分镜 / L5 角色卡 | PASSED |
| L6 渲染 | PASSED（SDXL worker 不可用 → 降级链静帧+推拉兜底，不开天窗）|
| L7 音乐 / L8 装配 | PASSED |

**成片**：`output/tongjian/4c3e7502…/L8/final.mp4`（40.4s / 832x480 / 24fps / 11 镜头）
**veya video_sandbox 质检：passed=True**（duration 40.4s / has_audio / black_ratio 0.0 / loudness -24.0 LUFS）

### 途中修复（P0 实证）
1. **L8 `hotwords` NameError**：`_run_render_layers` 续跑段作用域独立，从 chapter_ir 重建热词（已修）。
2. **deepseek 中文键输出 → 空剧本**：script.py `_coerce_script` 兼容 `{"旁白":[…],"对白":[…]}` 中文键 + 类型/行内字段归一（新增单测）。
3. **L3 空音频**：宿主 cosyvoice（gen-engine 容器）不可达 → `HEVI_AUDIO_PROVIDER=edge_tts` 切本机配音。
4. **SDXL 渲染不可用** → 既有降级链（场景空镜/静帧+推拉）兜底，仍出片。

### G1a 结论（终）
§8 契约（同形数据）→ arc_adapter → tongjian L0-L8 全链路出片通过质检；
待 G1b：语料层 KU 实装后逐字段对拍（para_ulid null → ULID 即差异可解释）。
