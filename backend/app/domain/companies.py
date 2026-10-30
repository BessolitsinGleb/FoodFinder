"""Как понять, что два найденных поставщика — одна и та же компания."""

import re
from urllib.parse import urlparse

# Площадки-агрегаторы: компании на них — поставщики, а сами площадки — нет.
# Их домен нельзя считать сайтом компании, иначе все продавцы с pulscen.ru склеятся в одного.
AGGREGATOR_DOMAINS = {
    "pulscen.ru", "tiu.ru", "satom.ru", "flagma.ru", "agroserver.ru", "b2b-center.ru",
    "avito.ru", "ozon.ru", "wildberries.ru", "market.yandex.ru", "yandex.ru", "2gis.ru",
    "zoon.ru", "rusprofile.ru", "list-org.com", "vk.com", "t.me", "spark-interfax.ru",
    "fabricators.ru", "optlist.ru", "prodtorg.ru", "foodmarkets.ru", "metaprom.ru",
}

_LEGAL_FORMS = r"\b(ооо|оао|зао|пао|ао|ип|тд|тк|пк|гк|llc|ltd)\b"


def domain_of(url: str | None) -> str | None:
    """https://www.Example.ru/catalog -> example.ru"""
    if not url:
        return None
    if "://" not in url:
        url = f"https://{url}"
    host = (urlparse(url).hostname or "").lower()
    host = host.removeprefix("www.")
    return host or None


def is_aggregator(domain: str | None) -> bool:
    if not domain:
        return False
    # Поддомены тоже: moscow.pulscen.ru
    return any(domain == agg or domain.endswith(f".{agg}") for agg in AGGREGATOR_DOMAINS)


def company_domain(website: str | None) -> str | None:
    """Домен собственного сайта компании или None, если это агрегатор."""
    domain = domain_of(website)
    return None if is_aggregator(domain) else domain


def site_of(domain: str) -> str:
    """saratov.mukomoloff.ru -> mukomoloff.ru: поддомены одного сайта — это один источник."""
    return ".".join(domain.split(".")[-2:])


def independent_sources(urls: list[str] | set[str], own_website: str | None) -> set[str]:
    """Сайты, где упоминается компания, кроме её собственного (сама себя популярной не сделает)."""
    own = domain_of(own_website)
    sites = {site_of(d) for url in urls if (d := domain_of(url))}
    return sites - ({site_of(own)} if own else set())


def normalize_company_name(name: str) -> str:
    """'ООО «Ромашка-Агро»' -> 'ромашка агро'"""
    text = name.lower().replace("ё", "е")
    text = re.sub(r"[«»\"'“”„]", " ", text)
    text = re.sub(_LEGAL_FORMS, " ", text)
    text = re.sub(r"[^\w]+", " ", text)
    return " ".join(text.split())
