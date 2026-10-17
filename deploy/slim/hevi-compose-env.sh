#!/bin/bash
# Usage: source-able; exports interpolation vars from the running hevi-api container, then runs compose with args
set -e
cd /data/soffy/projects/hevi/deploy
umask 077
E=$(mktemp -p /data/soffy/tmp/slim)
docker inspect hevi-cftunnel-hevi-api-1 --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -v '^$' > $E
set -a; . <(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' $E | sed "s/'/'\\\\''/g; s/=\(.*\)/='\1'/"); set +a
export CFTUNNEL_DATABASE_URL="$DATABASE_URL" CFTUNNEL_MINIO_ENDPOINT="$MINIO_ENDPOINT"
rm -f $E
docker compose -f docker-compose-cftunnel.yml "$@"
