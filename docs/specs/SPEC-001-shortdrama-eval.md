# SPEC-001 短剧/漫剧通道 · 工程量与依赖评估

> 状态:CC 评估回执 v0.2(2026-07-11)—— 三处红旗 + LLM 前置已由 soffy 拍板,见 §6。SPEC-001 可冻结进阶段 1。
> 对象:`SPEC-001 短剧/漫剧通道 草案 v0.1`
> 方法:对当前代码库实测四个子系统(director L4 / Series·Subject·StylePack / verdict·tasks·cost / tongjian·canvas),核实 spec 声称的"复用面"是否真实存在,而非采信 spec 自述。
> 结论一句话:**下游"全链复用"基本成立;上游"3 个新增件"低估工程量,且有两处事实性错误会在阶段 2 撞墙。最大机会:B0 层的 60–70% 已由 tongjian 通道实现,只是锁死在《资治通鉴》上。**

---

## 0. 总判断

Spec 口号"短剧通道 = 3 个新增件 + 全链复用":
- **"全链复用"半句成立** —— Series / StylePack / verdict / tasks / cost / canvas 都是真实、可复用的存量能力。
- **"3 个新增件"半句低估** —— 三个新增件里,B0 有现成模板可迁移(比 spec 想的省力),但剧集规划器、季级预算、跨集关系校验都有真实工程量,不是 spec 描述的"加一列/加参数"。
- **两处事实性错误(见 §2)会让阶段 2 无法过门,必须先改 spec。**

---

## 1. 复用面核实:哪些是真的(实测通过)

| Spec 声称"直接复用" | 代码实况(file:line) | 结论 |
|---|---|---|
| Series = 一部剧,episode 字段继承 | `series/series_service.py:82-162` 完整:spec_json / style_preset / subject_ids / StylePack 快照版本逐集继承,有 `tests/test_series.py` 佐证 | ✅ 真·可复用 |
| StylePack 全季锁定 + 版本 | `style/models.py:31` 有 version;`series_service.py:37-49` 建 Series 时快照锁版,`series_service.py:116-138` 逐集展开 | ✅ 真·可复用(注:是 5 字段 style/lighting/camera/color_grade/negative,非 spec 说的"三张查找表",无实质影响) |
| L3 verdict 逐镜头质检 | `verdict/scorecard.py:86-217` identity_distance + style_distance + 结构 + Tier1 VLM,落 `shot_states`(`tasks/models.py:46-61`) | ✅ 复用;加 `episode_number` 列成本极低(1 列 + result_mapper,~3 文件) |
| 任务系统 SSE/队列/resume/预留-消费-退款 | `task_service.py`:SSE(`routers/tasks.py`)、`enqueue`(:582)、`resume_task`(:402)、幂等结算 `:settle`(:281)、`FOR UPDATE SKIP LOCKED`(repository:84) | ✅ 生产级,一集=一任务成立 |
| L0 成本三层熔断 | `cost/circuit_breaker.py`:task(:19-26)/user(reserve-consume)/daily-global(:80-98) 三层 | ✅ 复用;但**无季级**(见 §3 红旗 3) |
| canvas IR 分镜图 | `canvas/graph_models.py:14-29` DAG,5 类节点 | ✅ 复用;注意它是**编排图,非分镜脚本**,措辞勿混 |

结论:这一层 spec 判断准确,可按"加参数/加一列"对待。

---

## 2. 必须修正的红旗(阻塞项)

### 🔴 红旗 1:Subject3D 不存在,且架构明确否决过它

