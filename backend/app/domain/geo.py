"""География: регионы РФ, федеральные округа и "близость" поставщика к покупателю.

Поставщиков ищем от ближнего к дальнему: город -> регион -> федеральный округ -> Россия.
Для этого регион нужно привести к каноническому названию: пользователи и сайты
пишут его как угодно ("Татарстан", "РТ", "Респ. Татарстан", "Татарстане").
"""

import re
from dataclasses import dataclass
from difflib import get_close_matches
from enum import StrEnum

FEDERAL_DISTRICTS: dict[str, list[str]] = {
    "Центральный": [
        "Белгородская область", "Брянская область", "Владимирская область",
        "Воронежская область", "Ивановская область", "Калужская область",
        "Костромская область", "Курская область", "Липецкая область", "Москва",
        "Московская область", "Орловская область", "Рязанская область",
        "Смоленская область", "Тамбовская область", "Тверская область",
        "Тульская область", "Ярославская область",
    ],
    "Северо-Западный": [
        "Архангельская область", "Вологодская область", "Калининградская область",
        "Ленинградская область", "Мурманская область", "Ненецкий автономный округ",
        "Новгородская область", "Псковская область", "Республика Карелия",
        "Республика Коми", "Санкт-Петербург",
    ],
    "Южный": [
        "Астраханская область", "Волгоградская область", "Краснодарский край",
        "Республика Адыгея", "Республика Калмыкия", "Республика Крым",
        "Ростовская область", "Севастополь",
    ],
    "Северо-Кавказский": [
        "Кабардино-Балкарская Республика", "Карачаево-Черкесская Республика",
        "Республика Дагестан", "Республика Ингушетия",
        "Республика Северная Осетия — Алания", "Ставропольский край",
        "Чеченская Республика",
    ],
    "Приволжский": [
        "Кировская область", "Нижегородская область", "Оренбургская область",
        "Пензенская область", "Пермский край", "Республика Башкортостан",
        "Республика Марий Эл", "Республика Мордовия", "Республика Татарстан",
        "Самарская область", "Саратовская область", "Удмуртская Республика",
        "Ульяновская область", "Чувашская Республика",
    ],
    "Уральский": [
        "Курганская область", "Свердловская область", "Тюменская область",
        "Ханты-Мансийский автономный округ — Югра", "Челябинская область",
        "Ямало-Ненецкий автономный округ",
    ],
    "Сибирский": [
        "Алтайский край", "Иркутская область", "Кемеровская область",
        "Красноярский край", "Новосибирская область", "Омская область",
        "Республика Алтай", "Республика Тыва", "Республика Хакасия", "Томская область",
    ],
    "Дальневосточный": [
        "Амурская область", "Еврейская автономная область", "Забайкальский край",
        "Камчатский край", "Магаданская область", "Приморский край",
        "Республика Бурятия", "Республика Саха (Якутия)", "Сахалинская область",
        "Хабаровский край", "Чукотский автономный округ",
    ],
}

REGION_TO_DISTRICT: dict[str, str] = {
    region: district for district, regions in FEDERAL_DISTRICTS.items() for region in regions
}

# Как регионы часто называют в жизни. Ключи — уже нормализованные (см. _normalize).
_ALIASES: dict[str, str] = {
    "мск": "Москва",
    "спб": "Санкт-Петербург",
    "питер": "Санкт-Петербург",
    "мо": "Московская область",
    "подмосковье": "Московская область",
    "ло": "Ленинградская область",
    "рт": "Республика Татарстан",
    "башкирия": "Республика Башкортостан",
    "рб": "Республика Башкортостан",
    "чувашия": "Чувашская Республика",
    "удмуртия": "Удмуртская Республика",
    "якутия": "Республика Саха (Якутия)",
    "кузбасс": "Кемеровская область",
    "хмао": "Ханты-Мансийский автономный округ — Югра",
    "югра": "Ханты-Мансийский автономный округ — Югра",
    "янао": "Ямало-Ненецкий автономный округ",
    "кбр": "Кабардино-Балкарская Республика",
    "кчр": "Карачаево-Черкесская Республика",
    "северная осетия": "Республика Северная Осетия — Алания",
    "чечня": "Чеченская Республика",
    "крым": "Республика Крым",
}

