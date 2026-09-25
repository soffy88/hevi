#!/bin/bash
echo "=== tailscale ==="
which tailscale && tailscale status 2>&1 | head -20
echo
echo "=== listening TCP ports on host netns ==="
(ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null) | head -40
echo
echo "=== docker containers (names + image + ports) ==="
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Ports}}' 2>&1 | head -40
