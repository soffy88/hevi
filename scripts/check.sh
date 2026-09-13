#!/usr/bin/env bash
# Reproducible RC5 code-quality gate.  External services and live providers
# are intentionally outside this script; those belong to staging qualification.
set -Eeuo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-"${ROOT_DIR}/.venv/bin/python"}
NPM_BIN=${NPM_BIN:-"/home/soffy/.npm-global/bin/npm"}

cd "${ROOT_DIR}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "check.sh: Python runtime not found: ${PYTHON_BIN}" >&2
  exit 2
fi
if [[ ! -x "${NPM_BIN}" ]]; then
  echo "check.sh: npm runtime not found: ${NPM_BIN}" >&2
  exit 2
fi

"${PYTHON_BIN}" -m ruff check hevi tests
"${PYTHON_BIN}" -m pytest tests/ --cov=hevi --cov-report=term --cov-fail-under=80

(
  cd hevi-web
  "${NPM_BIN}" test
  "${NPM_BIN}" run typecheck
  NEXT_PUBLIC_DEPLOY_ENV=production \
    NEXT_PUBLIC_API_BASE=https://api-prod.sxueji.com \
    NEXT_PUBLIC_USE_MOCK=false \
    NEXT_TELEMETRY_DISABLED=1 "${NPM_BIN}" run build
)

echo "check.sh: PASS"
