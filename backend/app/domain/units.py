"""Единицы измерения и примерная стоимость.

Поставщик пишет цену "за тонну", пользователь заказывает "500 кг" — чтобы посчитать
стоимость и сравнить цены разных поставщиков, приводим всё к базовой единице.
"""

import re
from decimal import ROUND_HALF_UP, Decimal

# Синоним -> (базовая единица, множитель)
_UNITS: dict[str, tuple[str, Decimal]] = {
    "г": ("кг", Decimal("0.001")),
    "гр": ("кг", Decimal("0.001")),
    "грамм": ("кг", Decimal("0.001")),
    "кг": ("кг", Decimal(1)),
    "килограмм": ("кг", Decimal(1)),
    "kg": ("кг", Decimal(1)),
    "т": ("кг", Decimal(1000)),
    "тн": ("кг", Decimal(1000)),
    "тонна": ("кг", Decimal(1000)),
    "тонн": ("кг", Decimal(1000)),
    "мл": ("л", Decimal("0.001")),
    "л": ("л", Decimal(1)),
    "литр": ("л", Decimal(1)),
    "шт": ("шт", Decimal(1)),
    "штука": ("шт", Decimal(1)),
    "штук": ("шт", Decimal(1)),
    "тыс шт": ("шт", Decimal(1000)),
}


def _clean(unit: str) -> str:
    """"руб./кг", "за 1 т", "Кг." -> "кг", "т", "кг" """
    text = unit.lower().replace(".", " ")
    text = re.sub(r"руб\w*|₽|rub|\bза\b|/|\b1\b", " ", text)
    return " ".join(text.split())


def to_base(quantity: Decimal, unit: str | None) -> tuple[Decimal, str] | None:
    """500, "г" -> (0.5, "кг"). None, если единицу не знаем."""
    if unit is None:
        return None
    known = _UNITS.get(_clean(unit))
    if known is None:
        return None
    base_unit, factor = known
    return quantity * factor, base_unit


def price_per_base_unit(price: Decimal | None, price_unit: str | None) -> tuple[Decimal, str] | None:
    """Цена 45 000 за "т" -> (45, "кг"): цена за одну базовую единицу."""
    if price is None:
        return None
    base = to_base(Decimal(1), price_unit)
    if base is None:
        return None
    amount_in_base, base_unit = base
    return price / amount_in_base, base_unit


def estimate_cost(
    price: Decimal | None,
    price_unit: str | None,
    quantity: Decimal | None,
    quantity_unit: str | None,
) -> Decimal | None:
    """Примерная стоимость заказа или None, если чего-то не хватает или единицы несовместимы."""
    if quantity is None:
        return None
    unit_price = price_per_base_unit(price, price_unit)
    amount = to_base(quantity, quantity_unit)
    if unit_price is None or amount is None or unit_price[1] != amount[1]:
        return None
    return (unit_price[0] * amount[0]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
