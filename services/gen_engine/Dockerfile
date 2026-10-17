# HEVI AI Engine — 统一 GPU 算力引擎
#
# 底座:git 子模块 services/voicebox(上游 voicebox Qwen3-TTS 项目), 保留其
# profiles/generate/audio 等音色克隆端点; 在此之上挂载 HEVI 的 /api/ai/* 端点
# (CosyVoice TTS / LongCat Talking Face), 并单独安装 vibevoice 到独立
# ai-venv(Python 3.11)以隔离其严格版本钉(accelerate==1.6.0 等)。
#
# Build context: 仓库根(需含 services/voicebox 子模块检出)
# Usage: docker compose -f deploy/docker-compose-cftunnel.yml build hevi-gen-engine

# PYTORCH_VARIANT: cpu(默认) | rocm | 其他(=PyPI 默认 CUDA 轮子)。
# 注意: FROM 之前的全局 ARG 不会自动进入各 stage —— 每个装 torch 的 stage 必须
# 自己再声明 `ARG PYTORCH_VARIANT`, 否则变量为空, 走 else 分支装成 PyPI 的
# CUDA 版 torch(2026-10-10 cosy-ref-v1 镜像因此装成 torch 2.14.1+cu130 + 16 个
# nvidia-* 包, 29 GB)。
# cpu 变体: torch/torchaudio 一律从 download.pytorch.org/whl/cpu 装, 随即把装上的
# 版本(+cpu)写成 pip constraints(PIP_CONSTRAINT), 并把 cpu 索引加到
# PIP_EXTRA_INDEX_URL; 后续 requirements/依赖解析既不能换成 CUDA 版 torch, 也拉
# 不进 nvidia-*(版本冲突时构建直接失败而不是静默换包)。最终 stage 末尾逐个
# python 环境校验 +cpu / cuda=None / 无 nvidia-*。
ARG PYTORCH_VARIANT=cpu

FROM oven/bun:1 AS frontend
WORKDIR /build
COPY services/voicebox/package.json services/voicebox/bun.lock services/voicebox/CHANGELOG.md ./
COPY services/voicebox/app/ ./app/
COPY services/voicebox/web/ ./web/
RUN sed -i 's/\r$//' package.json && \
    sed -i '/"tauri"/d; /"landing"/d' package.json && \
    sed -i -z 's/,\n  ]/\n  ]/' package.json
RUN bun install --no-save
RUN cd web && bunx --bun vite build

