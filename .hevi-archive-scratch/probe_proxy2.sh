#!/bin/bash
echo "=== who listens on 7890 / 8080 ==="
ss -ltnp 2>/dev/null | grep -E ':(7890|8080|1080|20171|20172)\b'
echo
echo "=== probe 7890 as http proxy ==="
curl -s -o /dev/null -w 'via-7890-http googleapis %{http_code} %{time_total}\n' --max-time 15 -x http://127.0.0.1:7890 https://www.googleapis.com/generate_204
curl -s -o /dev/null -w 'via-7890-http github %{http_code} %{time_total}\n' --max-time 15 -x http://127.0.0.1:7890 https://github.com
echo "=== probe 7890 as socks5 proxy ==="
curl -s -o /dev/null -w 'via-7890-socks googleapis %{http_code} %{time_total}\n' --max-time 15 -x socks5h://127.0.0.1:7890 https://www.googleapis.com/generate_204
echo "=== probe 8080 as http proxy ==="
curl -s -o /dev/null -w 'via-8080-http googleapis %{http_code} %{time_total}\n' --max-time 15 -x http://127.0.0.1:8080 https://www.googleapis.com/generate_204
