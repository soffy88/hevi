# HANDDRAW-R2 完成核验报告

工作树：/data/soffy/projects/hevi-handdraw
分支：feat/handdraw-line
原则：仅在本工作树改动；CPU/本地 TTS；未调用付费 API；未清理磁盘或删除文件。成人人工审片没有伪报为已完成，报告均明确标记为 pending。

## F1 — 旁白采样时间戳与渲染随机崩溃
- 将 beat 起止时间统一以 master WAV 的整数采样点表示，不再对秒数做四位小数舍入；load_master 的范围始终受实际样本长度约束。
- 增加 30 组随机 beat 样本的 build_narration_master → load_master 往返回归。
- 实测：随机时间戳回归在目标 pytest 中通过；另对四种风格（1/8/10/17）× 横/竖画幅各用相同 seed 渲染两次，16/16 成功、8/8 对的 MP4 SHA-256 一致；ffprobe 每条预览均为 2.000 秒。

## F2 — CosyVoice 批量合成与一致音色
- 改成整批一次请求，CosyVoice 超时默认 360 秒；批响应只有在含有与 beats 数量一一对应的 WAV 时才接受。对无法证明句子边界的单个拼接 WAV 不复用到每个 beat，整篇回退到 Piper，避免错误时间轴与混合音色。
- alignment 逐 beat 记录实际 engine、caption 对齐来源和语速。当前 127.0.0.1:17600 服务不可连接（本次健康探测 HTTP 000），因此这次实际成片的引擎如实为 Piper，未声称测过在线 CosyVoice 服务。
- 实测：CosyVoice ZIP 批响应、请求超时和不接受多句单 WAV 的本地传输回归通过；两条长片 alignment 都记录单一 piper，没有混用引擎。在线 gen-engine 服务不可用，在线服务端到端一项留作环境限制。

## F3 — 主题剧本、参数、时长与 seed
- 用确定性幼儿模板替代原来非 anger 主题都落到成人“复利效应”的路由。已实现轮流分享、刷牙、收拾玩具模板，结构覆盖问候、问题、尝试、解决、复述、行动、告别、互动提问。
- Capability render 入口统一 schema 校验，非法字段/JSON Schema 错误统一转换为 CapabilityError；不支持的 aspect、非法 duration/seed、缺失产物不再假成功。非法风格/手型不再静默替换。
- duration=2/3 是真实部分 MP4，duration=0 为完整交付。注册 API 的三秒预览被真实渲染并经 ffprobe 核验，响应头 x-capability-duration=3.000。同 seed PNG 与 MP4 SHA 测试通过。
- 实测：完整分享片 48.433333s, 1920×1080，音轨 48.430s，SHA-256 7bfc69212d5d6a4c9c06493e2b656c84752f2aea7511381823a810c9dd92d664；刷牙片 56.566667s, 1080×1920，音轨 56.551s，SHA-256 0c6b22f09990e3190c1d4ab9f22e5e2645e78f47834376ffcd5bc29b7ae50392。两个完整视频均为 4 页，完整时间轴解码检查通过。

## F4 — 四风格实质区分与透明画布
- 实现局部裁切笔刷光栅化、稳定 seed 随机纹理、淡彩速写松散构图/水彩、风格独立构图尺度与笔触配方；语义多边形外沿柔边像素归属修正，避免渲染时因轮廓空隙崩溃。
- 同一场景、800×800、seed=11 的最终图像与固定纸色合成后两两比较 SSIM：
  - 1–8 0.8051
  - 1–10 0.8291
  - 1–17 0.8032
  - 8–10 0.8071
  - 8–17 0.8026
  - 10–17 0.8304
- 最大 SSIM 0.8304 < 0.85；四张 PNG 均为 RGBA，画布角像素 alpha 为 0，没有不透明方形底板。

## F5 — 幼儿字幕、ASR 对齐与手部遮挡
- 横屏字幕字号 56px、竖屏 60px（合同底线分别为 48/56）；字幕按实际 ASR 字/词时间戳对齐，切句上限 12 字，去除孤立标点。视频渲染器先叠加手部，再将唯一一层字幕置于最上方。
- 对实际生成的第一句 TTS WAV 独立运行本地 CPU ASR 并重新计算 cue 时间，测试测得起点误差 p95 ≤ 0.2 秒；PCM 能量起点误差 ≤ 0.2 秒。不是读取自报 verification 数字代替测量。
- 实际成片字幕为烧录字幕；ffprobe/交付验证为 0 字幕流、0 相邻 sidecar，无重复字幕轨。

