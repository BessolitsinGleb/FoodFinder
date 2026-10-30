from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class FoodCategory(TimestampMixin, Base):
    """Категория товаров food-направления.

    Иерархическая: например "Ингредиенты" -> "Молочная продукция" -> "Сухое молоко".
    Корневые категории (ингредиенты, готовая продукция, упаковка, ...) имеют parent_id = NULL.
    """

    __tablename__ = "food_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    # Подборка "популярных" для новых пользователей, пока нет статистики заказов
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # RESTRICT: нельзя удалить категорию, пока у неё есть подкатегории
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("food_categories.id", ondelete="RESTRICT"), index=True
    )

    parent: Mapped["FoodCategory | None"] = relationship(
        back_populates="children", remote_side="FoodCategory.id", lazy="raise"
    )
    # passive_deletes="all": ORM не трогает подкатегории при удалении родителя,
    # решение принимает БД (RESTRICT -> ошибка, которую API отдаёт как 409)
    children: Mapped[list["FoodCategory"]] = relationship(
        back_populates="parent", lazy="raise", passive_deletes="all"
    )
