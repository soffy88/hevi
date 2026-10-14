# Image slimming (2026-10-14)

hevi-api ran with a CUDA build of torch plus ~3.5 GB of nvidia-*/triton wheels, but
the container has no GPU (runc, nvidia-smi broken on the host), so CUDA was never used.

- `strip-cuda-venv.sh` — swaps CUDA torch/torchvision/torchaudio for the CPU wheels of
  the same version and removes nvidia-*, cuda-*, triton. Used by `deploy/Dockerfile.api`
  (venv stage) for future builds.
- `Dockerfile.api-repack` — slims an already-built image without touching its code:
  same strip, then flattens all layers into one (node_modules copied twice and
  chown -R layers were stored twice). This is how the live image was produced on
  2026-10-14: 14.2 GB -> 7.3 GB. Rollback tag: `hevi-cftunnel-hevi-api:pre-slim-20261014`.

Rollback: `docker tag hevi-cftunnel-hevi-api:pre-slim-20261014 hevi-cftunnel-hevi-api:latest`
then recreate hevi-api with `docker compose -f deploy/docker-compose-cftunnel.yml up -d --no-build --no-deps hevi-api`
(the compose needs CFTUNNEL_DATABASE_URL / MINIO_* in the shell environment).
