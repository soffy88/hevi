#!/bin/bash
echo "=== common local proxy ports ==="
for p in 1080 1081 7890 7891 7897 8080 8118 8123 8888 8889 10808 10809 10810 20171 20172 3128 9050 9000 1087 7788; do
  timeout 1 bash -c "echo > /dev/tcp/127.0.0.1/$p" 2>/dev/null && echo "127.0.0.1:$p OPEN"
done
echo "=== gateway proxy ports ==="
for p in 1080 7890 8080 3128 10808 8888; do
  timeout 1 bash -c "echo > /dev/tcp/192.168.0.1/$p" 2>/dev/null && echo "192.168.0.1:$p OPEN"
done
echo "=== listen ports 1xxxx ==="
ss -ltnp 2>/dev/null | awk 'NR>1{print $4}' | sort -u | head -60
