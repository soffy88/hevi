# REVIEWSHEET_FIX_R3 — 合并核验 R2 未通过（2026-10-15，MERGE-1015 第 0 步）

核验：`/data/soffy/projects/hevi-pubfix` 的合并核验员。对象：worktree `/data/soffy/projects/hevi-reviewsheet`，分支 `feat/review-sheet`，HEAD `c9afc054`（`DONE REVIEWSHEET-R2`）。

## 判定：不合并

MERGE-1015 第 0 步对 reviewsheet 的硬验收是 `bash audit/reviewsheet/verify_r1/run_all.sh` 退出码 0。**在分支 HEAD 的干净检出上不成立**：TOTAL_BAD 3。使 run_all 通过（以及 `tests/test_reviewsheet_k2.py` 全过）的修复**只存在于 worktree 未提交的 WIP 里**，分支 HEAD 不含该修复 → 按"HEAD 不含声称的修复则不合并"处理。

## 阻断项（复测证据）

### G1 `run_all.sh` 在干净 HEAD 上 TOTAL_BAD 3
- 复现（在 HEAD `c9afc054` 的干净检出上，不取用 WIP）：
  ```
  git worktree add --detach /tmp/rs-head c9afc054
  cd /tmp/rs-head
  JWT_SECRET=test-only TMPDIR=$PWD/.tmp PYTHONPATH=$PWD \
    bash audit/reviewsheet/verify_r1/run_all.sh
  ```
- 实测：`results_kids_gate.json ... leaks 1 ['adult_text_4_12']`；`e2e problems ['camera patch 对渲染无效果', '合法 patch 重渲染后 gate=red']`；`TOTAL_BAD 3`（退出码非 0）。
- 期望：TOTAL_BAD 0、退出码 0。

### G2 分支自己的 pytest 在干净 HEAD 上失败
- 复现：
  ```
  cd <clean c9afc054 checkout>
  JWT_SECRET=test-only TMPDIR=$PWD/.tmp PYTHONPATH=$PWD \
    /data/soffy/projects/hevi/.venv/bin/python -m pytest tests/test_reviewsheet_k2.py -q
  ```
- 实测：`test_e2e_manifest_to_render_to_gate` 与 `test_capability_render_local` 失败：
  `subprocess.CalledProcessError: ffmpeg ... xfade ... returned non-zero exit status 234`（"received no packets"，多段短视频 xfade offset/padding 失败）。
- 根因：`hevi/kids/render_local.py::_concat_with_xfade` 在 HEAD 里用 `build_xfade_chain` 的 filter_complex xfade 链；WIP 改成了 concat demuxer。

### G3 WIP 修法本身放宽了确定性断言（若照 WIP 提交需修正）
- WIP（未提交）把 `tests/test_reviewsheet_k2.py` 的 `assert info3["sha256"] == sha1` 改成 `assert info3["sha256"]`（只要非空即过），等于**取消确定性验收**。
- 我独立复测（WIP 的 concat 版本）：同 manifest、同 seed 两次渲染 sha256 一致（`6e1446c8…`）→ 确定性本身成立，应保留 `== sha1` 的严格断言，不应放宽。

## 期望的 R3 修复
1. 把 WIP 里 `render_local.py` 的 concat demuxer 修法（或等价的健壮 xfade 修法）**提交**；`camera` 字段必须真正影响渲染（G1 的 `camera patch 对渲染无效果` 要修掉，且不得靠写死底色"作弊"）。
2. `kids_gate_extended` 的 `adult_text_4_12` 误报要修（合法 patch 重渲染后 gate 须为 `ok`）。
3. 保留严格确定性断言（`sha256 == sha1`）。
4. 提交后：`bash audit/reviewsheet/verify_r1/run_all.sh` 退出码 0，且 `pytest tests/test_reviewsheet_k2.py -q` 全过——**必须在干净 HEAD 上复现**，不得依赖未提交文件。

## 需保留（不要回退）
- R2 已修的 24 项（审稿表贴图/N=30/页脚/长台词、标注 patch 校验、kids_gate 扩展五类坏样本）与 `run_all.sh` 的 38/36/13 漏放为 0 的部分；`hevi/capabilities/registry.py` 里新增的 `qa.kids_gate.extended`/`kids.review_sheet`/`kids.render_local`/`kids.annotation_revision` 四个能力注册。

## 完成标志
- 干净 HEAD 上 `run_all.sh` 退出 0、`pytest tests/test_reviewsheet_k2.py` 全过；`REVIEWSHEET_DONE.md` 末行 `DONE REVIEWSHEET-R3`（或按返工轮次）。

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 `DISK_FULL_NOTE.md` 停止）；CPU-only、单进程渲染；不调付费 API；禁止 mock/硬编码通过；不 push；临时文件 `.tmp/`。
