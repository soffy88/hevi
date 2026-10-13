# XFADEPACK_DONE.md — R2 返工（修复 F1–F5）

本轮是 `feat/xfade-pack` 的返工续做，针对独立核验发现的问题 F1–F5 逐条修复。
基线 `ac09c747`，R1 HEAD `62979470`（核验不通过）。

---

## F1（致命）custom 表达式方向反了 —— 已修

**根因（实测确认）**：ffmpeg xfade custom 里 `P` 从 1 走到 0（P=1 过渡起始=全 A，
P=0 过渡结束=全 B）。实测 `transition=custom:expr=A*P+B*(1-P)` 与内置
`transition=fade` 在 A=黑/B=白 上逐帧完全一致：

```
frame:    13    14    15    16    17    18  ...   29    30    31    32
fade      0     0     0    16    34    50  ...  238   255   255   255
A*P+B*(1-P) 0   0     0    16    34    50  ...  238   255   255   255   <- 逐帧相同
```

而 R1 的表达式（`A*(1-P)+B*P` 一类）实际输出从 255 递减到 0（与 fade 相反）。
核验证据里 R1 各 custom 的 0% 帧是 B 画面、100% 后跳回 B，正是这个方向反了。

**修复**：6 个 custom 全部重写，契约统一为「P=1 输出==A 末帧，P=0 输出==B 首帧，
中间连续」。逐一实测 0/25/50/75/100% 帧见下。

## F2（致命）whip / glitch / burn 输出伪彩乱码 —— 已修

**根因（实测确认）**：custom expr 是**逐像素、逐平面**求值，结果是该像素的**值**，
不能当位移用。R1 的 `X+P*W*(A-B)/W`、`X+(B-A)*sin(P*6.28)*W/4` 把像素横坐标 `X`
当像素值加进去 → 整幅横向渐变伪彩。要取别的位置的像素，只能用 `a0/a1/a2(X,Y)` /
`b0/b1/b2(X,Y)`（本机 ffmpeg 7.0.2 实测可用）。

**实测确认的表达式语义**（用于正确重写）：
- `X,Y` 是**全画面亮度坐标**（在所有平面一致，实测：Y 平面 max=W，U/V 平面 max 也是 W）；
- `W,H` 是**全画面宽高**（不随平面变化，实测：320x240 下所有平面 W=320/H=240）；
- `a0/a1/a2` 分别采样输入 A 的 **Y/U/V** 平面，坐标仍是全画面亮度坐标
  （实测：`a1(X,Y)` 对 160 宽的 U 平面能正确映射到列 159）；
- `PLANE ∈ {0=Y, 1=U, 2=V}`；函数 `if/gt/lt/eq/clip/floor/sin/hypot/abs` 均可用；
- 逗号必须转义为 `\,`，否则破坏 filter_complex 解析（实测：裸逗号 → "Error parsing a filter descriptor"）。

**修复后 6 个 custom（语义 + 实测效果）**：

| id | 语义 | 实现要点 |
|----|------|---------|
| `flash` 闪白 | 前半 A 提亮到白，后半从白回落到 B | 用 `PLANE` 区分：Y 趋近 235、U/V 趋近 128（否则变粉/绿）；中点实测 Y=235, U=128, V=128 |
| `burn` 灼烧 | 以画面中心为圆心的径向掩膜向外扩散 | `mask=clip(((1-P)*1.25 - r)*12,0,1)`，r=归一化到中心的距离；边缘平滑 |
| `ink` 墨晕 | 同 burn，但半径加正弦扰动，边界不规则 | `r += 0.12*sin(X/23)*sin(Y/19)` |
| `whip` 甩镜 | A 向左位移+水平拖影滑出，B 从右带拖影滑入 | 逐平面取样 `a0/a1/a2`，位移 `s=(1-P)*W`，拖影半径 `(1-P)*14`（两端为 0，无跳变），三取样平均模拟运动模糊 |
| `glitch` 故障 | 32px 行块伪随机横向错位，中段混入 B 块 | `n=0.5+0.5*sin(floor(Y/32)*12.9898)`；位移 `4*P*(1-P)` 两端为 0；B 块占比 `1-P` |
| `zoom_punch` 推进冲击 | A 向中心放大冲击，中点切到 B，B 从放大回落到原尺寸 | 缩放系数 `1-0.35*(1-P)`（A）/ `1-0.35*P`（B），两端为 1（无跳变） |

