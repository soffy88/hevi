# HEVI-EXEC-01: C-P0 + V-P0 执行任务书(CC 入口文档)

- **给谁**: Claude Code(FULL AUTO)
- **依据**: HEVI-SPEC-02(电影级管线)、HEVI-SPEC-03(资产库)。SPEC-01 已落地,本任务书不涉及,但可复用其 L0-L2 产物与 orchestrator 基础设施
- **目标**: 「智伯索地」一场戏(animated 分支,5 镜头)全自动直出,踩在 vault 上跑
- **总原则**: 遇到问题直接定位并修复,不要停下来要求人工提供诊断输出;只有 §0 清单中的事项允许升级为人工决策

---

## 0. 前置决策(需 soffy 确认后 CC 才能开始,共 5 项)

| # | 决策项 | 选项/默认建议 |
|---|---|---|
| 1 | 视频生成平台账号与 API key | 首选 Vidu API(animated 主通道);备选 fal.ai(聚合 Kling/HappyHorse,一个 key 多通道)。至少开通一个 |
| 2 | 单 run 预算熔断线 | 默认 $20(C-P0 只有 5 镜头,足够) |
| 3 | TTS 通道 | 默认本地 CosyVoice 2;若本地部署超 1 天则临时切云 TTS,不阻塞主线 |
| 4 | 首战章节文本 | 《资治通鉴·周纪一》智伯索地段落,由 soffy 提供原文或确认 CC 自行取用已有 Mneme 语料 |
| 5 | human_gate | C-P0 默认 draft_review(soffy 看 Draft 遍结果 15 分钟),验证 LLM 导演审之前先有人工基线 |

---

## 1. 执行顺序(严格串行的四个里程碑)

### M1: Vault 骨架(V-P0,预计 1-2 天)
1. docker compose 增加 `hevi-vault`(MinIO),建桶:vault-identity/style/scene/audio/derived
2. PG 执行 SPEC-03 §3 全部 DDL;安装 pgvector 扩展并建 HNSW 索引
3. 实现三个 oskill:`asset_resolve` / `asset_create` / `asset_verify`(SPEC-03 §6 签名);manifest JSON Schema 校验器
4. 血缘落库钩子接入 orchestrator
- **验收**: 手工放入一个假资产包 → resolve 取回、verify 跑通 embedding 比对、lineage 有记录;MinIO 对象名 = 文件 sha256

### M2: 身份包管线(SPEC-02 §2 + §11.1,预计 2-3 天)
1. 实现身份包构建流:权威像 → 九宫格 + 动作姿势参考 → 5s 转身视频 → CosyVoice 声纹 → anime embedding 提取
2. 实现稳定性预检(3 取 2)作为 `asset_promote` 的门
3. 为智伯、韩康子、段规三个角色构建 animated@guofeng-ink 身份包并 promote 至 validated
- **验收**: 三个身份包 lifecycle=validated,manifest 含 stability_check.passed=true;PACK.md 有构建记录
- **红线**: shot prompt lint 规则(身份词禁入 prompt)在本里程碑一并实现并加单测

### M3: 场景生成闭环(SPEC-02 §4-§5 最小版,预计 3-4 天)
1. C2.5 场景化改编:只实现单场景(SC「智伯索地」),dialogue 锁 quotes 表红线 + CG2.5 门(动作不改因果)
2. C4 分镜:5 镜头(建立镜头 + 智伯正打 ×2 + 韩康子反打 + 段规反应),硬规则全部生效(one clean face、≤6s、≤2 短句、正反打拆分)
3. C6 单通道打通(Vidu Q3 Reference-to-Video):asset_resolve 取身份包 → 生成 → CG6 门(embedding 距离 + ASR 台词 diff + VLM 穿帮)→ 重roll/降级链
4. 平台绑定注册表最小版:Vidu My References 懒同步
- **验收**: 5 镜头全部产出过审 clip;故意注入一个错误参考验证 CG6 能拦截;每个 clip 在 vault_lineage 有完整血缘

### M4: 拼装与复盘(预计 1-2 天)
1. C8 最小版:5 clip + 旁白桥接 TTS + 一首曲库 BGM → EDL 拼装 → 30-45s 成片
2. 输出复盘报告:各门通过率、roll 率、每镜头成本、总成本 vs 预算、身份 embedding 距离分布 → 数据回写 SPEC-02 §7 的估算表
- **验收**: 成片可播,soffy draft_review 通过;复盘报告落盘

---

## 2. CC 执行红线(继承全项目惯例 + 本项目特有)

1. 服务层零业务逻辑;所有判断在 oskill/omodul
2. 部署更新必须 `docker compose up -d --build`,禁止 stop/start
3. dialogue 文本只准改写自 chapter_ir.quotes,任何情况下不得原创台词
4. 身份描述词禁止进入 shot prompt(lint 强制)
5. 每次外部 API 调用前检查预算熔断计数器;超线自动降级,不询问
6. 禁止在 Sora 2 通道上写任何代码
7. 所有生成资产必须经 vault 落库,禁止散落临时目录成为事实依赖

## 3. 里程碑间的升级条件(仅以下情况暂停并报告)

- M2 稳定性预检连续 3 个角色都无法 3 取 2 通过 → 报告并附失败样本(可能是模型选型问题,需人工换通道决策)
- M3 中文口型/台词 CER 在 Vidu 通道系统性超标 → 报告实测数据,建议切换通道方案
- 预算熔断触发 2 次 → 报告成本结构分析

---

## 4. 模型路由(双侧)

### 4.1 CC 编码侧(按里程碑配置,`/model` 切换)

| 里程碑 | 默认模型 | 理由 |
|---|---|---|
| M1 Vault 骨架 | Haiku 4.5 | DDL/MinIO 配置/schema 校验器/单测,规格已在 SPEC-03 写死,机械执行 |
| M2 身份包管线 | Sonnet 4.6 | 外部生成 API 集成、稳定性预检状态机、embedding 提取,集成复杂度高 |
| M3 场景闭环 | Sonnet 4.6 | CG 门重roll/降级状态机、四方联动调试(MinIO/PG/GPU/外部 API),全项目最易出隐性 bug 处 |
| M4 拼装复盘 | Haiku 4.5 | ffmpeg 规则拼装 + 报告生成,确定性任务 |
| 架构级 bug(跨里程碑设计冲突) | Opus 4.8(单会话) | 仅限如"血缘落库与断点续跑相互打架"类设计层问题,解决即切回 |

配套纪律:任务切小、里程碑间 `/clear`;Haiku 产出的代码在进入下一里程碑前由 Sonnet 会话做一次 spec 一致性 review(成本远低于返工)。

### 4.2 管线运行时侧(llm_call 分级,写入 orchestrator 配置)

| 级别 | 调用点 | 模型 |
|---|---|---|
| 质量命门 | G2 史实门、L2 剧本、C2.5 场景改编、LLM 导演审(Draft 遍) | claude-sonnet-4-6 |
| 中等判断 | L0 事件抽取、L1 宪法生成、C4 分镜语言规划 | claude-sonnet-4-6(量产期可试降 Haiku 并 A/B 良品率) |
| 轻量门/分类 | G0 抽查、G1 引用闭环、禁则词扫描、音效关键词匹配 | claude-haiku-4-5 |

原则:模型路由与视频通道路由同构——orchestrator 配置化,按调用点属性选模型,不在代码中硬编码模型名;量产 294 卷前以 C-P0/C-P1 实测数据为依据逐点下调,目标将单支 LLM 成本压缩 50% 以上。
