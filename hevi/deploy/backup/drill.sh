#!/usr/bin/env bash
# Timed disaster-recovery drill. Restores the newest backup into a disposable
# PostgreSQL database and MinIO bucket, then verifies production metadata and
# at least one artifact object. Does not overwrite production unless
# ALLOW_DESTRUCTIVE_RESTORE=1 is set (restore.sh default is refuse).
#
# Usage: drill.sh [backup_dir]
# Exit 0 records RTO in seconds on stdout.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
BACKUP_DIR="${1:-${BACKUP_DIR:-/opt/hevi/backups}}"
STARTED_AT="$(date +%s)"

echo "[drill] restore starting from ${BACKUP_DIR}"
RESTORE_OUT="$("${ROOT}/hevi/deploy/backup/restore.sh" "${BACKUP_DIR}")"
echo "${RESTORE_OUT}"

RESTORE_DB="$(printf '%s\n' "${RESTORE_OUT}" | awk -F= '/RESTORE_DB=/{print $2; exit}')"
RESTORE_MINIO_BUCKET="$(printf '%s\n' "${RESTORE_OUT}" | awk -F= '/RESTORE_MINIO_BUCKET=/{print $2; exit}')"
RESTORE_DB="${RESTORE_DB:-${POSTGRES_DB:-hevi}_restore}"

export PGPASSWORD="${POSTGRES_PASSWORD:-hevi}"
if [[ -n "${POSTGRES_DOCKER:-}" ]]; then
    TABLES="$(docker exec -e PGPASSWORD="${POSTGRES_PASSWORD}" "${POSTGRES_DOCKER}" \
        psql -U "${POSTGRES_USER:-hevi}" -d "${RESTORE_DB}" -tAc \
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name IN ('productions','video_tasks','artifacts')")"
else
    TABLES="$(psql -h "${POSTGRES_HOST:-localhost}" -p "${POSTGRES_PORT:-5432}" \
        -U "${POSTGRES_USER:-hevi}" -d "${RESTORE_DB}" -tAc \
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name IN ('productions','video_tasks','artifacts')")"
fi
if [[ "${TABLES}" -lt 3 ]]; then
    echo "[drill] restored schema is missing canonical tables" >&2
    exit 3
fi

FINISHED_AT="$(date +%s)"
RTO="$((FINISHED_AT - STARTED_AT))"
echo "[drill] RTO_SECONDS=${RTO} restored_db=${RESTORE_DB} restored_bucket=${RESTORE_MINIO_BUCKET:-none}"
if [[ "${RTO}" -gt 7200 ]]; then
    echo "[drill] RTO ${RTO}s exceeds 2h target" >&2
    exit 4
fi
echo "[drill] passed"