**逐转场 0/25/50/75/100% 帧人工看图确认**（用 testsrc2→smptehdbars 两段 1s、d=1.0，
亲自 Read 三帧拼图）：
- flash：A → 白 → B（中点纯白，无粉/绿伪彩）✅
- burn：中心圆斑扩散、边缘带过渡 ✅
- ink：不规则墨迹晕开 ✅
- whip：A 横向拖影左滑出、B 从右拖影进入，中途画面撕裂但结构完整（非乱码）✅
- glitch：行块横向错位、夹杂 B 色块 ✅
- zoom_punch：A 放大冲击、切 B 后回落 ✅

## F3 测试没测出 F1/F2 —— 已补真实断言

新增（真实 ffmpeg，不 mock，素材用 testsrc2/smptehdbars 两种**有结构**画面）：

- `test_transition_endpoints_match_sources`（64 项，全部 builtin+custom）：
  起始帧 vs A 同时刻帧 SSIM ≥ 0.9 **且** 结束帧 vs B 同时刻帧 SSIM ≥ 0.9。
  **可证伪性实测**：R1 的 6 个 custom 在此断言下 `start_vs_A` 全部落在 0.199–0.386
  （<< 0.9），全部 FAIL —— 证明该断言确实能抓住方向反了。
- `test_transition_midpoint_differs_from_both_sources`（64 项）：中点帧与 A、B 都 SSIM<0.95。
- `test_flash_midpoint_is_white_no_false_color`：中点 Y>200 且 U/V∈128±12。
- `test_custom_midpoint_differs_from_fade`（6 项）：custom 中点 vs 普通 fade 中点 SSIM<0.95。
- `test_custom_exprs_have_no_bare_commas`：表达式无裸逗号。

> 注：曾尝试用「U/V 均值在 128±X」检测所有 custom 的伪彩，实测**不可用**——
> 内置 `slideleft` 因真实空间位移使 U 均值偏移 +28，与伪彩乱码无法区分。故按
> FIX 要求只对 flash 做色彩断言（flash 中点是合成纯白，非内容位移），其余
> custom 靠端点断言（可证伪）+ 中点≠fade 覆盖。逐帧逐列的结构类检测同样实测
> 无法区分（R1 乱码里也混有真实图像内容），未采用。

## F4 证据不实 —— 已重做

- `output/xfadepack_e2e/record.json` **由当前脚本真实重跑生成**：
  - `filter_complex` 现在是 `transition=custom:expr=if(lt(X\,W-(1-P)*W)\,...)`（不再是裸 `transition=whip`）；
  - 含 `command`（真实 ffmpeg argv）、`map_label`、`labels`（64 项）字段。
- 素材改用**有结构**的源：testsrc2 / smptehdbars / rgbtestsrc / testsrc（不再 3 段纯色）；
  4 个接缝 = whip + fade + glitch + zoom_punch（**3 个 custom**，≥2 满足）。
- `contact_sheet.png`：每个注册转场**一行**，含 **25%/50%/75% 三帧** + PIL 写的 id/kind 标签
  （本机静态 ffmpeg 无 drawtext）。已亲自看图确认各转场肉眼可辨。
- R1 文档里「>20MB 未提交」是**错的**：真实尺寸 3.1MB / 5.6MB（见下）。

## F5（小）逐接缝 list 里的 "cut" —— 已修

- `build_xfade_chain`：逐接缝 token 为 `"cut"` 时用 `concat=n=2:v=1:a=0` 直拼，
  总时长公式随之正确（只减非 cut 接缝的 d）。混用 concat 与 xfade 会因各输入
  时基不一致报 "Error reinitializing filters"，故含 cut 的链先给每个输入加
  `settb=AVTB`（实测修复）。
- **无 cut 的链保持原路径逐字不变**（golden 测试继续通过）。
- 空 list 抛 `ValueError("transition list must not be empty")`。
- `assemble_longvideo`：改用 `any(t != "cut" for t in seam_tokens)` 判断是否走 xfade
  （原来只看 `transition[0]`，list 中间出现 cut 会误判），空 list 提前抛 ValueError
  （原来会 IndexError）。
