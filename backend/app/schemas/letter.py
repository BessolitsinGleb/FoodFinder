from datetime import datetime

from pydantic import Field

from app.schemas.common import ORMSchema, Schema


class LetterCreate(Schema):
    # Выбранные предложения. Если у поставщика выбрано несколько позиций — будет одно письмо на все.
    offer_ids: list[int] = Field(min_length=1, max_length=50)
    template: str | None = Field(default=None, description="Имя шаблона; по умолчанию — default")


class LetterRead(ORMSchema):
    id: int
    order_id: int
    supplier_id: int
    template: str
    subject: str
    body: str
    created_at: datetime
