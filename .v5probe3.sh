#!/bin/bash
echo "=== ss full with process ==="
ss -lntp 2>/dev/null | grep -E "8767|8766|8768|9120|8765" 
echo "=== try bind 8767 ipv4 ==="
python3 - <<'PY' 2>&1 | tail -3
import socket
s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
try:
    s.bind(("0.0.0.0",8767)); s.listen(1); print("BIND_8767_OK")
except Exception as e:
    print("BIND_8767_FAIL",e)
PY
echo "=== id / netns ==="
id
readlink /proc/self/ns/net /proc/1/ns/net 2>&1
echo "=== hostname ==="
hostname