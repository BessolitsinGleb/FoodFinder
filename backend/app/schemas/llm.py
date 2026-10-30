"""Схемы ответов LLM в пайплайне.

Модель возвращает JSON, и он может быть "грязным": null вместо пустого списка,
цена строкой "от 45 000 руб.". Базовый класс это прощает, чтобы из-за мелочи
не терять весь ответ.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.scoring import MatchLevel


def _strip_nul(value: Any) -> Any:
    # Текст со страниц может содержать \x00 — Postgres его не примет, и упал бы весь поиск
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [_strip_nul(v) for v in value]
    return value


class LLMOutput(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def _drop_nulls(cls, data: Any) -> Any:
        # null -> значение по умолчанию (для списков это [])
        if isinstance(data, dict):
            return {key: _strip_nul(value) for key, value in data.items() if value is not None}
        return data


def _to_decimal(value: Any) -> Decimal | None:
    """45000, "45 000", "от 45 000,50 руб." -> Decimal; всё непонятное -> None."""
    if value is None or isinstance(value, Decimal):
        return value
    if isinstance(value, int | float):
        return Decimal(str(value))
    match = re.search(r"\d[\d\s]*(?:[.,]\d+)?", str(value))
    if not match:
        return None
    try:
        return Decimal(match.group().replace(" ", "").replace(",", "."))
    except InvalidOperation:
        return None


class ExtractedSupplier(LLMOutput):
    name: str = Field(description="Название компании без кавычек-ёлочек")
    website: str | None = Field(default=None, description="Собственный сайт компании, не агрегатора")
    city: str | None = None
    region: str | None = Field(default=None, description="Субъект РФ, например 'Республика Татарстан'")
    address: str | None = None
    phones: list[str] = []
    emails: list[str] = []
    product_name: str | None = Field(default=None, description="Как товар назван у поставщика")
    match: MatchLevel = Field(description="Насколько товар совпадает с запросом")
    price: Decimal | None = Field(default=None, description="Цена числом, без валюты")
    price_unit: str | None = Field(default=None, description="За какую единицу цена: кг, т, шт, л")
    moq: Decimal | None = Field(default=None, description="Минимальный объём заказа числом")
    moq_unit: str | None = None
    delivery_terms: str | None = None
    delivery_time: str | None = Field(
        default=None, description="Срок доставки, только если прямо указан: '1-3 дня', 'на следующий день'"
    )
    regions_served: list[str] = Field(default=[], description="Куда возит: регионы или 'вся Россия'")
    certificates: list[str] = Field(default=[], description="Упомянутые документы: ГОСТ, декларации, ISO, ХАССП")
    source_url: str | None = Field(default=None, description="URL результата, где нашли поставщика")
    summary: str | None = Field(default=None, description="1-2 предложения: чем подходит")

    _numbers = field_validator("price", "moq", mode="before")(_to_decimal)


class ExtractedSuppliers(LLMOutput):
    suppliers: list[ExtractedSupplier] = []


class ReputationFacts(LLMOutput):
    """Факты о надёжности компании. Только то, что прямо написано в источниках."""

    inn: str | None = Field(default=None, description="ИНН, 10 или 12 цифр")
    founded_year: int | None = Field(default=None, description="Год регистрации/основания")
    rating: float | None = Field(default=None, ge=0, le=5, description="Средняя оценка по отзывам, шкала 0-5")
    reviews_count: int | None = Field(default=None, ge=0, description="Сколько всего отзывов нашлось")
    certificates: list[str] = []
    red_flags: list[str] = Field(default=[], description="Банкротство, суды, массовые жалобы и т.п.")
    is_liquidated: bool = Field(default=False, description="Компания ликвидирована / прекратила деятельность")

    @field_validator("inn", mode="before")
    @classmethod
    def _inn_digits_only(cls, value: Any) -> str | None:
        digits = re.sub(r"\D", "", str(value)) if value else ""
        return digits if len(digits) in (10, 12) else None


class GeneratedLetter(LLMOutput):
    subject: str
    body: str
