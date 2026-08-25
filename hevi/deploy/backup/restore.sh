#!/usr/bin/env bash
# HEVI disaster-recovery restore for the artifacts produced by backup.sh.
#
# Safe default: restore into a new PostgreSQL database and a separate MinIO
# bucket. Restoring over production requires ALLOW_DESTRUCTIVE_RESTORE=1.
# Usage: restore.sh <backup_dir> [timestamp]

set -euo pipefail

BACKUP_DIR="${1:?usage: restore.sh <backup_dir> [timestamp]}"
REQUESTED_TIMESTAMP="${2:-}"

if [[ -f /opt/hevi/.env ]]; then
    # shellcheck source=/dev/null
    set -o allexport && source /opt/hevi/.env && set +o allexport
fi

POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:-hevi}"
POSTGRES_DB="${POSTGRES_DB:-hevi}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-hevi}"
POSTGRES_DOCKER="${POSTGRES_DOCKER:-}"
MINIO_ENDPOINT="${MINIO_ENDPOINT:-localhost:9000}"
MINIO_ACCESS_KEY="${MINIO_ACCESS_KEY:-}"
MINIO_SECRET_KEY="${MINIO_SECRET_KEY:-}"
MINIO_BUCKET="${MINIO_BUCKET:-hevi-assets}"
MINIO_NETWORK="${MINIO_NETWORK:-}"
MINIO_INTERNAL_ENDPOINT="${MINIO_INTERNAL_ENDPOINT:-minio:9000}"

if [[ -n "${REQUESTED_TIMESTAMP}" ]]; then
    PG_FILE="${BACKUP_DIR}/postgres/hevi_${REQUESTED_TIMESTAMP}.sql.gz"
    MINIO_FILE="${BACKUP_DIR}/minio/${REQUESTED_TIMESTAMP}.tar.gz"
else
    PG_FILE="$(find "${BACKUP_DIR}/postgres" -maxdepth 1 -type f -name 'hevi_*.sql.gz' -printf '%T@ %p\n' | sort -nr | awk 'NR==1 {print $2}')"
    MINIO_FILE="$(find "${BACKUP_DIR}/minio" -maxdepth 1 -type f -name '*.tar.gz' -printf '%T@ %p\n' | sort -nr | awk 'NR==1 {print $2}')"
fi
if [[ "${SKIP_POSTGRES:-0}" != "1" ]]; then
    [[ -s "${PG_FILE}" ]] || { echo "PostgreSQL backup not found" >&2; exit 1; }
fi

RESTORE_SUFFIX="${REQUESTED_TIMESTAMP:-$(date +%Y%m%d_%H%M%S)}"
RESTORE_DB="${RESTORE_DB:-${POSTGRES_DB}_restore_${RESTORE_SUFFIX}}"
# MinIO bucket names follow DNS naming rules and cannot contain the underscore
# used by the timestamp format above.
RESTORE_MINIO_SUFFIX="${RESTORE_SUFFIX//_/-}"
RESTORE_MINIO_BUCKET="${RESTORE_MINIO_BUCKET:-${MINIO_BUCKET}-restore-${RESTORE_MINIO_SUFFIX}}"

if [[ "${RESTORE_DB}" == "${POSTGRES_DB}" || "${RESTORE_MINIO_BUCKET}" == "${MINIO_BUCKET}" ]] \
    && [[ "${ALLOW_DESTRUCTIVE_RESTORE:-0}" != "1" ]]; then
    echo "Refusing in-place restore. Set ALLOW_DESTRUCTIVE_RESTORE=1 explicitly." >&2
    exit 2
fi

if [[ "${SKIP_POSTGRES:-0}" != "1" ]]; then
    export PGPASSWORD="${POSTGRES_PASSWORD}"
    if [[ -n "${POSTGRES_DOCKER}" ]]; then
        if [[ "${RESTORE_DB}" != "${POSTGRES_DB}" ]]; then
            if ! docker exec -e PGPASSWORD="${POSTGRES_PASSWORD}" "${POSTGRES_DOCKER}" \
                psql -U "${POSTGRES_USER}" -d postgres -tAc \
                "SELECT 1 FROM pg_database WHERE datname='${RESTORE_DB}'" | grep -q 1; then
                docker exec -e PGPASSWORD="${POSTGRES_PASSWORD}" "${POSTGRES_DOCKER}" \
                    createdb -U "${POSTGRES_USER}" "${RESTORE_DB}"
            fi
        fi
        echo "[restore] PostgreSQL → ${RESTORE_DB}"
        gunzip -c "${PG_FILE}" | docker exec -i -e PGPASSWORD="${POSTGRES_PASSWORD}" \
            "${POSTGRES_DOCKER}" psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${RESTORE_DB}" \
            >/dev/null
    else
        if [[ "${RESTORE_DB}" != "${POSTGRES_DB}" ]]; then
            if ! psql -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}" \
                -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${RESTORE_DB}'" | grep -q 1; then
                createdb -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}" "${RESTORE_DB}"
            fi
        fi
        echo "[restore] PostgreSQL → ${RESTORE_DB}"
        gunzip -c "${PG_FILE}" | psql -v ON_ERROR_STOP=1 \
            -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}" -d "${RESTORE_DB}" \
            >/dev/null
    fi
fi

if [[ "${SKIP_MINIO:-0}" != "1" && -n "${MINIO_ACCESS_KEY}" && -s "${MINIO_FILE:-}" ]]; then
    TEMP_DIR="$(mktemp -d)"
    trap 'rm -rf "${TEMP_DIR}"' EXIT
    tar -xzf "${MINIO_FILE}" -C "${TEMP_DIR}"
    if [[ -n "${MINIO_NETWORK}" ]]; then
        docker run --rm --network "${MINIO_NETWORK}" --entrypoint /bin/sh \
            -v "${TEMP_DIR}:/backup:ro" \
            -e MINIO_ACCESS_KEY -e MINIO_SECRET_KEY \
            minio/mc:latest \
            -c "
            mc alias set restore_target http://${MINIO_INTERNAL_ENDPOINT} \"\$MINIO_ACCESS_KEY\" \"\$MINIO_SECRET_KEY\" --quiet &&
            mc mb restore_target/${RESTORE_MINIO_BUCKET} --ignore-existing --quiet &&
            mc mirror --overwrite /backup/* restore_target/${RESTORE_MINIO_BUCKET} --quiet
            "
    else
        command -v mc >/dev/null || { echo "mc is required for MinIO restore" >&2; exit 1; }
        mc alias set restore_target "http://${MINIO_ENDPOINT}" \
            "${MINIO_ACCESS_KEY}" "${MINIO_SECRET_KEY}" --quiet
        mc mb "restore_target/${RESTORE_MINIO_BUCKET}" --ignore-existing --quiet
        mc mirror --overwrite "${TEMP_DIR}"/* "restore_target/${RESTORE_MINIO_BUCKET}" --quiet
    fi
    echo "[restore] MinIO → ${RESTORE_MINIO_BUCKET}"
elif [[ "${SKIP_MINIO:-0}" != "1" ]]; then
    echo "[restore] MinIO skipped (backup or credentials unavailable)"
fi

echo "[restore] completed; verify counts and artifact hashes before cutover ✓"
echo "RESTORE_DB=${RESTORE_DB}"
echo "RESTORE_MINIO_BUCKET=${RESTORE_MINIO_BUCKET}"
