#!/bin/bash
# Measure connect behavior: instant-refuse (policy) vs hang (network)
measure() {
  local host=$1 port=$2
  local start=$(date +%s.%N)
  timeout 8 bash -c "echo > /dev/tcp/$host/$port" 2>/dev/null
  local rc=$?
  local end=$(date +%s.%N)
  local dur=$(awk "BEGIN{printf \"%.2f\", $end-$start}")
  echo "$host:$port rc=$rc elapsed=${dur}s"
}
echo "== google (blocked?) =="
measure www.googleapis.com 443
measure www.googleapis.com 80
measure 172.217.112.4 443
echo "== control (works) =="
measure registry.npmjs.org 443
measure github.com 443
measure api.github.com 443
echo "== gateway =="
measure 192.168.0.1 80
measure 192.168.0.1 53
