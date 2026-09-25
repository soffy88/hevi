#!/bin/bash
# Network egress diagnosis
echo "--- DNS A records for common hosts ---"
for h in googleapis.com www.googleapis.com oauth2.googleapis.com www.google.com cloudflare.com registry.npmjs.org github.com; do
  a=$(getent ahostsv4 "$h" 2>/dev/null | head -1)
  aaaa=$(getent ahostsv6 "$h" 2>/dev/null | head -1)
  echo "$h | v4=${a:-none} | v6=${aaaa:-none}"
done
echo
echo "--- raw IPv4 TCP connect tests (port 443) ---"
for ip in 142.250.0.1 8.8.8.8 1.1.1.1 140.82.121.4; do
  timeout 5 bash -c "echo > /dev/tcp/$ip/443" 2>/dev/null && echo "$ip:443 OPEN" || echo "$ip:443 closed/blocked"
done
echo
echo "--- curl to IP with SNI ---"
curl -s -o /dev/null -w 'ssl googleapis via 8.8.8.8 %{http_code} %{time_total}\n' --max-time 10 --resolve www.googleapis.com:443:8.8.8.8 https://www.googleapis.com/generate_204
echo "--- routes ---"
ip -4 route 2>/dev/null | head
ip -6 route 2>/dev/null | head
echo "--- interfaces ---"
ip -brief addr 2>/dev/null
