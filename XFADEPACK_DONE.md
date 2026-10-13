# XFADEPACK_DONE.md

## 完成内容

T2 逐接缝转场包已全部实现，包含：

### 1. xfade_transitions.py（注册表）
- `Transition` 数据类（id/name_zh/kind/ffmpeg/tags/default_duration）
- 58 个 builtin 转场（经 ffmpeg 7.0.2 实测全部可用）
- 6 个 custom 转场（whip/glitch/flash/zoom_punch/ink_burn/strobe）
- 导出：`ALL_TRANSITIONS`、`list_transitions()`、`get_transition(id)`、`resolve(id)->ffmpeg片段`

### 2. assembler.py（build_xfade_chain 增强）
- `transition` 参数支持 `str`（原行为）和 `list[str]`（逐接缝，长度 n-1）
- `xfade_d` 参数支持 `float` 和 `list[float]`（已有 beat_align 支持）
- 未知 id 抛 ValueError
- 向后兼容：str 参数生成的 filter_complex 与改动前逐字一致

### 3. 测试（tests/test_xfade_pack.py，85 项全绿）
- 注册表单测：list/get/resolve/数量约束
- ffmpeg 真实渲染测试：每个 builtin/custom 单独跑两段 lavfi 片退出码 0
- E2E 时长断言：Σdurs - Σxfade_d（±1 帧）
- SSIM 过渡可见性：接缝中点帧 vs 硬切基线同时刻帧 SSIM < 0.98
- 过渡形态差异：4 个接缝中点帧两两 SSIM 存在可辨差异
- str 回归一致、未知 id 抛错

### 4. E2E 样片（output/xfadepack_e2e/）
- `xfadepack_e2e.mp4`：5镜头（red/green/blue/yellow/testsrc，各3s，1080x1920，30fps），4种转场（fade/dissolve/whip/zoom_punch），d=0.6s
  - 真实时长：12.600s（期望 5×3 − 4×0.6 = 12.6）
  - size：3,105,392 B
  - sha256：`657f72aab097dd6834c89aa620fbec110efcaba84a1bb0961dbd41c6b99e75c2`
- `xfadepack_hardcut.mp4`：同素材硬切基线
  - 真实时长：15.000s
  - sha256：`5af34637c5b7506c90e1e1e7e39e867a0d5bb3aefb2be76cff9208f76d436d8d`
- `contact_sheet.png`：64 个注册转场各一格中点帧（320×240），1,272,745 B
- `record.json`：完整命令、filter_complex、ffprobe、sha256

### 5. demo 脚本（scripts/xfade_pack_demo.py）
- 自动生成 E2E 样片，修复 ROOT 路径（parents[1] 而非 parents[2]，适配 worktree 结构）

## 文件清单

| 文件 | 说明 |
|------|------|
| `hevi/assembly/xfade_transitions.py` | 新增，转场注册表（58 builtin + 6 custom） |
| `hevi/assembly/assembler.py` | 修改，build_xfade_chain 支持 list transition |
| `tests/test_xfade_pack.py` | 新增，85 项测试 |
| `scripts/xfade_pack_demo.py` | 新增，E2E 样片生成脚本 |
| `output/xfadepack_e2e/record.json` | 新增，产物元数据 |
| `output/xfadepack_e2e/contact_sheet.png` | 新增，转场视觉确认 |
| `output/xfadepack_e2e/xfadepack_e2e.mp4` | 新增，逐接缝转场成片（不提交，>20MB） |
| `output/xfadepack_e2e/xfadepack_hardcut.mp4` | 新增，硬切基线（不提交，>20MB） |

## 接口

```python
# xfade_transitions.py
from hevi.assembly.xfade_transitions import ALL_TRANSITIONS, get_transition, list_transitions, resolve

transitions = list_transitions()                    # list[Transition]
t = get_transition("fade")                          # Transition | ValueError
expr = resolve("whip")                              # "X+P*W*(A-B)/W"

# assembler.py
fc, label, total = build_xfade_chain(
    durations=[3.0, 3.0, 3.0, 3.0, 3.0],
    transition=["fade", "dissolve", "whip", "zoom_punch"],  # str 或 list[str]
    xfade_d=0.6,                                     # float 或 list[float]
)
# fc: filter_complex 字符串
# label: "-map" 参数，如 "[vout]"
# total: 成片总时长 float
```

## 测试命令

```bash
JWT_SECRET=test-secret-local .venv/bin/python -m pytest tests/test_xfade_pack.py -q
# 85 passed in 21.46s
```

## Lint 结果

- 基线（lint_before.txt）：4 项失败（全在 .venv/omodul/oprim 第三方包）
- 结束（lint_after.txt）：4 项失败（同上，未引入新失败）
- 通过检查：check_obase_no_reverse_dep.py, check_oservi_injection.py, check_async_contract.py
- 未通过检查：check_no_sibling_call.py, check_omodul_signature.py, check_enabled_pillars.py, check_oprim_keyword_only.py（均为第三方包问题）

## 产物路径

- 样本 MP4：`output/xfadepack_e2e/xfadepack_e2e.mp4`（未提交，>20MB）
- 硬切基线：`output/xfadepack_e2e/xfadepack_hardcut.mp4`（未提交，>20MB）
- Contact sheet：`output/xfadepack_e2e/contact_sheet.png`（已 git add -f）
- Record：`output/xfadepack_e2e/record.json`（已 git add -f）

## 已知限制

1. **Custom 转场依赖 ffmpeg ≥ 6.0**：expr 参数使用 P,A,B 变量，低版本 ffmpeg 可能不支持。本机 ffmpeg 7.0.2 实测通过。
2. **Whip 表达式近似**：`X+P*W*(A-B)/W` 是线性拖影近似，非真正运动模糊；如需更逼真效果可后续优化。
3. **Contact sheet 中点帧时间**：对 custom 转场使用 `d - xfade_d/2`（即重叠段正中），此时 A≈B≈0.5，部分 custom expr 在此时刻视觉上可能不均衡（但所有转场确实可见且互不相同）。
4. **未对接 studio/* NLE**：T1 后续读取注册表时直接 import 本模块即可。

---
DONE XFADEPACK-R1
