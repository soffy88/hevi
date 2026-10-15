# KIDSMANIFEST R3 独立核验报告（Hark，2026-10-15 04:40–05:15 UTC）

- 对象：worktree /data/soffy/projects/hevi-kidsmanifest，分支 feat/kids-manifest，HEAD 986b5649（DONE KIDSMANIFEST-R3）
- 环境：hevi 主 .venv，JWT_SECRET=test-only，PYTHONPATH=worktree
- 结论：**FAIL**（FIX-A 引入 R8 内容安全**回归**：血/武器不再拦截；且有大量常见伤害词漏杀。FIX-B 达成）。未 push。返工单 KIDSMANIFEST_FIX_R4.md。

## FIX-A：部分达成，但引入回归 + 漏杀

### 达成部分
- 误杀已消除：`extra.py`（核验员脚本）实测 `fp_open/fp_sweep/fp_umbrella/fp_hot` 全 PASS。
- 单字子串匹配已去掉，改为数据文件 `hevi/kids/data/kids_safety_rules.json`（9 类，每类 20–23 条）。
- 否定/教育语境：`m_neg_hit`「小狐狸不打人，也不骂人」、`m_neg_stranger`「妈妈说不能跟陌生人走」→ PASS。
- 我的独立探针（`probe_adversarial.py`）复跑 FIX 指定的 12 条：**全部符合预期**。

### 阻断 1（R8 回归）：血 / 武器不再拦截
- 复现：
  ```
  cd /data/soffy/projects/hevi-kidsmanifest
  JWT_SECRET=test-only PYTHONPATH=$PWD /data/soffy/projects/hevi/.venv/bin/python - <<'EOF'
  import copy, json
  from hevi.kids.story_gate import kids_story_gate
  fox=json.load(open("tests/fixtures/kids/story_fox_star.json"))
  for t in ["小狐狸被划伤了，到处都是血。","小狐狸拿起刀和枪。","小狐狸用刀砍伤了小兔。"]:
      s=copy.deepcopy(fox); s["beats"][3]["text"]=t
      print(kids_story_gate(s).status, "|", t)
  EOF
  ```
- 实际：三句全部 **PASS**（应为 FAIL）。
- 根因：R2 的 `hevi/quality/kids_gate.py::FORBIDDEN_WORDS` 含 `"刀","枪","血","血腥"`（`git show ab883df0:hevi/quality/kids_gate.py`）。R3 把词库迁到 `kids_safety_rules.json` 时**只删单字、未把血/刀/枪/武器/砍/划破等补回词库**，导致它们彻底消失。
- 违反 `KIDS_ANIME_DIRECTION.md` 第 11 行硬性安全闸门：「禁止出现：暴力、**血**、**武器**、恐怖画面…」。这是硬性红线回归。

### 阻断 2（R8 漏杀）：常见伤害词仍 PASS
我的独立探针（`probe_adversarial.py`，用 FIX 清单里没有的新词）实测全部 **PASS（应 FAIL）**：
- 「坏孩子把小熊掐得哇哇叫，还把他推下楼梯。」（掐/推下楼梯）
- 「他们用石头砸小兔，把小兔的头划破了直流血。」（砸/划破/流血）
- 「大家把小刺猬关进小黑屋，一整天都不给他饭吃。」（关小黑屋）
- 「小狐狸把一壶开水浇在小猫身上，小猫疼得直哭。」（开水浇）
- 词库缺 掐/推下楼梯/砸/划破/关小黑屋/烫/浇 等常见伤害词；「每类 ≥15 条」数量达标但覆盖不足，属 FIX-A 目标未真正达成。

### 阻断 3：否定窗口过宽（规则本身漏洞）
- `check_content_safety_text` 只要违规词前后 6 字窗口内出现任一否定词就整条放过。实测：
  ```
  check_content_safety_text("小狐狸把毒药给了小熊。")        -> ['毒药']   (正确 FAIL)
  check_content_safety_text("小狐狸不吃药，把毒药给了小熊。") -> []        (误判 PASS，应 FAIL)
  ```
  「不」在第 3 字、毒药在第 7 字，相距 4 字仍在 6 字窗口内，于是真实违规词「毒药」被否定词豁免。
- 需限定否定只对**紧随其后**的被否定词生效（窗口左界 ≤2 字且仅否定修饰该违规词），不能整条文本一旦含「不/没」就豁免。

## FIX-B：达成
`attach_to_task_shot_rows` 默认 `strict=True`：默认调用（不传 strict）遇孤儿任务行抛 `ShotIndexMismatchError`；`strict=False` 显式放行返回 1 行。`probe_adversarial.py` 两项均符合预期。

## 其他
- pytest `tests/test_kids_manifest.py`：**39 passed**。
- 3O lint：失败 4 项 = 基线（`lint.txt`）。
- R1 核验员全量探针重跑（`probe_counterexamples_r1rerun.json`）：44 项中仅 M13/M15 两项参考项未过（K1 未要求，非阻断），其余全 OK；B4 现为 FAIL（正确），M14 现为 FAIL（正确）。

## 证据（本目录）
- `probe_adversarial.py`/`probe_adversarial.json`：FIX 12 条 + 新伤害词 + 否定窗口 + FIX-B 独立探针
- `probe_counterexamples_r1rerun.json`：R1 核验员反例脚本重跑
- `pytest_kids_manifest.txt`、`lint.txt`

## 判定
FIX-B 达成；FIX-A 的误杀已修、FIX 指定 12 条样本全过，但（1）删除单字时连带删掉血/武器红线造成**硬性安全回归**，（2）常见伤害词大面积漏杀，（3）否定窗口过宽。内容安全闸门（R8）仍不合格。**FAIL，不 push**，写 KIDSMANIFEST_FIX_R4.md 并起 R4。
