"""Чистая логика без БД и сети: регионы, единицы, формулы оценки."""
from decimal import Decimal

import pytest

from app.domain.companies import company_domain, normalize_company_name
from app.domain.geo import Location, Proximity, normalize_region, proximity, search_areas
from app.domain.scoring import MatchLevel, OfferFacts, SafetyFacts, offer_score, safety
from app.domain.units import estimate_cost


@pytest.mark.parametrize("raw, expected", [
    ("Татарстан", "Республика Татарстан"),
    ("РТ", "Республика Татарстан"),
    ("Респ. Татарстан", "Республика Татарстан"),
    ("Свердловской обл.", "Свердловская область"),
    ("мск", "Москва"),
    ("Подмосковье", "Московская область"),
    ("Кемеровская область — Кузбасс", "Кемеровская область"),
    ("Алтайский край", "Алтайский край"),
    ("Республика Алтай", "Республика Алтай"),
    ("Нарния", None),
])
def test_normalize_region(raw, expected):
    assert normalize_region(raw) == expected


def test_search_goes_from_near_to_far():
    kazan = Location("Казань", "Республика Татарстан")
    assert search_areas(kazan) == ["Казань", "Республика Татарстан", "Приволжский федеральный округ", "Россия"]
    # Для Москвы город = регион, дубль не нужен
    assert search_areas(Location("Москва", "Москва"))[:2] == ["Москва", "Центральный федеральный округ"]


def test_proximity():
    kazan = Location("Казань", "Республика Татарстан")
    assert proximity(kazan, Location("казань", None)) == Proximity.SAME_CITY
    assert proximity(kazan, Location("Набережные Челны", "Республика Татарстан")) == Proximity.SAME_REGION
    assert proximity(kazan, Location("Самара", "Самарская область")) == Proximity.SAME_DISTRICT
    assert proximity(kazan, Location(None, "Москва")) == Proximity.COUNTRY
    assert proximity(kazan, Location("Где-то", None)) == Proximity.UNKNOWN


def test_estimate_cost_converts_units():
    assert estimate_cost(Decimal(45000), "т", Decimal(500), "кг") == Decimal("22500.00")
    assert estimate_cost(Decimal(50), "руб./кг", Decimal("1.5"), "т") == Decimal("75000.00")
    assert estimate_cost(Decimal(10), "шт", Decimal(1), "кг") is None  # несовместимые единицы
    assert estimate_cost(None, "кг", Decimal(1), "кг") is None


def test_safety_formula():
    reliable = safety(SafetyFacts(documents_count=2, has_legal_id=True, rating=5.0,
                                  reviews_count=100, sources_count=5, years_on_market=10))
    assert reliable.rating == Decimal("5.0")
    assert reliable.is_popular and reliable.is_safe

    unknown = safety(SafetyFacts(0, False, None, None, 0, None))
    assert unknown.rating == Decimal("1.0")
    assert not unknown.is_safe

    # Популярный, но без документов — не "безопасный"
    no_docs = safety(SafetyFacts(0, True, 4.8, 300, 5, 10))
    assert no_docs.is_popular and not no_docs.is_safe

    # 5 звёзд при двух отзывах весят мало
    few_reviews = safety(SafetyFacts(0, False, 5.0, 2, 0, None))
    assert few_reviews.breakdown["reviews"] == pytest.approx(0.1)


def _offer(**overrides):
    facts = dict(match=MatchLevel.EXACT, proximity=Proximity.SAME_CITY, delivers_to_buyer=False,
                 safety_rating=Decimal("5.0"), unit_price=Decimal(40), best_unit_price=Decimal(40),
                 has_contacts=True, has_moq=True, has_delivery_terms=True, has_delivery_time=True)
    return offer_score(OfferFacts(**facts | overrides))


def test_offer_score():
    assert _offer().total == Decimal("100.00")
    # Дороже вдвое -> ценовой компонент 0.5
    assert _offer(unit_price=Decimal(80)).breakdown["price"] == 0.5
    # Далеко, но возит к покупателю -> не ниже 0.6 за географию
    assert _offer(proximity=Proximity.COUNTRY, delivers_to_buyer=True).breakdown["proximity"] == 0.6
    assert _offer(match=MatchLevel.WEAK).total < _offer(match=MatchLevel.PARTIAL).total
    # Срок доставки указан — плюс 5 баллов; не указан — без штрафа сверх этого
    assert _offer().total - _offer(has_delivery_time=False).total == Decimal("5.00")


def test_company_dedup_helpers():
    assert company_domain("https://www.Agro-Moloko.ru/catalog") == "agro-moloko.ru"
    assert company_domain("https://moscow.pulscen.ru/firm/1") is None  # агрегатор — не сайт компании
    assert normalize_company_name("ООО «Агро-Молоко»") == normalize_company_name("агро молоко")


def test_only_real_documents_count():
    """Найдено ручным тестом: "ГОСТ" засчитывался как документ и делал продавца "безопасным"."""
    from app.domain.scoring import count_documents
    assert count_documents(["ГОСТ", "ТУ", "ГОСТ 33629-2015", "Честный знак"]) == 0
    assert count_documents(["Декларация соответствия ТР ТС 033", "ISO 22000", "Меркурий", "ГОСТ"]) == 3


def test_own_site_is_not_independent_source():
    """Найдено ручным тестом: поддомены сайта компании засчитывались как "популярность"."""
    from app.domain.companies import independent_sources
    urls = ["https://mukomoloff.ru/contact", "https://saratov.mukomoloff.ru/x",
            "https://msk.pulscen.ru/a", "https://kazan.pulscen.ru/b", "https://checko.ru/c"]
    assert independent_sources(urls, "https://mukomoloff.ru") == {"pulscen.ru", "checko.ru"}
