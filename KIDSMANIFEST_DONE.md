# KIDSMANIFEST 单元完成报告 (KIDSMANIFEST-R4)

## 范围与依据
- 单元 K1：幼儿故事闸门 `kids_story_gate` + `KidsConsistencyManifest`（绑定 ShotSpec）。
- 本轮依据：`KIDSMANIFEST_FIX_R4.md`（R3 独立核验 FAIL：内容安全闸门 R8 三项阻断 H1/H2/H3）。
- R3 已达成项保持不回退：误杀已消除（`fp_open/fp_sweep/fp_umbrella/fp_hot` 全 PASS）；FIX-B `attach_to_task_shot_rows` 默认 `strict=True` 抛 `ShotIndexMismatchError`。
- 许可：仅吸收 Renoise 方法论（无 LICENSE），未复制其原文/代码。

## 本轮修复（H1/H2/H3）
- `hevi/kids/data/kids_safety_rules.json`
  - **H1**：`violence` 类补回血液/武器硬红线词条：`血`、`流血`、`鲜血`、`血腥`、`出血`、`血泊`、`血淋淋`、`刀`、`枪`、`武器`、`砍`、`砍伤`、`砍死`、`砍杀`、`刺`、`刺伤`、`匕首`、`剪刀`、`划破`、`划伤`、`划开` 等。
  - **H2**：补足常见伤害词：`掐`、`掐住`、`推下楼梯`、`推下楼`、`砸`、`砸伤`、`砸死`、`用石头砸`、`浇`、`烫`、`烫伤`、`开水浇`、`踢打`、`踢伤`、`打人`、`咬人`、`咬伤`、`抢`、`抢走`、`摔`、`摔伤`、`摔下`、`扇耳光`、`拳打`、`脚踢`；`intimidation` 类补 `关小黑屋`、`关进小黑屋`、`关进黑屋子`、`不给饭吃`、`不给吃饭`、`饿肚子`、`关起来`。
  - 白名单扩充以防误杀：`喝水`、`一刀切菜`、`切菜`、`抢着`、`抢先`、`抢答`、`摔倒`、`摔了一跤`、`浇水`、`浇浇水`、`浇花`、`浇灌`、`推近`、`推远`、`刺激`、`刺猬`、`小刺猬`。
- `hevi/quality/kids_gate.py`
  - **H3**：`check_content_safety_text` 取消「6 字窗口内出现任意否定词即整条豁免」的宽否定窗口，改为 `_is_negated()`：仅当否定词**紧邻**违规词（间隔 ≤2 字）且中间无标点/分句符时才豁免。`不可以下毒`、`不打人` 等直接否定仍不误杀；`不吃药，把毒药…` 跨句违规被正确拦截。
  - **H1 白名单**：采用最长优先的复合白名单屏蔽（mask）后再做短语匹配，使 `一刀切菜`/`浇浇水` 等正常词不会被单字红线（刀/浇）误伤；否定词表去掉「妈妈说/老师说」等非否定前缀。
- `tests/test_kids_manifest.py`
  - 新增 R4 参数化测试：H1（血/武器 3 条断言 FAIL）、H2（4 条常见伤害词断言 FAIL）、H3（`小狐狸不吃药，把毒药给了小熊` 断言 FAIL；`不可以下毒`、`小狐狸不打人` 断言非 FAIL）。

## 验收标准实测结果（真实输出）

### 1. 核验员探针 `audit/kidsmanifest/verify_r3/probe_adversarial.py`
```
TOTAL 22  MISS 0
ADVDONE
```
（含 FIX 指定 12 条 + 新伤害词 5 条 + 否定窗口 2 条 + FIX-B 2 条，全部符合预期。）

### 2. 误杀回归 `audit/kidsmanifest/verify_r2/extra.py`
```
OK 计数 12 / 12（fp_open/fp_sweep/fp_umbrella/fp_hot 全 PASS，7 条漏杀全 FAIL，否定语境非 FAIL）
```

### 3. pytest
```
$ python -m pytest -q tests/test_kids_manifest.py
.................................................                        [100%]
49 passed in 5.05s
```
（R3 原 39 项不回退，新增 R4 10 项全过。）

### 4. 复现硬红线（H1）
```
['划伤', '血'] | 小狐狸被划伤了，到处都是血。
['刀', '枪'] | 小狐狸拿起刀和枪。
['刀', '砍', '砍伤'] | 小狐狸用刀砍伤了小兔。
```

## 安全规则
- 仅修改本地 worktree；未删除 worktree 外任何文件；未清理磁盘；未 `rm` 已跟踪文件；未 push；CPU 离线运行；无付费 API；无 mock。
- 未把 lint 日志提交进仓库。

DONE KIDSMANIFEST-R4