# Слова, которые не несут смысла при сравнении ("Тверская область" ~ "тверская")
_GENERIC_WORDS = r"\b(область|обл|край|республика|респ|автономный|автономная|округ|ао|город|г)\b"


def _normalize(text: str) -> str:
    text = text.lower().replace("ё", "е").replace("—", " ").replace("-", " ")
    text = re.sub(r"[^\w\s()]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _core(text: str) -> str:
    """Смысловая часть названия: "Респ. Татарстан" -> "татарстан"."""
    core = re.sub(_GENERIC_WORDS, " ", _normalize(text))
    core = re.sub(r"[()]", " ", core)
    return re.sub(r"\s+", " ", core).strip()


_CORE_TO_REGION: dict[str, str] = {_core(region): region for region in REGION_TO_DISTRICT}


def normalize_region(raw: str | None) -> str | None:
    """Привести регион к каноническому названию или вернуть None, если не узнали."""
    if not raw or not raw.strip():
        return None

    normalized = _normalize(raw)
    if normalized in _ALIASES:
        return _ALIASES[normalized]

    core = _core(raw)
    if core in _ALIASES:
        return _ALIASES[core]
    if core in _CORE_TO_REGION:
        return _CORE_TO_REGION[core]

    # Падежи и опечатки: "Татарстане", "Свердловской" -> ближайшее похожее название
    match = get_close_matches(core, _CORE_TO_REGION.keys(), n=1, cutoff=0.8)
    if match:
        return _CORE_TO_REGION[match[0]]

    # Составные названия: "Кемеровская область — Кузбасс" -> ищем по отдельным словам
    for word in core.split():
        if word in _CORE_TO_REGION:
            return _CORE_TO_REGION[word]
        if word in _ALIASES:
            return _ALIASES[word]
    return None


def federal_district(region: str | None) -> str | None:
    return REGION_TO_DISTRICT.get(region) if region else None


def normalize_city(raw: str | None) -> str | None:
    """Убираем "г." и лишние пробелы, приводим к виду "Нижний Новгород"."""
    if not raw or not raw.strip():
        return None
    city = re.sub(r"^\s*(г\.|г |город )\s*", "", raw.strip(), flags=re.IGNORECASE)
    return " ".join(word.capitalize() if word.islower() else word for word in city.split())


@dataclass(frozen=True, slots=True)
class Location:
    city: str | None
    region: str | None

    @property
    def district(self) -> str | None:
        return federal_district(self.region)


class Proximity(StrEnum):
    SAME_CITY = "same_city"
    SAME_REGION = "same_region"
    SAME_DISTRICT = "same_district"
    COUNTRY = "country"
    UNKNOWN = "unknown"


def _same_city(a: str | None, b: str | None) -> bool:
    return bool(a and b) and _normalize(a) == _normalize(b)


def proximity(buyer: Location, supplier: Location) -> Proximity:
    if _same_city(buyer.city, supplier.city):
        return Proximity.SAME_CITY
    if supplier.region is None:
        return Proximity.UNKNOWN
    if supplier.region == buyer.region:
        return Proximity.SAME_REGION
    if supplier.district and supplier.district == buyer.district:
        return Proximity.SAME_DISTRICT
    return Proximity.COUNTRY


def search_areas(buyer: Location) -> list[str]:
    """Географии для поисковых запросов — от ближней к дальней, без повторов.

    Для Москвы город и регион совпадают, поэтому дубли убираем.
    """
    areas = [
        buyer.city,
        buyer.region,
        f"{buyer.district} федеральный округ" if buyer.district else None,
        "Россия",
    ]
    result: list[str] = []
    for area in areas:
        if area and area not in result:
            result.append(area)
    return result
