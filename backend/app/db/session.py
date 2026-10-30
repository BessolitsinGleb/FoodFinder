from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

_db = get_settings().db

engine = create_async_engine(
    _db.url,
    echo=_db.echo,
    pool_size=_db.pool_size,
    max_overflow=_db.max_overflow,
    pool_pre_ping=True,  # проверять соединение перед выдачей из пула
)

# expire_on_commit=False: после commit объекты остаются доступными без
# повторного запроса (в async-режиме ленивая подгрузка недоступна).
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI-зависимость: одна сессия на запрос."""
    async with SessionFactory() as session:
        yield session
