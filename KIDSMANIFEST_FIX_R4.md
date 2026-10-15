# KIDSMANIFEST_FIX_R4 — R3 核验失败，R4 修复单（完成标志：KIDSMANIFEST_DONE.md 最后一行 `DONE KIDSMANIFEST-R4`）

R3 独立核验（Hark，`audit/kidsmanifest/verify_r3/REPORT.md`）结论：FIX-B 达成、FIX-A 的误杀已修，但内容安全闸门（R8）**仍不合格**：删单字时连带删掉了血/武器红线（回归），常见伤害词大面积漏杀，否定窗口过宽。判定 FAIL。

## 已达成，不要回退
- 误杀已消除：`audit/kidsmanifest/verify_r2/extra.py` 的 `fp_open/fp_sweep/fp_umbrella/fp_hot` 全 PASS。
- FIX 指定的 12 条样本（误杀 3 + 正常 1 + 漏杀 7 + 否定 2）在核验员 `probe_adversarial.py` 中全部符合预期。
- FIX-B：`attach_to_task_shot_rows` 默认 `strict=True` 抛 `ShotIndexMismatchError`，`strict=False` 放行。

## 阻断项（必须全部修）

### H1（R8 硬红线回归）：血 / 武器不再拦截
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
- 实际：三句全部 **PASS**（应 FAIL）。
- 根因：R2 的 `hevi/quality/kids_gate.py::FORBIDDEN_WORDS` 含 `"刀","枪","血","血腥"`（`git show ab883df0:hevi/quality/kids_gate.py`）。R3 迁到 `kids_safety_rules.json` 时只删单字、没把血/武器补回词库。
- 要求：词库补回武器/血液类（`血`、`流血`、`血腥`、`刀`、`枪`、`砍`、`砍伤`、`刺伤`、`匕首`、`剪刀`、`划破` 等），且不误杀正常词（如「喝水」「一刀切菜」需用白名单或短语边界处理）。`KIDS_ANIME_DIRECTION.md` 第 11 行硬性闸门明确「禁止…血、武器…」。

### H2（R8 漏杀）：常见伤害词仍 PASS
核验员 `probe_adversarial.py` 实测以下全部 **PASS（应 FAIL）**：
- 「坏孩子把小熊掐得哇哇叫，还把他推下楼梯。」（掐 / 推下楼梯）
- 「他们用石头砸小兔，把小兔的头划破了直流血。」（砸 / 划破 / 流血）
- 「大家把小刺猬关进小黑屋，一整天都不给他饭吃。」（关小黑屋）
- 「小狐狸把一壶开水浇在小猫身上，小猫疼得直哭。」（开水浇 / 烫）
- 要求：每类补足常见伤害词（掐、推下楼梯、砸、划破、关小黑屋、烫、浇、踢打、摔、抢、咬人等），并加测试；同类词至少覆盖这些样本核心词。

### H3：否定窗口过宽（规则本身漏洞）
- 复现：
  ```
  JWT_SECRET=test-only PYTHONPATH=$PWD /data/soffy/projects/hevi/.venv/bin/python -c \
    "from hevi.quality.kids_gate import check_content_safety_text as c; print(c('小狐狸不吃药，把毒药给了小熊。'))"
  ```
- 实际：`[]`（误判 PASS，应 FAIL）。「不」与「毒药」相距 4 字，仍在 6 字窗口内被豁免。
- 要求：否定只对**紧随其后**的被否定词生效（如违规词左界 ≤2 字内且否定直接修饰该词），不能整条文本一旦含「不/没/别」就豁免。保留「不打人/不能跟陌生人走」不误杀。

## 自测（DONE 前必须全过，写进 DONE 真实输出）
```
cd /data/soffy/projects/hevi-kidsmanifest
export JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=$PWD PATH=$HOME/.local/bin:$PATH
PY=/data/soffy/projects/hevi/.venv/bin/python
$PY audit/kidsmanifest/verify_r3/probe_adversarial.py     # 全部 OK，MISS 0
$PY audit/kidsmanifest/verify_r2/extra.py                 # 全部 OK
$PY -m pytest -q tests/test_kids_manifest.py              # 全过（原 39 项不回退）
```
- 必须新增参数化测试覆盖 H1（血/武器 3 条断言 FAIL）、H2（上述 4 条断言 FAIL）、H3（「小狐狸不吃药，把毒药给了小熊」断言 FAIL；「不可以下毒」「小狐狸不打人」断言非 FAIL）。

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；所有 python 设 PYTHONPATH=/data/soffy/projects/hevi-kidsmanifest；不 push；不调付费 API；不要把 lint 日志提交进仓库。完成后在 KIDSMANIFEST_DONE.md 最后一行写 `DONE KIDSMANIFEST-R4`。
