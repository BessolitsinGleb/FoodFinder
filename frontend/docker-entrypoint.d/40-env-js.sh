#!/bin/sh
# Адрес бэкенда берётся из переменной API_BASE при каждом запуске контейнера —
# один образ подходит и для локального запуска, и для Railway.
set -e
printf 'window.FF_API_BASE = "%s";\n' "${API_BASE}" > /usr/share/nginx/html/js/env.js
echo "env.js: API_BASE=${API_BASE}"
