#!/bin/bash
# Read-only environment probe (no secret values printed)
echo "=== HOME ==="; echo "$HOME"
echo "=== proxy/cert-ish env vars (name only) ==="
env | cut -d= -f1 | grep -iE 'proxy|http|ssl|cert|ca_|no_proxy|rclone' | sort
echo "=== resolve.conf nameservers ==="
grep -E '^nameserver' /etc/resolv.conf 2>/dev/null
echo "=== /etc/hosts (non-comment) ==="
grep -vE '^\s*#|^\s*$' /etc/hosts 2>/dev/null
echo "=== sandbox / reasonix config locations ==="
ls -la /home/soffy/projects 2>/dev/null | head
