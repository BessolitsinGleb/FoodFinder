import base64
import logging
import time
from email.message import EmailMessage
import aiosmtplib
import httpx2
from app.core.config import MailSettings
from app.core.exceptions import ExternalServiceError, ServiceUnavailableError

logger = logging.getLogger(__name__)

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
SUBJECT = "Код подтверждения почты"

def _body(code: str) -> str:
    return (
        f"Ваш код подтверждения: {code}\n\n"
        "Код действует 10 минут. Если вы не регистрировались — просто проигнорируйте письмо."
    )

class Mailer:
    """Письма с кодом подтверждения: через SMTP (VPS, локально) или по HTTPS — Gmail API / Brevo
    (хостинги, где исходящий SMTP закрыт, например бесплатный Render)."""

    def __init__(self, settings: MailSettings, transport: httpx2.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self._transport = transport  # подменяется в тестах
        self._gmail_token: str | None = None
        self._gmail_token_expires = 0.0

    async def send_verification_code(self, email: str, code: str) -> None:
        if self.settings.dev_log_codes:
            # Только для локальной разработки: код в логе вместо письма.
            # Подтверждение всё равно требует ввода этого кода.
            logger.warning("[DEV] Код подтверждения для %s: %s", email, code)
            return
        if not self.settings.is_configured:
            raise ServiceUnavailableError("Отправка писем не настроена: заполните SMTP__* в .env")

        if self.settings.provider == "brevo":
            await self._send_brevo(email, code)
        elif self.settings.provider == "gmail":
            await self._send_gmail(email, code)
        else:
            await self._send_smtp(email, code)

    async def _send_smtp(self, email: str, code: str) -> None:
        message = EmailMessage()
        message["From"] = self.settings.from_address
        message["To"] = email
        message["Subject"] = SUBJECT
        message.set_content(_body(code))
        try:
            await aiosmtplib.send(
                message,
                hostname=self.settings.host,
                port=self.settings.port,
                username=self.settings.user or None,
                password=self.settings.password.get_secret_value() or None,
                use_tls=self.settings.use_tls,
                start_tls=None if self.settings.use_tls else True,
                timeout=self.settings.timeout,
            )
        except (aiosmtplib.SMTPException, OSError) as exc:
            logger.warning("SMTP send failed: %s", exc)
            raise ExternalServiceError("Не удалось отправить письмо с кодом, попробуйте позже") from exc

    async def _gmail_access_token(self, client: httpx2.AsyncClient) -> str:
        """Короткоживущий (~1 ч) access-токен из refresh-токена; кэшируем до истечения."""
        if self._gmail_token and time.monotonic() < self._gmail_token_expires:
            return self._gmail_token
        response = await client.post(GOOGLE_TOKEN_URL, data={
            "client_id": self.settings.gmail_client_id,
            "client_secret": self.settings.gmail_client_secret.get_secret_value(),
            "refresh_token": self.settings.gmail_refresh_token.get_secret_value(),
            "grant_type": "refresh_token",
        })
        response.raise_for_status()
        data = response.json()
        self._gmail_token = data["access_token"]
        # Запас в минуту, чтобы не отправить письмо с токеном, который истекает прямо сейчас
        self._gmail_token_expires = time.monotonic() + int(data.get("expires_in", 3600)) - 60
        return self._gmail_token

    async def _send_gmail(self, email: str, code: str) -> None:
        message = EmailMessage()
        # From можно не указывать: Gmail сам подставит адрес аккаунта, выдавшего токен
        if self.settings.from_address:
            message["From"] = f"{self.settings.from_name} <{self.settings.from_address}>"
        message["To"] = email
        message["Subject"] = SUBJECT
        message.set_content(_body(code))
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        try:
            async with httpx2.AsyncClient(timeout=self.settings.timeout, transport=self._transport) as client:
                token = await self._gmail_access_token(client)
                response = await client.post(
                    GMAIL_SEND_URL, json={"raw": raw}, headers={"Authorization": f"Bearer {token}"}
                )
                response.raise_for_status()
        except httpx2.HTTPStatusError as exc:
            # invalid_grant = refresh-токен отозван или истёк: заново запустить scripts/gmail_auth.py
            logger.warning("Gmail send failed %s: %s", exc.response.status_code, exc.response.text[:300])
            self._gmail_token = None
            raise ExternalServiceError("Не удалось отправить письмо с кодом, попробуйте позже") from exc
        except httpx2.HTTPError as exc:
            logger.warning("Gmail API unreachable: %s", exc)
            raise ExternalServiceError("Не удалось отправить письмо с кодом, попробуйте позже") from exc

    async def _send_brevo(self, email: str, code: str) -> None:
        payload = {
            "sender": {"name": self.settings.from_name, "email": self.settings.from_address},
            "to": [{"email": email}],
            "subject": SUBJECT,
            "textContent": _body(code),
        }
        headers = {"api-key": self.settings.brevo_api_key.get_secret_value(), "accept": "application/json"}
        try:
            async with httpx2.AsyncClient(timeout=self.settings.timeout, transport=self._transport) as client:
                response = await client.post(BREVO_SEND_URL, json=payload, headers=headers)
                response.raise_for_status()
        except httpx2.HTTPStatusError as exc:
            # В ответе Brevo нет секретов: code + message ("sender not verified", "unauthorized"...)
            logger.warning("Brevo send failed %s: %s", exc.response.status_code, exc.response.text[:300])
            raise ExternalServiceError("Не удалось отправить письмо с кодом, попробуйте позже") from exc
        except httpx2.HTTPError as exc:
            logger.warning("Brevo unreachable: %s", exc)
            raise ExternalServiceError("Не удалось отправить письмо с кодом, попробуйте позже") from exc
