from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import Field, computed_field, field_validator, model_validator

from app.domain.geo import normalize_city
from app.domain.units import to_base
from app.models.order import OrderStatus
from app.schemas.common import ORMSchema, PatchSchema, Schema
from app.schemas.user import validate_region


def validate_unit(value: str | None) -> str | None:
    """Единицы ограничены известными: иначе не посчитать стоимость и не сравнить цены."""
    if value is not None and to_base(Decimal(1), value) is None:
        raise ValueError("Неизвестная единица. Допустимо: г, кг, т, мл, л, шт, тыс шт")
    return value


# ---------- Корзина ----------


class OrderCreate(Schema):
    top_k: int = Field(default=3, ge=1, le=5, description="Сколько лучших поставщиков на позицию")


class OrderUpdate(PatchSchema):
    non_nullable_fields = ("top_k", "status")

    top_k: int | None = Field(default=None, ge=1, le=5)
    # Вручную можно только отменить заказ или отметить завершённым
    status: Literal[OrderStatus.CANCELLED, OrderStatus.COMPLETED] | None = None


class DeliveryUpdate(Schema):
    """Ответ на вопрос "Доставляем в ваш город?". Пустое тело = "да, в мой город"."""

    city: str | None = Field(default=None, min_length=1, max_length=100)
    region: str | None = Field(default=None, min_length=1, max_length=100)
    # Точный адрес необязателен, но помогает искать поставщиков рядом
    address: str | None = Field(default=None, max_length=500)

    _city = field_validator("city")(normalize_city)
    _region = field_validator("region")(validate_region)


class OrderItemCreate(Schema):
    # Либо категория из списка, либо свой вариант ("Другое")
    category_id: int | None = None
    custom_title: str | None = Field(default=None, min_length=2, max_length=200)
    details: str | None = Field(default=None, max_length=1000, examples=["жирность 26%, мешки по 25 кг"])
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=3)
    unit: str | None = Field(default=None, examples=["кг"])

    _unit = field_validator("unit")(validate_unit)

    @model_validator(mode="after")
    def _category_or_custom(self) -> Self:
        if (self.category_id is None) == (self.custom_title is None):
            raise ValueError("Укажите либо category_id, либо custom_title (вариант 'Другое')")
        if self.quantity is not None and self.unit is None:
            raise ValueError("Для объёма нужна единица измерения")
        return self


class OrderItemUpdate(PatchSchema):
    details: str | None = Field(default=None, max_length=1000)
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=3)
    unit: str | None = None

    _unit = field_validator("unit")(validate_unit)


class OrderItemRead(ORMSchema):
    id: int
    category_id: int | None
    title: str
    details: str | None
    quantity: Decimal | None
    unit: str | None


class OrderRead(ORMSchema):
    id: int
    user_id: int
    status: OrderStatus
    delivery_city: str
    delivery_region: str
    delivery_address: str | None
    delivery_confirmed: bool
    top_k: int
    items: list[OrderItemRead]
    search_progress: dict[str, Any] | None
    search_error: str | None
    searched_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def delivery_question(self) -> str | None:
        """Вопрос, который фронт показывает до старта поиска."""
        if self.delivery_confirmed:
            return None
        return f"Доставка в г. {self.delivery_city} ({self.delivery_region})? Если нет — укажите адрес."


# ---------- Результаты поиска ----------


class SupplierRead(ORMSchema):
    id: int
    name: str
    website: str | None
    inn: str | None
    city: str | None
    region: str | None
    address: str | None
    phones: list[str]
    emails: list[str]
    regions_served: list[str]
    delivery_terms: str | None
    delivery_time: str | None
    certificates: list[str]
    rating: Decimal | None
    reviews_count: int | None
    founded_year: int | None
    red_flags: list[str]
    sources: list[str]
    safety_rating: Decimal | None
    safety_breakdown: dict[str, float] | None
    is_popular: bool
    is_safe: bool


class OfferRead(ORMSchema):
    id: int
    order_item_id: int
    rank: int | None
    score: Decimal
    score_breakdown: dict[str, float]
    product_name: str | None
    match_level: str
    price: Decimal | None
    price_unit: str | None
    moq: Decimal | None
    moq_unit: str | None
    estimated_cost: Decimal | None
    source_url: str | None
    agent_summary: str | None
    user_note: str | None
    is_selected: bool
    supplier: SupplierRead


class OfferUpdate(PatchSchema):
    non_nullable_fields = ("is_selected",)

    is_selected: bool | None = None
    user_note: str | None = Field(default=None, max_length=2000)


class ItemResults(Schema):
    item: OrderItemRead
    offers: list[OfferRead]


class OrderResults(Schema):
    order: OrderRead
    items: list[ItemResults]
    # Сумма по лучшему предложению на каждую позицию, где цену удалось посчитать
    estimated_total: Decimal | None
    priced_items: int
