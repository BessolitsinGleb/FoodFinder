from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMSchema, PatchSchema, Schema

# kebab-case латиницей: "dairy-products"
SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
# Slug варианта "Другое" — категории с таким slug в БД нет
OTHER_SLUG = "other"


class CategoryCreate(Schema):
    name: str = Field(min_length=1, max_length=100, examples=["Молочная продукция"])
    slug: str = Field(min_length=1, max_length=100, pattern=SLUG_PATTERN, examples=["dairy"])
    description: str | None = None
    parent_id: int | None = None
    is_featured: bool = False
    sort_order: int = 0


class CategoryUpdate(PatchSchema):
    non_nullable_fields = ("name", "slug", "is_featured", "sort_order")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    slug: str | None = Field(default=None, min_length=1, max_length=100, pattern=SLUG_PATTERN)
    # null здесь допустим: очистить описание / сделать категорию корневой
    description: str | None = None
    parent_id: int | None = None
    is_featured: bool | None = None
    sort_order: int | None = None


class CategoryRead(ORMSchema):
    id: int
    name: str
    slug: str
    description: str | None
    parent_id: int | None
    is_featured: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


class CategoryOption(BaseModel):
    """Вариант для выбора в корзине. У "Другое" id = null — пользователь вводит товар сам."""

    id: int | None
    name: str
    slug: str
    is_other: bool = False


OTHER_OPTION = CategoryOption(id=None, name="Другое", slug=OTHER_SLUG, is_other=True)
