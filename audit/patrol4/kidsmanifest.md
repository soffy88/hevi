# PATROL4 独立核验 — kidsmanifest（GOLIVE-1016 A.2）

核验人：patrol4（不是工人自报，全部用自己的反例脚本重跑）
核验脚本：`audit/patrol4/kidsmanifest_probe/verify_kidsmanifest_independent.py`、`verify_story_gate.py`（patrol4 自写，不复用单元自带 probe）
单元：`/data/soffy/projects/hevi-kidsmanifest`，分支 `feat/kids-manifest`，HEAD `3b2809c0`（DONE KIDSMANIFEST-R5）

## 结论：**PASS**（经 R4 FAIL → R5 修复后，patrol4 用自己的反例脚本原样重跑，`11/11` 全 PASS）

> 流程记录：patrol4 首轮核验工人自报的 `ca6408a3`（DONE KIDSMANIFEST-R4）判定 **FAIL**（3/11），
> 写了 `KIDSMANIFEST_FIX_R5.md`（commit `1c8d0f49`）并用 `/data/soffy/pi_loop_fix.sh` 起 R5
> （systemd-run --user，MemoryMax=4G）。R5 产出 `69eb678e` / `f19037e9` / `3b2809c0`。
> 工人自报 PASS 不算数 —— 以下全部是 patrol4 重跑结果。

## 证据数字

### 1. 暴力词反例（R4 的 FAIL 项，R5 后复测）
被测入口：`hevi.quality.kids_gate.check_content_safety_text`（生产真实路径）

**R4（修复前）**：`3/11`，6 个点名暴力词全部漏杀。
**R5（修复后，patrol4 重跑）**：
```
[PASS] adversarial: all 6 mandated words + synonyms blocked  23/23 blocked
[PASS] adversarial group '勒脖子' blocked 3/3
[PASS] adversarial group '踹飞' blocked 3/3
[PASS] adversarial group '针扎' blocked 3/3
[PASS] adversarial group '绑树堵嘴' blocked 3/3
[PASS] adversarial group '鞭打' blocked 3/3
[PASS] adversarial group '狗咬' blocked 3/3
```
（6 组点名词各 3 条（原句/同义/改写）共 18 条 + 血/刀枪/毒药/炸弹/死 5 条硬红线 = 23 条，`23/23 blocked`，
逐组均 `3/3`。例如狗咬组三条分别命中：`大狗咬住了小兔的腿。`→`['咬','咬住']`、
`恶犬张开嘴撕咬小朋友的手臂。`→`['咬','恶犬','撕咬']`、`那只狗用牙齿死死咬住小熊不放。`→`['咬','咬住','死']`。）

### 2. 正常幼儿词不误杀（R4 有 2 处 FP，R5 后复测）
```
[PASS] benign: normal preschool words not over-blocked 15/15 clean
[PASS] benign: direct negation not over-blocked all 3 clear
```
R4 的 2 处误杀已消除：`小刺猬背上有苹果，真可爱。`（原误报 `['苹果']`）、`妈妈在厨房用刀切菜，一刀切菜真整齐。`（原误报 `['刀']`）均不再误报。

### 3. 跨句规避拦截（PASS）
`小狐狸不吃药，把毒药给了小熊。` → `['毒药']`（H3 窄否定窗口未回退）。

### 4. story gate（PASS，6/6）
patrol4 独立构造样本，走真实 `kids_story_gate`：
```
[PASS] story gate: compliant -> must PASS           got=PASS  causal_ratio=0.8  fails=[]
[PASS] story gate: all AND-THEN -> must FAIL        got=FAIL  causal_ratio=0.0  fails=[R3_CAUSAL_RATIO, R4_ADJACENT_EMOTION x4, R9_FAREWELL_QUESTION, R5_RECAP_THEME]
[PASS] story gate: adjacent same emotion -> FAIL    got=FAIL  fails=[R4_ADJACENT_EMOTION x3]
[PASS] story gate: missing theme -> FAIL            got=FAIL  fails=[R5_SINGLE_THEME, R5_RECAP_THEME]
[PASS] story gate: missing fixed character -> FAIL  got=FAIL  fails=[R6_FIXED_CHARACTER]
[PASS] story gate: deterministic (2 runs identical sha256) 0c8418b63fbc9fa8
```
任务要求的 3 类坏样本全部正确 FAIL，合规样本正确 PASS，输出确定性一致。

### 5. 判定确定性（PASS）
content-safety 判定两次运行 sha256 一致：`d443053f9f8b26e74c4c568b…` == `d443053f9f8b26e74c4c568b…`

### 6. pytest（patrol4 实测）
```
$ pytest tests/test_kids_manifest.py tests/test_kids_gate.py -q
101 passed in 4.93s
```
（R4 时为 `49 passed`；R5 新增 52 项覆盖 6 组暴力词 + 同义 + 误杀回归。）

### 7. 3O lint
```
3O_V3_LINT=FAIL
failed: check_no_sibling_call.py, check_omodul_signature.py,
        check_enabled_pillars.py, check_oprim_keyword_only.py
```
**失败项 4 = 基线 4**，无新增，满足 ≤4。

### 8. 反硬编码核查（patrol4 额外做的泛化测试）
FIX_R5 明确禁止「把 patrol4 的测试句子特判进代码」。patrol4 核查 R5 的代码改动
（`69eb678e`：`hevi/kids/data/kids_safety_rules.json` +468 行词表，`hevi/quality/kids_gate.py` +63 行机制）：
- 改动是**真实词表扩充 + 分句上下文机制**，不是对 patrol4 句子的特判。
- 用 patrol4 **从未写过**的 8 条新反例复测，5/8 命中（`绳子套住喉咙`→`['不能呼吸','喉咙']`、
  `一脚踢下楼梯`→`['踢','踢下楼梯']`、`尖石头戳眼睛`→`['戳']`、`胶带封住嘴巴`→`['封']`、
  `藤条抽打手心`→`['抽打','藤条']`），证明是真实语义覆盖而非记忆匹配。
- 已知残余缺口（patrol4 如实记录，不据此判 FAIL，因不在 A.2 点名清单内）：
  `猫抓伤脸`、`铁链锁起来`、`枕头闷住脸` 未命中；另 `指甲刀`/`鞭子虫`（尺蠖，昆虫学名）有轻微误报。

## 处置
- R5 已达标：patrol4 反例脚本 `11/11`、pytest `101 passed`、lint 4=基线、无硬编码。
- **已合入 closure**（GOLIVE-1016 B 只合 PASS 的）。
- 残余缺口已在本报告第 8 节如实记录，留给后续轮次，不阻塞本次上线。

