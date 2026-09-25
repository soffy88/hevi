#!/bin/bash
# Test whether egress block is sandbox-specific by using a separate netns (docker)
echo "=== docker: google reachability ==="
docker run --rm --network bridge alpine:3.20 sh -c '
  apk add --no-cache curl >/dev/null 2>&1 || true
  echo "--- google ---"
  curl -s -o /dev/null -w "googleapis %{http_code} %{time_total}\n" --max-time 15 https://www.googleapis.com/generate_204 || echo "googleapis FAILED"
  echo "--- github control ---"
  curl -s -o /dev/null -w "github %{http_code} %{time_total}\n" --max-time 15 https://github.com || echo "github FAILED"
' 2>&1 | tail -20
