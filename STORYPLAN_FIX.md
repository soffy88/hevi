# STORYPLAN-VFY1 修复单（STORYPLAN_FIX.md）

> 源自 `audit/storyplan/verify_r1/REPORT.md`（VERDICT: FAIL）。下面每条均给出**可复现输入**，与 `audit/storyplan/verify_r1/counter.py`（反例脚本）一一对应。修复后请用同一脚本复测。

---

## FIX-1 叙事闭环门 C5 可被 6 字无关文本绕过（High）
- **位置**: `hevi/storyplan/check.py` C5 `closure_ok = len(overlap) >= 1 or len(closing_text) > 5`
- **问题**: `overlap` 是按单字（`re.findall(r"[\u4e00-\u9fa5]")`）取交集，钩子含"吗/呢/你"等高常见字时任意短句都能命中；且 `len(closing_text) > 5` 是纯长度兜底，语义零关联也能过。
- **反例输入**:
  ```python
  from hevi.storyplan.autofill import autofill_story_plan
  from hevi.storyplan.check import run_story_check
  p = autofill_story_plan("小水滴去哪儿了")
  p.narrative.closing_response = "随便写六个字"   # 与钩子零语义重叠
  rep = run_story_check(p)   # 实测 C5=PASS, rep.passed=True
  ```
- **期望**: closing 必须显式回应 hook（语义特征/关键词重叠，非单字），或至少要引用 beats 中 `expectation` 的核心实体。
- **建议**: 用主题词/beat expectation 的 token 交集做判定，删除纯 `len>5` 兜底；对 `overlap` 采用词语级（`jieba`/字 bigram）而非单字。

## FIX-2 时间线门 C6 漏判（High）
- **位置**: `hevi/storyplan/check.py` C6
- **问题**:
  - (a) `timeline.tracks` 整体为空、`duration_ms` 被改成 999999 时仍 PASS（因为只在 `if video_track and video_track.clips:` 内检查）。
  - (b) 不校验「各 clip 越界」：clip `end_ms` 超出 `duration_ms` 不报。
  - (c) 不校验「字幕不超出对应语音区间」：subtitle clip 比 voice clip 长 5s 仍 PASS。
- **反例输入**:
  ```python
  # (a) 空时间线
  p.timeline.tracks = []
  # (b) 越界
  vt = next(t for t in p.timeline.tracks if t.track_kind=="video")
  vt.clips[-1] = vt.clips[-1].model_copy(update={"end_ms": vt.clips[-1].end_ms + 5000})
  # (c) 字幕超出语音区间
  st = next(t for t in p.timeline.tracks if t.track_kind=="subtitle")
  st.clips[0] = st.clips[0].model_copy(update={"end_ms": st.clips[0].end_ms + 5000})
  ```
- **期望**: (a) 空/缺 video 轨 → FAIL；(b) 任一 clip `end_ms > duration_ms` 或 `start_ms < 0` → FAIL；(c) subtitle clip 区间必须被某一 voice clip 区间覆盖 → 否则 FAIL。

## FIX-3 内容安全词表 C7 缺口（Medium）
- **位置**: `hevi/storyplan/check.py` `FORBIDDEN_KIDS_WORDS`
- **问题**: 反例中"揍他/踢一脚/勒脖子/踹飞/鞭打/毒药/炸弹"等 C7 **未命中**，仅靠其它门兜底拒；词表缺大量术语（"勒""脖""鞭""踹""揍"）。
- **反例输入**: 见 `counter.py` 中 `HARMFUL` 列表；把文本塞入 `narration_text`+`hook.text` 后 C7 状态为 PASS。
- **期望**: 进入 `hevi/kids_gate` 词表或其超集，覆盖 `STORYPLAN_VFY_TASK.md` 4f 列的 15 类词根（揍/踢/勒脖子/踹飞/鞭打/毒药/炸弹/陌生人/辱骂/鬼怪/血…）；term 命中后 `violations` 应列出具体词。
- **备注**: 该反例 f 项整体已 15/15 拒（其它门兜底），但 C7 本身需补齐。

## FIX-4 autofill 非预设主题模板化（Medium）
- **位置**: `hevi/storyplan/autofill.py` `else` 分支
- **问题**: 非"水"/"手"主题走通用分支，`narration` / beats / shots 文案只把 `{clean_topic}` 换进句子里，其余完全一致。
- **反例输入**:
  ```python
  for t in ["小树为什么会长高","为什么要早睡","太空里有什么"]:
      autofill_story_plan(t).narration_text  # 剔除主题名后文本完全相同
  ```
