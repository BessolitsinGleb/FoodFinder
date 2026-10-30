#!/bin/sh
# Обновление прода: забрать свежий код из GitHub и пересобрать.
# Запуск на сервере из папки проекта:  sh deploy/deploy.sh
set -e
cd "$(dirname "$0")/.."

git pull --ff-only
docker compose -f docker-compose.prod.yml up -d --build
docker image prune -f >/dev/null

echo "Готово. Статус:"
docker compose -f docker-compose.prod.yml ps
