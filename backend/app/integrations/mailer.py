import logging
from email.message import EmailMessage
import aiosmtplib
from app.core.config import MailSettings
from app.core.exceptions import ExternalServiceError, ServiceUnavailableError

logger = logging.getLogger(__name__)

class Mailer:
    def __init__(self, settings: MailSettings) -> None:
        self.settings = settings

    async def send_verification_code(self, email: str, code: str) -> None:
        if self.settings.dev_log_codes:
            # Только для локальной разработки: код в логе вместо письма.
            # Подтверждение всё равно требует ввода этого кода.
            logger.warning("[DEV] Код подтверждения для %s: %s", email, code)
            return
        if not self.settings.is_configured:
            raise ServiceUnavailableError("Отправка писем не настроена: заполните SMTP__* в .env")

        message = EmailMessage()
        message["From"] = self.settings.from_address
        message["To"] = email
        message["Subject"] = "Код подтверждения почты"
        message.set_content(
            f"Ваш код подтверждения: {code}\n\n"
            "Код действует 10 минут. Если вы не регистрировались — просто проигнорируйте письмо."
        )
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
