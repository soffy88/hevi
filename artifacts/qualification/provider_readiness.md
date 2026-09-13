# Provider readiness

| Provider | Status | Secret present | Probe | Blocker |
|---|---|---|---|---|
| h3_local | BLOCKED_HARDWARE | True | False | nvidia-smi/CUDA unavailable |
| ComfyUI/local_gpu_backend | BLOCKED_HARDWARE | True | False | nvidia-smi/CUDA unavailable |
| llm | READY | False | True | — |
| remotion | READY | True | True | — |
| tts | READY | True | True | — |
| media_source | READY | True | True | — |
| hyperframes | READY | True | True | — |
