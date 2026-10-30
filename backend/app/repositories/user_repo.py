from sqlalchemy import delete, select
from app.models import EmailVerificationCode, User
from app.repositories.base import BaseRepo

class UserRepo(BaseRepo):
    async def get(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        return await self.session.scalar(select(User).where(User.email == email.lower()))

    def add(self, user: User) -> None:
        self.session.add(user)

    async def delete(self, user: User) -> None:
        # Заказы и коды удалятся каскадно (ON DELETE CASCADE в БД)
        await self.session.delete(user)

class EmailCodeRepo(BaseRepo):
    async def get_for_user(self, user_id: int) -> EmailVerificationCode | None:
        stmt = select(EmailVerificationCode).where(EmailVerificationCode.user_id == user_id)
        return await self.session.scalar(stmt)

    async def delete_for_user(self, user_id: int) -> None:
        await self.session.execute(
            delete(EmailVerificationCode).where(EmailVerificationCode.user_id == user_id)
        )

    def add(self, code: EmailVerificationCode) -> None:
        self.session.add(code)