## F6 — 真实产物与缺失产物负测
- 测试 fixture 每次在本工作树 pytest 临时目录重新渲染实际 2 秒 MP4；分别用 ffprobe 检查时长、分辨率、视频/音频流；用 PCM RMS 检查非静音；用 ffmpeg loudnorm 独立测 LUFS 与 true peak；用 CPU ASR 检查字幕时序。
- 实测预览：2.000 秒、1920×1080，视频和音频时长均 2.000 秒；独立 loudnorm 输入 I -16.94 LUFS、真峰值 -2.00 dBTP。
- 对解码 MP4 的 RGB 帧（320×180、8fps、画面上方 80%）直接统计可见墨迹，未读取 reveal/NPZ。实测 16 帧的像素计数为 [0, 0, 0, 967, 3921, 4081, 4011, 3857, 4108, 4034, 4162, 4118, 3971, 4176, 4143, 3950]；首末 0 → 3950，最大相邻下降 193（5% 阈值 208），6 个相邻帧上升；此外也断言从实际解码帧累积得到的覆盖率增加且单调。
- 缺失产物负测分别临时移开并复原视频、封面、master WAV、review、drawing plan、timeline、assets 目录，每一种都必须触发 hard failure；无 skip。

## F7 — KIDS_ANIME_DIRECTION 幼儿向闸门
- 规则闸门输出 JSON，检查禁用词、阶段顺序/台词标记、面向幼儿的语言、语速、字幕字号，以及可用时的实测 LUFS/true peak；自动检查和人工审核状态分开记录。成人主题负测被闸门拒绝。
- 完整横屏《小狐狸学会轮流》：语速 3.4771 字/秒，源混音 -15.76 LUFS、-2.00 dBTP，输出 loudnorm 实测 -16.87 LUFS、-2.03 dBTP，字幕 56px，规则闸门通过。
- 完整竖屏《为什么要刷牙》：语速 3.0619 字/秒，源混音 -15.79 LUFS、-2.00 dBTP，输出 loudnorm 实测 -16.72 LUFS、-2.38 dBTP，字幕 60px，规则闸门通过。
- 两份报告都把 human_review 标为 pending；工程检查通过不等于成人内容/视觉/听感人工审片已完成。

## F8 — Studio handdraw runtime 回归
- handdraw 纳入受支持的 render runtime 列表，Studio Slate 测试不再因仅允许 remotion/hyperframes/ffmpeg 而失败。
- 实测 tests/test_studio_slate.py：8 passed in 8.73s。

## 能力契约、NOTICE 与假审核修复
- 已接 GET /api/capabilities 和 POST /api/capabilities/{name}/preview，端点调用真实 registry/render，不是虚构响应。
- 注册能力：handdraw.full、handdraw.storyboard、handdraw.narration、handdraw.illustration。
- NOTICE 增加 sweety-handdraw-video 来源说明。review.json 与 drawing/art-direction review 将自动检查标记为 automated_only，人工内容、视觉、运动、音频、隐私审核如实写 not_reviewed/pending，不再硬编码人工通过。
- handdraw_resume_portrait.py 仅保留为 debug-only 历史工具，E2E 不依赖它。

## 实测测试与 lint
- 验收命令：JWT_SECRET=test-only TMPDIR=.tmp /data/soffy/projects/hevi/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_handdraw_capabilities.py tests/test_handdraw_deliverables.py
  - 结果：22 passed in 67.81s，exit code 0。
- 额外回归：JWT_SECRET=test-only TMPDIR=.tmp /data/soffy/projects/hevi/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_studio_slate.py
  - 结果：8 passed in 8.73s，exit code 0。
- /home/soffy/.local/bin/ruff check 对本次涉及的 21 个 Python 源/测试文件：All checks passed!；py_compile 通过；git diff --check 通过。
- 3O v3 lint 实跑结果：3O_V3_LINT=FAIL，9 个检查中 5 PASS / 4 FAIL；失败清单为 check_no_sibling_call.py、check_omodul_signature.py、check_enabled_pillars.py、check_oprim_keyword_only.py，错误均定位到虚拟环境 .../hevi/.venv/lib/python3.14/site-packages/oprim|omodul 的既有文件，而非本 worktree。失败数为 4，不超过 HANDDRAW_FIX.md 中给出的基线 4。遵守硬规则，没有修改该虚拟环境或主 checkout，也没有把 lint 日志加入 Git。
DONE HANDDRAW-R2
