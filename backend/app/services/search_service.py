"""Пайплайн поиска поставщиков.

Для каждой позиции корзины (по очереди):
1. Сбор кандидатов: ищем в интернете от ближнего к дальнему (город -> регион ->
   федеральный округ -> Россия), пока не наберём settings.min_candidates.
   LLM вытаскивает из выдачи поставщиков и их условия.
2. Грубое ранжирование без проверки репутации — чтобы не проверять всех (это дорого).
3. Проверка лучших: отзывы, ИНН, сертификаты. LLM только выписывает факты.
4. Оценка по формулам (app/domain/scoring.py) и сохранение: top_k лучших получают rank.

Почему пайплайн, а не "свободный" агент с тулами: порядок шагов фиксирован бизнесом,
так дешевле (меньше вызовов LLM), предсказуемее и проще отлаживать.
"""

import asyncio
import copy
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import SupplierSearchSettings
from app.core.exceptions import ExternalServiceError
from app.db.session import SessionFactory
from app.domain.companies import company_domain, independent_sources, normalize_company_name
from app.domain.geo import Location, normalize_city, normalize_region, proximity, search_areas
from app.domain.scoring import (
    MatchLevel,
    OfferFacts,
    OfferScore,
    SafetyFacts,
    SafetyResult,
    count_documents,
    offer_score,
    safety,
)
from app.domain.units import estimate_cost, price_per_base_unit, to_base
from app.integrations.llm import LLMClient
from app.integrations.web_search import SearchResult, WebSearchClient
from app.models import Order, OrderItem, OrderStatus, Supplier, SupplierOffer
from app.prompts.extraction import (
    EXTRACT_SUPPLIERS_SYSTEM,
    REPUTATION_SYSTEM,
    extract_suppliers_prompt,
    reputation_prompt,
)
from app.repositories.order_repo import OrderRepo
from app.repositories.supplier_repo import OfferRepo, SupplierRepo
from app.schemas.llm import ExtractedSupplier, ExtractedSuppliers, ReputationFacts

logger = logging.getLogger(__name__)

# Цены выше этого — почти наверняка ошибка распознавания (и не влезут в Numeric(14, 2))
MAX_SANE_PRICE = Decimal("1e11")
_WHOLE_COUNTRY = re.compile(r"вс[яей]+ росси|по росси|\bрф\b", re.IGNORECASE)


@dataclass
class Candidate:
    """Поставщик, найденный по одной позиции, пока ещё не сохранённый в БД."""

    info: ExtractedSupplier
    location: Location
    sources: set[str] = field(default_factory=set)  # где о компании упоминается
    reputation: ReputationFacts | None = None

    @property
    def key(self) -> str:
        """Ключ дедупликации: домен своего сайта, иначе нормализованное название."""
        return company_domain(self.info.website) or f"name:{normalize_company_name(self.info.name)}"

    def merge(self, other: ExtractedSupplier) -> None:
        """Тот же поставщик нашёлся ещё раз — дополняем пустые поля и списки."""
        for name in ExtractedSupplier.model_fields:
            mine, theirs = getattr(self.info, name), getattr(other, name)
            if isinstance(mine, list):
                setattr(self.info, name, _unique([*mine, *theirs]))
            elif mine is None and theirs is not None:
                setattr(self.info, name, theirs)
        if other.source_url:
            self.sources.add(other.source_url)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(v.strip() for v in values if v and v.strip()))


def _cut(value: str | None, length: int) -> str | None:
    return value[:length] if value else value


