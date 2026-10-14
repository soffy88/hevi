#!/bin/sh
# Replace a CUDA build of torch in a venv with the CPU-only wheel of the same
# version and drop the CUDA runtime packages (nvidia-*, cuda-*, triton).
# The deployment host has no usable GPU, so torch.cuda was never available at
# runtime; CPU torch behaves the same for every code path that runs here.
# Usage: strip-cuda-venv.sh <venv-dir>   (env TORCH_INDEX overrides the index)
set -eu
VENV="$1"
SP=$(echo "$VENV"/lib/python3*/site-packages)
ver() { ls -d "$SP/$1"-[0-9]*.dist-info 2>/dev/null | head -1 | sed -E "s#.*/$1-([^/]+)\.dist-info#\1#; s/\+.*//"; }
TORCH_V=$(ver torch); TV_V=$(ver torchvision); TA_V=$(ver torchaudio)
rm -rf "$SP"/nvidia "$SP"/nvidia_*.dist-info "$SP"/triton "$SP"/triton-*.dist-info \
       "$SP"/cuda "$SP"/cuda_*.dist-info
if [ -n "$TORCH_V" ]; then
  rm -rf "$SP"/torch "$SP"/torch-*.dist-info "$SP"/torchgen "$SP"/functorch
  PKGS="torch==$TORCH_V"
  if [ -n "$TV_V" ]; then rm -rf "$SP"/torchvision "$SP"/torchvision-*.dist-info "$SP"/torchvision.libs; PKGS="$PKGS torchvision==$TV_V"; fi
  if [ -n "$TA_V" ]; then rm -rf "$SP"/torchaudio "$SP"/torchaudio-*.dist-info "$SP"/torio; PKGS="$PKGS torchaudio==$TA_V"; fi
  /usr/local/bin/python -m pip --python "$VENV/bin/python" install --no-cache-dir --no-deps --disable-pip-version-check \
    --index-url "${TORCH_INDEX:-https://download.pytorch.org/whl/cpu}" $PKGS
  "$VENV/bin/python" -c "import torch; assert torch.version.cuda is None; print('cpu torch', torch.__version__)"
fi
