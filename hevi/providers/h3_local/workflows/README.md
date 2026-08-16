# h3_local 工作流模板约定

本目录放 ComfyUI **API 格式**工作流模板(node_id → `{class_type, inputs}`,
ComfyUI 前端 "Save (API Format)" 导出的那种),客户端只做占位符替换与 ref 裁剪。

## 占位符(客户端替换)

| 占位符 | 含义 |
|---|---|
| `__PROMPT__` | H3 三段式 integrated 描述(中文直出,不走英译) |
| `__LENGTH__` | 帧数(24fps,17k+5 网格,客户端按 duration 算好) |
| `__WIDTH__` / `__HEIGHT__` | 生成分辨率(512/768 档,竖/横由调用方给) |
| `__SEED__` | 种子(未给则随机) |
| `__OUTPUT__` | 输出 filename_prefix |
| `__REF_0__` … `__REF_N__` | 参考图(LoadImage 节点的 image 值;客户端上传后替换为 ComfyUI 侧文件名) |
| `__UNET_GGUF__` / `__CLIP_GGUF__` / `__VIDEO_VAE__` / `__AUDIO_VAE__` | 模型文件名(与 ComfyUI models 目录对应) |

参考图节点按 `__REF_N__` 序号裁剪:给 1 张图时 `__REF_1__` 的 LoadImage 节点与
`ref_image_1` 链接被自动移除。`MiniMaxH3ReferenceToVideo` 无 ref 时退化为纯文生视频。

## 当前模板 (h3_w4a8_zh.json)

8GB 显存档,节点链(与官方 video_minimax_h3_r2v 模板一致):

```
UNETLoader(minimax_h3_fl2va_pruned_w4a8_mixed.safetensors, weight_dtype=default)
  → MiniMaxH3SigmaShift(shift_video 12.0 / shift_audio 3.0)
CLIPLoaderGGUF(qwen3vl-32B-MiniMax-H3-Q2_K.gguf, type=minimax)
VAELoader(video_vae) + VAELoader(audio_vae)
  → MiniMaxH3ReferenceToVideo(prompt/width/height/length/ref_image_N)
  → BasicGuider + RandomNoise + KSamplerSelect(res_multistep)
    + BasicScheduler(simple, 20) → SamplerCustomAdvanced
  → VAEDecode(视频) + VAEDecodeAudio(音频)
  → CreateVideo(24fps) → SaveVideo(mp4)
```

模型栈说明(2026-08-16 起):

- **UNET 用 safetensors 而非 GGUF**:`minimax_h3_fl2va_pruned_w4a8_mixed.safetensors`
  (已量化 w4a8,故 `weight_dtype` 必须 `default`,不能再 cast);放在 ComfyUI
  `models/diffusion_models/`。
- **CLIP 仍走 GGUF**:`qwen3vl-32B-MiniMax-H3-Q2_K.gguf`(Q2_K 量化,
  `models/text_encoders/`),`CLIPLoaderGGUF(type=minimax)` 不变。
- **VAE 不变**:`minimax_h3_video_vae_fp16.safetensors` + `minimax_h3_audio_vae_fp32.safetensors`。
- 环境变量 `H3_UNET_GGUF`/`H3_CLIP_GGUF` 名称沿用(历史兼容),实际值为上表文件名。

## 换模板须知

- 用 ComfyUI 前端把工作流调好后,右上角菜单 → "Save (API Format)" 导出 JSON,
  把节点里的输入替换成上述占位符即可;客户端按 class_type 只认 `LoadImage` 的
  `__REF_N__` 约定,其余节点一律不动。
- 音频必须接 `CreateVideo`/`VHS_VideoCombine` 的 audio 输入 —— H3 原生音频是
  hevi「对白优先用 H3 原音」纪律的来源,别丢。
