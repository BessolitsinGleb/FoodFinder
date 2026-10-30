from typing import ClassVar, Generic, Self, TypeVar

from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

T = TypeVar("T")


class Schema(BaseModel):
    """Базовая схема входных данных.

    - пробелы по краям строк обрезаются;
    - лишние поля -> 422 (а не молча игнорируются): фронт сразу видит опечатку,
      а попытка прислать is_admin/user_id заметна;
    - NUL-символ запрещён: Postgres не хранит его в тексте и падает с 500.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def _no_nul(cls, value: Any) -> Any:
        if isinstance(value, str) and "\x00" in value:
            raise ValueError("Строка содержит недопустимый символ \\x00")
        return value


class ORMSchema(BaseModel):
    """Базовая схема ответа, собираемая из ORM-объекта."""

    model_config = ConfigDict(from_attributes=True)


class PatchSchema(Schema):
    """Базовая схема частичного обновления (PATCH).

    Обновляются только переданные поля (exclude_unset). Поля из
    `non_nullable_fields` можно не передавать, но нельзя явно выставить
    в null — в БД они NOT NULL.
    """

    non_nullable_fields: ClassVar[tuple[str, ...]] = ()

    @model_validator(mode="after")
    def _forbid_explicit_null(self) -> Self:
        for field in self.non_nullable_fields:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"Поле '{field}' не может быть null")
        return self


class PaginationParams(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int
