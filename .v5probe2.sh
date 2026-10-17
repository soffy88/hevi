#!/bin/bash
echo "=== CJK fonts ==="
fc-match -s "Noto Sans CJK SC:lang=zh" 2>&1 | head -5
fc-list :lang=zh 2>/dev/null | head -10
echo "=== count zh ==="
fc-list :lang=zh 2>/dev/null | wc -l
echo "=== find ttc/otf cjk ==="
ls /usr/share/fonts/ 2>&1
ls /usr/share/fonts/opentype/ 2>&1
ls /usr/share/fonts/truetype/ 2>&1 | head -30
echo "=== venv ==="
ls /data/soffy/projects/hevi/.venv/bin/python*
