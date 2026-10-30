import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
import jwt
from pwdlib import PasswordHash
from app.core.config import AuthSettings

# Argon2 — рекомендуемый сейчас алгоритм для паролей
_password_hash = PasswordHash.recommended()
# Хэш "ни от чего": сверяем с ним, когда пользователя нет, чтобы время ответа
# не выдавало, зарегистрирован ли email
_DUMMY_HASH = _password_hash.hash("dummy-password")

def hash_password(password: str) -> str:
    return _password_hash.hash(password)

def verify_password(password: str, password_hash: str | None) -> bool:
    # Нет пользователя или пароль не задан (старые записи до авторизации) — всё равно
    # гоняем хэш, чтобы время ответа не отличалось
    if not password_hash:
        _password_hash.verify(password, _DUMMY_HASH)
        return False
    return _password_hash.verify(password, password_hash)

def create_access_token(user_id: int, settings: AuthSettings) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
        "type": "access",
    }
    return jwt.encode(payload, settings.secret_key.get_secret_value(), algorithm=settings.algorithm)

def decode_access_token(token: str, settings: AuthSettings) -> int | None:
    """id пользователя из токена или None, если токен битый, чужой или просрочен."""
    try:
        payload = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=[settings.algorithm],
            options={"require": ["sub", "exp"]},
        )
        if payload.get("type") != "access":
            return None
        return int(payload["sub"])
    except (jwt.PyJWTError, ValueError):
        return None

def generate_code() -> str:
    # secrets, а не random: код не должен быть предсказуемым
    return f"{secrets.randbelow(1_000_000):06d}"

def hash_code(code: str, settings: AuthSettings) -> str:
    """В БД храним не сам код, а его HMAC: утечка таблицы не даст подтвердить чужую почту."""
    key = settings.secret_key.get_secret_value().encode()
    return hmac.new(key, code.encode(), hashlib.sha256).hexdigest()

def code_matches(code: str, code_hash: str, settings: AuthSettings) -> bool:
    return hmac.compare_digest(hash_code(code, settings), code_hash)
