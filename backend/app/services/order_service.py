from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import ConflictError, NotFoundError
from app.models import EDITABLE_STATUSES, Order, OrderItem, OrderStatus, SupplierOffer, User
from app.repositories.category_repo import CategoryRepo
from app.repositories.order_repo import OrderRepo
from app.repositories.supplier_repo import OfferRepo
from app.schemas import (
    DeliveryUpdate,
    ItemResults,
    OfferRead,
    OfferUpdate,
    OrderCreate,
    OrderItemCreate,
    OrderItemRead,
    OrderItemUpdate,
    OrderRead,
    OrderResults,
    OrderUpdate,
    PaginationParams,
)
from app.services.base import BaseService

class OrderService(BaseService):
    """Корзина: позиции, адрес доставки, запуск поиска и результаты.

    Все методы работают только с заказами переданного пользователя. Чужой заказ
    выглядит как несуществующий (404), чтобы не подтверждать даже факт его наличия.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.order_repo = OrderRepo(session)
        self.category_repo = CategoryRepo(session)
        self.offer_repo = OfferRepo(session)

    async def get(self, order_id: int, user: User) -> Order:
        order = await self.order_repo.get(order_id)
        if order is None or order.user_id != user.id:
            raise NotFoundError(f"Заказ {order_id} не найден")
        return order

    async def list_for_user(
        self, user: User, pagination: PaginationParams, status: OrderStatus | None
    ) -> tuple[Sequence[Order], int]:
        return await self.order_repo.list_for_user(user.id, pagination.limit, pagination.offset, status)

    async def create(self, user: User, data: OrderCreate) -> Order:
        # Адрес по умолчанию — город пользователя, но его ещё нужно подтвердить
        order = Order(
            user_id=user.id,
            top_k=data.top_k,
            delivery_city=user.city,
            delivery_region=user.region,
            items=[],
        )
        self.order_repo.add(order)
        await self.session.commit()
        return order

    async def update(self, order_id: int, user: User, data: OrderUpdate) -> Order:
        order = await self.get(order_id, user)
        if order.status == OrderStatus.SEARCHING:
            raise ConflictError("Дождитесь окончания поиска")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(order, field, value)
        await self.session.commit()
        return order

    async def set_delivery(self, order_id: int, user: User, data: DeliveryUpdate) -> Order:
        """Пользователь ответил на вопрос про адрес — фиксируем и считаем подтверждённым."""
        order = await self._get_editable(order_id, user)
        if data.city is not None:
            order.delivery_city = data.city
        if data.region is not None:
            order.delivery_region = data.region
        if data.address is not None:
            order.delivery_address = data.address
        order.delivery_confirmed = True
        self._mark_changed(order)
        await self.session.commit()
        return order

    async def add_item(self, order_id: int, user: User, data: OrderItemCreate) -> Order:
        order = await self._get_editable(order_id, user)

        if data.category_id is not None:
            category = await self.category_repo.get(data.category_id)
            if category is None:
                raise NotFoundError(f"Категория {data.category_id} не найдена")
            title = category.name
        else:
            title = data.custom_title  # вариант "Другое"

        order.items.append(
            OrderItem(
                category_id=data.category_id,
                title=title,
                details=data.details,
                quantity=data.quantity,
                unit=data.unit,
            )
        )
        self._mark_changed(order)
        await self.session.commit()
        return order

    async def update_item(self, order_id: int, item_id: int, user: User, data: OrderItemUpdate) -> Order:
        order = await self._get_editable(order_id, user)
        item = self._find_item(order, item_id)
        changes = data.model_dump(exclude_unset=True)
        # Проверяем итоговое состояние до изменения объекта
        if changes.get("quantity", item.quantity) is not None and changes.get("unit", item.unit) is None:
            raise ConflictError("Для объёма нужна единица измерения")
        for field, value in changes.items():
            setattr(item, field, value)
        self._mark_changed(order)
        await self.session.commit()
        return order

    async def remove_item(self, order_id: int, item_id: int, user: User) -> Order:
        order = await self._get_editable(order_id, user)
        order.items.remove(self._find_item(order, item_id))  # delete-orphan удалит строку
        self._mark_changed(order)
        await self.session.commit()
        return order

    async def start_search(self, order_id: int, user: User) -> Order:
        """Проверяем, что заказ готов к поиску, и ставим статус. Сам поиск — в фоне."""
        order = await self._get_editable(order_id, user)
        if not order.items:
            raise ConflictError("Корзина пуста — добавьте хотя бы одну позицию")
        if not order.delivery_confirmed:
            raise ConflictError("Подтвердите адрес доставки: PUT /orders/{id}/delivery")
        # Поиск стоит денег (Tavily + LLM): один активный поиск на пользователя
        if await self.order_repo.has_active_search(user.id):
            raise ConflictError("У вас уже идёт поиск — дождитесь его окончания")

        order.status = OrderStatus.SEARCHING
        order.search_error = None
        order.search_progress = {
            str(item.id): {"title": item.title, "status": "pending", "found": 0}
            for item in order.items
        }
        await self.session.commit()
        return order

    async def get_results(self, order_id: int, user: User) -> OrderResults:
        order = await self.get(order_id, user)
        offers_by_item: dict[int, list[SupplierOffer]] = defaultdict(list)
        for offer in await self.offer_repo.list_for_order(order_id):
            offers_by_item[offer.order_item_id].append(offer)

        items = [
            ItemResults(
                item=OrderItemRead.model_validate(item),
                offers=[OfferRead.model_validate(offer) for offer in offers_by_item[item.id]],
            )
            for item in order.items
        ]

        # Примерная сумма заказа: по выбранному предложению, а если не выбрано — по лучшему
        costs: list[Decimal] = []
        for item in order.items:
            offers = offers_by_item[item.id]
            chosen = next((o for o in offers if o.is_selected), offers[0] if offers else None)
            if chosen is not None and chosen.estimated_cost is not None:
                costs.append(chosen.estimated_cost)

        return OrderResults(
            order=OrderRead.model_validate(order),
            items=items,
            estimated_total=sum(costs) if costs else None,
            priced_items=len(costs),
        )

    async def update_offer(self, offer_id: int, user: User, data: OfferUpdate) -> SupplierOffer:
        offer = await self.offer_repo.get_for_user(offer_id, user.id)
        if offer is None:
            raise NotFoundError(f"Предложение {offer_id} не найдено")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(offer, field, value)
        await self.session.commit()
        return offer

    async def _get_editable(self, order_id: int, user: User) -> Order:
        order = await self.get(order_id, user)
        if order.status not in EDITABLE_STATUSES:
            raise ConflictError(f"Заказ в статусе '{order.status}' менять нельзя")
        return order

    @staticmethod
    def _find_item(order: Order, item_id: int) -> OrderItem:
        item = next((i for i in order.items if i.id == item_id), None)
        if item is None:
            raise NotFoundError(f"Позиция {item_id} не найдена в заказе {order.id}")
        return item

    @staticmethod
    def _mark_changed(order: Order) -> None:
        # Корзина изменилась — старая подборка больше не актуальна, нужен новый поиск
        order.status = OrderStatus.DRAFT
