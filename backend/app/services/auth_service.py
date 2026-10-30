"""Регистрация с подтверждением почты и вход по JWT.

Правило одно: почта считается подтверждённой ТОЛЬКО после ввода правильного,
не просроченного кода. Никаких автоподтверждений — ни при выключенном SMTP,
ни при ошибке отправки. Каждый отказ — отдельная ошибка с понятным текстом.
"""
import asyncio
from datetime import UTC, datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import AuthSettings
from app.core.exceptions import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    TooManyRequestsError,
    UnauthorizedError,
)
from app.core.security import (
    code_matches,
    create_access_token,
    generate_code,
    hash_code,
    hash_password,
    verify_password,
)
from app.integrations.mailer import Mailer
from app.models import EmailVerificationCode, User
from app.repositories.user_repo import EmailCodeRepo, UserRepo
from app.schemas.auth import RegisterRequest
from app.services.base import BaseService

class InvalidCodeError(AppError):
    status_code = 400

class CodeExpiredError(AppError):
    status_code = 410

class AuthService(BaseService):
    def __init__(self, session: AsyncSession, mailer: Mailer, settings: AuthSettings) -> None:
        super().__init__(session)
        self.user_repo = UserRepo(session)
        self.code_repo = EmailCodeRepo(session)
        self.mailer = mailer
        self.settings = settings

    async def register(self, data: RegisterRequest) -> None:
        user = await self.user_repo.get_by_email(data.email)
        if user is not None:
            if user.email_verified:
                raise ConflictError("Пользователь с таким email уже зарегистрирован")
            # Свежую неподтверждённую регистрацию не перезаписываем: иначе кто угодно мог бы
            # подменить пароль, пока владелец почты ещё не ввёл код
            if user.created_at > datetime.now(UTC) - timedelta(hours=self.settings.unverified_ttl_hours):
                raise ConflictError(
                    "Email уже зарегистрирован, но не подтверждён. "
                    "Введите код из письма или запросите новый: POST /auth/resend-code"
                )
            await self.user_repo.delete(user)
            await self.session.flush()

        user = User(
            name=data.name,
            email=data.email,
            # argon2 нарочно медленный (~50-100 мс CPU): в потоке, чтобы не блокировать других
            password_hash=await asyncio.to_thread(hash_password, data.password),
            city=data.city,
            region=data.region,
            email_verified=False,
        )
        self.user_repo.add(user)
        await self.session.flush()  # нужен user.id для кода
        await self._issue_code(user)

    async def resend_code(self, email: str) -> None:
        user = await self._get_unverified(email)
        current = await self.code_repo.get_for_user(user.id)
        if current is not None:
            wait = self.settings.resend_cooldown_seconds - (datetime.now(UTC) - current.created_at).total_seconds()
            if wait > 0:
                raise TooManyRequestsError(f"Новый код можно запросить через {int(wait) + 1} сек.")
        await self._issue_code(user)

    async def verify_email(self, email: str, code: str) -> str:
        """Проверить код и вернуть токен. Порядок проверок важен — см. комментарии."""
        user = await self._get_unverified(email)
        stored = await self.code_repo.get_for_user(user.id)
        if stored is None:
            raise InvalidCodeError("Код не найден или уже использован — запросите новый")

        # 1. Попытки кончились — код сгорел, даже если сейчас ввели верный
        if stored.attempts >= self.settings.code_max_attempts:
            raise TooManyRequestsError("Слишком много неверных попыток — запросите новый код")

        # 2. Просроченный код не принимаем, даже верный
        if stored.expires_at <= datetime.now(UTC):
            raise CodeExpiredError("Срок действия кода истёк — запросите новый")

        # 3. Неверный код: засчитываем попытку и сохраняем её ДО ответа с ошибкой
        if not code_matches(code, stored.code_hash, self.settings):
            stored.attempts += 1
            left = self.settings.code_max_attempts - stored.attempts
            await self.session.commit()
            if left <= 0:
                raise TooManyRequestsError("Слишком много неверных попыток — запросите новый код")
            raise InvalidCodeError(f"Неверный код. Осталось попыток: {left}")

        # Единственное место, где почта становится подтверждённой
        user.email_verified = True
        await self.code_repo.delete_for_user(user.id)
        await self.session.commit()
        return create_access_token(user.id, self.settings)

    async def login(self, email: str, password: str) -> str:
        # Форма логина не проходит через Schema: NUL отсекаем здесь, иначе Postgres ответит 500
        if "\x00" in email or "\x00" in password:
            raise UnauthorizedError("Неверный email или пароль")
        user = await self.user_repo.get_by_email(email)
        # Пароль проверяем и для несуществующего пользователя: время ответа одинаковое,
        # и по нему нельзя понять, зарегистрирован ли email
        password_ok = await asyncio.to_thread(verify_password, password, user.password_hash if user else None)
        if user is None or not password_ok:
            raise UnauthorizedError("Неверный email или пароль")
        if not user.email_verified:
            raise ForbiddenError("Почта не подтверждена — введите код из письма")
        return create_access_token(user.id, self.settings)

    async def _get_unverified(self, email: str) -> User:
        user = await self.user_repo.get_by_email(email)
        if user is None:
            raise NotFoundError("Пользователь с таким email не найден")
        if user.email_verified:
            raise ConflictError("Почта уже подтверждена — можно входить")
        return user

    async def _issue_code(self, user: User) -> None:
        """Новый код заменяет старый (и сбрасывает попытки). Коммит — только после отправки письма:
        если SMTP упал, в БД не останется кода, который никто не получил."""
        code = generate_code()
        await self.code_repo.delete_for_user(user.id)
        self.code_repo.add(
            EmailVerificationCode(
                user_id=user.id,
                code_hash=hash_code(code, self.settings),
                expires_at=datetime.now(UTC) + timedelta(minutes=self.settings.code_ttl_minutes),
            )
        )
        try:
            await self.session.flush()
            await self.mailer.send_verification_code(user.email, code)
        except Exception:
            await self.session.rollback()
            raise
        await self.session.commit()
