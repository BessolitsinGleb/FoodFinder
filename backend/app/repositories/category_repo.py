from collections.abc import Sequence

from sqlalchemy import exists, func, select
from sqlalchemy.orm import aliased

from app.models import FoodCategory, OrderItem
from app.repositories.base import BaseRepo


class CategoryRepo(BaseRepo):
    async def get(self, category_id: int) -> FoodCategory | None:
        return await self.session.get(FoodCategory, category_id)

    async def list_page(
        self, limit: int, offset: int, parent_id: int | None = None, root_only: bool = False
    ) -> tuple[Sequence[FoodCategory], int]:
        stmt = select(FoodCategory).order_by(FoodCategory.sort_order, FoodCategory.name)
        if root_only:
            stmt = stmt.where(FoodCategory.parent_id.is_(None))
        elif parent_id is not None:
            stmt = stmt.where(FoodCategory.parent_id == parent_id)
        return await self._paginate(stmt, limit, offset)

    async def popular(self, limit: int) -> Sequence[FoodCategory]:
        """Конечные категории (без подкатегорий), отсортированные по тому, как часто их заказывают.

        Пока статистики нет, наверху оказываются категории с is_featured —
        стартовая подборка из миграции.
        """
        child = aliased(FoodCategory)
        is_leaf = ~exists().where(child.parent_id == FoodCategory.id)
        times_ordered = func.count(OrderItem.id)

        stmt = (
            select(FoodCategory)
            .outerjoin(OrderItem, OrderItem.category_id == FoodCategory.id)
            .where(is_leaf)
            .group_by(FoodCategory.id)
            .order_by(
                times_ordered.desc(),
                FoodCategory.is_featured.desc(),
                FoodCategory.sort_order,
                FoodCategory.name,
            )
            .limit(limit)
        )
        return (await self.session.scalars(stmt)).all()

    def add(self, category: FoodCategory) -> None:
        self.session.add(category)

    async def delete(self, category: FoodCategory) -> None:
        await self.session.delete(category)