FROM python:3.11-slim AS backend-builder
ARG PYTORCH_VARIANT=cpu
ARG ROCM_VERSION=6.3
WORKDIR /build
RUN apt-get -o Acquire::Retries=8 -o Acquire::http::Timeout=60 update && apt-get -o Acquire::Retries=8 -o Acquire::http::Timeout=60 install -y --no-install-recommends git build-essential && rm -rf /var/lib/apt/lists/*  # apt retries: sing-box 代理间歇 502
RUN pip install --no-cache-dir --timeout 120 --retries 8 --upgrade pip
COPY services/voicebox/backend/requirements.txt .
RUN if [ "$PYTORCH_VARIANT" = "rocm" ]; then \
      pip install --no-cache-dir --timeout 120 --retries 8 --prefix=/install --index-url "https://download.pytorch.org/whl/rocm${ROCM_VERSION}" torch torchaudio && \
      printf '[global]\nindex-url = https://download.pytorch.org/whl/rocm%s\nextra-index-url = https://pypi.org/simple\n' "$ROCM_VERSION" > /etc/pip.conf; \
    elif [ "$PYTORCH_VARIANT" = "cpu" ]; then \
      pip install --no-cache-dir --timeout 120 --retries 8 --prefix=/install --index-url "https://download.pytorch.org/whl/cpu" torch torchaudio && \
      printf '[global]\nindex-url = https://download.pytorch.org/whl/cpu\nextra-index-url = https://pypi.org/simple\n' > /etc/pip.conf; \
    fi && \
    # cpu: 钉住刚装的 torch/torchaudio(+cpu), requirements 的 torch>=2.2.0 等不得换包
    if [ "$PYTORCH_VARIANT" = "cpu" ]; then \
      pip freeze --path /install/lib/python3.11/site-packages | grep -iE '^(torch|torchaudio)==' > /tmp/torch-pin-system.txt && \
      grep -q '+cpu' /tmp/torch-pin-system.txt; \
    else : > /tmp/torch-pin-system.txt; fi && cat /tmp/torch-pin-system.txt
RUN PIP_CONSTRAINT=/tmp/torch-pin-system.txt pip install --no-cache-dir --timeout 120 --retries 8 --prefix=/install -r requirements.txt
RUN pip install --no-cache-dir --timeout 120 --retries 8 --prefix=/install --no-deps chatterbox-tts
RUN pip install --no-cache-dir --timeout 120 --retries 8 --prefix=/install --no-deps hume-tada

# ── 独立 ai-venv:vibevoice 及其严格版本钉(不污染 voicebox 运行环境) ──
# fish-speech 同样进 ai-venv —— 其依赖(audiotools/numpy<=1.26.4)与 voicebox 冲突。
# 注: audiotools 已从 PyPI 移除且 git 源在 CI 构建环境不可达, fish-speech 作为
# 可选能力暂不强制安装(端点保留, 缺失时 501 降级); 后续在可访问 GitHub 的环境补装。
RUN apt-get -o Acquire::Retries=8 -o Acquire::http::Timeout=60 update && apt-get -o Acquire::Retries=8 -o Acquire::http::Timeout=60 install -y --no-install-recommends \
    portaudio19-dev ffmpeg \
    && rm -rf /var/lib/apt/lists/*  # apt retries: sing-box 代理间歇 502
RUN python -m venv /opt/ai-venv && \
    /opt/ai-venv/bin/pip install --no-cache-dir --timeout 120 --retries 8 --upgrade pip && \
    if [ "$PYTORCH_VARIANT" = "cpu" ]; then \
      /opt/ai-venv/bin/pip install --no-cache-dir --timeout 120 --retries 8 --index-url "https://download.pytorch.org/whl/cpu" torch torchaudio && \
      /opt/ai-venv/bin/pip freeze | grep -iE '^(torch|torchaudio)==' > /tmp/torch-pin-ai.txt && \
      grep -q '+cpu' /tmp/torch-pin-ai.txt && \
      # 本 stage 的 /etc/pip.conf 已是 index-url=cpu + extra-index-url=pypi; 这里不能再设
      # PIP_EXTRA_INDEX_URL(环境变量会覆盖 pip.conf 的 pypi extra, vibevoice 就找不到)。
      export PIP_CONSTRAINT=/tmp/torch-pin-ai.txt; \
    else \
      /opt/ai-venv/bin/pip install --no-cache-dir --timeout 120 --retries 8 torch torchaudio; \
    fi && \
    /opt/ai-venv/bin/pip install --no-cache-dir --timeout 120 --retries 8 \
      "vibevoice==0.0.1" \
      "transformers==4.51.3" \
      "accelerate==1.6.0" \
      "diffusers>=0.30" \
      "numpy" "scipy" "librosa" "numba>=0.57" "llvmlite>=0.40" "tqdm" && \
    /opt/ai-venv/bin/pip install --no-cache-dir --timeout 120 --retries 8 \
      "fish-speech==0.1.0" \
      "git+https://github.com/descriptinc/audiotools.git" \
      "tiktoken" "soundfile" "pyyaml" "einops" "omegaconf" "fire" "loguru" "vector-quantize-pytorch" && \
    # ── F5-TTS 零样本音色克隆(f5-tts 依赖与 voicebox 主环境兼容, 进 ai-venv) ──
    /opt/ai-venv/bin/pip install --no-cache-dir --timeout 120 --retries 8 --no-deps "f5-tts==1.1.21" && \
    /opt/ai-venv/bin/pip install --no-cache-dir --timeout 120 --retries 8 \
      "vocos" "pydub" "matplotlib" "cached_path" "hydra-core" "ema-pytorch" \
      "wandb" "pypinyin" "rjieba" "tomli" "click" "x-transformers"

# ── 独立 cosy-venv:重供货 CosyVoice(transformers==5.13 + 行为补丁) ──
# 与 ai-venv 的 transformers==4.51.3(vibevoice)版本钉冲突, 单独 venv
# (同 asr-venv 模式)。cosyvoice/ + third_party/Matcha-TTS 为 vendored 代码,
# 拷入 site-packages(见 services/gen_engine/cosyvoice/README.md)。
FROM python:3.11-slim AS cosy-builder
ARG PYTORCH_VARIANT
WORKDIR /build
RUN apt-get -o Acquire::Retries=8 -o Acquire::http::Timeout=60 update && apt-get -o Acquire::Retries=8 -o Acquire::http::Timeout=60 install -y --no-install-recommends build-essential git ffmpeg \
    && rm -rf /var/lib/apt/lists/*  # apt retries: sing-box 代理间歇 502
RUN python -m venv /opt/cosy-venv && \
    /opt/cosy-venv/bin/pip install --no-cache-dir --timeout 120 --retries 8 --upgrade pip && \
    if [ "$PYTORCH_VARIANT" = "cpu" ]; then \
      /opt/cosy-venv/bin/pip install --no-cache-dir --timeout 120 --retries 8 --index-url "https://download.pytorch.org/whl/cpu" torch torchaudio && \
      /opt/cosy-venv/bin/pip freeze | grep -iE '^(torch|torchaudio)==' > /tmp/torch-pin-cosy.txt && \
      grep -q '+cpu' /tmp/torch-pin-cosy.txt && \
      export PIP_CONSTRAINT=/tmp/torch-pin-cosy.txt PIP_EXTRA_INDEX_URL="https://download.pytorch.org/whl/cpu"; \
    else \
      /opt/cosy-venv/bin/pip install --no-cache-dir --timeout 120 --retries 8 torch torchaudio; \
    fi && \
    /opt/cosy-venv/bin/pip install --no-cache-dir --timeout 120 --retries 8 \
      "transformers==5.13.0" "accelerate" "einops" "hyperpyyaml" "omegaconf" \
      "x-transformers" "inflect" "onnxruntime" "pyarrow" "pyworld" "regex" \
      "gdown" "wetext>=0.1.4" "modelscope" "librosa" "soundfile" "numpy" \
      "tqdm" "scipy" "huggingface-hub" "pydantic" "jieba" "pypinyin" \
      "openai-whisper" "tiktoken" \
      "conformer==0.3.2" "diffusers==0.29.0" "lightning==2.2.4" \
      "wget" "rich" "json5" "matplotlib" "rootutils" "pillow" && \
    # hydra-core 1.3.2 的 OverrideLexer/Parser 由 antlr 4.9 生成(ATN v3), 只能配
    # antlr4-python3-runtime==4.9.3; 装 4.13 会在 import cosyvoice.flow.flow_matching
    # 时报 "Could not deserialize ATN with version 3 (expected 4)", cosy_worker
    # exit=1(2026-10-10 CPU 部署实测)。4.9.3 只有 sdist, pip 可本地构建(ai-venv 同样
    # 如此装上)。omegaconf 同步钉 2.3.0(hydra 1.3.2 声明 omegaconf<2.4)。
    /opt/cosy-venv/bin/pip install --no-cache-dir --timeout 120 --retries 8 --no-deps \
      "hydra-core==1.3.2" "omegaconf==2.3.0" "antlr4-python3-runtime==4.9.3"
# cpu: openai-whisper pulls triton (~0.9 GB) on x86_64; it only serves CUDA
# kernels (whisper imports it lazily inside try), so drop it for the cpu variant.
RUN if [ "$PYTORCH_VARIANT" = "cpu" ]; then \
      rm -rf /opt/cosy-venv/lib/python3.11/site-packages/triton \
             /opt/cosy-venv/lib/python3.11/site-packages/triton-*.dist-info; \
    fi
COPY services/gen_engine/cosyvoice/ /opt/cosy-venv/lib/python3.11/site-packages/cosyvoice/
COPY services/gen_engine/third_party/Matcha-TTS/matcha/ /opt/cosy-venv/lib/python3.11/site-packages/matcha/

# ── VibeASR.cpp CPU 推理引擎: 容器内编译(宿主 GLIBC 2.43 vs 容器 2.41 不兼容) ──
FROM python:3.11-slim AS vibeasr-builder
RUN apt-get -o Acquire::Retries=8 -o Acquire::http::Timeout=60 update && apt-get -o Acquire::Retries=8 -o Acquire::http::Timeout=60 install -y --no-install-recommends build-essential cmake git \
    && rm -rf /var/lib/apt/lists/*  # apt retries: sing-box 代理间歇 502
COPY services/gen_engine/vibeasr-src/ /build/vibeasr/
WORKDIR /build/vibeasr
RUN cmake -B build -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=OFF \
    && cmake --build build -j4 --target asr_infer
FROM python:3.11-slim
ARG PYTORCH_VARIANT
RUN groupadd -r voicebox && useradd -r -g voicebox -m -s /bin/bash voicebox
WORKDIR /app
RUN apt-get -o Acquire::Retries=8 -o Acquire::http::Timeout=60 update && apt-get -o Acquire::Retries=8 -o Acquire::http::Timeout=60 install -y --no-install-recommends \
    ffmpeg sox curl gosu gcc g++ make \
    && rm -rf /var/lib/apt/lists/*  # apt retries: sing-box 代理间歇 502  # gcc: qwen-tts 的 triton CUDA kernel JIT 编译必需
# VibeASR.cpp 编译产物(容器内编译, GLIBC 匹配)
COPY --from=vibeasr-builder /build/vibeasr/build/bin/asr_infer /opt/vibeasr/asr_infer
COPY --from=vibeasr-builder /build/vibeasr/build/3rdparty/llama.cpp/src/libllama.so \
     /build/vibeasr/build/3rdparty/llama.cpp/ggml/src/libggml.so /opt/vibeasr/
ENV LD_LIBRARY_PATH=/opt/vibeasr:${LD_LIBRARY_PATH}
COPY --from=backend-builder /install /usr/local
COPY --from=backend-builder /opt/ai-venv /opt/ai-venv
COPY --from=cosy-builder /opt/cosy-venv /opt/cosy-venv
COPY --chown=voicebox:voicebox services/voicebox/backend/ /app/backend/
# ── ASR 独立 venv: VibeVoice-ASR-HF 需要 transformers>=5.3.0, 与 ai-venv 的 4.51.3 隔离。 ──
RUN python -m venv /opt/asr-venv && \
    /opt/asr-venv/bin/pip install --no-cache-dir --timeout 120 --retries 8 --upgrade pip && \
    if [ "$PYTORCH_VARIANT" = "cpu" ]; then \
      /opt/asr-venv/bin/pip install --no-cache-dir --timeout 120 --retries 8 --index-url "https://download.pytorch.org/whl/cpu" torch && \
      /opt/asr-venv/bin/pip freeze | grep -iE '^torch==' > /tmp/torch-pin-asr.txt && \
      grep -q '+cpu' /tmp/torch-pin-asr.txt && \
      export PIP_CONSTRAINT=/tmp/torch-pin-asr.txt PIP_EXTRA_INDEX_URL="https://download.pytorch.org/whl/cpu"; \
    fi && \
    /opt/asr-venv/bin/pip install --no-cache-dir --timeout 120 --retries 8 \
      "transformers>=5.3.0" "torch" "accelerate" "bitsandbytes" "soundfile" "librosa" "numpy" "huggingface-hub" && \
    rm -f /tmp/torch-pin-asr.txt

# ── cpu 变体守门: 每个 python 环境必须是 +cpu torch、cuda=None、无 nvidia-* ──
RUN if [ "$PYTORCH_VARIANT" = "cpu" ]; then \
      for py in /usr/local/bin/python /opt/ai-venv/bin/python /opt/cosy-venv/bin/python /opt/asr-venv/bin/python; do \
        $py -c "import sys, torch; v = torch.__version__; print(sys.executable, v, torch.version.cuda); assert v.endswith('+cpu') and torch.version.cuda is None, v" || exit 1; \
        if $py -m pip list 2>/dev/null | grep -i nvidia; then echo "FAIL: nvidia-* packages in $py"; exit 1; fi; \
      done; \
    fi

COPY --chown=voicebox:voicebox services/gen_engine/ /app/gen_engine/
COPY --chown=voicebox:voicebox services/gen_engine/vibevoice_asr/modular/modeling_vibevoice_asr.py \
     /opt/ai-venv/lib/python3.11/site-packages/vibevoice/modular/modeling_vibevoice_asr.py
COPY --chown=voicebox:voicebox services/gen_engine/vibevoice_asr/modular/configuration_vibevoice.py \
     /opt/ai-venv/lib/python3.11/site-packages/vibevoice/modular/configuration_vibevoice.py
COPY --chown=voicebox:voicebox services/gen_engine/vibevoice_asr/processor/vibevoice_asr_processor.py \
     /opt/ai-venv/lib/python3.11/site-packages/vibevoice/processor/vibevoice_asr_processor.py
COPY --chown=voicebox:voicebox services/gen_engine/vibevoice_asr/processor/audio_utils.py \
     /opt/ai-venv/lib/python3.11/site-packages/vibevoice/processor/audio_utils.py
# fish-speech v1.5.1 VQGAN(FSQ 架构, firefly_gan_vq): 0.1.0 包缺 vqgan 模块。
COPY --chown=voicebox:voicebox services/gen_engine/fish_vqgan/models/vqgan/ \
     /opt/ai-venv/lib/python3.11/site-packages/fish_speech/models/vqgan/
COPY --chown=voicebox:voicebox services/gen_engine/fish_vqgan/configs/firefly_gan_vq.yaml \
     /opt/ai-venv/lib/python3.11/site-packages/fish_speech/configs/firefly_gan_vq.yaml
COPY --chown=voicebox:voicebox services/gen_engine/fish_vqgan/utils/spectrogram.py \
     /opt/ai-venv/lib/python3.11/site-packages/fish_speech/utils/spectrogram.py
COPY --chown=voicebox:voicebox services/gen_engine/vibevoice_asr/modular/modular_vibevoice_text_tokenizer.py \
     /opt/ai-venv/lib/python3.11/site-packages/vibevoice/modular/modular_vibevoice_text_tokenizer.py
COPY --from=frontend --chown=voicebox:voicebox /build/web/dist /app/frontend/
RUN mkdir -p /app/data/generations /app/data/profiles /app/data/cache /home/voicebox/.cache/huggingface && chown -R voicebox:voicebox /app/data /home/voicebox/.cache
EXPOSE 17493
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=60s CMD curl -f http://localhost:17493/api/ai/health || exit 1
COPY --chmod=755 services/voicebox/scripts/rocm-entrypoint.sh /usr/local/bin/rocm-entrypoint.sh
# 非 root 运行时 rocm-entrypoint 的 gosu 会失败, 由 gen_engine 自带入口按 uid 分流。
COPY --chmod=755 services/gen_engine/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh /usr/local/bin/rocm-entrypoint.sh
USER voicebox
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "gen_engine.server:app", "--host", "0.0.0.0", "--port", "17493"]
