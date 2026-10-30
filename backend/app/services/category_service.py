from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models import FoodCategory
from app.repositories.category_repo import CategoryRepo
from app.schemas import (
    OTHER_OPTION,
    CategoryCreate,
    CategoryOption,
    CategoryUpdate,
    PaginationParams,
)
from app.services.base import BaseService

NAME_OR_SLUG_TAKEN = "Категория с таким name или slug уже существует"


class CategoryService(BaseService):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.category_repo = CategoryRepo(session)

    async def get(self, category_id: int) -> FoodCategory:
        category = await self.category_repo.get(category_id)
        if category is None:
            raise NotFoundError(f"Категория {category_id} не найдена")
        return category

    async def list_page(
        self, pagination: PaginationParams, parent_id: int | None, root_only: bool
    ) -> tuple[Sequence[FoodCategory], int]:
        return await self.category_repo.list_page(
            pagination.limit, pagination.offset, parent_id=parent_id, root_only=root_only
        )

    async def popular_options(self, limit: int) -> list[CategoryOption]:
        """Что предложить пользователю вместо ручного ввода: популярные категории + "Другое"."""
        categories = await self.category_repo.popular(limit)
        options = [CategoryOption(id=c.id, name=c.name, slug=c.slug) for c in categories]
        return [*options, OTHER_OPTION]

    async def create(self, data: CategoryCreate) -> FoodCategory:
        if data.parent_id is not None:
            await self._check_parent(data.parent_id)
        category = FoodCategory(**data.model_dump())
        self.category_repo.add(category)
        await self._commit(NAME_OR_SLUG_TAKEN)
        return category

    async def update(self, category_id: int, data: CategoryUpdate) -> FoodCategory:
        category = await self.get(category_id)
        changes = data.model_dump(exclude_unset=True)
        if changes.get("parent_id") is not None:
            await self._check_parent(changes["parent_id"], category_id)
        for field, value in changes.items():
            setattr(category, field, value)
        await self._commit(NAME_OR_SLUG_TAKEN)
        return category

    async def delete(self, category_id: int) -> None:
        category = await self.get(category_id)
        await self.category_repo.delete(category)
        # У позиций заказов category_id обнулится (SET NULL), а название останется в title.
        # Подкатегории удалить не дадут (RESTRICT).
        await self._commit("Нельзя удалить категорию, у которой есть подкатегории")

    async def _check_parent(self, parent_id: int, category_id: int | None = None) -> None:
        """Родитель существует и не образует цикл (категория не может стать потомком самой себя)."""
        node: FoodCategory | None = await self.get(parent_id)
        if category_id is None:
            return
        while node is not None:
            if node.id == category_id:
                raise ConflictError("Категория не может быть потомком самой себя")
            node = await self.category_repo.get(node.parent_id) if node.parent_id else None
