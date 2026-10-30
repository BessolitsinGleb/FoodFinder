from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError


class BaseService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _commit(self, conflict_message: str = "Конфликт данных") -> None:
        """Commit; нарушение unique/FK превращаем в ConflictError (409).

        Проверки "заранее" не спасают от гонок двух запросов,
        поэтому последнее слово за ограничениями БД.
        """
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise ConflictError(conflict_message) from None
