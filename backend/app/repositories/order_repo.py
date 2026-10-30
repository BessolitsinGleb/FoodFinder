from collections.abc import Sequence

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.models import Order, OrderItem, OrderStatus
from app.repositories.base import BaseRepo


class OrderRepo(BaseRepo):
    async def get(self, order_id: int) -> Order | None:
        """Заказ вместе с позициями — они нужны почти везде."""
        stmt = select(Order).where(Order.id == order_id).options(selectinload(Order.items))
        return await self.session.scalar(stmt)

    async def list_for_user(
        self, user_id: int, limit: int, offset: int, status: OrderStatus | None = None
    ) -> tuple[Sequence[Order], int]:
        stmt = (
            select(Order)
            .where(Order.user_id == user_id)
            .options(selectinload(Order.items))
            .order_by(Order.created_at.desc(), Order.id.desc())
        )
        if status is not None:
            stmt = stmt.where(Order.status == status)
        return await self._paginate(stmt, limit, offset)

    async def has_active_search(self, user_id: int) -> bool:
        stmt = select(Order.id).where(Order.user_id == user_id, Order.status == OrderStatus.SEARCHING)
        return await self.session.scalar(stmt.limit(1)) is not None

    async def get_item(self, order_id: int, item_id: int) -> OrderItem | None:
        stmt = select(OrderItem).where(OrderItem.id == item_id, OrderItem.order_id == order_id)
        return await self.session.scalar(stmt)

    def add(self, order: Order) -> None:
        self.session.add(order)

    def add_item(self, item: OrderItem) -> None:
        self.session.add(item)

    async def delete_item(self, item: OrderItem) -> None:
        await self.session.delete(item)

    async def mark_search_failed(self, order_id: int, error: str) -> None:
        """UPDATE без загрузки объекта: вызывается после rollback, когда объекты сессии уже невалидны."""
        await self.session.execute(
            update(Order)
            .where(Order.id == order_id)
            .values(status=OrderStatus.FAILED, search_error=error)
        )

    async def fail_interrupted_searches(self) -> int:
        """Поиск идёт фоновой задачей внутри процесса. Если сервер перезапустился посреди поиска,
        заказ навсегда остался бы в SEARCHING — помечаем такие заказы упавшими."""
        result = await self.session.execute(
            update(Order)
            .where(Order.status == OrderStatus.SEARCHING)
            .values(status=OrderStatus.FAILED, search_error="Поиск прерван перезапуском сервера")
        )
        return result.rowcount
