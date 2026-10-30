from fastapi import APIRouter, BackgroundTasks, Query, status
from app.api.deps import CurrentUser, LLMDep, OrderServiceDep, PaginationDep, WebSearchDep
from app.core.config import get_settings
from app.models import Order, OrderStatus, SupplierOffer
from app.schemas import (
    DeliveryUpdate,
    OfferRead,
    OfferUpdate,
    OrderCreate,
    OrderItemCreate,
    OrderItemUpdate,
    OrderRead,
    OrderResults,
    OrderUpdate,
    Page,
)
from app.services.search_service import run_supplier_search

# Все заказы — только текущего пользователя (из токена). Чужой заказ = 404.
router = APIRouter(tags=["orders"])

# ---------- Корзина ----------

@router.post("/orders", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
async def create_order(payload: OrderCreate, user: CurrentUser, service: OrderServiceDep) -> Order:
    """Новая корзина. В ответе delivery_question — его нужно задать пользователю."""
    return await service.create(user, payload)

@router.get("/orders", response_model=Page[OrderRead])
async def list_orders(
    user: CurrentUser,
    service: OrderServiceDep,
    pagination: PaginationDep,
    order_status: OrderStatus | None = Query(default=None, alias="status"),
) -> Page[OrderRead]:
    """История заказов, новые сверху."""
    items, total = await service.list_for_user(user, pagination, order_status)
    return Page[OrderRead](items=items, total=total, **pagination.model_dump())

@router.get("/orders/{order_id}", response_model=OrderRead)
async def get_order(order_id: int, user: CurrentUser, service: OrderServiceDep) -> Order:
    return await service.get(order_id, user)

@router.patch("/orders/{order_id}", response_model=OrderRead)
async def update_order(
    order_id: int, payload: OrderUpdate, user: CurrentUser, service: OrderServiceDep
) -> Order:
    return await service.update(order_id, user, payload)

@router.put("/orders/{order_id}/delivery", response_model=OrderRead)
async def set_delivery(
    order_id: int, payload: DeliveryUpdate, user: CurrentUser, service: OrderServiceDep
) -> Order:
    """Ответ на "Доставка в ваш город?": пустое тело = да, иначе новый город/регион/адрес."""
    return await service.set_delivery(order_id, user, payload)

@router.post("/orders/{order_id}/items", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
async def add_item(
    order_id: int, payload: OrderItemCreate, user: CurrentUser, service: OrderServiceDep
) -> Order:
    return await service.add_item(order_id, user, payload)

@router.patch("/orders/{order_id}/items/{item_id}", response_model=OrderRead)
async def update_item(
    order_id: int, item_id: int, payload: OrderItemUpdate, user: CurrentUser, service: OrderServiceDep
) -> Order:
    return await service.update_item(order_id, item_id, user, payload)

@router.delete("/orders/{order_id}/items/{item_id}", response_model=OrderRead)
async def remove_item(order_id: int, item_id: int, user: CurrentUser, service: OrderServiceDep) -> Order:
    return await service.remove_item(order_id, item_id, user)

# ---------- Поиск и результаты ----------

@router.post("/orders/{order_id}/search", response_model=OrderRead, status_code=status.HTTP_202_ACCEPTED)
async def start_search(
    order_id: int,
    user: CurrentUser,
    service: OrderServiceDep,
    llm: LLMDep,
    web: WebSearchDep,
    background_tasks: BackgroundTasks,
) -> Order:
    """Запускает поиск в фоне (это минуты). Прогресс — в search_progress через GET /orders/{id}."""
    order = await service.start_search(order_id, user)
    background_tasks.add_task(run_supplier_search, order.id, llm, web, get_settings().search)
    return order

@router.get("/orders/{order_id}/results", response_model=OrderResults)
async def get_results(order_id: int, user: CurrentUser, service: OrderServiceDep) -> OrderResults:
    """Топ-k поставщиков по каждой позиции + примерная сумма заказа."""
    return await service.get_results(order_id, user)

@router.patch("/offers/{offer_id}", response_model=OfferRead)
async def update_offer(
    offer_id: int, payload: OfferUpdate, user: CurrentUser, service: OrderServiceDep
) -> SupplierOffer:
    """Отметить поставщика выбранным или оставить заметку."""
    return await service.update_offer(offer_id, user, payload)
