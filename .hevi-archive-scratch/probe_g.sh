#!/bin/bash
echo "=== resolve google endpoints (v4) ==="
for h in www.googleapis.com drive.googleapis.com oauth2.googleapis.com accounts.google.com content.googleapis.com; do
  ips=$(getent ahostsv4 "$h" 2>/dev/null | awk '{print $1}' | sort -u | tr '\n' ' ')
  echo "$h -> $ips"
done
echo
echo "=== TCP 443 tests ==="
IPS="172.217.112.4 142.251.45.132 74.125.135.95 142.250.0.1 216.58.200.42 172.217.0.0"
for ip in $IPS; do
  timeout 6 bash -c "echo > /dev/tcp/$ip/443" 2>/dev/null && echo "$ip:443 OPEN" || echo "$ip:443 blocked"
done
echo
echo "=== curl with 10s to www.googleapis.com ==="
curl -s -o /dev/null -w 'www.googleapis.com %{http_code} %{time_total}\n' --max-time 10 -4 https://www.googleapis.com/generate_204
echo "=== traceroute-ish (no root, use tracepath if present) ==="
which tracepath traceroute 2>/dev/null
