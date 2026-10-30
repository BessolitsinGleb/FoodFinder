"""Реестр инструментов (tools) агента. Сами тулы — в chat_tools.py.

Как добавить тул:

    class FindSuppliersArgs(BaseModel):
        query: str = Field(description="Что ищем")
        region: str | None = Field(default=None, description="Регион поставки")

    @registry.tool(
        name="find_suppliers",
        description="Поиск поставщиков по запросу и региону",
        args_model=FindSuppliersArgs,
    )
    async def find_suppliers(args: FindSuppliersArgs, ctx: ToolContext) -> list[dict]:
        ...

Модуль с тулами нужно импортировать при старте приложения, чтобы декораторы сработали.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.integrations.web_search import WebSearchClient
from app.models import User

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ToolContext:
    """То, что нужно тулам помимо аргументов от модели."""

    session: AsyncSession
    user: User  # тулы работают только с данными этого пользователя
    web: WebSearchClient | None = None
    # Заказ, открытый у пользователя в интерфейсе. Менять можно только его:
    # агент не должен "заодно" править другие заказы, даже свои.
    active_order_id: int | None = None


type ToolHandler = Callable[[Any, ToolContext], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: ToolHandler
    mutating: bool = False  # меняет данные пользователя (корзину)

    def to_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_model.model_json_schema(),
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def __len__(self) -> int:
        return len(self._tools)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' уже зарегистрирован")
        self._tools[tool.name] = tool

    def tool(
        self, *, name: str, description: str, args_model: type[BaseModel], mutating: bool = False
    ) -> Callable[[ToolHandler], ToolHandler]:
        """Декоратор для регистрации async-функции как тула."""

        def decorator(handler: ToolHandler) -> ToolHandler:
            self.register(Tool(name, description, args_model, handler, mutating))
            return handler

        return decorator

    def schemas(self, include_mutating: bool = True) -> list[dict[str, Any]]:
        return [
            tool.to_openai_schema()
            for tool in self._tools.values()
            if include_mutating or not tool.mutating
        ]

    async def call(self, name: str, raw_args: str, ctx: ToolContext) -> str:
        """Выполнить тул и вернуть результат строкой для сообщения role=tool.

        Ошибки не пробрасываются, а возвращаются модели текстом — так она
        может исправить аргументы или сообщить пользователю о проблеме.
        """
        tool = self._tools.get(name)
        if tool is None:
            return _error(f"Неизвестный инструмент: {name}")

        try:
            args = tool.args_model.model_validate_json(raw_args or "{}")
        except ValidationError as exc:
            return _error(f"Некорректные аргументы: {exc.errors(include_url=False)}")

        # Гарантия в коде, а не только в промпте: менять можно лишь открытый заказ
        if tool.mutating and getattr(args, "order_id", None) != ctx.active_order_id:
            if ctx.active_order_id is None:
                return _error("Изменять корзину можно только из открытого заказа — попросите пользователя открыть его")
            return _error(f"Изменять можно только текущий заказ id={ctx.active_order_id}")

        # После тула подключение к БД сразу возвращаем в пул: дальше снова долгий вызов LLM.
        # При ошибке — close(), а не rollback(): rollback "протух" бы загруженные объекты
        # (ctx.user), и следующий тул упал бы на неявной подгрузке в async.
        try:
            result = await tool.handler(args, ctx)
            await ctx.session.commit()
        except AppError as exc:
            # Ожидаемые отказы сервисов ("заказ не найден", "менять нельзя") — модель перескажет их
            await ctx.session.close()
            return _error(exc.detail)
        except Exception:
            logger.exception("Tool '%s' failed", name)
            await ctx.session.close()
            return _error("Внутренняя ошибка инструмента")

        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, default=str)


def _error(message: str) -> str:
    return json.dumps({"error": message}, ensure_ascii=False, default=str)


# Глобальный реестр приложения
registry = ToolRegistry()
