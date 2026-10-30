FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

WORKDIR /app

# Сначала только зависимости — этот слой кэшируется, пока не меняется requirements.txt
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Не запускаем приложение от root
RUN useradd --create-home --uid 1000 app && chown -R app /app
USER app

EXPOSE 8000
CMD ["sh", "start.sh"]
