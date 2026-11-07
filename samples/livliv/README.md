# LivLiv 样片（2026-11-07）
- 角色渲染（512x512 30fps，edge-tts 32.3s 同款口播，SwiftShader）：
  - d03ft/clip.mp4（Nana refined，68s/370MB RSS）
  - d01/clip.mp4（Yui，63s/321MB）
  - v06/clip.mp4（Usa，64s/320MB）
  - 对齐：samples/livliv/alignment.json（1s/30帧 corr=0.95）
- 口播精剪 engine=livliv（1080x1920，证据2/2）：
  - koubo_run1/koubo_cut.mp4（d03ft，153s）、koubo_run2（d01，132s）、koubo_run3（v06，138s）
  - contact_sheet_6frames.png / contact_run1-3.png / contact_sheet.png
- 基线：static_baseline.mp4（wav2lip 本地链上游 ImportError 真坏 → 静态回退等价物，32.3s）
  评委（hevi/judge opencode 换位对比，硬伤预过滤决定性 A=0 vs B=18，模型调用 0）：Winner=A（livliv）。
- 许可：hevi/avatar_livliv/licenses/；署名 Characters: LivLiv (livliv.ai)，AI制作。
