# KIDSMANIFEST 单元完成报告 (KIDSMANIFEST-R5)

## 范围与依据
- 单元 K1：幼儿故事闸门 `kids_story_gate` + `KidsConsistencyManifest`（绑定 ShotSpec），内容安全闸门 R8 走生产入口 `hevi.quality.kids_gate.check_content_safety_text`。
- 本轮依据：`KIDSMANIFEST_FIX_R5.md`。patrol4（GOLIVE_1016_TASK.md A.2）用自己的反例脚本 `verify_kidsmanifest_independent.py` 重跑，判定 R4 自报 **FAIL**（3/11）：GOLIVE-1016 A.2 点名的 6 个暴力词全部漏杀，另有 2 处正常幼儿词误杀。
- R4 已达成项本轮保持不回退（见下方「已确认 PASS 不回退」实测）。

## patrol4 修复前基线（如实记录）
```
3/11 checks passed   VERDICT: FAIL
[FAIL] adversarial: all 6 mandated words + synonyms blocked 12/23 blocked
       MISSED=勒脖子, 勒脖子-同义, 踹飞, 针扎, 绑树堵嘴×3, 鞭打×3, 狗咬
[FAIL] adversarial group '勒脖子' 1/3 | '踹飞' 2/3 | '针扎' 2/3
[FAIL] adversarial group '绑树堵嘴' 0/3 | '鞭打' 0/3 | '狗咬' 2/3
[FAIL] benign: 13/15 clean  FALSE_POSITIVE=[('日常-切菜',['刀']), ('日常-刺猬',['苹果'])]
```

## 本轮修复

### P0 — 6 类点名暴力行为及其同义/改写（新增 7 个 category，共补入真实语义词）
`hevi/kids/data/kids_safety_rules.json` 新增 category（覆盖词条总数 356，whitelist 70）：

| category | 词条数 | 覆盖点（同义/改写，非仅原词） |
|---|---|---|
| `strangulation` | 22 | 勒/勒住/勒紧/箍住/扼住/锁喉/喉咙/捂住嘴/窒息/喘不过气/呼吸困难 |
| `kicking` | 16 | 踹/踹飞/踹倒/猛踹/一脚踹/踢飞/踢倒/踢翻/踢下楼梯/践踏 |
| `stabbing` | 19 | 针/针扎/扎针/针刺/刺进/刺穿/刺入/戳/捅/锥子/缝衣针/注射器/刺了很多下 |
| `binding_gagging` | 20 | 绑/绑住/绑在/五花大绑/绑票/捆/捆绑/堵嘴/堵上嘴/塞住嘴/封住嘴/缠住 |
| `whipping` | 19 | 鞭子/皮鞭/鞭打/抽打/皮带/棍子/棍棒/藤条/戒尺/荆条/使劲抽/打板子 |
| `biting` | 9 | 咬/咬住/咬死/咬破/咬着/咬烂/恶犬/犬咬 |
| `gagging` | 11 | 堵/堵嘴/堵住嘴/塞/塞住嘴/封/封住嘴/捂住/捂住嘴/蒙住/毛巾塞 |

配套白名单扩充（避免新增单字词误伤幼儿高频词）：`针线`、`绣花针`、`别针`、`打针`、`打预防针`、`绑鞋带`、`系鞋带`、`绑安全带`、`绑头发`、`扎辫子`、`包扎`、`咬了一口`、`咬咬牙`、`鞭炮`、`切水果`、`削皮` 等。

### P1 — 2 处误杀（over-blocking）
1. **苹果**：从 `brand` 移除（幼儿内容里「苹果」首先是水果），改为只保留真实品牌词 `苹果公司`/`苹果手机`/`苹果牌`。`小刺猬背上有苹果，真可爱。` → `[]`。
2. **刀**：新增 `context_exemptions` 机制 + `hevi/quality/kids_gate.py` 的 `_is_context_exempt()` / `_clause_bounds()`：
   - `刀` 仅在**同一分句**同时满足「切割动词（切/削/剁/剖/切片…）」**与**「食材/厨事名词（菜/厨房/砧板/水果/苹果/黄瓜…）」两个词组时才豁免，且该分句出现任何伤害标记（砍/捅/刺/割/杀/伤/血/喉咙/脖子/手臂…）一律不豁免。
   - 同机制覆盖 `咬`（+食物名词）、`扎`（+头发/辫子/口袋）、`绑`（+鞋带/安全带/头发/礼物）、`捆`（+书/绳子/画）、`堵`（+车/马路/路口/下水道）、`塞`（+口袋/书包/箱子/盒子）、`封`（+信封/包裹/罐头/罐子）共 8 个单字词。
   - 豁免只作用于**当前分句**（`_clause_bounds` 遇标点即止），因此 R4/H3 的跨句规避能力不被放宽：`不吃药，把毒药给了小熊` 仍报 `['毒药']`。
   - 攻击语境仍拦截：`坏人用刀刺伤了小熊。` → `['刀','刺','刺伤']`。

