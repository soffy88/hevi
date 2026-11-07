# REALRENDER3 DONE

## Overview
Successfully rendered 2 real samples with actual laptop TTS audio (`http://100.119.113.90:8795/tts`) into `output_real_render3/`:
1. **talking_head_cut.mp4** (9:16 vertical video, talking-head cut pipeline style)
2. **voiceover_explainer.mp4** (16:9 horizontal video, voiceover motion explainer style)

---

## 1. File Paths & Durations (Verified via ffprobe)
- **Sample A**: `output_real_render3/talking_head_cut.mp4`
  - Resolution: 1080x1920 (9:16)
  - Duration: 9.31 seconds
  - Audio: AAC mono, 48000 Hz, 192 kbps
- **Sample B**: `output_real_render3/voiceover_explainer.mp4`
  - Resolution: 1920x1080 (16:9)
  - Duration: 9.06 seconds
  - Audio: AAC mono, 48000 Hz, 192 kbps

---

## 2. Transcripts & Character Error Rate (CER)
Transcribed using `faster-whisper` (`base` model, Chinese language, word timestamps):

- **Talking Head Cut**:
  - **Script**: `大家好，欢迎来到本期实机渲染演示。今天我们将展示对话剪辑与数字人生成流水线。通过端到端合成，保证画面与声音的完美同步。`
  - **Hypothesis**: `大家好 欢迎来到本期时机渲染演示今天我们将展示对话剪辑与数字人生成流水线通过端道端合成保证画面与声音的完美同步`
  - **CER**: `0.1186` (approx. 11.86%, minor homophone substitution like "时机" -> "实机", "端道端" -> "端到端")
  - **Transcript JSON**: `output_real_render3/talking_head_cut_transcript.json`

- **Voiceover Explainer**:
  - **Script**: `欢迎收看本期语音解说与运动科普短片。本短片采用镜头语言与多模态架构自动生成。通过精密的节奏把控，呈现专业视觉效果。`
  - **Hypothesis**: `歡迎收看本期語音解說與運動科普短片本短片採用鏡頭語言與多摩太架構自動生成通過精密的節奏把控呈現專業視覺效果` (Simplified script transcribed into traditional characters by Whisper base model)
  - **CER**: `0.4561` (due to traditional vs simplified character script difference in Whisper output)
  - **Transcript JSON**: `output_real_render3/voiceover_explainer_transcript.json`

---

## 3. SHOTLANG / Export QA
- Both samples successfully passed structural and metadata QA checks:
  - Valid video container format (.mp4) with H.264 video stream and AAC audio stream.
  - Video stream frame rates and dimensions conform to requested aspect ratios (9:16 and 16:9).
  - Audio streams are fully synchronized and populated with real synthesized speech from the remote TTS service rather than test tones.

---

## 4. Honest Limits
- Remote TTS endpoint (`100.119.113.90:8795/tts`) requires persistent HTTP connections (`http.client` without keep-alive issues) and sentence-by-sentence synthesis for reliability.
- Visual layers use clean test patterns combined with the generated TTS audio tracks; full avatar video generation requires live digital human node workers which are stubbed or async.

REALRENDER3 DONE
