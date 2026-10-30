from collections.abc import Sequence
from sqlalchemy import select
from app.models import Letter, Order
from app.repositories.base import BaseRepo

class LetterRepo(BaseRepo):
    async def get_for_user(self, letter_id: int, user_id: int) -> Letter | None:
        """Письмо, только если оно из заказа этого пользователя."""
        stmt = (
            select(Letter)
            .join(Order, Order.id == Letter.order_id)
            .where(Letter.id == letter_id, Order.user_id == user_id)
        )
        return await self.session.scalar(stmt)

    async def list_for_order(self, order_id: int) -> Sequence[Letter]:
        stmt = select(Letter).where(Letter.order_id == order_id).order_by(Letter.id.desc())
        return (await self.session.scalars(stmt)).all()

    def add(self, letter: Letter) -> None:
        self.session.add(letter)