### 实现要点（`hevi/quality/kids_gate.py`）
- `check_content_safety_text` 读入 `context_exemptions`，在非否定命中后先过 `_is_context_exempt` 再记违规；豁免判定使用**未 mask 的原文**，保证 `切菜` 等白名单词仍能作为良性语境证据生效。
- 未使用任何 mock/硬编码特判：`堵住`/`塞住`/`封住` 这类多字词原先会绕过单字上下文豁免（`小汽车堵住了路口` 误报），因此把三个词统一收敛为单字 `堵`/`塞`/`封` 词条，由统一的分句上下文机制裁决，而不是把具体句子写进代码。

## 验收标准实测结果（真实输出，CPU-only 离线）

### 1. patrol4 独立反例脚本（原样重跑）
```
$ /data/soffy/projects/hevi/.venv/bin/python \
    /data/soffy/projects/hevi-pubfix/audit/patrol4/kidsmanifest_probe/verify_kidsmanifest_independent.py
[PASS] adversarial: all 6 mandated words + synonyms blocked 23/23 blocked
[PASS] adversarial group '勒脖子' blocked 3/3
[PASS] adversarial group '踹飞' blocked 3/3
[PASS] adversarial group '针扎' blocked 3/3
[PASS] adversarial group '绑树堵嘴' blocked 3/3
[PASS] adversarial group '鞭打' blocked 3/3
[PASS] adversarial group '狗咬' blocked 3/3
[PASS] benign: normal preschool words not over-blocked 15/15 clean
[PASS] benign: direct negation not over-blocked all 3 clear
[PASS] evasion: cross-clause violation blocked found=['毒药']
[PASS] determinism: repeat run byte-identical (sha256) 21312ce2d37390cc7abb0d86 == 21312ce2d37390cc7abb0d86
11/11 checks passed
VERDICT: PASS
```

### 2. P0 表中 18/18（点名词 + 同义 + 改写，逐条真实返回）
```
大灰狼勒住了小兔的脖子。              ['勒', '勒住']
坏人用手臂紧紧箍住小熊的喉咙，让他喘不过气。    ['喉咙', '喘不过气', '箍住']
小狐狸被掐住了脖子，脸都红了。           ['掐', '掐住']
大熊一脚把小兔踹飞到墙上。             ['踹', '踹飞']
他用力踢过去，小朋友整个人飞了出去。        ['踢']
大灰狼猛踢一脚，小羊被踢得远远飞走。        ['踢', '踢得远远']
坏巫婆拿针扎小兔的手指。              ['扎', '针', '针扎']
她用尖尖的注射器刺进小熊的手臂。          ['刺', '刺进', '注射器']
小狐狸被缝衣针刺了很多下，疼得大哭。        ['刺', '刺了很多下', '缝衣针', '针', '针刺']
坏人把小兔绑在树上，还用布堵住他的嘴。       ['堵', '绑', '绑在']
他们把小朋友捆在树干上，用毛巾塞住嘴巴不让他叫。   ['塞', '塞住嘴', '捆', '捆在', '毛巾塞']
小狐狸被绳索绑住手脚，封住了嘴，说不出话。     ['封', '绑', '绑住', '绑住手脚']
大灰狼用鞭子抽打小马。               ['抽打', '鞭子', '鞭子抽']
他举起皮带使劲抽小朋友的背。            ['使劲抽', '皮带']
坏国王用棍子反复抽打小仆人。            ['抽打', '棍子']
大狗咬住了小兔的腿。                ['咬', '咬住']
恶犬张开嘴撕咬小朋友的手臂。            ['咬', '恶犬', '撕咬']
那只狗用牙齿死死咬住小熊不放。           ['咬', '咬住', '死']
→ P0 18/18 全部非空（拦截）
```