- Spec 阶段 2 地基是"Subject3D 主角高保真档接入(依赖 v2.2 Phase 3/4)"。
- 实况:`docs/HEVI-ARCHITECTURE.md:98` 白纸黑字 **「3D 角色 | ❌否 | 接不进 2D 链路,ROI 不成立」**。
- 现有 Subject 是纯 2D:参考图 + CLIP `identity_embedding`(`subjects/models.py:22-31`,`subject_embed.py` 说明用 CLIP 而非 ArcFace,因主体多为风格化/AI 生成脸)。跨集锁定靠 `subject_id` 传 i2v,**这套是 work 的**。
- **判断**:这不是"复用",是团队已否决的高风险 R&D。**建议阶段 2 砍掉 Subject3D**,跨集身份一致性压在现有 2D CLIP identity lock 上。若坚持 3D,须单列为高风险探索项,不计入复用面。

### 🔴 红旗 2:B0 层的省力路径是泛化 tongjian,不是接 Stratum

- Spec 2.2 让 B0"复用 Stratum/AII 存量能力"(外部系统)。
- 实况:`hevi/tongjian/schemas.py` 的 `ChapterIR` 已是 StoryGraph 的近亲,且 `tongjian/chapter_ir.py:99-200` 已解决最脏的工程细节——**LLM 抽结构 + 确定性代码定位 span 偏移(从不信 LLM 报的字符位置)**,正好绕过了本仓库踩过的 local-LLM JSON 不可靠坑。

| Spec 要的 StoryGraph | tongjian 已有(`schemas.py`) | 差距 |
|---|---|---|
| characters[] + aliases + description | `CharacterIR`:canonical_name / aliases[] / role / faction / fate | ✅ 有 |
| timeline[] events + participants + beat_type | `EventIR`:actors[] / causes[] / effects[] / dramatic_weight / year | ✅ 有(dramatic_weight ≈ beat 权重) |
| 对白/情感 | `QuoteIR`:speaker / emotion | ✅ 有 |
| locations[] | `ChapterIR.locations[]` | ✅ 有 |
| relationships[] + evolution | — | ❌ 缺 |
| arcs[] 情感弧线 | — | ❌ 缺 |
| 跨章 timeline 合并 | 逐章单视频 | ❌ 缺 |

- **判断**:B0 ≈ 把 tongjian L0-L2 从"资治通鉴专用"抽象成"小说通用" + 补 `relationships[].evolution` / `arcs[]` / 跨章合并。是**扩展一个 work 的管线**,不是对着外部 Stratum 从零搭。工程量差一个数量级。

### 🔴 红旗 3:"剧集规划器 = Producer 的短剧特化"是错标签

- Spec 3.2 说规划器复用 Producer。但 `director/producer.py:38-92` 的 Producer **只做成本/可行性路由**(topic+时长档 → provider+预算),不做任何叙事规划。叙事逻辑在 `director/planner.py`/`storyboard.py`(单集)与 tongjian 的 Constitution+Script 层。
- **判断**:剧集规划器是**新的规划层**,坐在 Director 之上、消费 StoryGraph、产出 SeasonPlan,更像"tongjian Constitution 层提升到整季粒度",不是 Producer 加参数。归类成"扩展 Producer"会误导实现者改错文件。

---

## 3. 工程量分级(基于实况)

| 新增件 | 实况起点 | 工程量 | 关键风险 |
|---|---|---|---|
| B0 故事解析层 | tongjian L0-L2 ~65% 可迁移 | **中**(非大):泛化 + relationships.evolution + arcs + 跨章合并 | 长文本分卷增量合并、别名归并 |
| 剧集规划器(SeasonPlan) | 全新层,可仿 tongjian Constitution | **中大**:切集/分配节拍/执行前自我批判(spec 3.4) | 集数是否撑得起原文体量的判断 |
| 剧集看板前端 | TongjianConsole + HeviCanvas + SSE 可复用外壳;Series 无富看板 | **中**:季/集/幕/镜层级壳,镜头级以下全复用 | 纯前端组织外壳 |
| verdict 加 episode 维度 | `shot_states` 加列 | **低** | — |
| 跨集关系一致性校验(Tier0) | verdict 全新校验项,无关系元数据 | **中**:确定性版查台词称呼/关系指代 vs 图谱 | 依赖 B0 的 relationships 先建好 |
| 季级预算熔断 | 三层熔断只到 daily-global,**无季级** | **中大**:新 `series_budgets` 表 + create_task 前置校验 + Tier3 重构 | spec 6 自标为防季级烧穿的关键防线 |

