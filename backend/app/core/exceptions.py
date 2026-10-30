"""Ошибки бизнес-логики.

Сервисы не знают про HTTP и бросают эти исключения, а application.py
превращает их в ответы с нужным статусом. Так сервисы можно вызывать
откуда угодно: из роутеров, фоновых задач, тулов агента.
"""

class AppError(Exception):
    status_code = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

class UnauthorizedError(AppError):
    status_code = 401

class ForbiddenError(AppError):
    status_code = 403

class NotFoundError(AppError):
    status_code = 404

class ConflictError(AppError):
    status_code = 409

class TooManyRequestsError(AppError):
    status_code = 429

class ServiceUnavailableError(AppError):
    """Внешний сервис не настроен (нет ключа) или недоступен."""

    status_code = 503

class ExternalServiceError(AppError):
    """Внешний сервис (LLM, поиск, почта) ответил ошибкой или мусором."""

    status_code = 502
