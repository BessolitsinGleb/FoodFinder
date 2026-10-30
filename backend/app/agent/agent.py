import logging
from dataclasses import dataclass
from typing import Any
from app.agent.tools import ToolContext, ToolRegistry
from app.core.exceptions import ExternalServiceError
from app.integrations.llm import LLMClient
from app.prompts.chat import build_system_prompt
from app.schemas.agent import TokenUsage

logger = logging.getLogger(__name__)

class AgentError(ExternalServiceError):
    pass

@dataclass(slots=True)
class AgentResult:
    reply: str
    model: str
    usage: TokenUsage

class SupplierAgent:

    def __init__(self, llm: LLMClient, tools: ToolRegistry, max_steps: int) -> None:
        self._llm = llm
        self._tools = tools
        self._max_steps = max_steps

    async def run(
        self,
        *,
        message: str,
        history: list[dict[str, str]],
        ctx: ToolContext,
    ) -> AgentResult:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_system_prompt(ctx.user, ctx.active_order_id)},
            *history,
            {"role": "user", "content": message},
        ]
        usage = TokenUsage()

        for _ in range(self._max_steps):
            # Без открытого заказа тулы изменения корзины модели даже не показываем
            tools = self._tools.schemas(include_mutating=ctx.active_order_id is not None)
            # Ошибки провайдера и пустой ответ LLMClient сам превращает в ExternalServiceError
            response = await self._llm.chat(messages, tools=tools)

            if response.usage:
                usage.prompt_tokens += response.usage.prompt_tokens
                usage.completion_tokens += response.usage.completion_tokens
                usage.total_tokens += response.usage.total_tokens

            reply = response.choices[0].message
            if not reply.tool_calls:
                return AgentResult(reply=reply.content or "", model=response.model, usage=usage)

            messages.append(reply.model_dump(exclude_none=True))
            for call in reply.tool_calls:
                if call.type != "function":
                    content = '{"error": "Поддерживаются только function-тулы"}'
                else:
                    logger.info("Agent calls tool %s", call.function.name)
                    content = await self._tools.call(
                        call.function.name, call.function.arguments, ctx
                    )
                messages.append({"role": "tool", "tool_call_id": call.id, "content": content})

        raise AgentError("Агент превысил лимит шагов")
