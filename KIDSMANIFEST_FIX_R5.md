# KIDSMANIFEST_FIX_R5.md — patrol4 独立核验发现的漏杀 / 误杀（GOLIVE-1016 A.2）

核验人：patrol4（GOLIVE_1016_TASK.md A.2）。工人自报 DONE KIDSMANIFEST-R4 **不算数**，patrol4 用自己的反例脚本重跑后判定 **FAIL**，要求 R5 修复。

核验脚本（patrol4 自写，不复用单元自带 probe）：
`/data/soffy/projects/hevi-pubfix/audit/patrol4/kidsmanifest_probe/verify_kidsmanifest_independent.py`
被测入口（真实生产路径，非 mock）：
`hevi.quality.kids_gate.check_content_safety_text`（kids gate 审字幕/对白时调用的同一函数）

## 结论：**FAIL** —— GOLIVE-1016 A.2 明确点名要求的 6 个暴力词全部漏杀，另有 2 处正常词误杀。

patrol4 反例脚本实测：`3/11 检查通过`，其中
```
[FAIL] adversarial: all 6 mandated words + synonyms blocked  12/23 blocked
[FAIL] adversarial group '勒脖子' blocked 1/3
[FAIL] adversarial group '踹飞' blocked 2/3
[FAIL] adversarial group '针扎' blocked 2/3
[FAIL] adversarial group '绑树堵嘴' blocked 0/3
[FAIL] adversarial group '鞭打' blocked 0/3
[FAIL] adversarial group '狗咬' blocked 2/3
[FAIL] benign: normal preschool words not over-blocked 13/15 clean
```

---

## P0（阻塞上线）：6 个点名暴力词全部不在规则表内

GOLIVE-1016 A.2 点名要求拦截：**勒脖子、踹飞、针扎、绑树堵嘴、鞭打、狗咬** 及其同义改写。
patrol4 直接查 `hevi/kids/data/kids_safety_rules.json` 的全部 category 词表，以下词**一个都不存在**：

| 探测词 | in_rules |
|---|---|
| 勒 / 勒脖子 / 脖子 | False |
| 踹 / 踹飞 | False |
| 针 / 针扎 | False |
| 绑 / 绑树 / 堵 / 堵嘴 | False |
| 鞭 / 鞭打 / 抽打 | False |
| 狗 / 狗咬 / 咬 / 咬住 | False |

### 实测漏杀（`check_content_safety_text` 返回空 list = 未拦截）
| 用例 | 文本 | 返回 |
|---|---|---|
| 勒脖子 | `大灰狼勒住了小兔的脖子。` | `[]` |
| 勒脖子-同义 | `坏人用手臂紧紧箍住小熊的喉咙，让他喘不过气。` | `[]` |
| 勒脖子-改写 | `小狐狸被掐住了脖子，脸都红了。` | `[]` |
| 踹飞 | `大熊一脚把小兔踹飞到墙上。` | `[]` |
| 踹飞-同义 | `他用力踢过去，小朋友整个人飞了出去。` | `[]` |
| 针扎 | `坏巫婆拿针扎小兔的手指。` | `[]` |
| 针扎-同义 | `她用尖尖的注射器刺进小熊的手臂。` | `[]` |
| 绑树堵嘴 | `坏人把小兔绑在树上，还用布堵住他的嘴。` | `[]` |
| 绑树堵嘴-同义 | `他们把小朋友捆在树干上，用毛巾塞住嘴巴不让他叫。` | `[]` |
| 绑树堵嘴-改写 | `小狐狸被绳索绑住手脚，封住了嘴，说不出话。` | `[]` |
| 鞭打 | `大灰狼用鞭子抽打小马。` | `[]` |
| 鞭打-同义 | `他举起皮带使劲抽小朋友的背。` | `[]` |
| 鞭打-改写 | `坏国王用棍子反复抽打小仆人。` | `[]` |
| 狗咬 | `大狗咬住了小兔的腿。` | `[]` |
| 狗咬-同义 | `恶犬张开嘴撕咬小朋友的手臂。` | `[]` |
| 狗咬-改写 | `那只狗用牙齿死死咬住小熊不放。` | `[]` |

