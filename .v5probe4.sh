#!/bin/bash
echo "=== 8767 openapi ==="
curl -s -m 5 http://127.0.0.1:8767/openapi.json | head -c 3000
echo
echo "=== 8767 other paths ==="
for p in / /docs /static/ /files/ /downloads/ /health /api/health /api/static/; do
  code=$(curl -s -m 4 -o /dev/null -w "%{http_code}" "http://127.0.0.1:8767$p")
  echo "$p -> $code"
done
echo "=== 8766 ==="
for p in / /health; do
  code=$(curl -s -m 4 -o /dev/null -w "%{http_code}" "http://127.0.0.1:8766$p")
  echo "8766$p -> $code"
done
curl -s -m 4 http://127.0.0.1:8766/ | head -c 500
echo
echo "=== who owns 8766/8768 ==="
docker inspect veya-backend --format '{{range $p,$v := .NetworkSettings.Ports}}{{$p}} -> {{$v}}{{"\n"}}{{end}}'