注:spec "加一列 episode 维度"轻描淡写——只有 verdict 那一项是真·加列;关系校验与季级预算都是有真实工程量的新件。

---

## 4. 依赖与阻塞

1. **LLM 可靠性(阶段 1 前置)—— ✅ 已解决(2026-07-11 核实)**:原以为要充值 DashScope,实况是 registry 已有非欠费云端通路 `llm/"qwen_cloud"`(`hevi/providers/registry.py:187-205`,阿里云百炼 workspace 专属端点 `ALIBABA_MAAS_*`,凭证已在 `.env`,2026-07-10 端到端验证过)。选择方式:**逐层显式选 `qwen_cloud`**(不是设 `HEVI_LLM_PROVIDER`,`default` 仍是欠费公共端点),tongjian 已把 L0/L1/L2/L4/L5 路由到它(`routers/tongjian.py:158-162`)。B0/规划器从 tongjian 泛化时沿用即可,**零额外工作**。
2. **阶段门 G1 可达**:验收门 G1(3 集身份一致 identity_distance 达标)靠现有 2D CLIP lock 即可支撑,不需 Subject3D。
3. **阶段门 G2 依赖倒置**:G2 现挂在 Subject3D 上(红旗 1),须重写为"依赖 2D identity lock + Tier0 关系校验",否则永过不了门。

---

## 5. 建议的实现顺序修正(保留 spec 分阶段纪律,改三处)

1. **B0 重定位**:从"接 Stratum"改成"泛化 `hevi/tongjian/` L0-L2 + 补 relationships/arcs/跨章合并"。实现者从 tongjian 起步,而非 greenfield。
2. **砍 Subject3D**:阶段 2 一致性守护改压在现有 2D CLIP identity lock 上;3D 若做,单列高风险探索。
3. **剧集规划器正名**:归为"新规划层(仿 tongjian Constitution,季粒度)",不是 Producer 扩展。

修正后的**阶段 1 最小闭环**:
```
前置:打通 LLM provider(HEVI_LLM_PROVIDER=dashscope + 充值)
  → tongjian L0-L2 泛化为小说通用(StoryGraph 初版,relationships/arcs 可后置)
  → 剧集规划器切 3 集(SeasonPlan + 执行前自我批判)
  → 复用现有 Director/L1 逐集出片
  → 剧集看板只读版(复用 SSE 进度)
验收门 G1:短篇小说 → 自动切 3 集 → 逐集出片 → 角色跨 3 集身份一致(identity_distance 达标,靠 2D CLIP lock)
```

---

## 6. 冻结决策(soffy 已拍板 2026-07-11)

- [x] **红旗 1:砍 Subject3D**,阶段 2 跨集一致性压在现有 2D CLIP identity lock 上。3D 若做,单列高风险探索,不进主线、不作 G2 门槛。
- [x] **红旗 2:B0 基于 tongjian 泛化**(从 `hevi/tongjian/` ChapterIR 起步,补 relationships.evolution + arcs + 跨章合并),不接外部 Stratum。
- [x] **红旗 3:剧集规划器 = 新规划层**(仿 tongjian Constitution,季粒度,消费 StoryGraph 产出 SeasonPlan),不改 `producer.py`。
- [x] **LLM 前置:用 `qwen_cloud`**(阿里云百炼 workspace 端点,已接好线 + 已验证 + 凭证在 `.env`)。逐层显式选,零额外工作。

**SPEC-001 冻结,进入阶段 1。** 修正后的阶段 1 最小闭环见 §5。

*评估结束。*
