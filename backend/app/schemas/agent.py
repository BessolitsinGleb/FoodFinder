from typing import Literal
from pydantic import BaseModel, Field
from app.schemas.common import Schema

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str

class AgentChatRequest(Schema):
    # История хранится на сервере (Redis), клиент шлёт только новое сообщение
    message: str = Field(min_length=1, max_length=4000)
    # Заказ, о котором идёт речь, — чтобы агент мог сразу смотреть и править корзину
    order_id: int | None = None

class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

class AgentChatResponse(BaseModel):
    reply: str
    model: str
    usage: TokenUsage
