from fastapi import APIRouter, Depends, Query, status
from app.api.deps import CategoryServiceDep, PaginationDep, get_admin
from app.models import FoodCategory
from app.schemas import CategoryCreate, CategoryOption, CategoryRead, CategoryUpdate, Page

# Читать справочник может кто угодно, менять — только администратор (users.is_admin)
router = APIRouter(prefix="/categories", tags=["categories"])
admin_only = [Depends(get_admin)]

@router.get("/popular", response_model=list[CategoryOption])
async def popular_categories(
    service: CategoryServiceDep, limit: int = Query(default=8, ge=1, le=30)
) -> list[CategoryOption]:
    """Что предложить в корзине: самые заказываемые категории + вариант "Другое" последним."""
    return await service.popular_options(limit)

@router.post("", response_model=CategoryRead, status_code=status.HTTP_201_CREATED, dependencies=admin_only)
async def create_category(payload: CategoryCreate, service: CategoryServiceDep) -> FoodCategory:
    return await service.create(payload)

@router.get("", response_model=Page[CategoryRead])
async def list_categories(
    service: CategoryServiceDep,
    pagination: PaginationDep,
    parent_id: int | None = Query(default=None, description="Только подкатегории указанной"),
    root_only: bool = Query(default=False, description="Только корневые категории"),
) -> Page[CategoryRead]:
    items, total = await service.list_page(pagination, parent_id, root_only)
    return Page[CategoryRead](items=items, total=total, **pagination.model_dump())

@router.get("/{category_id}", response_model=CategoryRead)
async def get_category(category_id: int, service: CategoryServiceDep) -> FoodCategory:
    return await service.get(category_id)

@router.patch("/{category_id}", response_model=CategoryRead, dependencies=admin_only)
async def update_category(
    category_id: int, payload: CategoryUpdate, service: CategoryServiceDep
) -> FoodCategory:
    return await service.update(category_id, payload)

@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=admin_only)
async def delete_category(category_id: int, service: CategoryServiceDep) -> None:
    await service.delete(category_id)
