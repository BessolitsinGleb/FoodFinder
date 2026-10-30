from sqlalchemy.ext.asyncio import AsyncSession
from app.agent import SupplierAgent, ToolContext
from app.agent.agent import AgentResult
from app.integrations.web_search import WebSearchClient
from app.models import User
from app.repositories.chat_memory_repo import ChatMemoryRepo
from app.services.order_service import OrderService

class ChatService:
    """Диалог с агентом. История — только в Redis (ChatMemoryRepo), в БД её нет."""

    def __init__(
        self,
        session: AsyncSession,
        agent: SupplierAgent,
        memory: ChatMemoryRepo,
        web: WebSearchClient | None,
    ) -> None:
        self.session = session
        self.agent = agent
        self.memory = memory
        self.web = web

    async def send(self, user: User, message: str, order_id: int | None) -> AgentResult:
        if order_id is not None:
            await OrderService(self.session).get(order_id, user)  # чужой заказ -> 404
        history = await self.memory.get(user.id)
        # Агент думает десятки секунд. Без этого запрос держал бы подключение к БД всё это время,
        # и ~15 одновременных чатов выбрали бы весь пул. Объекты остаются доступны
        # (expire_on_commit=False), а тулы при необходимости возьмут подключение заново.
        await self.session.commit()
        result = await self.agent.run(
            message=message,
            history=history,
            ctx=ToolContext(session=self.session, user=user, web=self.web, active_order_id=order_id),
        )
        # Сохраняем только текст реплик; служебные вызовы тулов в истории не нужны
        await self.memory.append(
            user.id,
            {"role": "user", "content": message},
            {"role": "assistant", "content": result.reply},
        )
        return result

    async def history(self, user: User) -> list[dict[str, str]]:
        return await self.memory.get(user.id)

    async def clear(self, user: User) -> None:
        await self.memory.clear(user.id)
