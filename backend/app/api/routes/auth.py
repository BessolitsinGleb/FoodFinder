from typing import Annotated
from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from app.api.deps import AuthServiceDep
from app.schemas.auth import (
    MessageResponse,
    RegisterRequest,
    ResendCodeRequest,
    TokenResponse,
    VerifyEmailRequest,
)

router = APIRouter(prefix="/auth", tags=["auth"])

def _errors(*pairs: tuple[int, str]) -> dict[int | str, dict]:
    """Описание ошибок для Swagger — фронт видит, какие ответы бывают."""
    return {code: {"description": text} for code, text in pairs}

@router.post(
    "/register",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_errors(
        (409, "Email уже зарегистрирован (подтверждён или ждёт кода)"),
        (422, "Некорректные данные: пароль короче 8 символов, неизвестный регион и т.п."),
        (502, "Письмо не отправилось — регистрация не сохранена"),
        (503, "Отправка писем не настроена (SMTP__*)"),
    ),
)
async def register(payload: RegisterRequest, service: AuthServiceDep) -> MessageResponse:
    await service.register(payload)
    return MessageResponse(message="Код подтверждения отправлен на почту")

@router.post(
    "/verify-email",
    response_model=TokenResponse,
    responses=_errors(
        (400, "Неверный код (в тексте — сколько попыток осталось) или код не найден"),
        (404, "Пользователь с таким email не найден"),
        (409, "Почта уже подтверждена"),
        (410, "Срок действия кода истёк — нужен новый"),
        (422, "Код — не 6 цифр"),
        (429, "Попытки закончились — нужен новый код"),
    ),
)
async def verify_email(payload: VerifyEmailRequest, service: AuthServiceDep) -> TokenResponse:
    """Подтверждение почты кодом из письма. Успех — сразу выдаём токен."""
    token = await service.verify_email(payload.email, payload.code)
    return TokenResponse(access_token=token)

@router.post(
    "/resend-code",
    response_model=MessageResponse,
    responses=_errors(
        (404, "Пользователь с таким email не найден"),
        (409, "Почта уже подтверждена"),
        (429, "Слишком рано — в тексте сказано, через сколько секунд можно"),
        (502, "Письмо не отправилось"),
    ),
)
async def resend_code(payload: ResendCodeRequest, service: AuthServiceDep) -> MessageResponse:
    """Новый код. Старый сразу перестаёт действовать, счётчик попыток сбрасывается."""
    await service.resend_code(payload.email)
    return MessageResponse(message="Новый код отправлен на почту")

@router.post(
    "/login",
    response_model=TokenResponse,
    responses=_errors(
        (401, "Неверный email или пароль"),
        (403, "Почта не подтверждена"),
    ),
)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], service: AuthServiceDep
) -> TokenResponse:
    """OAuth2 password flow: username = email. Так работает кнопка Authorize в Swagger."""
    token = await service.login(form.username, form.password)
    return TokenResponse(access_token=token)
