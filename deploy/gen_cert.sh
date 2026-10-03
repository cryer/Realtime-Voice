#!/usr/bin/env bash
# 生成自签 HTTPS 证书（手机浏览器调用麦克风必须 HTTPS）。
# 用法: ./gen_cert.sh <服务器IP>   例如: ./gen_cert.sh <server-ip>
set -e
cd "$(dirname "$0")/.."
IP=${1:?usage: ./gen_cert.sh <server-ip>}
mkdir -p certs
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout certs/key.pem -out certs/cert.pem -days 825 \
  -subj "/CN=voice-agent" \
  -addext "subjectAltName=IP:${IP},IP:127.0.0.1,DNS:localhost"
echo "已生成 certs/cert.pem / certs/key.pem (SAN: ${IP})"
echo "手机首次访问 https://${IP}:6790 时选择「继续前往」信任该自签证书。"
