FROM nginx:1.27-alpine

# PORT задаёт Railway; локально — 8080
ENV PORT=8080 \
    API_BASE=http://localhost:8000/api/v1

# Конфиг nginx — шаблон: при старте образ сам подставит ${PORT}
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
# Скрипт пишет адрес API в js/env.js при запуске контейнера
COPY docker-entrypoint.d/ /docker-entrypoint.d/
RUN chmod +x /docker-entrypoint.d/*.sh

COPY index.html auth.html orders.html order.html profile.html /usr/share/nginx/html/
COPY css/ /usr/share/nginx/html/css/
COPY js/ /usr/share/nginx/html/js/
COPY assets/ /usr/share/nginx/html/assets/

EXPOSE 8080
