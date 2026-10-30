from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    false,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.category import FoodCategory
    from app.models.supplier import SupplierOffer
    from app.models.user import User


class OrderStatus(StrEnum):
    DRAFT = "draft"  # корзина: пользователь набирает позиции
    SEARCHING = "searching"  # агент ищет поставщиков
    READY = "ready"  # подборка готова, можно выбирать и генерировать письма
    FAILED = "failed"  # поиск упал (можно перезапустить)
    COMPLETED = "completed"  # письма поставщикам сформированы
    CANCELLED = "cancelled"


# Пока заказ в этих статусах, корзину можно менять (после изменения нужен новый поиск)
EDITABLE_STATUSES = {OrderStatus.DRAFT, OrderStatus.READY, OrderStatus.FAILED}


class Order(TimestampMixin, Base):
    """Заказ = корзина пользователя + результат поиска поставщиков. Вместе — история заказов."""

    __tablename__ = "orders"
    # История запрашивается как "заказы пользователя, новые сверху" —
    # составной индекс покрывает и фильтр, и сортировку.
    __table_args__ = (Index("ix_orders_user_id_created_at", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # native_enum=False -> обычный VARCHAR + CHECK; добавлять статусы проще,
    # чем менять нативный ENUM в Postgres.
    status: Mapped[OrderStatus] = mapped_column(
        Enum(
            OrderStatus,
            name="order_status",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        default=OrderStatus.DRAFT,
        server_default=OrderStatus.DRAFT.value,
    )

    # Куда везти. При создании подставляем город/регион пользователя,
    # но поиск не стартует, пока пользователь не подтвердит адрес.
    delivery_city: Mapped[str] = mapped_column(String(100))
    delivery_region: Mapped[str] = mapped_column(String(100))
    delivery_address: Mapped[str | None] = mapped_column(Text)
    delivery_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    # Сколько лучших поставщиков показывать на каждую позицию (1..5)
    top_k: Mapped[int] = mapped_column(SmallInteger, default=3, server_default="3")

    # Прогресс поиска по позициям: {"<item_id>": {"status": "...", "found": 3}}
    search_progress: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    search_error: Mapped[str | None] = mapped_column(Text)
    searched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(back_populates="orders", lazy="raise")
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="OrderItem.id",
        lazy="raise",
    )


class OrderItem(TimestampMixin, Base):
    """Позиция корзины: что именно нужно и в каком объёме."""

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    # NULL, если пользователь выбрал "Другое" и ввёл свою категорию
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("food_categories.id", ondelete="SET NULL"), index=True
    )
    # Название позиции: копия имени категории или свой текст для "Другое".
    # Копия нужна, чтобы история не "поехала" при переименовании категории.
    title: Mapped[str] = mapped_column(String(200))
    # Уточнения: "жирность 26%", "ГОСТ", "фасовка мешки 25 кг"
    details: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    unit: Mapped[str | None] = mapped_column(String(20))

    order: Mapped["Order"] = relationship(back_populates="items", lazy="raise")
    category: Mapped["FoodCategory | None"] = relationship(lazy="raise")
    offers: Mapped[list["SupplierOffer"]] = relationship(
        back_populates="order_item",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