- **期望**: 至少按主题词触发的语义标签（动物/自然/习惯/太空…）给出不同叙述模板，或按名词数量派生出不同 beat 划分。
- **注意**: 任务书 B 只说"规则+模板"，允许模板；但 VFY 明确要求 h「产物必须随主题变化，不得是同一模板换名字」→ 需至少让 narration/shot purpose 结构化字段随主题变化。

## FIX-5 take_select 未实现规格 D 帧打分（High）
- **位置**: `hevi/storyplan/take_select.py`
- **问题**: `motion_completeness`/`stability`/`no_tail_redundancy` 均由 `duration_sec` 与常量推导，方程式外；从不读取 `video_path`、不解码帧、不计算 SSIM/帧差。
- **反例输入**:
  ```python
  cands = [
    TakeCandidate(take_id="t_full_motion", video_path="good.mp4", duration_sec=5.0),
    TakeCandidate(take_id="t_frozen_broken", video_path="bad.mp4", duration_sec=5.0),
  ]
  select_best_take(cands, "动作完整到达结束状态")  # 两者同分 96.1
  ```
- **期望**: 用 ffmpeg 抽帧（CPU，序号确定）→ 首尾帧差 + 相邻帧 SSIM + 结束状态到达度打分，`selected_in_sec/out_sec` 由真实帧决定；两个同时长但一个冻结的 take 分数必须不同。
- **验收**: 修复后 `counter.py` 的 `g3_take_select_no_frame_inspection` 必须转 PASS。

## FIX-6 能力未接入统一目录与 API（High）
- **位置**: `hevi/storyplan/capabilities.py`、`hevi/api/main.py`
- **问题**:
  - `hevi/storyplan/capabilities.py` 自建 `_REGISTRY`，并未并入 `hevi/production/capabilities.py` 的 `_CATALOG`（GET /api/capabilities 的真相源）。
  - `hevi/storyplan/api.py` 的 `/story-plan` 路由 **未** `app.include_router(..., prefix="/api")` 到主 app。
  - 三个能力的 `validate_params` 是空实现，非法参数不拒（任务 F 要求「非法参数拒绝」）。
- **反例输入**:
  ```python
  from hevi.production.capabilities import capability_catalog
  need = {"story_plan", "story_check", "take_select"}
  ids = {c["id"] for c in capability_catalog()}  # need & ids == set()
  # 并且: grep -n "story-plan" hevi/api/main.py -> 无
  ```
- **期望**: 在 `hevi/production/capabilities.py` 注册 descriptor 并挂载路由；`GET /api/capabilities` 应能查到三者；`validate_params` 用 params_schema 校验非法参数（如 topic 空字符串、candidates 缺字段）报 422。

## FIX-7 样片缺失 / 声明不可核验（High）
- **位置**: `audit/storyplan/`（R1 交付）
- **问题**: 仓库内无任何 storyplan 主题 mp4/png 成片，也无 `sha256`；`STORYPLAN_DONE.md`/`REPORT.md` 声称「样片 1 小水滴去哪儿了 16:9 / 样片 2 小熊为什么洗手 9:16 / take_select 演示」，但无媒体可佐证。
- **反例输入**:
  ```bash
  find . -name "*.mp4" | grep -iE "story|水滴|小熊|raindrop|bear"   # 空
  ```
- **期望**: 用仓内 CPU 线（stickdir/handdraw/anatomy/artmotion）渲染 ≥2 支 6–20s 1080p 成片（16:9 与 9:16 各一），存 `audit/storyplan/samples/`，附 `ffprobe` 输出、sha256、抽帧 sheet、无结构基线对照 FAIL 报告；只提交小体积产物。

---

## 复现方式
```bash
cd /data/soffy/projects/hevi-storyplan
JWT_SECRET=test-only PYTHONPATH=/data/soffy/projects/hevi-storyplan TMPDIR=.tmp \
  /data/soffy/projects/hevi/.venv/bin/python audit/storyplan/verify_r1/counter.py
# 修复目标：末行 "未达预期 0"（当前 6）
```

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；所有 python 设 PYTHONPATH=/data/soffy/projects/hevi-storyplan；不 push；不调付费 API；不要把 lint 日志提交进仓库。完成后在 STORYPLAN_DONE.md 最后一行写 DONE STORYPLAN-R2。
