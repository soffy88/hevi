# HUOBAO 单元完成报告 (HUOBAO-R1)

吸收上游火宝短剧（chatfire-AI/huobao-drama v4.x）剧本→资产→分镜智能体层，并与 HEVI 既有架构深度对齐。

## 一、完成成果与实现模块
1. **研究调研 (`HUOBAO_EVAL.md` & `provenance-ledger.yaml`)**：
   - 逐个对比火宝 4 个 Mastra 智能体（`script_rewriter`、`extractor`、`storyboard_breaker`、`prompt_generator`）与 Hevi 原有架构。
   - 登记上游来源及 CC BY-NC-SA 4.0 许可证与 NC 限制。
2. **资产管理与跨集去重 (`hevi/huobao/assets.py`)**：
   - 实现角色（Character）、场景（Scene）、道具（Prop）三类实体管理。
   - 名字归一化与别名括号合并机制（跨集去重、同人不同称谓归一）。
   - 道具过滤三问算法（严控每集 0-3 个高价值道具）。
   - 场景强约束规则：强制剥离人物，生成纯背景空镜提示词。
3. **资产参考图与分镜一致性渲染 (`hevi/huobao/keyframes.py` & `refs.py`)**：
   - 纯 CPU 运行，使用本地 SD-Turbo + 国风动漫 `guofeng_anime` 预设，为资产生成标准参考图并分配确定性 seed。
   - 分镜提示词全面支持 `@角色`、`@场景`、`@道具` 引用语法；未知引用触发严格的 `UnknownAssetReferenceError` 异常防御。
4. **小说改写与台词保留守卫 (`hevi/huobao/rewrite.py`)**：
   - 支持语气选择（悬疑、快节奏爽剧、古风沉浸、虐恋深情、诙谐幽默）。
   - 继承 dramaplan r6 逐字台词保留机制（100% 校验原著对白未丢失）。
5. **工作台与 API 增强 (`hevi/huobao/batch.py` & `hevi/api/routers/huobao.py`)**：
   - 批量生成前预估（镜头数、总片长、CPU 耗时预估）。
   - 失败镜头选择性重试（只重跑状态为 failed 的镜头）。
   - 合并前置文件存在性与大小校验（`validate_merge_prerequisites`）。
6. **能力契约注册 (`hevi/capabilities/registry.py` & `hevi/huobao/capabilities.py`)**：
   - 按 CAPABILITY_CONTRACT.md 实现统一能力注册表。
   - 注册并向外发布本线全部能力名。

## 二、本线注册的全部能力名
- `huobao.character_ref` (kind: shot, aspects: 16:9 / 9:16)
- `huobao.scene_ref` (kind: shot, aspects: 16:9 / 9:16)
- `huobao.shot` (kind: shot, aspects: 16:9 / 9:16)

## 三、测试覆盖
- 运行 `pytest tests/test_huobao.py` 与 `tests/test_capabilities.py`，资产去重、@引用解析、台词保留、重试、合并前校验及产物依赖完整通过。

DONE HUOBAO-R1
