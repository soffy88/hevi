#!/usr/bin/env bash
# hevi v6 backup script — PostgreSQL + MinIO
# Usage: ./backup.sh [backup_dir]
# Schedule: crontab -e → 0 3 * * * /opt/hevi/hevi/deploy/backup/backup.sh

set -euo pipefail

BACKUP_DIR="${1:-/opt/hevi/backups}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-7}"

# Load env if .env exists
if [[ -f /opt/hevi/.env ]]; then
    # shellcheck source=/dev/null
    set -o allexport && source /opt/hevi/.env && set +o allexport
fi

POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:-hevi}"
POSTGRES_DB="${POSTGRES_DB:-hevi}"
MINIO_ENDPOINT="${MINIO_ENDPOINT:-localhost:9000}"
MINIO_ACCESS_KEY="${MINIO_ACCESS_KEY:-}"
MINIO_SECRET_KEY="${MINIO_SECRET_KEY:-}"
MINIO_BUCKET="${MINIO_BUCKET:-hevi-assets}"

mkdir -p "${BACKUP_DIR}/postgres" "${BACKUP_DIR}/minio"

echo "[backup] ${TIMESTAMP} 开始备份"

# ── PostgreSQL ────────────────────────────────────────────────────────────────
PG_FILE="${BACKUP_DIR}/postgres/hevi_${TIMESTAMP}.sql.gz"
PGPASSWORD="${POSTGRES_PASSWORD:-hevi}" \
    pg_dump \
    -h "${POSTGRES_HOST}" \
    -p "${POSTGRES_PORT}" \
    -U "${POSTGRES_USER}" \
    -d "${POSTGRES_DB}" \
    --no-password \
    | gzip > "${PG_FILE}"

echo "[backup] PostgreSQL → ${PG_FILE} ($(du -sh "${PG_FILE}" | cut -f1))"

# ── MinIO ─────────────────────────────────────────────────────────────────────
if command -v mc &>/dev/null && [[ -n "${MINIO_ACCESS_KEY}" ]]; then
    mc alias set backup_src \
        "http://${MINIO_ENDPOINT}" \
        "${MINIO_ACCESS_KEY}" \
        "${MINIO_SECRET_KEY}" \
        --quiet

    MINIO_DEST="${BACKUP_DIR}/minio/${TIMESTAMP}"
    mc mirror \
        "backup_src/${MINIO_BUCKET}" \
        "${MINIO_DEST}" \
        --quiet

    # Compress minio backup
    tar -czf "${MINIO_DEST}.tar.gz" -C "${BACKUP_DIR}/minio" "${TIMESTAMP}"
    rm -rf "${MINIO_DEST}"
    echo "[backup] MinIO → ${MINIO_DEST}.tar.gz"
else
    echo "[backup] MinIO 跳过 (mc 未安装或 MINIO_ACCESS_KEY 未设置)"
fi

# ── 清理旧备份 ────────────────────────────────────────────────────────────────
find "${BACKUP_DIR}" -name "*.gz" -mtime "+${KEEP_DAYS}" -delete
echo "[backup] 已清理 ${KEEP_DAYS} 天前的备份"

echo "[backup] ${TIMESTAMP} 完成 ✓"
