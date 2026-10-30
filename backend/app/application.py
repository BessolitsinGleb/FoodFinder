import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from redis.exceptions import RedisError
from app.agent import SupplierAgent, registry
from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import AppError, TooManyRequestsError, UnauthorizedError
from app.db.session import SessionFactory, engine
from app.integrations.llm import LLMClient
from app.integrations.mailer import Mailer
from app.integrations.rate_limiter import RateLimiter
from app.integrations.web_search import WebSearchClient
from app.repositories.order_repo import OrderRepo

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if not settings.auth.secret_key.get_secret_value():
        # Без ключа токены подписывать нечем; молча генерировать свой нельзя —
        # после рестарта все пользователи вылетели бы из системы
        raise RuntimeError("AUTH__SECRET_KEY не задан — добавьте его в .env")

    # Клиенты создаются один раз на всё приложение (внутри — пул соединений).
    # Нет ключа — нет клиента: соответствующие эндпоинты вернут 503, остальное работает.
    llm = LLMClient(settings.llm) if settings.llm.is_configured else None
    web = WebSearchClient(settings.web) if settings.web.is_configured else None
    if llm is None:
        logger.warning("LLM__API_KEY не задан — агент, поиск и письма недоступны")
    if web is None:
        logger.warning("WEB__API_KEY не задан — поиск поставщиков недоступен")
    if not settings.smtp.is_configured and not settings.smtp.dev_log_codes:
        logger.warning("SMTP__* не заполнены — регистрация будет отвечать 503")

    redis = Redis.from_url(settings.redis.url, decode_responses=True)
    try:
        await redis.ping()
    except RedisError as exc:
        # Не падаем: лимитер пропускает запросы без Redis, а чат честно ответит 503
        logger.error("Redis недоступен (%s): чат с агентом не будет работать", exc)

    app.state.llm = llm
    app.state.web = web
    app.state.agent = SupplierAgent(llm, registry, settings.llm.max_agent_steps) if llm else None
    app.state.mailer = Mailer(settings.smtp)
    app.state.redis = redis
    app.state.rate_limiter = RateLimiter(redis, settings.rate_limit)

    async with SessionFactory() as session:
        interrupted = await OrderRepo(session).fail_interrupted_searches()
        await session.commit()
    if interrupted:
        logger.warning("Помечено как failed прерванных поисков: %s", interrupted)

    yield

    if llm is not None:
        await llm.close()
    if web is not None:
        await web.close()
    await redis.aclose()
    await engine.dispose()

async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Сервисы бросают AppError с нужным статусом, здесь — единственное место перевода в HTTP
    assert isinstance(exc, AppError)
    headers = {}
    if isinstance(exc, UnauthorizedError):
        headers["WWW-Authenticate"] = "Bearer"
    if isinstance(exc, TooManyRequestsError):
        headers["Retry-After"] = "1"
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=headers)

def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(
        level=logging.DEBUG if settings.app.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # debug в FastAPI не передаём: он отдаёт клиенту полный traceback при 500.
    # APP__DEBUG влияет только на подробность логов.
    app = FastAPI(title=settings.app.name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.app.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(api_router, prefix=settings.app.api_prefix)
    return app
