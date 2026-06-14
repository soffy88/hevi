# HTTPS 证书申请 (Let's Encrypt / Certbot)

## 前提条件

- 域名已解析到服务器 IP
- 80 端口可访问(用于 ACME challenge)
- nginx 已启动并包含 `/.well-known/acme-challenge/` location

## 初次申请

```bash
# 1. 安装 certbot
apt-get install -y certbot

# 2. 申请证书 (webroot 模式,不停 nginx)
certbot certonly \
  --webroot \
  --webroot-path /var/www/certbot \
  -d hevi.example.com \
  --email admin@example.com \
  --agree-tos \
  --non-interactive

# 3. 证书位于:
#   /etc/letsencrypt/live/hevi.example.com/fullchain.pem
#   /etc/letsencrypt/live/hevi.example.com/privkey.pem

# 4. 更新 nginx/hevi.conf 中的 server_name 和证书路径后重载
nginx -s reload
```

## Docker 环境申请

```bash
# 在宿主机执行,挂载 certbot volume
docker run -it --rm \
  -v nginx_certs:/etc/letsencrypt \
  -v nginx_www:/var/www/certbot \
  certbot/certbot certonly \
  --webroot \
  --webroot-path /var/www/certbot \
  -d hevi.example.com \
  --email admin@example.com \
  --agree-tos
```

## 自动续期

```bash
# 添加 crontab (每天凌晨 2 点检查)
0 2 * * * certbot renew --quiet && docker compose \
  -f /opt/hevi/hevi/deploy/docker-compose-prod.yml \
  exec nginx nginx -s reload
```

## 注意事项

- 证书有效期 90 天,建议每 60 天续期
- 生产环境替换 `hevi.example.com` 为真实域名
- 首次申请前确认 DNS A 记录已生效 (`dig hevi.example.com`)