**要求**：把这 6 类行为及其同义/改写（至少覆盖上表全部 18 条，以及单元自己认为合理的扩展同义词）加入 `hevi/kids/data/kids_safety_rules.json` 对应 category（建议新增 `strangulation` / `kicking` / `stabbing` / `binding_gagging` / `whipping` / `biting`，或并入现有 `violence`），使上表 **18/18 全部被拦截**。词表要能覆盖「同义改写」，不能只加 6 个原词。

## P1：2 处正常幼儿词误杀（over-blocking，会让产线不可用）

| 用例 | 文本 | 误报返回 |
|---|---|---|
| 日常-刺猬 | `小刺猬背上有苹果，真可爱。` | `['苹果']` |
| 日常-切菜 | `妈妈在厨房用刀切菜，一刀切菜真整齐。` | `['刀']` |

根因：
- `苹果` 在 `brand` 类别里（当作品牌名处理），但「苹果」在幼儿内容里首先是水果，属高频正常词 → 应从 `brand` 移除或加入白名单。
- `刀` 在 `violence` 类别里，且**不在 whitelist**；R4 加的 `一刀切菜`/`切菜` 白名单只能挡住这两个完整词，`用刀切菜` 这种「单字 刀 + 正常动词」的组配仍被误杀 → 需要补 `用刀`/`刀切` 等白名单，或对「刀 + 厨事动词」做组合豁免。

**要求**：以上 2 条不再误报；同时不得放宽导致 P0 的漏杀回归。

## 已确认 PASS 的部分（R5 不得回退）

- 直接否定不误杀：`不可以打人` / `不会下毒` / `没有带刀` 全部不报 FAIL（3/3）。
- 跨句规避被正确拦截：`小狐狸不吃药，把毒药给了小熊。` → `['毒药']`（R4 的 H3 窄否定窗口有效）。
- 血/武器硬红线仍生效：`小兔被划伤了，到处都是血。`、`小狐狸拿起刀和枪。`、`小狐狸用刀砍伤了小兔。` 均被拦截。
- 单元 pytest：`49 passed in 2.53s`；`tests/ -k "kids or shot_spec"`：`134 passed, 1 skipped, 5 xfailed`（无回归）。
- story gate 6/6 PASS（patrol4 独立构造的 3 类坏样本全部 FAIL、合规样本 PASS、输出确定性 sha256 一致）。
- content-safety 判定确定性：两次运行 sha256 一致（`2e0e2592106fb91c…`）。

## R5 验收标准（patrol4 将原样重跑）

1. P0 表中 **18/18** 漏杀用例全部被拦截。
2. P1 表中 **2/2** 误杀用例不再误报。
3. patrol4 反例脚本 `verify_kidsmanifest_independent.py` **11/11 全 PASS**。
4. 上述「已确认 PASS 的部分」全部不回退。
5. 新增/修改单测真实运行通过（禁止 mock）；`tests/test_kids_manifest.py` 全绿；`tests/ -k "kids or shot_spec"` 无新增失败。
6. 3O lint 失败数仍 ≤ 4（基线 4 项）。
7. 更新 `KIDSMANIFEST_DONE.md`，如实记录 R5 实测（命令、数字、覆盖词表），最后一行 `DONE KIDSMANIFEST-R5`。

## 安全
只在本 worktree `/data/soffy/projects/hevi-kidsmanifest` 内修改；不删 worktree 外文件；不清理磁盘；不 rm 已跟踪文件；不 push；CPU-only 离线运行；无付费 API；禁止 mock / 硬编码通过（不允许把 patrol4 的测试句子特判进代码——必须补真实的语义/词表覆盖）。
