"""Конфигурация приложения.

Все настройки читаются из переменных окружения и .env-файла (сначала корень
проекта, затем backend/ — более поздний файл перекрывает значения).
Настройки сгруппированы по секциям; вложенные поля задаются через "__":

    APP__DEBUG=true
    DB__HOST=localhost
    LLM__API_KEY=sk-or-...
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL, make_url

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent

class AppSettings(BaseModel):
    name: str = "Food Suppliers API"
    env: Literal["local", "dev", "prod"] = "local"
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 8000
    api_prefix: str = "/api/v1"
    # В .env задаётся JSON-списком: APP__CORS_ORIGINS='["http://localhost:5173"]'
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

class DatabaseSettings(BaseModel):
    host: str = "localhost"
    port: int = 5432
    user: str = "postgres"
    password: SecretStr = SecretStr("")
    name: str = "food_suppliers"
    echo: bool = False  # логировать SQL-запросы
    pool_size: int = 5
    max_overflow: int = 10
    # Строка подключения целиком (так её выдаёт Railway: postgresql://user:pass@host:port/db).
    # Если задана — важнее отдельных полей выше.
    dsn: SecretStr | None = None

    @property
    def url(self) -> URL:
        if self.dsn and self.dsn.get_secret_value():
            # Драйвер всегда asyncpg, какой бы префикс ни пришёл (postgres://, postgresql://)
            return make_url(self.dsn.get_secret_value()).set(drivername="postgresql+asyncpg")
        # URL.create сам экранирует спецсимволы в пароле
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.user,
            password=self.password.get_secret_value() or None,
            host=self.host,
            port=self.port,
            database=self.name,
        )

class LLMSettings(BaseModel):
    """Настройки LLM-провайдера (OpenRouter, OpenAI-совместимый API)."""

    api_key: SecretStr = SecretStr("")
    base_url: str = "https://openrouter.ai/api/v1"
    # Слаг модели на OpenRouter; есть также deepseek/deepseek-v4-flash (дешевле и быстрее)
    model: str = "deepseek/deepseek-v4-flash"
    temperature: float = 0.3
    max_tokens: int = 4096
    # "Размышления" модели (reasoning). В чате помогают, а для извлечения фактов и писем
    # только тратят токены: с ними ответ часто обрезался и приходил пустым.
    chat_reasoning: bool = True
    json_reasoning: bool = False
    timeout: float = 120.0
    max_retries: int = 2
    # Максимум итераций "модель -> вызов тулов -> модель" за один запрос
    max_agent_steps: int = 8
    # Необязательные заголовки для атрибуции приложения в OpenRouter
    app_url: str | None = None
    app_title: str | None = "Food Suppliers"

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key.get_secret_value())

class WebSearchSettings(BaseModel):
    """Tavily — поиск в интернете для агента."""

    api_key: SecretStr = SecretStr("")
    base_url: str = "https://api.tavily.com"
    # basic = 1 кредит за запрос, advanced = 2 (точнее, но дороже)
    search_depth: Literal["basic", "advanced"] = "basic"
    timeout: float = 30.0

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key.get_secret_value())

class SupplierSearchSettings(BaseModel):
    """Ручки пайплайна поиска поставщиков: по сути, баланс "качество vs стоимость"."""

    # Сколько результатов брать из одного поискового запроса
    results_per_query: int = 8
    # Расширяем географию (город -> регион -> округ -> Россия), пока не наберём столько кандидатов
    min_candidates: int = 8
    # Сколько кандидатов сверх top_k проверяем по отзывам и документам.
    # Проверка = 2 поисковых запроса + 1 вызов LLM на поставщика, поэтому проверяем не всех.
    extra_to_verify: int = 3
    # Сколько поставщиков проверяем параллельно
    verify_concurrency: int = 3

class LettersSettings(BaseModel):
    templates_dir: Path = BACKEND_DIR / "app" / "templates" / "letters"
    default_template: str = "default"

class AuthSettings(BaseModel):
    # Обязателен: без него приложение не стартует (см. application.lifespan)
    secret_key: SecretStr = SecretStr("")
    algorithm: str = "HS256"
    access_token_minutes: int = 60 * 24
    code_ttl_minutes: int = 10
    # После стольких неверных вводов код сгорает — нужно запросить новый
    code_max_attempts: int = 5
    resend_cooldown_seconds: int = 60
    # Неподтверждённую регистрацию старше этого срока можно перезаписать (например, опечатались в пароле)
    unverified_ttl_hours: int = 24

class MailSettings(BaseModel):
    """SMTP для писем с кодом подтверждения."""

    host: str = ""
    port: int = 587
    user: str = ""
    password: SecretStr = SecretStr("")
    from_address: str = ""
    # 465 — сразу TLS (use_tls), 587 — STARTTLS (по умолчанию)
    use_tls: bool = False
    timeout: float = 15.0
    # Только для разработки: код пишется в лог вместо отправки. Почта всё равно
    # подтверждается только вводом кода — автоподтверждения нет.
    dev_log_codes: bool = False

    @property
    def is_configured(self) -> bool:
        return bool(self.host and self.from_address)

class RedisSettings(BaseModel):
    url: str = "redis://localhost:6379/0"

class RateLimitSettings(BaseModel):
    # Не больше requests запросов за window_ms на одного пользователя (или IP, если не залогинен)
    requests: int = 3
    window_ms: int = 1000

class ChatSettings(BaseModel):
    """Память диалога с агентом — только в Redis, сама стирается по TTL."""

    history_messages: int = 20
    history_ttl_seconds: int = 60 * 60

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    app: AppSettings = AppSettings()
    db: DatabaseSettings = DatabaseSettings()
    llm: LLMSettings = LLMSettings()
    web: WebSearchSettings = WebSearchSettings()
    search: SupplierSearchSettings = SupplierSearchSettings()
    letters: LettersSettings = LettersSettings()
    auth: AuthSettings = AuthSettings()
    smtp: MailSettings = MailSettings()
    redis: RedisSettings = RedisSettings()
    rate_limit: RateLimitSettings = RateLimitSettings()
    chat: ChatSettings = ChatSettings()

@lru_cache
def get_settings() -> Settings:
    return Settings()
