from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepo:
    """Репозиторий только читает и добавляет объекты в сессию.

    commit делает сервис: одна бизнес-операция = одна транзакция,
    даже если она затрагивает несколько репозиториев.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _paginate(self, stmt: Select[Any], limit: int, offset: int) -> tuple[Sequence[Any], int]:
        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        total = await self.session.scalar(count_stmt) or 0
        items = (await self.session.scalars(stmt.limit(limit).offset(offset))).all()
        return items, total
