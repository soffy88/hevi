# STORYPLAN-VFY1 独立核验报告

**核验对象**: 提交 `755888f8`（DONE STORYPLAN-R1，分支 `feat/story-plan`）
**核验者**: 独立核验员（只读 + 自写反例，不改源码）
**核验日期**: 2026-10-15
**核验方法**: 逐项独立复测 `STORYPLAN_TASK.md` 验收项；运行项目自带 pytest；运行 `scripts/ci/run_3o_v3_lint.py` 比对 `lint_baseline.txt`；自写反例脚本 `audit/storyplan/verify_r1/counter.py`；对 `STORYPLAN_DONE.md` / `REPORT.json` 中的数字**不轻信，全部重算**。

```
VERDICT: FAIL
```

---

## 一、验收项逐条复测（对照 STORYPLAN_TASK.md 交付 A–H）

| 项 | 验收点 | 结论 | 说明 |
|---|---|---|---|
| A | 三层数据模型（叙事/镜头/时间线）JSON schema + pydantic | PASS | `hevi/storyplan/model.py` 字段齐全、枚举校验生效 |
| B | 一句话自动补全，产物随主题变化 | FAIL | 预设主题（水/熊）有专属文案；但非动物主题（小树/早睡/太空）剔除主题名后是**同一模板换名字**（见 h） |
| C | story_check 七大门禁 | FAIL | C1–C5、C6 头/尾黑场有效；但 C5 闭环可被 6 个无关字绕过、C6 漏判「空时间线/缺轨/字幕超语音区间」（见 d2,e3,e4） |
| D | take_select 帧打分选最优 | PARTIAL | 按时长真选最优、给理由、非固定首条（g PASS）；但**未实现规格要求的帧差/SSIM 运动完整度评分**，仅按时长打分（g3） |
| E | 审片 HTML（分镜表+多轨+验收+in/out） | PASS | `export.py` 产出单文件 HTML，pytest 已断言 `<html` 与「结构自检门」 |
| F | 能力注册 story_plan/story_check/take_select 且可被 API/DirectorBrief 调用 | FAIL | 模块内 `_REGISTRY` 已注册三者；但**统一目录 `hevi/production/capabilities.py`(GET /api/capabilities 真相源)未收录**，`/story-plan` 路由**未挂载**到 `app.include_router`，对外不可调用（见 i） |
| G | 样片（≥2 支 6–20s 1080p、CPU 渲染、sha256、对照基线） | FAIL | worktree 内**无任何 mp4/png 成片**；`audit/storyplan/REPORT.json` 仅含元数据，无媒体产物，ffprobe/sha256/sheet 无从核验（见第五节） |
| H | pytest 真实运行 + 3O lint ≤ 基线 4 | PASS | pytest 7 passed；lint 失败集合与 `lint_baseline.txt` **完全一致**（4 项，无新增） |

---

## 二、pytest 实测

```bash
JWT_SECRET=test-only PYTHONPATH=/data/soffy/projects/hevi-storyplan TMPDIR=.tmp \
  /data/soffy/projects/hevi/.venv/bin/python -m pytest tests/test_storyplan.py -q
# 结果：7 passed
```
测试数 = **7**（与 `STORYPLAN_DONE.md` 声称一致，但系独立重跑确认，非采信报告）。

## 三、3O lint 基线比对

```bash
/data/soffy/projects/hevi/.venv/bin/python scripts/ci/run_3o_v3_lint.py
# 失败项：check_no_sibling_call.py, check_omodul_signature.py, check_enabled_pillars.py, check_oprim_keyword_only.py
```
当前失败集合 = `lint_baseline.txt` 基线 **4 项，完全吻合，零新增**。✅

---

## 四、反例脚本 `audit/storyplan/verify_r1/counter.py` 结果（21 项）

脚本独立构造反例，逐条断言 story_check 行为。结论：`PASS 15 / FAIL 6`，证据见 `counter_results.json`。

