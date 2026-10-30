from fastapi import APIRouter, status
from app.api.deps import ChatServiceDep, CurrentUser
from app.schemas import AgentChatRequest, AgentChatResponse, ChatMessage

router = APIRouter(prefix="/agent", tags=["agent"])

@router.post("/chat", response_model=AgentChatResponse)
async def chat(payload: AgentChatRequest, user: CurrentUser, service: ChatServiceDep) -> AgentChatResponse:
    """Сообщение агенту. Историю помнит сервер (Redis, стирается сама через CHAT__HISTORY_TTL_SECONDS)."""
    result = await service.send(user, payload.message, payload.order_id)
    return AgentChatResponse(reply=result.reply, model=result.model, usage=result.usage)

@router.get("/history", response_model=list[ChatMessage])
async def history(user: CurrentUser, service: ChatServiceDep) -> list[dict[str, str]]:
    return await service.history(user)

@router.delete("/history", status_code=status.HTTP_204_NO_CONTENT)
async def clear_history(user: CurrentUser, service: ChatServiceDep) -> None:
    await service.clear(user)
