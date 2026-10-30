from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from app.models import Order, OrderItem, Supplier, SupplierOffer
from app.repositories.base import BaseRepo


class SupplierRepo(BaseRepo):
    async def get(self, supplier_id: int) -> Supplier | None:
        return await self.session.get(Supplier, supplier_id)

    async def find_by_domain(self, domain: str) -> Supplier | None:
        return await self.session.scalar(select(Supplier).where(Supplier.domain == domain))

    async def find_by_name_and_city(self, name: str, city: str | None) -> Supplier | None:
        """Для поставщиков без своего сайта. Сравнение без учёта регистра."""
        stmt = select(Supplier).where(
            func.lower(Supplier.name) == name.lower(), Supplier.domain.is_(None)
        )
        if city:
            stmt = stmt.where(func.lower(Supplier.city) == city.lower())
        else:
            stmt = stmt.where(Supplier.city.is_(None))
        return await self.session.scalar(stmt.limit(1))

    def add(self, supplier: Supplier) -> None:
        self.session.add(supplier)


class OfferRepo(BaseRepo):
    async def get_for_user(self, offer_id: int, user_id: int) -> SupplierOffer | None:
        """Предложение, только если оно из заказа этого пользователя."""
        stmt = (
            select(SupplierOffer)
            .join(OrderItem, OrderItem.id == SupplierOffer.order_item_id)
            .join(Order, Order.id == OrderItem.order_id)
            .where(SupplierOffer.id == offer_id, Order.user_id == user_id)
            .options(selectinload(SupplierOffer.supplier), selectinload(SupplierOffer.order_item))
        )
        return await self.session.scalar(stmt)

    async def list_for_order(self, order_id: int, shortlisted_only: bool = True) -> Sequence[SupplierOffer]:
        """Предложения по всем позициям заказа: сначала по позиции, внутри — по месту в топе."""
        stmt = (
            select(SupplierOffer)
            .join(OrderItem, OrderItem.id == SupplierOffer.order_item_id)
            .where(OrderItem.order_id == order_id)
            .options(selectinload(SupplierOffer.supplier))
            .order_by(OrderItem.id, SupplierOffer.rank.nulls_last(), SupplierOffer.score.desc())
        )
        if shortlisted_only:
            stmt = stmt.where(SupplierOffer.rank.is_not(None))
        return (await self.session.scalars(stmt)).all()

    async def list_by_ids(self, order_id: int, offer_ids: list[int]) -> Sequence[SupplierOffer]:
        """Только предложения из этого заказа — чужие id молча не попадут."""
        stmt = (
            select(SupplierOffer)
            .join(OrderItem, OrderItem.id == SupplierOffer.order_item_id)
            .where(OrderItem.order_id == order_id, SupplierOffer.id.in_(offer_ids))
            .options(selectinload(SupplierOffer.supplier), selectinload(SupplierOffer.order_item))
            .order_by(SupplierOffer.supplier_id, OrderItem.id)
        )
        return (await self.session.scalars(stmt)).all()

    async def delete_for_item(self, item_id: int) -> None:
        """Перед повторным поиском старая подборка по позиции не нужна."""
        await self.session.execute(delete(SupplierOffer).where(SupplierOffer.order_item_id == item_id))

    def add(self, offer: SupplierOffer) -> None:
        self.session.add(offer)
