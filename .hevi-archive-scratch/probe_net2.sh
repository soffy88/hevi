#!/bin/bash
for t in 142.251.45.132:80 142.251.45.132:443 74.125.135.95:443 104.16.132.229:443 20.205.243.166:443 151.101.0.223:443; do
  ip=${t%%:*}; p=${t##*:}
  timeout 7 bash -c "echo > /dev/tcp/$ip/$p" 2>/dev/null && echo "$t OPEN" || echo "$t blocked"
done
echo "--- curl via gateway proxy guess? ---"
echo "--- direct https with longer window ---"
curl -s -o /dev/null -w 'googleapis %{http_code} %{time_total}\n' --max-time 30 -4 https://www.googleapis.com/generate_204
curl -s -o /dev/null -w 'npmjs %{http_code} %{time_total}\n' --max-time 20 -4 https://registry.npmjs.org/