### 3. P1 表中 2/2 不再误报
```
小刺猬背上有苹果，真可爱。          []
妈妈在厨房用刀切菜，一刀切菜真整齐。  []
```
（`苹果` 已不在 `brand`；`刀` 走分句豁免。攻击语境 `坏人用刀刺伤了小熊。` → `['刀','刺','刺伤']` 仍拦截。）

### 4. 已确认 PASS 的部分全部不回退
```
直接否定不误杀：不可以打人 / 不会下毒 / 没有带刀 → [] / [] / []
跨句规避仍拦截：小狐狸不吃药，把毒药给了小熊。 → ['毒药']
血/武器硬红线：小兔被划伤了，到处都是血。        → ['划伤','血']
              小狐狸拿起刀和枪。                 → ['刀','枪']
              小狐狸用刀砍伤了小兔。              → ['刀','砍','砍伤']
```
story gate（patrol4 独立 `verify_story_gate.py`）：
```
[PASS] 合规样本 → PASS
[PASS] 全 AND-THEN 坏样本 → FAIL
[PASS] 相邻同情绪坏样本 → FAIL
[PASS] 缺主题坏样本 → FAIL
[PASS] 缺固定角色坏样本 → FAIL
[PASS] 确定性（2 次 sha256 一致） 0c8418b63fbc9fa88e14bc92
6/6 checks passed   VERDICT: PASS
```

### 5. pytest（真实运行，无 mock）
```
$ python -m pytest -q tests/test_kids_manifest.py tests/test_kids_gate.py tests/test_kids_prompt_compile.py
104 passed in 4.27s                       # R4 为 58 项，新增 R5 46 项

$ python -m pytest -q tests/ -k "kids or shot_spec"
180 passed, 1 skipped, 7880 deselected, 5 xfailed, 1 warning in 42.67s   # 无新增失败
```
新增 R5 单测（`tests/test_kids_manifest.py`）：
- `test_r5_p0_mandated_violent_words_blocked`（18 条点名词/同义/改写 + 扩展同义，参数化）
- `test_r5_p0_all_six_groups_covered_by_rules`（断言 6 组词与核心同义词真实存在于规则表 category，非靠句子特判）
- `test_r5_p1_benign_preschool_words_not_blocked`（10 条幼儿正常句不得误报）
- `test_r5_p1_apple_no_longer_a_brand_violation`
- `test_r5_p1_knife_cutting_context_exempt_but_attack_still_blocked`（豁免与攻击拦截双向断言）
- `test_r5_p1_negation_still_not_over_blocked`、`test_r5_hard_redlines_still_blocked`、`test_r5_cross_clause_evasion_still_blocked`
- `test_r5_story_gate_blocks_mandated_violence` / `test_r5_story_gate_allows_benign_preschool_text`（story gate 端到端双向）
- `test_r5_determinism_of_content_safety_verdict`（sha256 一致）

> 说明：`tests/test_shot_spec_render.py::test_duration_clip_pad_and_sfx_alignment` 在一次整跑中曾失败，单独重跑及再次整跑均通过（180 passed），与本轮 kids 词表改动无关（ffmpeg 资源类偶发）；日志见 `audit/kidsmanifest/verify_r5/`。

### 6. 3O lint
```
$ python scripts/ci/run_3o_v3_lint.py
3O_V3_LINT=FAIL
failed: check_no_sibling_call.py, check_omodul_signature.py, check_enabled_pillars.py, check_oprim_keyword_only.py
rc=1
```
失败项 4 个，与 R4 基线完全一致（≤4，未新增）。

## 证据文件
- `audit/kidsmanifest/verify_r5/patrol4_independent.txt`（patrol4 11/11 PASS）
- `audit/kidsmanifest/verify_r5/story_gate.txt`（6/6 PASS）
- `audit/kidsmanifest/verify_r5/pytest_kids.txt`（104 passed）
- `audit/kidsmanifest/verify_r5/pytest_kids_shot_spec.txt`（180 passed, 1 skipped, 5 xfailed）
- `audit/kidsmanifest/verify_r5/lint.txt`（4 failed，同基线）

## 安全规则
- 仅修改本地 worktree `/data/soffy/projects/hevi-kidsmanifest`；未删除 worktree 外任何文件；未清理磁盘空间；未 `rm` 已跟踪文件；`git add` 仅含本轮自有文件；未 push；未合并。
- CPU-only 离线运行，无付费 API；无 mock，无把核验句子特判进代码的硬编码（覆盖靠真实词表 + 分句上下文语义机制）。

DONE KIDSMANIFEST-R5
