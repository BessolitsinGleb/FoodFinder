"""
Общая инфраструктура тестов.

- Переменные окружения выставляются ДО импорта приложения (Settings читается при импорте).
- БД: отдельная PostgreSQL-база food_suppliers_test (JSONB есть только в Postgres).
  Создаётся автоматически; пользователь/пароль берутся из .env, как у основной БД.
- Redis — fakeredis, почта — фейк, который запоминает коды. OpenRouter и Tavily — фейки.
  Тесты бесплатные, детерминированные и не трогают настоящий Redis.
"""
import asyncio
import os
import sys
from pathlib import Path

os.environ.update({
    "DB__NAME": os.environ.get("TEST_DB_NAME", "food_suppliers_test"),
    "LLM__API_KEY": "test-key",
    "WEB__API_KEY": "test-key",
    "AUTH__SECRET_KEY": "test-secret-key-test-secret-key-0123456789",
    # Несуществующий порт: даже если локально запущен Redis, тесты его не тронут
    "REDIS__URL": "redis://127.0.0.1:1/0",
    # Общий лимитер тестам мешает; отдельный тест проверяет его на 3 запросах
    "RATE_LIMIT__REQUESTS": "100000",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402
import fakeredis  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text, update  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.agent import SupplierAgent, registry  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.integrations.rate_limiter import RateLimiter  # noqa: E402
from app.models import User  # noqa: E402
from main import app  # noqa: E402
from tests.fakes import FakeLLM, FakeMailer, FakeWebSearch  # noqa: E402

API = "/api/v1"
PASSWORD = "secret-password"


async def _prepare_database() -> None:
    db = get_settings().db
    conn = await asyncpg.connect(
        host=db.host, port=db.port, user=db.user,
        password=db.password.get_secret_value() or None, database="postgres",
    )
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db.name):
            await conn.execute(f'CREATE DATABASE "{db.name}"')
    finally:
        await conn.close()

    # Отдельный движок без пула: соединения основного engine должны жить в цикле TestClient
    setup_engine = create_async_engine(db.url, poolclass=NullPool)
    async with setup_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await setup_engine.dispose()


@pytest.fixture(scope="session")
def client():
    asyncio.run(_prepare_database())
    with TestClient(app) as c:
        yield c


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def fake_web():
    return FakeWebSearch()


@pytest.fixture
def mailer():
    return FakeMailer()


@pytest.fixture
def redis(client):
    # Создаём внутри цикла TestClient — там же, где его будут использовать
    return client.portal.call(_make_fake_redis)


async def _make_fake_redis():
    return fakeredis.FakeAsyncRedis(decode_responses=True)


@pytest.fixture(autouse=True)
def clean_state(client, fake_llm, fake_web, mailer, redis):
    """Чистая БД перед каждым тестом и фейки вместо внешних сервисов."""
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)

    async def _truncate():
        async with engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))

    client.portal.call(_truncate)
    app.state.llm = fake_llm
    app.state.web = fake_web
    app.state.agent = SupplierAgent(fake_llm, registry, max_steps=6)
    app.state.mailer = mailer
    app.state.redis = redis
    app.state.rate_limiter = RateLimiter(redis, get_settings().rate_limit)
    yield


# ---------- хелперы ----------

def register(client, email="ivan@test.ru", **overrides):
    data = {"name": "Иван", "email": email, "password": PASSWORD, "city": "казань", "region": "Татарстан"}
    return client.post(f"{API}/auth/register", json=data | overrides)


def login(client, email="ivan@test.ru", password=PASSWORD):
    # OAuth2-форма: username = email
    return client.post(f"{API}/auth/login", data={"username": email, "password": password})


def make_user(client, mailer, email="ivan@test.ru", **overrides) -> dict:
    """Полный путь фронта: регистрация -> код из письма -> токен. Возвращает заголовки."""
    assert register(client, email, **overrides).status_code == 201
    res = client.post(f"{API}/auth/verify-email", json={"email": email, "code": mailer.codes[email]})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def make_admin(client, mailer, email="admin@test.ru") -> dict:
    headers = make_user(client, mailer, email)

    async def promote():
        async with engine.begin() as conn:
            await conn.execute(update(User).where(User.email == email).values(is_admin=True))

    client.portal.call(promote)
    return headers


def create_category(client, admin_headers, name, slug, **overrides):
    res = client.post(f"{API}/categories", json={"name": name, "slug": slug} | overrides, headers=admin_headers)
    assert res.status_code == 201, res.text
    return res.json()