| 反例 | 期望 | 实测 | 结论 |
|---|---|---|---|
| a1 无钩子文本 | 拒 | C1=FAIL | PASS |
| a2 钩子晚于窗口(start 6s) | 拒 | C1=FAIL | PASS |
| a3 钩子 start 800ms（前置门禁） | 拒 | C1=FAIL | PASS |
| b1 镜头缺 sound/acceptance | 拒 | C2=FAIL | PASS |
| b2 动作无结束状态(end_state 空) | 拒 | C2=FAIL | PASS |
| c 幼儿语速 40 字/秒(>3.5) | 拒 | C4=FAIL | PASS |
| d1 结尾完全缺失 | 拒 | C5=FAIL | PASS |
| **d2 结尾与钩子零重叠(仅 6 字)** | **拒** | **C5=PASS 被放过** | **FAIL（C5 宽松 `len>5` 漏洞）** |
| e1 视频轨首段留白(黑场) | 拒 | C6=FAIL | PASS |
| e2 视频轨尾部未铺满(黑场) | 拒 | C6=FAIL | PASS |
| **e3 全部时间线轨缺失(空 timeline)** | **拒** | **C6=PASS 被放过** | **FAIL（C6 不查空时间线）** |
| **e4 字幕超出对应语音区间** | **拒** | **C6=PASS 被放过** | **FAIL（C6 不查越界）** |
| **f 15 条有害/惊吓幼儿文本(揍/踢/勒脖子/踹飞/鞭打/毒药/炸弹/陌生人/辱骂/鬼怪/血…)** | **全拒** | **15/15 拒**(其中 C7 漏判 5 条"揍/踢/勒脖子/踹飞/鞭打"，靠其它门兜底) | **PASS（但 C7 词表有缺口，见 FIX）** |
| f 10 条正常幼儿句(开门/打招呼/打扫…) | 不误杀 | 误杀 0/10 | PASS |
| g take_select 多候选(3.1/5.0/9.5s) 选最优 | 非固定首条 | 选 t_target(5.0s) | PASS |
| g2 并列(同信号) 确定性回退 | 不随机 | best=t_last 确定性 | PASS |
| **g3 帧级缺陷(完整 vs 冻结同 5s)** | 应选完整 | **同分 96.1**（仅看时长） | **FAIL（偏离规格 D 帧打分）** |
| h 5 主题(含非动物)产物随主题变化 | 非模板换名 | 非预设主题剔除名后**同模板** | **FAIL** |
| i 能力注册 story_plan/story_check/take_select | 在 registry | 模块 `_REGISTRY` 含三者 | PASS（模块级） |
| **i GET /api/capabilities 含三者 + 路由挂载** | 可被调用 | **统一 catalog 未含；/story-plan 未挂载** | **FAIL** |
| j grep mock/placeholder/dummy/fake/passed=True 硬写 | 无渲染硬写 | 仅 1 处 `dummy.mp4` 默认回退参数 | PASS |

> 注：C7 词表对"揍他/踢一脚/勒脖子/踹飞/鞭打"未命中（无对应词），仅靠其它门（如 C5 零重叠）兜底拒绝；"流血/拿刀/开枪/恐怖故事/吓死人"命中。属安全词表缺口。

---

## 五、样片核验（任务 5）

- worktree 内 `git ls-files` 与磁盘搜索均**无任何 `*.mp4`/`*.png`/`*.jpg` 成片产物**（storyplan 相关）。
- `audit/storyplan/REPORT.json` 仅含 `duration_sec` 与 check 结果等**元数据**，无实际媒体文件，亦无 `sha256`。
- 因此：ffprobe 时长/分辨率/音轨、**sha256**、抽 6 帧 `sheet.jpg`、**看图确认画面真实** —— **均无法执行**（无成片）。
- `STORYPLAN_DONE.md` 与 `REPORT.md` 声称「样片 1/样片 2/ take_select 演示」，但**无媒体产物可佐证**；其自检结论（规划版 PASS、基线 FAIL）已由本核验独立重跑 `autofill_story_plan` + `run_story_check` 复现为真，但"成片渲染"部分不可核验，按任务要求判定 **G 项 FAIL**。

---

## 六、可复现问题与反例输入（详见 `STORYPLAN_FIX.md`）

1. **C5 闭环门可被绕过**：`closing_response="随便写六个字"`（与钩子零语义重叠）仍 PASS → 应改为语义重叠校验。
2. **C6 时间线门漏判**：(a) 全部轨缺失、`duration_ms` 巨大也 PASS；(b) 字幕 clip 超出对应语音区间不查。应补「轨存在性 + 各 clip 不越界 + subtitle⊆voice 区间」校验。
3. **C7 内容安全词表缺口**："揍/踢/勒脖子/踹飞/鞭打/毒药/炸弹"等未覆盖（靠其它门兜底）。应补齐。
4. **autofill 非预设主题模板化**（`h`）：小树/早睡/太空等只换主题名， narration 与 shot 文案完全一致 → 不满足"随主题变化"。
5. **take_select 未按规格 D 帧打分**：仅按 `duration_sec` 评分，缺失运动完整度(开始→结束状态到达)/首尾稳定/突变闪烁形变(帧差+SSIM)，无法区分破损镜头与完整镜头。
6. **能力未接入统一目录与 API**：`hevi/storyplan/capabilities.py` 自建 `_REGISTRY` 未并入 `hevi/production/capabilities.py`，且 `hevi/storyplan/api.py` 的 `/story-plan` 路由**未** `include_router` 到主 app → GET /api/capabilities 查不到、接口外部不可调用。
7. **样片缺失**：未提交任何 mp4/png 成片与 sha256，R1「样片」声明不可核验。

---

## 七、结论

`755888f8` 的三层结构、模型、story_check 主门禁、take_select 选型、审片 HTML、pytest(7)、3O lint(≤基线) 均真实成立、可复现，**无 mock 渲染/自检/选段硬写**。
但存在 4 类功能性缺口（闭环门绕过、时间线越界漏判、安全词表缺口、非预设主题模板化、take_select 未帧打分）与 2 类集成缺口（能力未进统一目录/路由、样片无产物），且样片声明不可核验。综合判定 **VERDICT: FAIL**，详见 `STORYPLAN_FIX.md`。
