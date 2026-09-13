# Provider readiness

| Provider | Status | Configured | Secret present | Endpoint | Blocker |
|---|---|---|---|---|---|
| h3_local | BLOCKED_HARDWARE | False | True | http://127.0.0.1:8188 | nvidia-smi/CUDA unavailable |
| ComfyUI/local_gpu_backend | BLOCKED_HARDWARE | False | True | http://127.0.0.1:8188 | nvidia-smi/CUDA unavailable |
| llm | BLOCKED_SECRET | False | False | local | required configuration/secret absent |
| remotion | READY | True | True | local | — |
| tts | READY | True | True | local | — |
| media_source | READY | True | True | local | — |
| hyperframes | READY | True | True | local | — |
