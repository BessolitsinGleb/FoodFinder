from typing import Annotated
from fastapi import Depends, Query, Request
from fastapi.security import OAuth2PasswordBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from app.agent import SupplierAgent
from app.core.config import get_settings
from app.core.exceptions import ForbiddenError, ServiceUnavailableError, TooManyRequestsError, UnauthorizedError
from app.core.security import decode_access_token
from app.db.session import get_session
from app.integrations.llm import LLMClient
from app.integrations.web_search import WebSearchClient
from app.models import User
from app.repositories.chat_memory_repo import ChatMemoryRepo
from app.schemas.common import PaginationParams
from app.services.auth_service import AuthService
from app.services.category_service import CategoryService
from app.services.chat_service import ChatService
from app.services.letter_service import LetterService
from app.services.order_service import OrderService
from app.services.user_service import UserService

SessionDep = Annotated[AsyncSession, Depends(get_session)]
PaginationDep = Annotated[PaginationParams, Query()]

# auto_error=False: отсутствие токена обрабатываем сами, чтобы текст ошибки был нашим
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{get_settings().app.api_prefix}/auth/login", auto_error=False)

# ---------- Ограничитель запросов ----------

async def rate_limit(request: Request, token: Annotated[str | None, Depends(oauth2_scheme)]) -> None:
    """Не больше RATE_LIMIT__REQUESTS запросов в окно на пользователя (или на IP без токена).

    Токен только декодируем, без похода в БД: лимитер должен быть дешёвым.
    """
    user_id = decode_access_token(token, get_settings().auth) if token else None
    client_key = f"user:{user_id}" if user_id else f"ip:{request.client.host if request.client else 'unknown'}"
    if not await request.app.state.rate_limiter.allow(client_key):
        raise TooManyRequestsError("Слишком много запросов — подождите секунду")

# ---------- Авторизация ----------

def get_user_service(session: SessionDep) -> UserService:
    return UserService(session)

UserServiceDep = Annotated[UserService, Depends(get_user_service)]

async def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)], users: UserServiceDep
) -> User:
    if not token:
        raise UnauthorizedError("Нужна авторизация: передайте Bearer-токен")
    user_id = decode_access_token(token, get_settings().auth)
    if user_id is None:
        raise UnauthorizedError("Токен недействителен или истёк — войдите заново")
    return await users.get_active(user_id)

CurrentUser = Annotated[User, Depends(get_current_user)]

def get_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise ForbiddenError("Действие доступно только администратору")
    return user

AdminUser = Annotated[User, Depends(get_admin)]

# ---------- Внешние сервисы ----------
# Клиенты создаются один раз в lifespan и лежат в app.state.
# Если ключа нет — клиента нет, и эндпоинт честно отвечает 503.

def get_llm(request: Request) -> LLMClient:
    llm: LLMClient | None = request.app.state.llm
    if llm is None:
        raise ServiceUnavailableError("LLM не настроен: задайте LLM__API_KEY")
    return llm

def get_web_search(request: Request) -> WebSearchClient:
    web: WebSearchClient | None = request.app.state.web
    if web is None:
        raise ServiceUnavailableError("Поиск в интернете не настроен: задайте WEB__API_KEY")
    return web

LLMDep = Annotated[LLMClient, Depends(get_llm)]
WebSearchDep = Annotated[WebSearchClient, Depends(get_web_search)]

def get_redis(request: Request) -> Redis:
    return request.app.state.redis

# ---------- Сервисы ----------

def get_auth_service(session: SessionDep, request: Request) -> AuthService:
    return AuthService(session, request.app.state.mailer, get_settings().auth)

def get_category_service(session: SessionDep) -> CategoryService:
    return CategoryService(session)

def get_order_service(session: SessionDep) -> OrderService:
    return OrderService(session)

def get_letter_service(session: SessionDep, request: Request) -> LetterService:
    # LLM нужен только для генерации; список и скачивание писем работают и без ключа
    return LetterService(session, request.app.state.llm, get_settings().letters)

def get_chat_service(
    session: SessionDep, request: Request, llm: LLMDep, redis: Annotated[Redis, Depends(get_redis)]
) -> ChatService:
    # llm в аргументах — ради проверки "ключ задан", иначе 503
    agent: SupplierAgent = request.app.state.agent
    memory = ChatMemoryRepo(redis, get_settings().chat)
    return ChatService(session, agent, memory, request.app.state.web)

AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
CategoryServiceDep = Annotated[CategoryService, Depends(get_category_service)]
OrderServiceDep = Annotated[OrderService, Depends(get_order_service)]
LetterServiceDep = Annotated[LetterService, Depends(get_letter_service)]
ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]
