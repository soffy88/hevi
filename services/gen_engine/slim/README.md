# gen_engine image slimming (2026-10-14)

Every torch in this image is already +cpu. What was still wasted:
- triton (~0.9 GB) in cosy-venv, pulled in by openai-whisper; CUDA-only. The
  Dockerfile now removes it for the cpu variant.
- four Python environments carry byte-identical copies of the same wheels
  (CPU torch ~0.8 GB each, llvmlite, scipy, sympy, ...).

`Dockerfile.gen-engine-repack` slims an already-built image without code changes:
drops triton, hard-links identical files across the environments
(`dedup-hardlink.py`, ~4 GB saved) and flattens the layers. Live image
2026-10-14: 15.4 GB -> 9.0 GB. Rollback tag: `gen_engine-gen-engine:pre-slim-20261014`.
