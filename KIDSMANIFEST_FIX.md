# KIDSMANIFEST_FIX — R2 核验失败，R3 修复单（完成标志：KIDSMANIFEST_DONE.md 最后一行 `DONE KIDSMANIFEST-R3`）

R2 独立核验：pytest 107 passed、lint=基线 4 项、probe 45 项中仅 3 项 MISS、/api/capabilities 路由在。**但内容安全闸门（R8）仍不合格**，另有 1 项默认值不符。

## FIX-A（阻断）R8 内容安全：既误杀又漏杀
证据：用同一 fox 故事换一个节拍文本（beats[3].text）逐条实测（脚本 audit/kidsmanifest/verify_r2/extra.py，可直接跑）：
- 误杀（正常幼儿台词被判 FAIL）：「小狐狸打开了门，向大家打招呼。」「大家一起打扫房间」「小狐狸打着小雨伞」。原因：FORBIDDEN_WORDS 含单字"打""死""刀""枪""血""笨""丑"，按子串匹配，"打开/打招呼/打扫/打伞"全中。
- 漏杀（有害内容 PASS）：「狠狠地揍了小兔子一顿」「大家一起踢小松鼠，推他摔进泥坑里嘲弄他」「怪兽把小朋友一口吞进肚子里，再也没有出来」「在水里放了毒药」「点燃炸弹，把房子炸飞」「陌生叔叔说跟我走吧，小狐狸没告诉爸爸妈妈就跟着走了」「大家都骂小刺猬是傻瓜、胖子，没人理他」。
要求：
1. 去掉单字子串匹配。改成「词/短语」匹配：用分词（jieba 若已在依赖里，否则用带边界的正则 + 白名单复合词表：打开/打招呼/打扫/打伞/打电话/打球/打鼓/打瞌睡/打哈欠/打雪仗…），白名单必须是数据文件（hevi/kids/data/*.json），不得散落硬编码。
2. 扩充有害词/短语库（数据文件，分类：暴力伤害、恐吓、死亡、霸凌辱骂、危险行为、陌生人诱拐、毒/炸/火、成人、品牌），每类至少 15 条，至少覆盖上面 7 条漏杀样本的核心词（揍/踢/推倒/嘲弄/吞下/毒药/炸弹/炸飞/跟陌生人走/骂/傻瓜/胖子 等）。
3. 否定/教育语境不误杀：「小狐狸不打人，也不骂人」「妈妈说不能跟陌生人走」应 PASS 或最多 WARN（因为幼儿教育故事常见），但肯定语境必须 FAIL。写成规则（否定词 + 窗口），并有测试。
4. 必须新增测试，且用上面 12 条文本做成参数化测试（误杀 3 条 + 正常 1 条断言 PASS；漏杀 7 条断言 FAIL；否定语境 2 条断言非 FAIL）。测试不得只断言 status 字段存在。
5. hevi/quality/kids_gate.py 的 FORBIDDEN_WORDS 若被视频后置闸门（字幕检查）共用，同步改成同一份数据源并保持原有测试通过。

## FIX-B attach_to_task_shot_rows 默认值
- 实测：探针 B4（任务行 shot_index=99 不在 manifest）仍"静默跳过"，因为签名是 `strict: bool = False`。R1 FIX-13 要求"默认 strict 抛错"。
- 要求：默认 strict=True；确需宽松时显式传 strict=False，并有测试覆盖两种。

## 自测
```
cd /data/soffy/projects/hevi-kidsmanifest
PATH=$HOME/.local/bin:$PATH JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=$PWD /data/soffy/projects/hevi/.venv/bin/python audit/kidsmanifest/verify_r2/extra.py   # 全部 OK
PATH=$HOME/.local/bin:$PATH JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=$PWD /data/soffy/projects/hevi/.venv/bin/python audit/kidsmanifest/verify_r1/probe_counterexamples.py .tmp/p.json   # B4 变 OK
```
DONE 里如实写：每条自测的真实输出，不要写"MISS 0"除非 extra.py 全 OK。

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；所有 python 设 PYTHONPATH=/data/soffy/projects/hevi-kidsmanifest；不 push；不调付费 API；不要把 lint 日志提交进仓库。完成后在 KIDSMANIFEST_DONE.md 最后一行写 DONE KIDSMANIFEST-R3。
