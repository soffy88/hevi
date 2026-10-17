#!/bin/bash
echo "=== direct host /tmp access from sandbox ==="
ls -la /tmp/hevi-science-v5/ 2>&1
echo "--- stat ---"
stat -c '%s %n' /tmp/hevi-science-v5/black-hole-v5-final.mp4 2>&1
echo "--- head bytes readable? ---"
head -c 16 /tmp/hevi-science-v5/black-hole-v5-final.mp4 2>&1 | od -An -tx1 2>&1 | head -2
echo "=== md5 via container ==="
docker exec hevi-v5-serve md5sum /srv/black-hole-v5-final.mp4 2>&1
echo "=== stat via container ==="
docker exec hevi-v5-serve stat -c '%s %n' /srv/black-hole-v5-final.mp4 2>&1
echo "=== is any process serving it / open fds ==="
docker top hevi-v5-serve 2>&1
