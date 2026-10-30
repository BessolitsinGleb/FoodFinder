#!/bin/sh
# Первичная настройка чистого Ubuntu-сервера. Запускается один раз от root.
set -e

apt-get update -q
apt-get upgrade -yq
apt-get install -yq git curl ufw

# Docker + compose plugin (официальный установщик)
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi

# Наружу — только SSH и веб
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Вход по SSH только по ключу
sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl reload ssh 2>/dev/null || systemctl reload sshd

# Немного swap: на сервере с 1 ГБ памяти сборка образов без него может упасть
if [ ! -f /swapfile ]; then
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "Сервер готов: $(docker --version)"
