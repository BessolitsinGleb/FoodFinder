"""Формулы оценки поставщиков.

Принцип: LLM только достаёт факты из найденных страниц (есть ли сертификаты,
сколько отзывов, какой рейтинг, где находится), а оценку считает код по формуле.
Так оценка воспроизводима и объяснима: в ответе API лежит разбивка по компонентам.

1. Безопасность продавца — шкала от 1 до 5 (safety_rating).
2. Итоговый скор предложения — от 0 до 100, по нему выбираем top-k на каждую позицию.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.domain.geo import Proximity

# ---------- Безопасность продавца ----------

# Отзывов достаточно, чтобы считать рейтинг надёжным и продавца — популярным
POPULAR_REVIEWS = 20
# ...или о компании пишут хотя бы в стольких независимых источниках
POPULAR_SOURCES = 3
# Столько лет на рынке считаем "давно работает"
MATURE_YEARS = 5

SAFETY_WEIGHTS = {
    "documents": 0.35,  # сертификаты, декларации, лицензии
    "legal": 0.15,  # найден ИНН/ОГРН — компания реально существует как юрлицо
    "reviews": 0.25,  # средний рейтинг с поправкой на число отзывов
    "popularity": 0.10,  # упоминания в независимых источниках
    "age": 0.15,  # сколько лет на рынке
}

# Что считается документом. "ГОСТ 33629" или "ТУ" — это стандарт, по которому сделан товар,
# а не подтверждающий документ продавца; "Честный знак" — маркировка. Их не считаем.
_DOCUMENT_MARKERS = (
    "декларац", "сертификат", "iso", "haccp", "хассп", "fssc", "brc",
    "меркурий", "всд", "ветеринар", "halal", "халял", "лиценз", "свидетельств",
)


def count_documents(names: list[str] | set[str]) -> int:
    return len({n.strip().lower() for n in names if any(m in n.lower() for m in _DOCUMENT_MARKERS)})


@dataclass(frozen=True, slots=True)
class SafetyFacts:
    documents_count: int
    has_legal_id: bool
    rating: float | None  # средний рейтинг по отзывам, 0..5
    reviews_count: int | None
    sources_count: int
    years_on_market: int | None


@dataclass(frozen=True, slots=True)
class SafetyResult:
    rating: Decimal  # 1.0 .. 5.0
    is_popular: bool
    is_safe: bool
    breakdown: dict[str, float]


def _capped(value: float, cap: float) -> float:
    return min(max(value, 0.0) / cap, 1.0)


def is_popular(reviews_count: int | None, sources_count: int) -> bool:
    return (reviews_count or 0) >= POPULAR_REVIEWS or sources_count >= POPULAR_SOURCES


def safety(facts: SafetyFacts) -> SafetyResult:
    reviews = (facts.reviews_count or 0)
    components = {
        "documents": _capped(facts.documents_count, 2),  # 2+ документа = максимум
        "legal": 1.0 if facts.has_legal_id else 0.0,
        # 4.8 при трёх отзывах значит меньше, чем 4.5 при сотне: умножаем на "уверенность"
        "reviews": (facts.rating or 0) / 5 * _capped(reviews, POPULAR_REVIEWS),
        "popularity": _capped(facts.sources_count, POPULAR_SOURCES),
        "age": _capped(facts.years_on_market or 0, MATURE_YEARS),
    }
    weighted = sum(SAFETY_WEIGHTS[name] * value for name, value in components.items())
    rating = Decimal(str(round(1 + 4 * weighted, 1)))

    popular = is_popular(facts.reviews_count, facts.sources_count)
    return SafetyResult(
        rating=rating,
        is_popular=popular,
        # Безопасный = популярный и с подтверждёнными документами
        is_safe=popular and facts.documents_count > 0,
        breakdown={name: round(value, 3) for name, value in components.items()},
    )


# ---------- Итоговый скор предложения ----------


class MatchLevel(StrEnum):
    """Насколько товар поставщика совпадает с запросом (это решает LLM)."""

    EXACT = "exact"  # ровно то, что нужно
    PARTIAL = "partial"  # близко: другая фасовка, жирность и т.п.
    WEAK = "weak"  # смежный товар
    NONE = "none"  # не подходит — отбрасываем


MATCH_VALUES = {MatchLevel.EXACT: 1.0, MatchLevel.PARTIAL: 0.6, MatchLevel.WEAK: 0.2, MatchLevel.NONE: 0.0}

PROXIMITY_VALUES = {
    Proximity.SAME_CITY: 1.0,
    Proximity.SAME_REGION: 0.8,
    Proximity.SAME_DISTRICT: 0.5,
    Proximity.COUNTRY: 0.25,
    Proximity.UNKNOWN: 0.1,
}
# Если поставщик далеко, но сам пишет, что возит в регион покупателя
DELIVERS_TO_BUYER_MIN = 0.6
# Цена не указана — не обнуляем, но и не ставим наравне с известной
UNKNOWN_PRICE_VALUE = 0.3

OFFER_WEIGHTS = {
    "match": 0.30,
    "proximity": 0.20,
    "safety": 0.25,
    "price": 0.15,
    # Поставщик сам указал срок доставки — плюс; не указал — не штрафуем, просто без бонуса
    "delivery_time": 0.05,
    "completeness": 0.05,
}


@dataclass(frozen=True, slots=True)
class OfferFacts:
    match: MatchLevel
    proximity: Proximity
    delivers_to_buyer: bool
    safety_rating: Decimal
    unit_price: Decimal | None  # цена за базовую единицу
    best_unit_price: Decimal | None  # лучшая цена среди кандидатов той же позиции
    has_contacts: bool
    has_moq: bool
    has_delivery_terms: bool
    has_delivery_time: bool = False


@dataclass(frozen=True, slots=True)
class OfferScore:
    total: Decimal  # 0 .. 100
    breakdown: dict[str, float]


def offer_score(facts: OfferFacts) -> OfferScore:
    proximity_value = PROXIMITY_VALUES[facts.proximity]
    if facts.delivers_to_buyer:
        proximity_value = max(proximity_value, DELIVERS_TO_BUYER_MIN)

    if facts.unit_price and facts.best_unit_price:
        price_value = float(facts.best_unit_price / facts.unit_price)  # самый дешёвый = 1.0
    else:
        price_value = UNKNOWN_PRICE_VALUE

    filled = [facts.has_contacts, facts.has_moq, facts.has_delivery_terms, facts.unit_price is not None]
    components = {
        "match": MATCH_VALUES[facts.match],
        "proximity": proximity_value,
        "safety": float(facts.safety_rating - 1) / 4,
        "price": min(price_value, 1.0),
        "delivery_time": 1.0 if facts.has_delivery_time else 0.0,
        "completeness": sum(filled) / len(filled),
    }
    total = sum(OFFER_WEIGHTS[name] * value for name, value in components.items()) * 100
    return OfferScore(
        total=Decimal(str(round(total, 2))),
        breakdown={name: round(value, 3) for name, value in components.items()},
    )
