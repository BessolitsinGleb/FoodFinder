from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import UnauthorizedError
from app.models import User
from app.repositories.user_repo import UserRepo
from app.schemas import UserUpdate
from app.services.base import BaseService

class UserService(BaseService):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.user_repo = UserRepo(session)

    async def get_active(self, user_id: int) -> User:
        """Пользователь из токена. Удалённый или неподтверждённый — 401: токен больше не годится."""
        user = await self.user_repo.get(user_id)
        if user is None or not user.email_verified:
            raise UnauthorizedError("Пользователь не найден или не подтверждён")
        return user

    async def update(self, user: User, data: UserUpdate) -> User:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(user, field, value)
        await self.session.commit()
        return user

    async def delete(self, user: User) -> None:
        await self.user_repo.delete(user)
        await self.session.commit()