class SupplierSearchService:
    def __init__(
        self,
        session: AsyncSession,
        llm: LLMClient,
        web: WebSearchClient,
        settings: SupplierSearchSettings,
    ) -> None:
        self.session = session
        self.order_repo = OrderRepo(session)
        self.supplier_repo = SupplierRepo(session)
        self.offer_repo = OfferRepo(session)
        self.llm = llm
        self.web = web
        self.settings = settings

    async def run(self, order_id: int) -> None:
        order = await self.order_repo.get(order_id)
        if order is None or order.status != OrderStatus.SEARCHING:
            logger.warning("Order %s is not waiting for search, skip", order_id)
            return

        buyer = Location(order.delivery_city, order.delivery_region)
        progress = copy.deepcopy(order.search_progress or {})
        errors: list[str] = []

        # Позиции — строго по очереди: прогресс понятен пользователю, лимиты API не взрываются
        for item in order.items:
            entry = progress.setdefault(str(item.id), {"title": item.title})
            entry["status"] = "searching"
            await self._save_progress(order, progress)
            try:
                entry["found"] = await self._search_item(item, buyer, order.top_k)
                entry["status"] = "done"
            except ExternalServiceError as exc:
                # Одна позиция упала — остальные всё равно ищем
                logger.warning("Search failed for item %s: %s", item.id, exc.detail)
                entry["status"] = "failed"
                entry["error"] = exc.detail
                errors.append(f"{item.title}: {exc.detail}")

        order.status = OrderStatus.FAILED if len(errors) == len(order.items) else OrderStatus.READY
        order.search_error = "; ".join(errors) or None
        order.searched_at = datetime.now(UTC)
        await self._save_progress(order, progress)

    async def _save_progress(self, order: Order, progress: dict) -> None:
        # JSONB-поле нужно присвоить заново (новым объектом), иначе SQLAlchemy не заметит изменения
        order.search_progress = copy.deepcopy(progress)
        await self.session.commit()

    async def _search_item(self, item: OrderItem, buyer: Location, top_k: int) -> int:
        candidates = await self._collect_candidates(item, buyer)
        base_unit = self._comparison_unit(item, candidates)

        # Проверка репутации дорогая: сначала ранжируем без неё и проверяем только лучших
        candidates.sort(key=lambda c: self._score(c, buyer, base_unit, None).total, reverse=True)
        shortlist = candidates[: top_k + self.settings.extra_to_verify]
        await self._verify(shortlist)
        alive = [c for c in shortlist if not (c.reputation and c.reputation.is_liquidated)]

        best_price = min(
            (p for c in alive if (p := self._unit_price(c, base_unit)) is not None), default=None
        )
        ranked = sorted(
            ((c, self._score(c, buyer, base_unit, best_price)) for c in alive),
            key=lambda pair: pair[1].total,
            reverse=True,
        )

        await self.offer_repo.delete_for_item(item.id)
        saved_suppliers: set[int] = set()
        for candidate, score in ranked:
            supplier = await self._save_supplier(candidate)
            if supplier.id in saved_suppliers:  # два кандидата оказались одной компанией
                continue
            saved_suppliers.add(supplier.id)
            rank = len(saved_suppliers)
            self.offer_repo.add(
                self._build_offer(item, supplier, candidate, score, rank if rank <= top_k else None)
            )
        await self.session.commit()
        return min(len(saved_suppliers), top_k)

    # ---------- 1. Сбор кандидатов ----------

    async def _collect_candidates(self, item: OrderItem, buyer: Location) -> list[Candidate]:
        candidates: dict[str, Candidate] = {}
        seen_urls: set[str] = set()
        last_error: ExternalServiceError | None = None

        for area in search_areas(buyer):
            query = " ".join(filter(None, [item.title, item.details, "поставщик оптом", area]))
            try:
                results = await self.web.search(query, self.settings.results_per_query)
                fresh = [r for r in results if r.url not in seen_urls]
                seen_urls.update(r.url for r in fresh)
                if fresh:
                    for info in await self._extract_suppliers(item, buyer, fresh):
                        self._add_candidate(candidates, info)
            except ExternalServiceError as exc:
                # Не получилось на этом шаге — пробуем следующую географию
                logger.warning("Search step %r failed: %s", area, exc.detail)
                last_error = exc

            if len(candidates) >= self.settings.min_candidates:
                break

        if not candidates and last_error is not None:
            raise last_error
        return list(candidates.values())

    async def _extract_suppliers(
        self, item: OrderItem, buyer: Location, results: list[SearchResult]
    ) -> list[ExtractedSupplier]:
        extracted = await self.llm.complete_json(
            system=EXTRACT_SUPPLIERS_SYSTEM,
            user=extract_suppliers_prompt(item, buyer, results),
            schema=ExtractedSuppliers,
        )
        return [s for s in extracted.suppliers if s.match != MatchLevel.NONE and s.name.strip()]

    @staticmethod
    def _add_candidate(candidates: dict[str, Candidate], info: ExtractedSupplier) -> None:
        city = normalize_city(info.city)
        # Для Москвы/Питера/Севастополя город и есть регион
        region = normalize_region(info.region) or normalize_region(city)
        candidate = Candidate(info=info, location=Location(city, region))
        if info.source_url:
            candidate.sources.add(info.source_url)

        existing = candidates.get(candidate.key)
        if existing:
            existing.merge(info)
        else:
            candidates[candidate.key] = candidate

    # ---------- 3. Проверка репутации ----------

    async def _verify(self, candidates: list[Candidate]) -> None:
        semaphore = asyncio.Semaphore(self.settings.verify_concurrency)

        async def verify_one(candidate: Candidate) -> None:
            async with semaphore:
                await self._verify_candidate(candidate)

        await asyncio.gather(*(verify_one(c) for c in candidates))

    async def _verify_candidate(self, candidate: Candidate) -> None:
        name = candidate.info.name
        queries = [
            " ".join(filter(None, [name, candidate.location.city, "отзывы"])),
            f"{name} ИНН сертификат декларация соответствия",
        ]
        try:
            batches = await asyncio.gather(*(self.web.search(q, max_results=5) for q in queries))
            results = [r for batch in batches for r in batch]

            # Для "популярности" считаем только страницы, где компания реально упоминается
            mention = normalize_company_name(name)
            candidate.sources.update(
                r.url for r in results
                if mention and mention in normalize_company_name(f"{r.title} {r.content}")
            )
            candidate.reputation = await self.llm.complete_json(
                system=REPUTATION_SYSTEM,
                user=reputation_prompt(name, candidate.info.website, candidate.location.city, results),
                schema=ReputationFacts,
            )
        except ExternalServiceError as exc:
            # Не проверили — поставщик не выпадает, просто получит низкую оценку безопасности
            logger.warning("Could not verify %r: %s", name, exc.detail)

    # ---------- 4. Оценка ----------

    @staticmethod
    def _safety(candidate: Candidate) -> SafetyResult:
        reputation = candidate.reputation or ReputationFacts()
        documents = set(candidate.info.certificates) | set(reputation.certificates)
        years = date.today().year - reputation.founded_year if reputation.founded_year else None
        return safety(
            SafetyFacts(
                # Только подтверждающие документы, без упоминаний ГОСТ/ТУ
                documents_count=count_documents(documents),
                has_legal_id=reputation.inn is not None,
                rating=reputation.rating,
                reviews_count=reputation.reviews_count,
                # Только сторонние сайты: собственный сайт и его поддомены не считаются
                sources_count=len(independent_sources(candidate.sources, candidate.info.website)),
                years_on_market=years,
            )
        )

    @staticmethod
    def _comparison_unit(item: OrderItem, candidates: list[Candidate]) -> str | None:
        """В какой базовой единице сравнивать цены: как у позиции, иначе как у большинства."""
        if item.unit:
            base = to_base(Decimal(1), item.unit)
            return base[1] if base else None
        units = Counter(
            p[1] for c in candidates
            if (p := price_per_base_unit(c.info.price, c.info.price_unit)) is not None
        )
        return units.most_common(1)[0][0] if units else None

    @staticmethod
    def _unit_price(candidate: Candidate, base_unit: str | None) -> Decimal | None:
        per_unit = price_per_base_unit(candidate.info.price, candidate.info.price_unit)
        if per_unit is None or per_unit[1] != base_unit or per_unit[0] <= 0:
            return None
        return per_unit[0]

    @staticmethod
    def _delivers_to(candidate: Candidate, buyer: Location) -> bool:
        for area in candidate.info.regions_served:
            if _WHOLE_COUNTRY.search(area) or normalize_region(area) == buyer.region:
                return True
            if buyer.district and buyer.district.lower() in area.lower():
                return True
        return False

    def _score(
        self, candidate: Candidate, buyer: Location, base_unit: str | None, best_price: Decimal | None
    ) -> OfferScore:
        info = candidate.info
        return offer_score(
            OfferFacts(
                match=info.match,
                proximity=proximity(buyer, candidate.location),
                delivers_to_buyer=self._delivers_to(candidate, buyer),
                safety_rating=self._safety(candidate).rating,
                unit_price=self._unit_price(candidate, base_unit),
                best_unit_price=best_price,
                has_contacts=bool(info.phones or info.emails),
                has_moq=info.moq is not None,
                has_delivery_terms=bool(info.delivery_terms),
                has_delivery_time=bool(info.delivery_time),
            )
        )

    # ---------- Сохранение ----------

    async def _save_supplier(self, candidate: Candidate) -> Supplier:
        info = candidate.info
        reputation = candidate.reputation or ReputationFacts()
        domain = company_domain(info.website)

        if domain:
            supplier = await self.supplier_repo.find_by_domain(domain)
        else:
            supplier = await self.supplier_repo.find_by_name_and_city(info.name, candidate.location.city)
        if supplier is None:
            supplier = Supplier(name=_cut(info.name.strip(), 255), domain=domain)
            self.supplier_repo.add(supplier)

        # Свежие данные важнее старых, но пустым значением не затираем
        if domain:
            supplier.website = _cut(info.website, 500)
        supplier.city = _cut(candidate.location.city, 100) or supplier.city
        supplier.region = candidate.location.region or supplier.region
        supplier.address = info.address or supplier.address
        supplier.delivery_terms = info.delivery_terms or supplier.delivery_terms
        supplier.delivery_time = _cut(info.delivery_time, 200) or supplier.delivery_time
        supplier.inn = reputation.inn or supplier.inn
        supplier.founded_year = reputation.founded_year or supplier.founded_year
        # Списки присваиваем новыми объектами — так SQLAlchemy видит изменения в JSONB
        supplier.phones = _unique([*(supplier.phones or []), *info.phones])
        supplier.emails = _unique([*(supplier.emails or []), *info.emails])
        supplier.regions_served = _unique([*(supplier.regions_served or []), *info.regions_served])
        supplier.certificates = _unique(
            [*(supplier.certificates or []), *info.certificates, *reputation.certificates]
        )
        supplier.sources = _unique([*(supplier.sources or []), *candidate.sources])

        if candidate.reputation is not None:
            supplier.rating = Decimal(str(round(reputation.rating, 1))) if reputation.rating is not None else None
            supplier.reviews_count = reputation.reviews_count
            supplier.red_flags = _unique(reputation.red_flags)
            supplier.verified_at = datetime.now(UTC)

        result = self._safety(candidate)
        supplier.safety_rating = result.rating
        supplier.safety_breakdown = result.breakdown
        supplier.is_popular = result.is_popular
        supplier.is_safe = result.is_safe

        await self.session.flush()  # нужен supplier.id для предложения
        return supplier

    @staticmethod
    def _build_offer(
        item: OrderItem, supplier: Supplier, candidate: Candidate, score: OfferScore, rank: int | None
    ) -> SupplierOffer:
        info = candidate.info
        price = info.price if info.price is not None and info.price < MAX_SANE_PRICE else None
        moq = info.moq if info.moq is not None and info.moq < MAX_SANE_PRICE else None
        return SupplierOffer(
            order_item_id=item.id,
            supplier_id=supplier.id,
            product_name=_cut(info.product_name, 300),
            match_level=info.match.value,
            price=price,
            price_unit=_cut(info.price_unit, 20),
            moq=moq,
            moq_unit=_cut(info.moq_unit, 20),
            estimated_cost=estimate_cost(price, info.price_unit, item.quantity, item.unit),
            source_url=_cut(info.source_url, 1000),
            score=score.total,
            score_breakdown=score.breakdown,
            rank=rank,
            agent_summary=info.summary,
        )


async def run_supplier_search(
    order_id: int, llm: LLMClient, web: WebSearchClient, settings: SupplierSearchSettings
) -> None:
    """Точка входа фоновой задачи. Своя сессия: сессия HTTP-запроса к этому моменту уже закрыта."""
    async with SessionFactory() as session:
        try:
            await SupplierSearchService(session, llm, web, settings).run(order_id)
        except Exception:
            logger.exception("Supplier search crashed for order %s", order_id)
            await session.rollback()
            await OrderRepo(session).mark_search_failed(order_id, "Внутренняя ошибка поиска")
            await session.commit()
