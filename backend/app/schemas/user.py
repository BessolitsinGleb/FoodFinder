from datetime import datetime
from pydantic import Field, field_validator
from app.domain.geo import normalize_city, normalize_region
from app.schemas.common import ORMSchema, PatchSchema

def normalize_email(value: str | None) -> str | None:
    return value.lower() if value else value

def validate_region(value: str | None) -> str | None:
    """Регион приводим к каноническому названию: от него зависит поиск поставщиков рядом."""
    if value is None:
        return None
    region = normalize_region(value)
    if region is None:
        raise ValueError(f"Неизвестный регион '{value}'. Список регионов: GET /geo/regions")
    return region

class UserUpdate(PatchSchema):
    # email не меняется: новый адрес пришлось бы заново подтверждать
    non_nullable_fields = ("name", "city", "region")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    region: str | None = Field(default=None, min_length=1, max_length=100)

    _city = field_validator("city")(normalize_city)
    _region = field_validator("region")(validate_region)

class UserRead(ORMSchema):
    id: int
    name: str
    email: str
    city: str
    region: str
    created_at: datetime
    updated_at: datetime
