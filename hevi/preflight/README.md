# hevi.preflight —— 生成前三件套

目标：生成 prompt 一次能过，失败不烧钱。门禁与编译全程本地离线，
不登录谷歌、不调 Flow/Gemini API；烧 credits 的动作永远在门禁之后。

## 三件

1. **门禁套件**（`gate.run_gate`）：prompt 审计 → 首帧验真 →
   对白适配 → 成本预估＋预算门。任一 FAIL 即 blocked，不许发；
   人工 override 须留理由，FAIL 记录不删除。
   - prompt 审计：复用通鉴既有现代词黑名单
     （`hevi.tongjian.script._MODERN_VOCAB_BLACKLIST`），作用域与通鉴一致
     （只约束 narration/dialogue/commentary，modern_echo 豁免）；
     无文字声明硬查（须在编译后 prompt 里）；定妆引用／可执行描述检查。
   - 首帧验真：文件存在、画幅匹配是硬查；与定妆的漂移只用色彩直方图
     作粗信号（超极端阈才 WARN），**不许写成脸判定**；伪文字无 OCR 手段，
     只出人工目视清单（牌匾／题字／脸／画风三项必出）。
   - 对白适配：普通话清晰上限 4.5 字／秒，硬上限 6.0 字／秒；
     8 秒窗清晰预算 36 字、>48 字 FAIL；讲解段走 TTS，不占视频窗口。
   - 预算门：月度剩余是硬上限（超了 FAIL）；当日 50 点是赠额非硬 cap
     （超了只 WARN，2026-10-24 当天实花 80 credits 即证）；PixStag 按秒
     USD 无本地台账，只 INFO；SVI 本地 GPU credits 为 0。
2. **prompt 编译器**（`compiler.compile_beat`）：beat → Veo Fast（8 秒）／
   Omni Flash（10 秒）／SVI-Film（每 5 秒一段 prompt-stream）等模型 prompt；
   画风锁定段、人物锁定段、无文字段自动拼；输出结构化 JSON＋可读文本，
   缺字段只 warning、不编造。
3. **一次通过率统计**（`passrate.PassRateLedger`）：JSONL 记录每次生成
   （prompt 哈希、模型、成本、过／不过＋失败原因六分类）；
   一次通过率按“首条记录即 pass 的 beat”算；反哺报告把失败模式映射到
   模板修正建议。

## 能力注册

`preflight.gate`／`preflight.compile`／`preflight.passrate`
（见 `capabilities.py`，与 stickman 同模式），由
`hevi/capabilities/__init__.py` 尾部钩子注册。

## 诚实边界

- 脸漂移、伪文字目前**不能自动判定**：门禁只能做到“粗信号＋强制人工
  目视清单”，回测结论见 BACKTEST.md，不得对外谎称已自动验真。
- 对白转写含糊是生成后问题：门禁只能拦超窗赶话；含糊本身由生成后
  ASR 验真（如 faster-whisper）捕获，再记进通过率台账。
- 计价口径以 2026-10-24 实测为准（Veo Fast 20／Lite 10／Quality 100／
  Omni Flash 15 per 10s／PixStag $0.015/s）；模型调价须同步改
  `beats.MODEL_SPECS`，不得在调用处手写数字。