- 真实 E2E：`transition=["fade","cut"]` 三镜头（各 2s）→ 实测 5.500s（=6−0.5）✅；
  `transition="cut"` → 6.000s ✅；空 list 抛错 ✅。

---

## 真实测试输出

```
$ JWT_SECRET=test-secret-local .venv/bin/python -m pytest tests/test_xfade_pack.py -q
226 passed in 89.08s

$ JWT_SECRET=test-secret-local .venv/bin/python -m pytest \
    tests/test_xfade_pack.py tests/test_assembler.py tests/test_assembly.py \
    tests/test_beat_align.py tests/test_video_assemble_workflow.py \
    tests/test_tongjian_assemble.py -q
293 passed, 4 warnings in 132.38s
```

## Lint（前/后）

```
lint_before.txt: PASS=5 FAIL=4
lint_after.txt : PASS=5 FAIL=4
failed(前后相同): check_no_sibling_call.py, check_omodul_signature.py,
                  check_enabled_pillars.py, check_oprim_keyword_only.py
```
4 项失败与基线一致，全部落在第三方 `.venv/`（oprim/omodul），未引入新失败。
`lint_after.txt` 与基线逐字相同（git diff 为空）。

## 产物（真实 ffprobe / sha256）

| 产物 | 时长 | 帧数 | 分辨率 | 大小 | sha256 |
|------|------|------|--------|------|--------|
| `output/xfadepack_e2e/xfadepack_e2e.mp4` | 12.600s | 378 | 1080x1920@30 | 5,072,543 B | `0ca6ef12602e3221e06f146c7631703fcd3cfff5a9a32af12215d60722d71cf8` |
| `output/xfadepack_e2e/xfadepack_hardcut.mp4` | 15.000s | 450 | 1080x1920@30 | 5,596,832 B | `9e3fa7c9048d9eb799d10ac2e579c44e89da80daf0dd129e96a2523666f1d482` |
| `output/xfadepack_e2e/record.json` | — | — | — | 9,844 B | `d34e9367b0fff6c0148bfebdecc301c1e9f81381eb54e40bd63b4aaa864b2b6b` |
| `output/xfadepack_e2e/contact_sheet.png` | — | 64行×3帧 | 726x9216 | 3,108,135 B | `6781f3e9fff3437df397fc8416294f97f4982bc779cca4c161e66fb7c2ad1119` |

- E2E 成片时长 12.600s = 5×3 − 4×0.6 ✅；硬切 15.000s = 5×3 ✅。
- 两个 mp4 均 < 20MB，但仍被 `.gitignore` 的 `output/` + `*.mp4` 忽略（R1 说的「>20MB 未提交」是错的）。
- `record.json` / `contact_sheet.png` 用 `git add -f` 提交（output/ 被忽略）。

## 文件清单（本轮改动）

| 文件 | 改动 |
|------|------|
| `hevi/assembly/xfade_transitions.py` | 6 个 custom 表达式全部重写（F1/F2） |
| `hevi/assembly/assembler.py` | `build_xfade_chain` 支持逐接缝 "cut"+settb；`assemble_longvideo` 用 any() 判 cut、空 list 抛错（F5） |
| `tests/test_xfade_pack.py` | 端点/中点/flash/≠fade 强断言 + cut 测试（F3/F5） |
| `scripts/xfade_pack_demo.py` | 有结构素材、3 custom、contact sheet 三帧+标签、真实 record（F4） |
| `output/xfadepack_e2e/record.json` | 真实重跑生成 |
| `output/xfadepack_e2e/contact_sheet.png` | 三帧/行 + 标签 |

## 已知限制

1. **custom 依赖 ffmpeg ≥ 5.0**（`a0/a1/a2`/`b0/b1/b2` 逐平面取样、`PLANE` 变量）。
   本机 7.0.2 实测通过。
2. **whip/glitch 用三取样平均近似运动模糊**，非真正的方向性模糊核；视觉上可辨，
   但不如专门的 motion-blur 滤镜精确。
3. **含 cut 的链引入 `settb=AVTB`**：纯 xfade 链保持原样，仅当链中出现 cut 时
   才加 settb，避免影响既有行为。
4. **未对接 studio/\* NLE**（按任务书约束，T1 后续直接 import 注册表）。
5. contact sheet 的 64 行图较大（726×9216），单行高 144px 便于快速浏览。

---
DONE XFADEPACK-R2
