from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import Boolean, DateTime, ForeignKey, SmallInteger, String, false
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.order import Order

class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    # Храним в нижнем регистре (нормализуется в схеме), поэтому уникальность
    # фактически регистронезависимая.
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # Войти можно только после ввода кода из письма
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Может редактировать справочник категорий. Выдаётся вручную в БД.
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Город и регион проживания — с них агент начинает поиск поставщиков.
    # Регион хранится в каноническом виде (см. app/domain/geo.py).
    city: Mapped[str] = mapped_column(String(100))
    region: Mapped[str] = mapped_column(String(100), index=True)

    # lazy="raise": в async нельзя неявно подгружать связи, так что
    # случайное обращение без selectinload() сразу упадёт с понятной ошибкой.
    orders: Mapped[list["Order"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )

class EmailVerificationCode(TimestampMixin, Base):
    """Код подтверждения почты. У пользователя не больше одного действующего кода."""

    __tablename__ = "email_verification_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
