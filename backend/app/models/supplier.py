from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.order import OrderItem


class Supplier(TimestampMixin, Base):
    """Поставщик — общий справочник для всех пользователей.

    Один и тот же поставщик может найтись в разных заказах и по разным категориям,
    поэтому его данные хранятся отдельно от конкретного предложения (SupplierOffer).
    Дедупликация — по домену сайта, а если сайта нет — по названию и городу.
    """

    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    website: Mapped[str | None] = mapped_column(String(500))
    domain: Mapped[str | None] = mapped_column(String(255), unique=True)
    inn: Mapped[str | None] = mapped_column(String(12))

    city: Mapped[str | None] = mapped_column(String(100))
    region: Mapped[str | None] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(Text)
    phones: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'"))
    emails: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'"))

    # Регионы, куда поставщик сам пишет, что доставляет ("вся Россия", "ПФО", ...)
    regions_served: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'")
    )
    delivery_terms: Mapped[str | None] = mapped_column(Text)
    delivery_time: Mapped[str | None] = mapped_column(String(200))  # как написано на сайте

    # Факты для формулы безопасности (app/domain/scoring.py)
    certificates: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'")
    )
    rating: Mapped[Decimal | None] = mapped_column(Numeric(2, 1))
    reviews_count: Mapped[int | None] = mapped_column(Integer)
    founded_year: Mapped[int | None] = mapped_column(Integer)
    red_flags: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'"))
    sources: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'"))

    # Результат формулы
    safety_rating: Mapped[Decimal | None] = mapped_column(Numeric(2, 1))
    safety_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    is_popular: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    is_safe: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    offers: Mapped[list["SupplierOffer"]] = relationship(
        back_populates="supplier", passive_deletes=True, lazy="raise"
    )


class SupplierOffer(TimestampMixin, Base):
    """Предложение поставщика по конкретной позиции корзины + его оценка."""

    __tablename__ = "supplier_offers"
    __table_args__ = (UniqueConstraint("order_item_id", "supplier_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_item_id: Mapped[int] = mapped_column(
        ForeignKey("order_items.id", ondelete="CASCADE"), index=True
    )
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id", ondelete="CASCADE"), index=True
    )

    product_name: Mapped[str | None] = mapped_column(String(300))
    match_level: Mapped[str] = mapped_column(String(20))
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    price_unit: Mapped[str | None] = mapped_column(String(20))
    moq: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))  # минимальный объём заказа
    moq_unit: Mapped[str | None] = mapped_column(String(20))
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    source_url: Mapped[str | None] = mapped_column(String(1000))

    score: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    score_breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # Место в топе по позиции (1 = лучший); NULL — кандидат не попал в top_k
    rank: Mapped[int | None] = mapped_column(Integer)

    agent_summary: Mapped[str | None] = mapped_column(Text)  # кратко: чем подходит
    user_note: Mapped[str | None] = mapped_column(Text)  # заметки пользователя
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    order_item: Mapped["OrderItem"] = relationship(back_populates="offers", lazy="raise")
    supplier: Mapped["Supplier"] = relationship(back_populates="offers", lazy="raise")
